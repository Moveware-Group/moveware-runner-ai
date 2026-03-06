"""
Post-Mortem Analysis System

When a build exhausts all fix attempts, this module performs a deep analysis
of the entire error chain, extracts new knowledge base rules, creates a
GitHub Issue documenting the failure, and optionally re-queues the run so
the new knowledge can be applied immediately.

This is the "Approach A" self-healing layer: safe, automatic, no code
changes to the runner itself.
"""
import json
import os
import re
import time
import traceback
from typing import Any, Dict, List, Optional

from .db import add_progress_event, connect
from .error_knowledge_base import record_lesson, extract_lessons_from_error


# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

POST_MORTEM_MAX_RETRIES = int(os.getenv("POST_MORTEM_MAX_RETRIES", "1"))
RUNNER_REPO = os.getenv("RUNNER_GITHUB_REPO", "Moveware-Group/moveware-runner-ai")


# ---------------------------------------------------------------------------
#  Collect fix-attempt history for a run
# ---------------------------------------------------------------------------

def _get_fix_attempts(run_id: int) -> List[Dict[str, Any]]:
    """Retrieve all fix_attempts rows for a given run, ordered by attempt number."""
    try:
        with connect() as conn:
            rows = conn.execute(
                """SELECT attempt_number, error_text, error_category, fix_strategy,
                          files_changed, model_used, success, duration_seconds,
                          metadata_json, created_at
                   FROM fix_attempts
                   WHERE run_id = ?
                   ORDER BY attempt_number""",
                (run_id,),
            ).fetchall()
        return [
            {
                "attempt": r[0],
                "error_text": r[1],
                "error_category": r[2],
                "fix_strategy": r[3],
                "files_changed": json.loads(r[4] or "[]"),
                "model": r[5],
                "success": bool(r[6]),
                "duration_s": r[7],
                "metadata": json.loads(r[8] or "{}"),
                "ts": r[9],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[post_mortem] Failed to load fix attempts: {e}")
        return []


def _get_run_info(run_id: int) -> Dict[str, Any]:
    """Get basic run info (issue_key, payload, etc.)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, issue_key, status, payload_json, created_at, updated_at FROM runs WHERE id=?",
            (run_id,),
        ).fetchone()
    if not row:
        return {}
    return {
        "run_id": row[0],
        "issue_key": row[1],
        "status": row[2],
        "payload": json.loads(row[3] or "{}"),
        "created_at": row[4],
        "updated_at": row[5],
    }


# ---------------------------------------------------------------------------
#  Deep analysis
# ---------------------------------------------------------------------------

def _analyse_error_chain(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyse the full chain of fix attempts to identify:
    - Root cause pattern
    - Whether the same error repeated (stuck loop)
    - Whether fixes made the problem worse
    - Which error categories appeared
    - Concrete suggestions for new KB rules
    """
    if not attempts:
        return {"pattern": "no_attempts", "suggestions": []}

    categories = [a["error_category"] for a in attempts]
    errors = [a["error_text"][:500] for a in attempts]
    models = [a["model"] for a in attempts]

    unique_categories = list(dict.fromkeys(categories))
    same_error_streak = _count_same_error_streak(errors)

    analysis: Dict[str, Any] = {
        "total_attempts": len(attempts),
        "unique_categories": unique_categories,
        "dominant_category": max(set(categories), key=categories.count),
        "same_error_streak": same_error_streak,
        "models_used": list(dict.fromkeys(models)),
        "pattern": "unknown",
        "root_cause_summary": "",
        "suggestions": [],
        "proposed_rules": [],
    }

    if same_error_streak >= 3:
        analysis["pattern"] = "stuck_loop"
        analysis["root_cause_summary"] = (
            f"The same error repeated {same_error_streak} times in a row. "
            "The AI was unable to find a different approach."
        )
    elif len(unique_categories) == 1:
        analysis["pattern"] = "single_category_failure"
        analysis["root_cause_summary"] = (
            f"All {len(attempts)} attempts failed with the same error category: "
            f"'{unique_categories[0]}'. The fix strategies were insufficient."
        )
    elif len(unique_categories) >= 3:
        analysis["pattern"] = "cascading_errors"
        analysis["root_cause_summary"] = (
            f"Fixes introduced new errors across {len(unique_categories)} categories: "
            f"{', '.join(unique_categories)}. Each fix partially worked but broke something else."
        )
    else:
        analysis["pattern"] = "mixed_failure"
        analysis["root_cause_summary"] = (
            f"Attempts alternated between error categories: {', '.join(unique_categories)}."
        )

    # Extract concrete rule proposals from the final error
    final_error = attempts[-1]["error_text"]
    analysis["proposed_rules"] = _propose_rules_from_error(final_error)

    # Suggestions for the runner codebase
    analysis["suggestions"] = _generate_improvement_suggestions(analysis, attempts)

    return analysis


def _count_same_error_streak(errors: List[str]) -> int:
    """Count the longest streak of similar consecutive errors."""
    if not errors:
        return 0
    max_streak = 1
    current_streak = 1
    for i in range(1, len(errors)):
        sig_prev = _error_signature(errors[i - 1])
        sig_curr = _error_signature(errors[i])
        if sig_prev == sig_curr:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
    return max_streak


def _error_signature(error_text: str) -> str:
    """Reduce an error to a stable signature for comparison."""
    sig = re.sub(r"line \d+|col \d+|at .*?:\d+:\d+", "", error_text[:300])
    sig = re.sub(r"\s+", " ", sig).strip().lower()
    return sig


def _propose_rules_from_error(error_text: str) -> List[Dict[str, str]]:
    """Extract concrete KB rule proposals from an error message."""
    rules: List[Dict[str, str]] = []

    # Type assignment mismatches
    for m in re.finditer(
        r"Type '(\w+)' is not assignable to (?:type|parameter of type) '([^']+)'",
        error_text,
    ):
        src, tgt = m.group(1), m.group(2)
        rules.append({
            "category": "type_error",
            "severity": "critical",
            "rule": (
                f"When passing '{src}' where '{tgt}' is expected, "
                f"cast at the call site: `value as {tgt}`. "
                "Do NOT modify the source type definition."
            ),
        })

    # Missing exports
    for m in re.finditer(
        r"['\"](\w+)['\"] is not exported from ['\"]([^'\"]+)['\"]",
        error_text,
    ):
        symbol, module = m.group(1), m.group(2)
        rules.append({
            "category": "missing_export",
            "severity": "critical",
            "rule": (
                f"Module '{module}' does NOT export '{symbol}'. "
                "Read the actual source file to verify available exports before importing."
            ),
        })

    # Property does not exist on type
    for m in re.finditer(
        r"Property ['\"](\w+)['\"] does not exist on type ['\"](\w+)['\"]",
        error_text,
    ):
        prop, type_name = m.group(1), m.group(2)
        rules.append({
            "category": "type_error",
            "severity": "critical",
            "rule": (
                f"Type '{type_name}' does NOT have property '{prop}'. "
                "Read the type definition file before using properties."
            ),
        })

    # Cannot find module
    for m in re.finditer(r"Cannot find module ['\"]([^'\"]+)['\"]", error_text):
        module = m.group(1)
        if not module.startswith("."):
            rules.append({
                "category": "missing_dependency",
                "severity": "warn",
                "rule": f"Module '{module}' must be installed (npm install {module}) before importing.",
            })

    # ESLint rule not found
    for m in re.finditer(r"Definition for rule ['\"]([^'\"]+)['\"] was not found", error_text):
        rule_name = m.group(1)
        rules.append({
            "category": "eslint_config",
            "severity": "warn",
            "rule": (
                f"ESLint rule '{rule_name}' is not available in this project. "
                f"Either install the plugin or add '\"{ rule_name }\": \"off\"' to .eslintrc."
            ),
        })

    # Duplicate declaration
    for m in re.finditer(r"Duplicate (?:module-level )?declaration of ['\"](\w+)['\"]", error_text):
        var = m.group(1)
        rules.append({
            "category": "duplicate_declaration",
            "severity": "critical",
            "rule": (
                f"Variable '{var}' is declared multiple times at module scope. "
                "Use unique names (e.g. body1, body2) or wrap in describe/block scopes."
            ),
        })

    return rules


def _generate_improvement_suggestions(
    analysis: Dict[str, Any], attempts: List[Dict[str, Any]]
) -> List[str]:
    """Generate suggestions for how the runner could be improved to handle this failure."""
    suggestions: List[str] = []

    if analysis["pattern"] == "stuck_loop":
        suggestions.append(
            "Add an auto-fix function for this specific error pattern "
            "so future runs resolve it instantly without LLM inference."
        )
        suggestions.append(
            "Consider increasing MAX_FIX_ATTEMPTS or adding an earlier "
            "bail-out when the same error repeats 3+ times."
        )

    if analysis["dominant_category"] == "type_error":
        suggestions.append(
            "Enhance the type_context_extractor to proactively read the "
            "relevant type definitions and inject them into the LLM prompt."
        )

    if analysis["dominant_category"] in ("missing_export", "import_error"):
        suggestions.append(
            "Add a pre-execution step that validates all imports against "
            "actual file exports before the build."
        )

    if analysis["pattern"] == "cascading_errors":
        suggestions.append(
            "The fix cycle introduced new errors on each attempt. Consider "
            "a 'snapshot and rollback' strategy: revert if a fix introduces "
            "more errors than it resolves."
        )

    if len(attempts) >= 5:
        all_files = set()
        for a in attempts:
            all_files.update(a.get("files_changed", []))
        if len(all_files) <= 2:
            suggestions.append(
                f"All fixes targeted the same {len(all_files)} file(s). "
                "The root cause may be in a dependency or shared module."
            )

    return suggestions


# ---------------------------------------------------------------------------
#  GitHub Issue creation
# ---------------------------------------------------------------------------

def _create_github_issue(
    issue_key: str,
    run_id: int,
    analysis: Dict[str, Any],
    attempts: List[Dict[str, Any]],
    final_error: str,
) -> Optional[str]:
    """
    Create a GitHub Issue on the runner repo documenting the failure.
    Returns the issue URL, or None if creation failed.
    """
    try:
        from .github_app import get_github_token
        import requests

        token = get_github_token()
        if not token:
            print("[post_mortem] No GitHub token available, skipping issue creation")
            return None

        title = f"[Post-Mortem] {issue_key} (run #{run_id}): {analysis['dominant_category']} - {analysis['pattern']}"

        # Build attempt table
        attempt_rows = []
        for a in attempts:
            status = "pass" if a["success"] else "FAIL"
            attempt_rows.append(
                f"| {a['attempt']} | {a['model'] or '?'} | {a['error_category']} | {status} | {a.get('duration_s', '?')}s |"
            )
        attempt_table = (
            "| # | Model | Error Category | Result | Duration |\n"
            "|---|-------|---------------|--------|----------|\n"
            + "\n".join(attempt_rows)
        )

        # Build proposed rules section
        rules_section = ""
        if analysis.get("proposed_rules"):
            rules_items = "\n".join(
                f"- **[{r['severity']}] {r['category']}**: {r['rule']}"
                for r in analysis["proposed_rules"]
            )
            rules_section = f"\n\n## Proposed KB Rules (auto-added)\n\n{rules_items}"

        # Build suggestions section
        suggestions_section = ""
        if analysis.get("suggestions"):
            sugg_items = "\n".join(f"- {s}" for s in analysis["suggestions"])
            suggestions_section = f"\n\n## Runner Improvement Suggestions\n\n{sugg_items}"

        body = (
            f"## Post-Mortem: {issue_key} (Run #{run_id})\n\n"
            f"**Pattern:** `{analysis['pattern']}`\n"
            f"**Root Cause:** {analysis['root_cause_summary']}\n"
            f"**Attempts:** {analysis['total_attempts']}\n"
            f"**Dominant Error:** `{analysis['dominant_category']}`\n\n"
            f"## Fix Attempt History\n\n{attempt_table}\n\n"
            f"## Final Error\n\n```\n{final_error[:2000]}\n```"
            f"{rules_section}"
            f"{suggestions_section}\n\n"
            f"---\n"
            f"*Auto-generated by AI Runner post-mortem analysis.*\n"
            f"*New KB rules have been automatically added. "
            f"The run has been re-queued to test with the new knowledge.*"
        )

        resp = requests.post(
            f"https://api.github.com/repos/{RUNNER_REPO}/issues",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={
                "title": title[:256],
                "body": body,
                "labels": ["post-mortem", "self-healing"],
            },
            timeout=15,
        )

        if resp.status_code in (201, 200):
            url = resp.json().get("html_url", "")
            print(f"[post_mortem] GitHub Issue created: {url}")
            return url
        else:
            print(f"[post_mortem] GitHub Issue creation failed ({resp.status_code}): {resp.text[:300]}")
            return None

    except Exception as e:
        print(f"[post_mortem] GitHub Issue creation error: {e}")
        return None


# ---------------------------------------------------------------------------
#  Re-queue the failed run
# ---------------------------------------------------------------------------

def _requeue_run(run_id: int) -> bool:
    """Reset a failed run to 'queued' so it picks up new KB knowledge."""
    try:
        ts = int(time.time())
        with connect() as conn:
            conn.execute(
                """UPDATE runs
                   SET status = 'queued',
                       locked_by = NULL,
                       locked_at = NULL,
                       last_error = NULL,
                       updated_at = ?
                   WHERE id = ? AND status = 'failed'""",
                (ts, run_id),
            )
            conn.execute(
                "INSERT INTO events(run_id,ts,level,message,meta_json) VALUES(?,?,?,?,?)",
                (run_id, ts, "info", "Run re-queued by post-mortem analysis (new KB rules applied)", "{}"),
            )
        print(f"[post_mortem] Run {run_id} re-queued")
        return True
    except Exception as e:
        print(f"[post_mortem] Failed to re-queue run {run_id}: {e}")
        return False


def _get_post_mortem_count(run_id: int) -> int:
    """Count how many times post-mortem has already re-queued this run."""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=? AND message LIKE '%re-queued by post-mortem%'",
                (run_id,),
            ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------------

def run_post_mortem(
    run_id: int,
    repo_name: str,
    final_errors: str,
    fix_attempt_count: int,
) -> Dict[str, Any]:
    """
    Execute a full post-mortem after a build has exhausted all fix attempts.

    This function:
    1. Collects the full fix-attempt history for the run
    2. Performs deep analysis of the error chain
    3. Extracts and records new KB rules automatically
    4. Creates a GitHub Issue documenting the failure
    5. Re-queues the run (once) so the new rules are applied

    Args:
        run_id: The failed run ID
        repo_name: Repository name (for KB scoping)
        final_errors: The final error text
        fix_attempt_count: How many fix attempts were made

    Returns:
        Dict with post-mortem results
    """
    result: Dict[str, Any] = {
        "run_id": run_id,
        "post_mortem": True,
        "lessons_added": 0,
        "rules_proposed": 0,
        "github_issue_url": None,
        "requeued": False,
        "analysis": {},
    }

    try:
        print(f"\n{'='*60}")
        print(f"POST-MORTEM ANALYSIS — Run #{run_id}")
        print(f"{'='*60}")

        if run_id:
            add_progress_event(
                run_id, "analyzing",
                "Starting post-mortem analysis — learning from failure",
                {"phase": "post_mortem"},
            )

        # 1. Collect fix-attempt history
        attempts = _get_fix_attempts(run_id)
        run_info = _get_run_info(run_id)
        issue_key = run_info.get("issue_key", "UNKNOWN")

        print(f"  Issue: {issue_key}")
        print(f"  Fix attempts collected: {len(attempts)}")

        # 2. Deep analysis
        analysis = _analyse_error_chain(attempts)
        result["analysis"] = analysis
        print(f"  Pattern: {analysis['pattern']}")
        print(f"  Root cause: {analysis['root_cause_summary']}")

        # 3. Extract and record KB rules from the FULL error chain
        total_lessons = 0

        # 3a. Extract from the final error (existing mechanism)
        total_lessons += extract_lessons_from_error(repo_name, final_errors)

        # 3b. Extract from each attempt's error (may catch patterns the final error missed)
        seen_errors = set()
        for attempt in attempts:
            err_sig = _error_signature(attempt["error_text"])
            if err_sig not in seen_errors:
                seen_errors.add(err_sig)
                total_lessons += extract_lessons_from_error(repo_name, attempt["error_text"])

        # 3c. Record the proposed rules from analysis
        for rule in analysis.get("proposed_rules", []):
            try:
                record_lesson(
                    repo_name,
                    rule["category"],
                    rule["rule"],
                    severity=rule.get("severity", "critical"),
                    scope="global",
                )
                total_lessons += 1
            except Exception:
                pass

        # 3d. Record a meta-lesson about the overall failure pattern
        pattern_rule = (
            f"Build for {issue_key} failed after {fix_attempt_count} attempts. "
            f"Pattern: {analysis['pattern']}. {analysis['root_cause_summary']} "
            f"Categories: {', '.join(analysis['unique_categories'])}."
        )
        record_lesson(repo_name, "post_mortem", pattern_rule, severity="critical")
        total_lessons += 1

        result["lessons_added"] = total_lessons
        result["rules_proposed"] = len(analysis.get("proposed_rules", []))
        print(f"  KB rules added: {total_lessons}")

        if run_id:
            add_progress_event(
                run_id, "analyzing",
                f"Post-mortem: extracted {total_lessons} new KB rules from error chain",
                {"lessons_added": total_lessons, "pattern": analysis["pattern"]},
            )

        # 4. Create GitHub Issue
        github_url = _create_github_issue(
            issue_key, run_id, analysis, attempts, final_errors,
        )
        result["github_issue_url"] = github_url

        if github_url and run_id:
            add_progress_event(
                run_id, "analyzing",
                f"Post-mortem: created GitHub Issue for tracking",
                {"github_issue_url": github_url},
            )

        # 5. Re-queue the run (only if we haven't already re-queued too many times)
        prior_retries = _get_post_mortem_count(run_id)
        if prior_retries < POST_MORTEM_MAX_RETRIES:
            requeued = _requeue_run(run_id)
            result["requeued"] = requeued
            if requeued and run_id:
                add_progress_event(
                    run_id, "analyzing",
                    f"Post-mortem: run re-queued with {total_lessons} new KB rules "
                    f"(retry {prior_retries + 1}/{POST_MORTEM_MAX_RETRIES})",
                    {"requeue_attempt": prior_retries + 1},
                )
            print(f"  Re-queued: {requeued} (attempt {prior_retries + 1}/{POST_MORTEM_MAX_RETRIES})")
        else:
            print(f"  Re-queue skipped: already retried {prior_retries} time(s) via post-mortem")
            if run_id:
                add_progress_event(
                    run_id, "failed",
                    f"Post-mortem: max retries ({POST_MORTEM_MAX_RETRIES}) exhausted — requires human review",
                    {"prior_retries": prior_retries},
                )

        print(f"{'='*60}\n")
        return result

    except Exception as e:
        print(f"[post_mortem] Error during analysis: {e}")
        traceback.print_exc()
        result["error"] = str(e)
        return result
