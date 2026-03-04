"""
Preventive Error Knowledge Base

Aggregates lessons learned from past build failures and injects them
into the INITIAL Claude prompt — BEFORE code generation starts.

The goal: errors that the system has seen and fixed before should
never occur again. Over time, the first-attempt success rate should
approach 100% as the knowledge base grows.

Architecture:
  1. After every build (success or failure), record a "lesson"
  2. Before code generation, query the knowledge base for relevant
     lessons and inject them as explicit DO / DO NOT rules
  3. Track per-repo, per-file, and per-type-name corrections so the
     AI gets hyper-specific guidance
"""
import json
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .db import connect, now


# ---------------------------------------------------------------------------
#  Schema
# ---------------------------------------------------------------------------

def init_knowledge_base_schema() -> None:
    """Create tables for the preventive knowledge base."""
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_lessons (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_name   TEXT    NOT NULL,
                category    TEXT    NOT NULL,
                scope       TEXT    NOT NULL DEFAULT 'global',
                rule_text   TEXT    NOT NULL,
                severity    TEXT    NOT NULL DEFAULT 'warn',
                occurrences INTEGER NOT NULL DEFAULT 1,
                prevented   INTEGER NOT NULL DEFAULT 0,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL,
                meta_json   TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_type_corrections (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_name   TEXT NOT NULL,
                type_name   TEXT NOT NULL,
                wrong_prop  TEXT NOT NULL,
                correct_prop TEXT,
                action      TEXT NOT NULL DEFAULT 'remove',
                occurrences INTEGER NOT NULL DEFAULT 1,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_file_patterns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_name   TEXT NOT NULL,
                file_path   TEXT NOT NULL,
                pattern_type TEXT NOT NULL,
                description TEXT NOT NULL,
                correct_code TEXT,
                occurrences INTEGER NOT NULL DEFAULT 1,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_lessons_repo ON kb_lessons(repo_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_lessons_cat ON kb_lessons(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_type_repo ON kb_type_corrections(repo_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_file_repo ON kb_file_patterns(repo_name)")


def seed_manual_rules(rules: list) -> int:
    """
    Seed manually-created rules into the knowledge base.
    Each rule is a dict with: repo_name, category, rule_text, severity, scope (all required).
    Skips rules that already exist (idempotent).
    Returns number of new rules added.
    """
    added = 0
    for rule in rules:
        repo = rule["repo_name"]
        text = rule["rule_text"]
        ts = now()
        with connect() as conn:
            existing = conn.execute(
                "SELECT id FROM kb_lessons WHERE repo_name=? AND rule_text=?",
                (repo, text),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO kb_lessons
                       (repo_name, category, scope, rule_text, severity, occurrences, created_at, updated_at)
                       VALUES (?,?,?,?,?,100,?,?)""",
                    (repo, rule["category"], rule.get("scope", "global"), text,
                     rule.get("severity", "critical"), ts, ts),
                )
                added += 1
    return added


# ---------------------------------------------------------------------------
#  Recording lessons  (called after build success / failure)
# ---------------------------------------------------------------------------

def record_lesson(
    repo_name: str,
    category: str,
    rule_text: str,
    severity: str = "warn",
    scope: str = "global",
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Record or reinforce a preventive lesson."""
    ts = now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, occurrences FROM kb_lessons WHERE repo_name=? AND rule_text=?",
            (repo_name, rule_text),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE kb_lessons SET occurrences=?, updated_at=?, severity=? WHERE id=?",
                (existing[1] + 1, ts, severity, existing[0]),
            )
        else:
            conn.execute(
                """INSERT INTO kb_lessons
                   (repo_name, category, scope, rule_text, severity, occurrences, created_at, updated_at, meta_json)
                   VALUES (?,?,?,?,?,1,?,?,?)""",
                (repo_name, category, scope, rule_text, severity, ts, ts, json.dumps(meta or {})),
            )


def record_type_correction(
    repo_name: str,
    type_name: str,
    wrong_prop: str,
    correct_prop: Optional[str] = None,
    action: str = "remove",
) -> None:
    """Record that a property name was wrong on a given type."""
    ts = now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, occurrences FROM kb_type_corrections WHERE repo_name=? AND type_name=? AND wrong_prop=?",
            (repo_name, type_name, wrong_prop),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE kb_type_corrections SET occurrences=?, correct_prop=?, action=?, updated_at=? WHERE id=?",
                (existing[1] + 1, correct_prop, action, ts, existing[0]),
            )
        else:
            conn.execute(
                """INSERT INTO kb_type_corrections
                   (repo_name, type_name, wrong_prop, correct_prop, action, occurrences, created_at, updated_at)
                   VALUES (?,?,?,?,?,1,?,?)""",
                (repo_name, type_name, wrong_prop, correct_prop, action, ts, ts),
            )


def record_file_pattern(
    repo_name: str,
    file_path: str,
    pattern_type: str,
    description: str,
    correct_code: Optional[str] = None,
) -> None:
    """Record a file-level pattern (e.g. correct export name, required import)."""
    ts = now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, occurrences FROM kb_file_patterns WHERE repo_name=? AND file_path=? AND pattern_type=? AND description=?",
            (repo_name, file_path, pattern_type, description),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE kb_file_patterns SET occurrences=?, updated_at=?, correct_code=? WHERE id=?",
                (existing[1] + 1, ts, correct_code or "", existing[0]),
            )
        else:
            conn.execute(
                """INSERT INTO kb_file_patterns
                   (repo_name, file_path, pattern_type, description, correct_code, occurrences, created_at, updated_at)
                   VALUES (?,?,?,?,?,1,?,?)""",
                (repo_name, file_path, pattern_type, description, correct_code or "", ts, ts),
            )


def mark_lesson_prevented(repo_name: str, rule_text: str) -> None:
    """Increment the 'prevented' counter when a lesson avoids a repeat error."""
    with connect() as conn:
        conn.execute(
            "UPDATE kb_lessons SET prevented = prevented + 1 WHERE repo_name=? AND rule_text=?",
            (repo_name, rule_text),
        )


# ---------------------------------------------------------------------------
#  Auto-extraction of lessons from build errors
# ---------------------------------------------------------------------------

def extract_lessons_from_error(
    repo_name: str,
    error_text: str,
    fix_description: str = "",
    files_changed: Optional[List[str]] = None,
) -> int:
    """
    Analyse a build error and automatically extract preventive lessons.
    Returns the number of lessons recorded.
    """
    count = 0

    # 1. Property-does-not-exist → type correction
    for m in re.finditer(
        r"['\"](\w+)['\"] does not exist (?:on|in) type ['\"](\w+?)(?:<.*?>)?['\"]",
        error_text,
    ):
        wrong_prop, type_name = m.group(1), m.group(2)
        correct = _guess_correct_property(wrong_prop, fix_description)
        action = "rename" if correct else "remove"
        record_type_correction(repo_name, type_name, wrong_prop, correct, action)

        rule = f"Type '{type_name}' does NOT have property '{wrong_prop}'."
        if correct:
            rule += f" Use '{correct}' instead."
        else:
            rule += " Do NOT use this property — read the type definition first."
        record_lesson(repo_name, "type_error", rule, severity="critical", scope=type_name)
        count += 1

    # 2. Missing export
    for m in re.finditer(
        r"['\"](\w+)['\"] is not exported from ['\"]([^'\"]+)['\"]",
        error_text,
    ):
        symbol, module = m.group(1), m.group(2)
        record_lesson(
            repo_name,
            "missing_export",
            f"Module '{module}' does NOT export '{symbol}'. "
            "Read the source file to check what it actually exports before importing.",
            severity="critical",
            scope=module,
        )
        record_file_pattern(repo_name, module, "missing_export", f"'{symbol}' is not exported")
        count += 1

    # 3. No exported member
    for m in re.finditer(
        r"Module ['\"]([^'\"]+)['\"] has no exported member ['\"](\w+)['\"]",
        error_text,
    ):
        module, symbol = m.group(1), m.group(2)
        record_lesson(
            repo_name,
            "missing_export",
            f"Module '{module}' does NOT export '{symbol}'. "
            "Verify the exact export name (case-sensitive) before importing.",
            severity="critical",
            scope=module,
        )
        count += 1

    # 4. Syntax errors in specific files
    for m in re.finditer(
        r"([^\s:]+\.(?:ts|tsx)):.*?error TS\d+: (.+?)$",
        error_text,
        re.MULTILINE,
    ):
        file_path, err_msg = m.group(1), m.group(2)
        if any(kw in err_msg for kw in ["expected", "Unexpected token", "Expression expected"]):
            record_file_pattern(
                repo_name, file_path, "syntax",
                f"This file is prone to syntax errors: {err_msg[:100]}",
            )
            count += 1

    # 5. Object literal / known properties (Prisma include/select)
    for m in re.finditer(
        r"Object literal may only specify known properties, and ['\"](\w+)['\"] does not exist in type ['\"](\w+?)(?:<.*?>)?['\"]",
        error_text,
    ):
        wrong_prop, type_name = m.group(1), m.group(2)
        correct = _guess_correct_property(wrong_prop, fix_description)
        record_type_correction(repo_name, type_name, wrong_prop, correct, "rename" if correct else "remove")
        rule = f"'{wrong_prop}' is NOT a valid field on Prisma type '{type_name}'."
        if correct:
            rule += f" Use '{correct}' instead."
        record_lesson(repo_name, "prisma_schema_mismatch", rule, severity="critical", scope=type_name)
        count += 1

    # 6. Generic "does not exist on type" (catch-all after specific patterns)
    for m in re.finditer(
        r"Property ['\"](\w+)['\"] does not exist on type ['\"](\w+?)(?:<.*?>)?['\"]",
        error_text,
    ):
        wrong_prop, type_name = m.group(1), m.group(2)
        if not _already_recorded(repo_name, type_name, wrong_prop):
            correct = _guess_correct_property(wrong_prop, fix_description)
            record_type_correction(repo_name, type_name, wrong_prop, correct, "rename" if correct else "remove")
            rule = f"Type '{type_name}' does NOT have property '{wrong_prop}'."
            if correct:
                rule += f" The correct property is '{correct}'."
            record_lesson(repo_name, "type_error", rule, severity="warn", scope=type_name)
            count += 1

    # 7. Function signature mismatches
    for m in re.finditer(
        r"Expected (\d+) arguments?, but got (\d+)",
        error_text,
    ):
        expected, got = m.group(1), m.group(2)
        record_lesson(
            repo_name,
            "function_signature",
            f"Function call had {got} args but expected {expected}. "
            "Always read function signatures before calling them.",
            severity="warn",
        )
        count += 1

    return count


def _guess_correct_property(wrong_prop: str, fix_description: str) -> Optional[str]:
    """Try to extract the correct property name from the fix description."""
    if not fix_description:
        return None

    patterns = [
        rf"(?:changed|renamed|replaced)\s+['\"]?{re.escape(wrong_prop)}['\"]?\s+(?:to|with|→)\s+['\"]?(\w+)['\"]?",
        rf"use\s+['\"]?(\w+)['\"]?\s+instead\s+of\s+['\"]?{re.escape(wrong_prop)}['\"]?",
        rf"['\"]?{re.escape(wrong_prop)}['\"]?\s*→\s*['\"]?(\w+)['\"]?",
    ]
    for pat in patterns:
        m = re.search(pat, fix_description, re.IGNORECASE)
        if m:
            return m.group(1)

    # Case-variation heuristic: if fix mentions a word similar to wrong_prop
    candidates = re.findall(r'\b(\w+)\b', fix_description)
    for c in candidates:
        if c.lower() == wrong_prop.lower() and c != wrong_prop:
            return c

    return None


def _already_recorded(repo_name: str, type_name: str, wrong_prop: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM kb_type_corrections WHERE repo_name=? AND type_name=? AND wrong_prop=?",
            (repo_name, type_name, wrong_prop),
        ).fetchone()
        return row is not None


# ---------------------------------------------------------------------------
#  Querying lessons for prompt injection
# ---------------------------------------------------------------------------

@dataclass
class PreventiveLessons:
    """Aggregated lessons for a specific code generation request."""
    rules: List[str] = field(default_factory=list)
    type_corrections: List[str] = field(default_factory=list)
    file_warnings: List[str] = field(default_factory=list)
    total_lessons: int = 0
    total_prevented: int = 0


def get_preventive_lessons(
    repo_name: str,
    task_description: str = "",
    file_hints: Optional[List[str]] = None,
    max_rules: int = 30,
) -> PreventiveLessons:
    """
    Query the knowledge base for lessons relevant to the current task.

    Args:
        repo_name: Repository identifier
        task_description: The Jira issue summary + description
        file_hints: Filenames or paths mentioned in the task
        max_rules: Maximum rules to return (keeps prompt size manageable)

    Returns:
        PreventiveLessons with categorized rules for prompt injection.
    """
    result = PreventiveLessons()
    desc_lower = task_description.lower()

    with connect() as conn:
        # --- Critical lessons (always include) ---
        critical = conn.execute(
            """SELECT rule_text, occurrences, prevented, scope
               FROM kb_lessons
               WHERE repo_name=? AND severity='critical'
               ORDER BY occurrences DESC
               LIMIT ?""",
            (repo_name, max_rules // 2),
        ).fetchall()

        for rule_text, occ, prev, scope in critical:
            # Include if universal or if scope mentioned in task
            if scope == "global" or scope.lower() in desc_lower:
                result.rules.append(f"[CRITICAL, seen {occ}x] {rule_text}")
                result.total_lessons += 1
                result.total_prevented += prev

        # --- Scope-relevant warnings ---
        remaining = max_rules - len(result.rules)
        if remaining > 0:
            warnings = conn.execute(
                """SELECT rule_text, occurrences, prevented, scope
                   FROM kb_lessons
                   WHERE repo_name=? AND severity='warn'
                   ORDER BY occurrences DESC
                   LIMIT ?""",
                (repo_name, remaining),
            ).fetchall()

            for rule_text, occ, prev, scope in warnings:
                if scope == "global" or scope.lower() in desc_lower:
                    result.rules.append(f"[seen {occ}x] {rule_text}")
                    result.total_lessons += 1
                    result.total_prevented += prev

        # --- Type corrections ---
        type_corr = conn.execute(
            """SELECT type_name, wrong_prop, correct_prop, action, occurrences
               FROM kb_type_corrections
               WHERE repo_name=?
               ORDER BY occurrences DESC
               LIMIT 30""",
            (repo_name,),
        ).fetchall()

        for type_name, wrong, correct, action, occ in type_corr:
            if type_name.lower() in desc_lower or not task_description:
                if action == "rename" and correct:
                    result.type_corrections.append(
                        f"'{type_name}' has NO property '{wrong}' — use '{correct}' ({occ}x)"
                    )
                else:
                    result.type_corrections.append(
                        f"'{type_name}' has NO property '{wrong}' — do NOT use it ({occ}x)"
                    )

        # --- File-level warnings ---
        if file_hints:
            for fh in file_hints[:10]:
                file_pats = conn.execute(
                    """SELECT pattern_type, description, occurrences
                       FROM kb_file_patterns
                       WHERE repo_name=? AND file_path LIKE ?
                       ORDER BY occurrences DESC
                       LIMIT 5""",
                    (repo_name, f"%{fh}%"),
                ).fetchall()
                for ptype, desc, occ in file_pats:
                    result.file_warnings.append(f"{fh}: {desc} ({occ}x)")

    return result


def format_preventive_prompt(lessons: PreventiveLessons) -> str:
    """Format lessons as a prompt section for Claude."""
    if lessons.total_lessons == 0 and not lessons.type_corrections:
        return ""

    sections = []
    sections.append(
        "**LESSONS LEARNED FROM PAST BUILDS — YOU MUST FOLLOW THESE RULES:**\n"
        f"The system has recorded {lessons.total_lessons} lessons from previous builds "
        f"in this repository (prevented {lessons.total_prevented} repeat errors so far).\n"
    )

    if lessons.rules:
        sections.append("**Build Rules (from past failures):**")
        for rule in lessons.rules:
            sections.append(f"  - {rule}")
        sections.append("")

    if lessons.type_corrections:
        sections.append("**Type/Property Corrections (DO NOT use wrong property names):**")
        for tc in lessons.type_corrections:
            sections.append(f"  - {tc}")
        sections.append("")

    if lessons.file_warnings:
        sections.append("**File-specific Warnings:**")
        for fw in lessons.file_warnings:
            sections.append(f"  - {fw}")
        sections.append("")

    sections.append(
        "**CRITICAL:** These rules come from REAL build failures in THIS repository. "
        "Violating them WILL cause the build to fail. When in doubt, READ the source "
        "files and type definitions before writing code that uses them.\n"
    )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
#  Statistics / dashboard
# ---------------------------------------------------------------------------

def get_knowledge_base_stats(repo_name: Optional[str] = None) -> Dict[str, Any]:
    """Return stats about the knowledge base."""
    with connect() as conn:
        where = "WHERE repo_name=?" if repo_name else ""
        params: tuple = (repo_name,) if repo_name else ()

        total = conn.execute(f"SELECT COUNT(*) FROM kb_lessons {where}", params).fetchone()[0]
        critical = conn.execute(
            f"SELECT COUNT(*) FROM kb_lessons {where} {'AND' if where else 'WHERE'} severity='critical'",
            params,
        ).fetchone()[0]
        prevented = conn.execute(
            f"SELECT COALESCE(SUM(prevented),0) FROM kb_lessons {where}", params
        ).fetchone()[0]
        type_corr = conn.execute(
            f"SELECT COUNT(*) FROM kb_type_corrections {('WHERE repo_name=?' if repo_name else '')}",
            params if repo_name else (),
        ).fetchone()[0]

        top_categories = conn.execute(
            f"""SELECT category, COUNT(*) as cnt, SUM(occurrences) as occ
                FROM kb_lessons {where}
                GROUP BY category ORDER BY occ DESC LIMIT 10""",
            params,
        ).fetchall()

        return {
            "total_lessons": total,
            "critical_lessons": critical,
            "total_prevented": prevented,
            "type_corrections": type_corr,
            "top_categories": [
                {"category": c, "lessons": n, "occurrences": o} for c, n, o in top_categories
            ],
        }
