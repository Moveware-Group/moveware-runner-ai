"""
GitHub Actions CI integration for the AI orchestrator.

After the executor pushes code, this module checks whether CI checks
(GitHub Actions workflows) pass on the branch. If CI fails, the error
output is fed back into the self-healing loop so Claude can fix the issue.

Uses the GitHub REST API via the GH_TOKEN already configured for the orchestrator.
No additional credentials required.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


@dataclass
class CICheckResult:
    """Result of a single CI check run."""
    name: str
    status: str  # "completed", "in_progress", "queued"
    conclusion: str  # "success", "failure", "cancelled", "skipped", etc.
    url: str = ""
    started_at: str = ""
    completed_at: str = ""
    output_title: str = ""
    output_summary: str = ""


@dataclass
class CIStatus:
    """Aggregate CI status for a branch."""
    branch: str
    overall: str  # "success", "failure", "pending", "none"
    checks: List[CICheckResult] = field(default_factory=list)
    failed_logs: str = ""

    def to_prompt_context(self) -> str:
        """Format failed CI checks as context for LLM self-healing."""
        if self.overall == "success":
            return ""

        parts = [f"**CI Checks Failed on branch `{self.branch}`:**"]
        for check in self.checks:
            if check.conclusion in ("failure", "cancelled"):
                icon = "FAIL" if check.conclusion == "failure" else "CANCELLED"
                parts.append(f"- [{icon}] {check.name}")
                if check.output_title:
                    parts.append(f"  Title: {check.output_title}")
                if check.output_summary:
                    summary = check.output_summary[:500]
                    parts.append(f"  Summary: {summary}")

        if self.failed_logs:
            parts.append(f"\nCI Log Output:\n```\n{self.failed_logs[-3000:]}\n```")

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.overall == "success":
            return f"CI checks passed on `{self.branch}`."

        lines = [f"**CI Checks on `{self.branch}`:**\n"]
        for check in self.checks:
            if check.conclusion == "success":
                lines.append(f"- [PASS] {check.name}")
            elif check.conclusion == "failure":
                lines.append(f"- [FAIL] {check.name}")
                if check.url:
                    lines.append(f"  [View logs]({check.url})")
            elif check.conclusion == "skipped":
                lines.append(f"- [SKIP] {check.name}")
            else:
                lines.append(f"- [{check.conclusion.upper()}] {check.name}")

        return "\n".join(lines)


def _get_token() -> Optional[str]:
    return os.getenv("GH_TOKEN")


def _headers() -> dict:
    token = _get_token()
    if not token:
        return {}
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def is_configured() -> bool:
    """Always available since GH_TOKEN is a core orchestrator credential."""
    return bool(_get_token())


def get_check_runs(
    owner: str,
    repo: str,
    ref: str,
) -> List[CICheckResult]:
    """
    Fetch check runs for a git ref (branch name or SHA).

    Args:
        owner: Repository owner
        repo: Repository name
        ref: Branch name or commit SHA
    """
    if not is_configured():
        return []

    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}/check-runs"

    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for run in data.get("check_runs", []):
            results.append(CICheckResult(
                name=run.get("name", ""),
                status=run.get("status", ""),
                conclusion=run.get("conclusion") or "pending",
                url=run.get("html_url", ""),
                started_at=run.get("started_at", ""),
                completed_at=run.get("completed_at", ""),
                output_title=(run.get("output") or {}).get("title", ""),
                output_summary=(run.get("output") or {}).get("summary", ""),
            ))
        return results

    except requests.RequestException as e:
        print(f"GitHub CI API error: {e}")
        return []


def get_workflow_run_logs(
    owner: str,
    repo: str,
    run_id: int,
) -> str:
    """Fetch logs from a failed workflow run (returns text)."""
    if not is_configured():
        return ""

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs"

    try:
        resp = requests.get(url, headers=_headers(), timeout=15, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text[:5000]
        return ""
    except requests.RequestException:
        return ""


def wait_for_ci(
    owner: str,
    repo: str,
    ref: str,
    timeout_seconds: int = 300,
    poll_interval: int = 15,
) -> CIStatus:
    """
    Wait for CI checks to complete on a branch/ref.

    Polls GitHub every `poll_interval` seconds until all checks complete
    or the timeout is reached.

    Args:
        owner: Repository owner
        repo: Repository name
        ref: Branch name or commit SHA
        timeout_seconds: Max wait time (default 5 minutes)
        poll_interval: Seconds between polls

    Returns:
        CIStatus with overall result and individual check details
    """
    ci_status = CIStatus(branch=ref, overall="none")

    if not is_configured():
        return ci_status

    start = time.time()
    while time.time() - start < timeout_seconds:
        checks = get_check_runs(owner, repo, ref)

        if not checks:
            # No checks found yet — might not have been triggered
            if time.time() - start > 30:
                # After 30s, assume no CI is configured
                ci_status.overall = "none"
                return ci_status
            time.sleep(poll_interval)
            continue

        ci_status.checks = checks

        all_completed = all(c.status == "completed" for c in checks)
        if all_completed:
            any_failed = any(c.conclusion == "failure" for c in checks)
            ci_status.overall = "failure" if any_failed else "success"
            return ci_status

        time.sleep(poll_interval)

    # Timeout reached
    ci_status.overall = "pending"
    return ci_status


def check_ci_after_push(
    owner: str,
    repo: str,
    branch: str,
    wait: bool = False,
    timeout_seconds: int = 300,
) -> CIStatus:
    """
    Main entry point: check CI status after pushing to a branch.

    Args:
        owner: Repository owner (e.g., "moveware-group")
        repo: Repository name (e.g., "online-docs")
        branch: Branch that was pushed to
        wait: If True, polls until CI completes. If False, returns current status.
        timeout_seconds: Max wait time when wait=True

    Returns:
        CIStatus with overall result and check details
    """
    if wait:
        return wait_for_ci(owner, repo, branch, timeout_seconds)

    # Immediate check
    ci_status = CIStatus(branch=branch, overall="none")
    checks = get_check_runs(owner, repo, branch)

    if not checks:
        return ci_status

    ci_status.checks = checks
    all_completed = all(c.status == "completed" for c in checks)

    if all_completed:
        any_failed = any(c.conclusion == "failure" for c in checks)
        ci_status.overall = "failure" if any_failed else "success"
    else:
        ci_status.overall = "pending"

    return ci_status
