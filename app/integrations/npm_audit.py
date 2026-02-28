"""
npm audit integration for the AI orchestrator.

Runs `npm audit` after dependency installation to detect known security
vulnerabilities. Reports findings with severity levels and provides
structured context for the LLM to fix or mitigate issues.

No additional credentials required — uses npm's public advisory database.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class VulnerabilityFinding:
    """A single vulnerability from npm audit."""
    name: str
    severity: str  # "critical", "high", "moderate", "low", "info"
    title: str = ""
    url: str = ""
    range: str = ""
    fix_available: bool = False
    via: str = ""


@dataclass
class AuditResult:
    """Aggregated npm audit results."""
    total: int = 0
    critical: int = 0
    high: int = 0
    moderate: int = 0
    low: int = 0
    info: int = 0
    findings: List[VulnerabilityFinding] = field(default_factory=list)
    fix_available_count: int = 0
    error: Optional[str] = None

    @property
    def has_actionable_issues(self) -> bool:
        return self.critical > 0 or self.high > 0

    def to_prompt_context(self) -> str:
        """Format as context for LLM to address vulnerabilities."""
        if self.error:
            return f"**npm audit:** Could not run — {self.error}"
        if self.total == 0:
            return ""

        parts = [
            "**npm audit — Security Vulnerabilities Found:**",
            f"- Critical: {self.critical} | High: {self.high} | Moderate: {self.moderate} | Low: {self.low}",
        ]

        if self.fix_available_count:
            parts.append(f"- {self.fix_available_count} vulnerabilities have fixes available")

        critical_and_high = [
            f for f in self.findings
            if f.severity in ("critical", "high")
        ]
        if critical_and_high:
            parts.append("\n**Critical/High vulnerabilities:**")
            for v in critical_and_high[:10]:
                fix_str = " (fix available)" if v.fix_available else " (no fix)"
                parts.append(f"- `{v.name}` [{v.severity}]: {v.title}{fix_str}")
                if v.url:
                    parts.append(f"  Advisory: {v.url}")

        parts.append(
            "\n**Action required:** Update affected packages to patched versions. "
            "If no fix is available, consider alternative packages or document the risk."
        )

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return f"**npm audit:** {self.error}"
        if self.total == 0:
            return "**npm audit:** No vulnerabilities found."

        icon = "WARN" if self.has_actionable_issues else "INFO"
        lines = [
            f"**npm audit [{icon}]:** {self.total} vulnerabilities found\n",
            "| Severity | Count |",
            "|----------|-------|",
        ]
        if self.critical:
            lines.append(f"| Critical | {self.critical} |")
        if self.high:
            lines.append(f"| High | {self.high} |")
        if self.moderate:
            lines.append(f"| Moderate | {self.moderate} |")
        if self.low:
            lines.append(f"| Low | {self.low} |")

        if self.fix_available_count:
            lines.append(f"\n{self.fix_available_count} can be fixed with `npm audit fix`")

        return "\n".join(lines)


def run_audit(repo_path: Path) -> AuditResult:
    """
    Run `npm audit --json` and parse the results.

    Args:
        repo_path: Path to the repository with package.json

    Returns:
        AuditResult with parsed vulnerability data
    """
    result = AuditResult()

    package_json = repo_path / "package.json"
    if not package_json.exists():
        return result

    node_modules = repo_path / "node_modules"
    if not node_modules.exists():
        result.error = "node_modules not found — run npm install first"
        return result

    try:
        proc = subprocess.run(
            ["npm", "audit", "--json"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # npm audit exits with non-zero when vulnerabilities exist — that's expected
        output = proc.stdout
        if not output.strip():
            return result

        data = json.loads(output)

        # Parse metadata
        metadata = data.get("metadata", {}) or {}
        vuln_info = metadata.get("vulnerabilities", {}) or {}

        result.critical = vuln_info.get("critical", 0)
        result.high = vuln_info.get("high", 0)
        result.moderate = vuln_info.get("moderate", 0)
        result.low = vuln_info.get("low", 0)
        result.info = vuln_info.get("info", 0)
        result.total = vuln_info.get("total", 0)

        if result.total == 0:
            total_from_counts = result.critical + result.high + result.moderate + result.low + result.info
            result.total = total_from_counts

        # Parse individual vulnerabilities
        vulnerabilities = data.get("vulnerabilities", {}) or {}
        for pkg_name, vuln_data in vulnerabilities.items():
            severity = vuln_data.get("severity", "info")
            fix_available = bool(vuln_data.get("fixAvailable"))

            via = vuln_data.get("via", [])
            title = ""
            url = ""
            if isinstance(via, list):
                for v in via:
                    if isinstance(v, dict):
                        title = v.get("title", "")
                        url = v.get("url", "")
                        break
                    elif isinstance(v, str):
                        title = f"Via {v}"

            result.findings.append(VulnerabilityFinding(
                name=pkg_name,
                severity=severity,
                title=title,
                url=url,
                range=vuln_data.get("range", ""),
                fix_available=fix_available,
                via=str(via)[:100],
            ))

            if fix_available:
                result.fix_available_count += 1

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "info": 4}
        result.findings.sort(key=lambda f: severity_order.get(f.severity, 5))

    except subprocess.TimeoutExpired:
        result.error = "npm audit timed out (30s)"
    except json.JSONDecodeError:
        result.error = "Could not parse npm audit output"
    except FileNotFoundError:
        result.error = "npm not found"
    except Exception as e:
        result.error = str(e)

    return result


def run_audit_fix(repo_path: Path, force: bool = False) -> str:
    """
    Run `npm audit fix` to automatically resolve vulnerabilities.

    Args:
        repo_path: Path to the repository
        force: If True, runs with --force (may install breaking changes)

    Returns:
        Output message describing what was fixed
    """
    cmd = ["npm", "audit", "fix"]
    if force:
        cmd.append("--force")

    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = proc.stdout or proc.stderr or ""
        if "fixed" in output.lower():
            return f"Fixed vulnerabilities:\n{output[:500]}"
        return "No fixable vulnerabilities found"
    except Exception as e:
        return f"npm audit fix failed: {e}"
