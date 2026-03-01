"""
Semgrep SAST integration for the AI orchestrator.

Runs Semgrep's AST-aware static analysis against changed files to detect
OWASP Top 10 vulnerabilities with data-flow tracking, cross-file analysis,
and framework-specific rules (Next.js, Express, Django, Flask, etc.).

Semgrep is far more accurate than regex-based scanning because it understands
code structure: variable assignments, function calls, import chains, and
taint propagation from user input to dangerous sinks.

Activation:
  - Always on (open-source rules) if `semgrep` CLI is installed
  - Full OWASP coverage when SEMGREP_APP_TOKEN is set (free account)

Install: pip install semgrep  (or: pipx install semgrep)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class SemgrepFinding:
    """A single Semgrep finding."""
    rule_id: str
    path: str
    line_start: int
    line_end: int
    severity: str  # "ERROR", "WARNING", "INFO"
    message: str
    category: str = ""
    owasp: str = ""
    cwe: str = ""
    snippet: str = ""
    fix: str = ""


@dataclass
class SemgrepResult:
    """Aggregated Semgrep scan results."""
    findings: List[SemgrepFinding] = field(default_factory=list)
    errors_count: int = 0
    warnings_count: int = 0
    info_count: int = 0
    files_scanned: int = 0
    scan_time_ms: int = 0
    rules_used: int = 0
    engine: str = "oss"  # "oss" (open-source) or "pro" (with token)
    error: Optional[str] = None

    @property
    def has_blocking_issues(self) -> bool:
        return self.errors_count > 0

    @property
    def total(self) -> int:
        return self.errors_count + self.warnings_count + self.info_count

    def to_prompt_context(self) -> str:
        """Format findings as LLM context for the self-healing loop."""
        if self.error:
            return f"**Semgrep SAST:** Could not run — {self.error}"
        if not self.findings:
            return ""

        parts = [
            f"**Semgrep SAST — {self.total} security issues found "
            f"({self.errors_count} errors, {self.warnings_count} warnings):**\n",
        ]

        # Group by severity, show errors first
        for sev_label, sev_key in [("ERRORS (must fix)", "ERROR"), ("WARNINGS", "WARNING")]:
            group = [f for f in self.findings if f.severity == sev_key]
            if not group:
                continue

            parts.append(f"**{sev_label}:**")
            for f in group[:8]:
                owasp_tag = f" [{f.owasp}]" if f.owasp else ""
                cwe_tag = f" (CWE: {f.cwe})" if f.cwe else ""
                parts.append(
                    f"- `{f.path}:{f.line_start}` — **{f.rule_id}**{owasp_tag}{cwe_tag}\n"
                    f"  {f.message}"
                )
                if f.snippet:
                    parts.append(f"  ```\n  {f.snippet[:300]}\n  ```")
                if f.fix:
                    parts.append(f"  **Fix:** {f.fix}")

        parts.append(
            "\n**Fix all ERROR-level issues. These represent real security vulnerabilities "
            "detected through data-flow analysis.**"
        )

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return f"**Semgrep SAST:** {self.error}"
        if not self.findings:
            return f"**Semgrep SAST:** No issues found ({self.files_scanned} files, {self.rules_used} rules)."

        icon = "FAIL" if self.has_blocking_issues else "WARN"
        lines = [
            f"**Semgrep SAST [{icon}]:** {self.total} findings "
            f"({self.errors_count} errors, {self.warnings_count} warnings, "
            f"{self.info_count} info)\n",
            "| Severity | Rule | File | OWASP |",
            "|----------|------|------|-------|",
        ]

        for f in self.findings[:15]:
            owasp = f.owasp or "-"
            lines.append(f"| {f.severity} | `{f.rule_id}` | `{f.path}:{f.line_start}` | {owasp} |")

        if len(self.findings) > 15:
            lines.append(f"\n_...and {len(self.findings) - 15} more findings_")

        lines.append(f"\nEngine: {self.engine} | {self.files_scanned} files | {self.rules_used} rules")

        return "\n".join(lines)


def is_installed() -> bool:
    """Check if the semgrep CLI is available."""
    try:
        proc = subprocess.run(
            ["semgrep", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_app_token() -> bool:
    """Check if a Semgrep App token is configured for Pro rules."""
    return bool(os.environ.get("SEMGREP_APP_TOKEN"))


def scan(
    repo_path: Path,
    changed_files: Optional[List[str]] = None,
    timeout_seconds: int = 120,
    severity_threshold: str = "INFO",
) -> SemgrepResult:
    """
    Run Semgrep scan on the repository or specific files.

    Args:
        repo_path: Path to the repository root
        changed_files: If provided, only scan these files (relative to repo)
        timeout_seconds: Max scan time
        severity_threshold: Minimum severity to report ("ERROR", "WARNING", "INFO")

    Returns:
        SemgrepResult with parsed findings
    """
    result = SemgrepResult()

    if not is_installed():
        result.error = "semgrep CLI not installed (pip install semgrep)"
        return result

    # Build command
    if _has_app_token():
        # Pro engine with full OWASP rule coverage
        cmd = ["semgrep", "ci", "--json", "--suppress-errors"]
        result.engine = "pro"
    else:
        # Open-source engine with community rules
        cmd = [
            "semgrep", "scan",
            "--config", "auto",
            "--json",
            "--suppress-errors",
            "--metrics", "off",
        ]
        result.engine = "oss"

    # Severity filter
    sev_map = {"ERROR": ["--severity", "ERROR"],
               "WARNING": ["--severity", "ERROR", "--severity", "WARNING"],
               "INFO": []}
    cmd.extend(sev_map.get(severity_threshold, []))

    # Target specific files or whole repo
    if changed_files:
        # Filter to files that exist and are scannable
        scannable = [
            f for f in changed_files
            if (repo_path / f).exists() and _is_scannable(f)
        ]
        if not scannable:
            return result
        cmd.extend(scannable)
    else:
        cmd.append(".")

    env = os.environ.copy()
    env["SEMGREP_SEND_METRICS"] = "off"

    try:
        print(f"Running Semgrep SAST scan ({result.engine} engine)...")
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
            if proc.returncode not in (0, 1):
                stderr = proc.stderr or ""
                result.error = f"Semgrep exited with code {proc.returncode}: {stderr[:300]}"
            return result

        data = json.loads(output)

        # Parse results
        results_list = data.get("results", [])
        for item in results_list:
            finding = _parse_finding(item)
            if finding:
                result.findings.append(finding)

                if finding.severity == "ERROR":
                    result.errors_count += 1
                elif finding.severity == "WARNING":
                    result.warnings_count += 1
                else:
                    result.info_count += 1

        # Parse scan metadata
        paths = data.get("paths", {})
        result.files_scanned = len(paths.get("scanned", []))

        # Parse timing/stats if available
        stats = data.get("stats", {}) or data.get("time", {})
        if isinstance(stats, dict):
            result.rules_used = stats.get("rules", 0) or stats.get("total_rules", 0)

        # Sort by severity
        sev_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        result.findings.sort(key=lambda f: sev_order.get(f.severity, 3))

    except subprocess.TimeoutExpired:
        result.error = f"Semgrep scan timed out after {timeout_seconds}s"
    except json.JSONDecodeError:
        result.error = "Could not parse Semgrep JSON output"
    except FileNotFoundError:
        result.error = "semgrep CLI not found"
    except Exception as e:
        result.error = str(e)

    return result


def _parse_finding(item: dict) -> Optional[SemgrepFinding]:
    """Parse a single Semgrep JSON result into a SemgrepFinding."""
    try:
        check_id = item.get("check_id", "")
        path = item.get("path", "")
        start = item.get("start", {})
        end = item.get("end", {})
        extra = item.get("extra", {})

        severity = extra.get("severity", "INFO").upper()
        message = extra.get("message", "")
        metadata = extra.get("metadata", {}) or {}

        # Extract OWASP and CWE tags
        owasp_list = metadata.get("owasp", [])
        owasp = ", ".join(owasp_list) if isinstance(owasp_list, list) else str(owasp_list)

        cwe_list = metadata.get("cwe", [])
        cwe = ", ".join(cwe_list) if isinstance(cwe_list, list) else str(cwe_list)

        category = metadata.get("category", "")
        fix = extra.get("fix", "") or metadata.get("fix", "")

        # Get code snippet
        lines = extra.get("lines", "")

        return SemgrepFinding(
            rule_id=check_id,
            path=path,
            line_start=start.get("line", 0),
            line_end=end.get("line", 0),
            severity=severity,
            message=message,
            category=category,
            owasp=owasp,
            cwe=cwe,
            snippet=lines[:300] if lines else "",
            fix=fix[:200] if fix else "",
        )
    except Exception:
        return None


def _is_scannable(file_path: str) -> bool:
    """Check if a file is worth scanning with Semgrep."""
    scannable_exts = {
        '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
        '.py', '.rb', '.go', '.java', '.kt', '.scala',
        '.php', '.swift', '.rs', '.c', '.cpp', '.cs',
        '.json', '.yaml', '.yml', '.tf', '.dockerfile',
    }
    skip_dirs = {'node_modules', '.next', 'dist', 'build', '.git', 'vendor'}

    ext = Path(file_path).suffix.lower()
    if ext not in scannable_exts:
        return False
    if any(skip in file_path for skip in skip_dirs):
        return False
    return True
