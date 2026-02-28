"""
Playwright test runner integration for the AI orchestrator.

Executes existing Playwright E2E tests in the target repository after
the AI commits changes. Catches functional regressions before the PR
is created. Reports failures with test names, error messages, and
screenshots paths so the LLM self-healing loop can fix them.

No additional credentials required — uses the repo's Playwright setup.

Prerequisites in the target repo:
  - Playwright installed (`@playwright/test` in devDependencies)
  - `playwright.config.ts` or `playwright.config.js` present
  - Tests in a `tests/` or `e2e/` directory
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class TestResult:
    """Result of a single Playwright test."""
    name: str
    suite: str = ""
    status: str = ""  # "passed", "failed", "skipped", "timedOut"
    duration_ms: int = 0
    error_message: str = ""
    error_snippet: str = ""
    retry: int = 0


@dataclass
class PlaywrightResult:
    """Aggregated Playwright test run results."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    timed_out: int = 0
    duration_ms: int = 0
    failures: List[TestResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.timed_out == 0 and self.error is None

    def to_prompt_context(self) -> str:
        """Format failures as context for the LLM self-healing loop."""
        if self.error:
            return f"**Playwright E2E Tests:** Could not run — {self.error}"
        if self.all_passed:
            return ""

        parts = [
            f"**Playwright E2E Tests FAILED:** {self.failed} of {self.total} tests failed",
        ]

        for t in self.failures[:5]:
            parts.append(f"\n**FAIL: {t.suite} > {t.name}**")
            if t.error_message:
                parts.append(f"```\n{t.error_message[:1000]}\n```")
            if t.error_snippet:
                parts.append(f"Code context:\n```\n{t.error_snippet[:500]}\n```")

        parts.append(
            "\n**Fix the failing tests by correcting the implementation, "
            "not by modifying the test files (unless the tests themselves are wrong).**"
        )

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return f"**E2E Tests:** {self.error}"

        icon = "PASS" if self.all_passed else "FAIL"
        duration_s = self.duration_ms / 1000

        lines = [
            f"**E2E Tests [{icon}]:** {self.passed}/{self.total} passed ({duration_s:.1f}s)",
        ]

        if self.failures:
            lines.append("\n**Failures:**")
            for t in self.failures[:5]:
                lines.append(f"- {t.suite} > {t.name}")
                if t.error_message:
                    preview = t.error_message[:150].replace("\n", " ")
                    lines.append(f"  `{preview}`")

        return "\n".join(lines)


def detect_playwright(repo_path: Path) -> bool:
    """Check if the repository has Playwright configured."""
    indicators = [
        repo_path / "playwright.config.ts",
        repo_path / "playwright.config.js",
        repo_path / "playwright.config.mjs",
    ]
    return any(p.exists() for p in indicators)


def detect_test_directories(repo_path: Path) -> List[str]:
    """Find directories containing Playwright tests."""
    candidates = ["tests", "e2e", "test", "__tests__", "tests/e2e"]
    found = []
    for d in candidates:
        test_dir = repo_path / d
        if test_dir.exists() and test_dir.is_dir():
            # Check if it contains test files
            test_files = list(test_dir.glob("**/*.spec.ts")) + \
                         list(test_dir.glob("**/*.spec.js")) + \
                         list(test_dir.glob("**/*.test.ts")) + \
                         list(test_dir.glob("**/*.test.js"))
            if test_files:
                found.append(d)
    return found


def _install_browsers(repo_path: Path) -> bool:
    """Install Playwright browsers if not present."""
    try:
        proc = subprocess.run(
            ["npx", "playwright", "install", "--with-deps", "chromium"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode == 0
    except Exception:
        return False


def run_tests(
    repo_path: Path,
    project: str = "chromium",
    timeout_seconds: int = 180,
    max_retries: int = 0,
    grep: Optional[str] = None,
    changed_files: Optional[List[str]] = None,
) -> PlaywrightResult:
    """
    Execute Playwright tests in the repository.

    Args:
        repo_path: Path to the repository
        project: Playwright project to run (default: chromium)
        timeout_seconds: Max total test run time
        max_retries: Number of retries for flaky tests
        grep: Filter tests by name pattern
        changed_files: If provided, only runs tests related to changed files

    Returns:
        PlaywrightResult with pass/fail and failure details
    """
    result = PlaywrightResult()

    if not detect_playwright(repo_path):
        result.error = "No playwright.config found in repository"
        return result

    # Build command
    cmd = [
        "npx", "playwright", "test",
        "--project", project,
        "--reporter", "json",
    ]

    if max_retries > 0:
        cmd.extend(["--retries", str(max_retries)])

    if grep:
        cmd.extend(["--grep", grep])

    # If changed files provided, try to run only related tests
    if changed_files:
        related_tests = _find_related_tests(repo_path, changed_files)
        if related_tests:
            cmd.extend(related_tests)

    import os
    env = os.environ.copy()
    env["CI"] = "true"
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    try:
        print(f"Running Playwright tests ({project})...")
        proc = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )

        output = proc.stdout
        if not output.strip():
            if proc.returncode != 0:
                stderr = proc.stderr or ""
                if "no tests found" in stderr.lower() or "no tests matched" in stderr.lower():
                    result.error = "No tests found matching criteria"
                elif "executable doesn't exist" in stderr.lower() or "browsertype.launch" in stderr.lower():
                    print("Playwright browsers not installed, attempting install...")
                    if _install_browsers(repo_path):
                        return run_tests(repo_path, project, timeout_seconds, max_retries, grep)
                    result.error = "Playwright browsers not installed"
                else:
                    result.error = f"Playwright exited with code {proc.returncode}: {stderr[:500]}"
            return result

        # Parse JSON reporter output
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            # Sometimes output has non-JSON preamble — try to find the JSON
            json_start = output.find("{")
            if json_start >= 0:
                try:
                    data = json.loads(output[json_start:])
                except json.JSONDecodeError:
                    result.error = "Could not parse Playwright JSON output"
                    return result
            else:
                result.error = "No JSON output from Playwright"
                return result

        # Extract stats
        stats = data.get("stats", {})
        result.total = stats.get("expected", 0) + stats.get("unexpected", 0) + stats.get("skipped", 0)
        result.passed = stats.get("expected", 0)
        result.failed = stats.get("unexpected", 0)
        result.skipped = stats.get("skipped", 0)
        result.timed_out = stats.get("timedOut", 0) if "timedOut" in stats else 0
        result.duration_ms = stats.get("duration", 0)

        # Extract failure details
        suites = data.get("suites", [])
        _extract_failures(suites, result.failures)

    except subprocess.TimeoutExpired:
        result.error = f"Test run timed out after {timeout_seconds}s"
    except FileNotFoundError:
        result.error = "npx not found — Node.js may not be installed"
    except Exception as e:
        result.error = str(e)

    return result


def _extract_failures(suites: List[Dict], failures: List[TestResult], parent_title: str = "") -> None:
    """Recursively extract failed tests from the Playwright JSON report."""
    for suite in suites:
        suite_title = suite.get("title", "")
        full_title = f"{parent_title} > {suite_title}" if parent_title else suite_title

        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                status = test.get("status", "")
                if status in ("unexpected", "timedOut"):
                    error_msg = ""
                    error_snippet = ""

                    results = test.get("results", [])
                    if results:
                        last_result = results[-1]
                        error_obj = last_result.get("error", {})
                        if isinstance(error_obj, dict):
                            error_msg = error_obj.get("message", "")
                            error_snippet = error_obj.get("snippet", "")
                        elif isinstance(error_obj, str):
                            error_msg = error_obj

                    failures.append(TestResult(
                        name=spec.get("title", ""),
                        suite=full_title,
                        status="failed" if status == "unexpected" else "timedOut",
                        duration_ms=test.get("results", [{}])[-1].get("duration", 0) if test.get("results") else 0,
                        error_message=error_msg,
                        error_snippet=error_snippet,
                        retry=test.get("results", [{}])[-1].get("retry", 0) if test.get("results") else 0,
                    ))

        # Recurse into nested suites
        _extract_failures(suite.get("suites", []), failures, full_title)


def _find_related_tests(repo_path: Path, changed_files: List[str]) -> List[str]:
    """
    Find test files that are likely related to the changed source files.

    Uses simple name matching: if `components/Button.tsx` changed,
    looks for `Button.spec.ts`, `Button.test.ts`, etc.
    """
    related = []
    test_dirs = detect_test_directories(repo_path)

    for changed in changed_files:
        stem = Path(changed).stem  # e.g., "Button" from "components/Button.tsx"
        if stem.startswith("_") or stem in ("index", "layout", "page", "loading", "error"):
            continue

        for test_dir in test_dirs:
            test_path = repo_path / test_dir
            for pattern in [f"**/{stem}.spec.ts", f"**/{stem}.test.ts",
                            f"**/{stem}.spec.js", f"**/{stem}.test.js"]:
                matches = list(test_path.glob(pattern))
                for m in matches:
                    rel = str(m.relative_to(repo_path))
                    if rel not in related:
                        related.append(rel)

    return related
