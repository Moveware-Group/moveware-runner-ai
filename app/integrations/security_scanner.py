"""
Static security scanner for the AI orchestrator.

Scans code changes for common security vulnerabilities before commit.
Checks for OWASP-style issues: hardcoded secrets, SQL injection patterns,
XSS vectors, insecure configurations, and dangerous function usage.

No external dependencies or credentials required — runs pure regex
analysis on the changed files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class SecurityFinding:
    """A single security issue found in code."""
    file: str
    line: int
    severity: str  # "critical", "high", "medium", "low"
    category: str
    message: str
    snippet: str = ""


@dataclass
class SecurityScanResult:
    """Aggregated security scan results."""
    findings: List[SecurityFinding] = field(default_factory=list)
    files_scanned: int = 0
    error: Optional[str] = None

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    @property
    def has_blocking_issues(self) -> bool:
        return self.critical_count > 0

    def to_prompt_context(self) -> str:
        """Format as context for LLM to fix security issues."""
        if not self.findings:
            return ""

        parts = [
            f"**Security Scan — {len(self.findings)} issues found "
            f"({self.critical_count} critical, {self.high_count} high):**",
        ]

        for f in self.findings[:15]:
            parts.append(
                f"\n- [{f.severity.upper()}] `{f.file}:{f.line}` — **{f.category}**"
                f"\n  {f.message}"
            )
            if f.snippet:
                parts.append(f"  ```\n  {f.snippet}\n  ```")

        parts.append(
            "\n**Fix all critical and high severity issues before committing. "
            "Never hardcode secrets — use environment variables instead.**"
        )

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if not self.findings:
            return f"**Security Scan:** No issues found ({self.files_scanned} files scanned)."

        icon = "FAIL" if self.has_blocking_issues else "WARN"
        lines = [
            f"**Security Scan [{icon}]:** {len(self.findings)} issues in {self.files_scanned} files\n",
            "| Severity | File | Issue |",
            "|----------|------|-------|",
        ]

        for f in self.findings[:10]:
            lines.append(f"| {f.severity} | `{f.file}:{f.line}` | {f.category}: {f.message[:60]} |")

        if len(self.findings) > 10:
            lines.append(f"\n_...and {len(self.findings) - 10} more issues_")

        return "\n".join(lines)


# Security rules: (pattern, severity, category, message)
# Patterns are compiled once at module load for performance.

_SECRET_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (
        re.compile(r"""(?:password|passwd|pwd|secret|token|api_key|apikey|api[-_]?secret|auth[-_]?token)\s*[:=]\s*['"][^'"]{8,}['"]""", re.IGNORECASE),
        "critical", "Hardcoded Secret",
        "Possible hardcoded secret or API key. Use environment variables instead.",
    ),
    (
        re.compile(r"""(?:sk_live|sk_test|rk_live|rk_test|pk_live)_[A-Za-z0-9]{20,}"""),
        "critical", "Stripe Key Exposed",
        "Stripe API key found in source code. Move to environment variable.",
    ),
    (
        re.compile(r"""(?:AKIA|ASIA)[A-Z0-9]{16}"""),
        "critical", "AWS Key Exposed",
        "Possible AWS access key found in source code.",
    ),
    (
        re.compile(r"""ghp_[A-Za-z0-9]{36}|gho_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}"""),
        "critical", "GitHub Token Exposed",
        "GitHub personal access token found in source code.",
    ),
    (
        re.compile(r"""eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_.+/=]+"""),
        "high", "JWT Token in Source",
        "Possible JWT token hardcoded in source. Tokens should be runtime values.",
    ),
    (
        re.compile(r"""-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"""),
        "critical", "Private Key in Source",
        "Private key found in source code. Store in secrets manager.",
    ),
]

_INJECTION_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (
        re.compile(r"""(?:query|exec|execute|raw)\s*\(\s*[`'"].*\$\{""", re.IGNORECASE),
        "high", "SQL Injection Risk",
        "String interpolation in SQL query. Use parameterized queries.",
    ),
    (
        re.compile(r"""\.innerHTML\s*=\s*(?!['"]<)"""),
        "high", "XSS Risk (innerHTML)",
        "Direct innerHTML assignment with dynamic content. Use textContent or sanitize.",
    ),
    (
        re.compile(r"""dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html\s*:"""),
        "medium", "XSS Risk (dangerouslySetInnerHTML)",
        "Using dangerouslySetInnerHTML — ensure content is sanitized (DOMPurify).",
    ),
    (
        re.compile(r"""eval\s*\("""),
        "high", "Code Injection (eval)",
        "Use of eval() is dangerous. Use safer alternatives (JSON.parse, Function).",
    ),
    (
        re.compile(r"""new Function\s*\(.*\+"""),
        "high", "Code Injection (new Function)",
        "Dynamic Function constructor with concatenation. Risk of code injection.",
    ),
    (
        re.compile(r"""child_process.*exec\s*\(.*\+"""),
        "high", "Command Injection",
        "String concatenation in shell command. Use execFile with array args.",
    ),
    (
        re.compile(r"""subprocess\.(?:run|call|Popen)\s*\(.*\+.*shell\s*=\s*True""", re.DOTALL),
        "high", "Command Injection (Python)",
        "Shell=True with string concatenation. Use list args without shell=True.",
    ),
]

_CONFIG_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (
        re.compile(r"""(?:cors|Access-Control-Allow-Origin).*\*""", re.IGNORECASE),
        "medium", "Overly Permissive CORS",
        "CORS allows all origins (*). Restrict to specific domains in production.",
    ),
    (
        re.compile(r"""(?:httpOnly|http_only)\s*[:=]\s*false""", re.IGNORECASE),
        "medium", "Insecure Cookie",
        "Cookie without httpOnly flag. Set httpOnly: true to prevent XSS access.",
    ),
    (
        re.compile(r"""(?:secure)\s*[:=]\s*false""", re.IGNORECASE),
        "medium", "Insecure Cookie (no Secure flag)",
        "Cookie without Secure flag. Set secure: true in production.",
    ),
    (
        re.compile(r"""(?:NODE_TLS_REJECT_UNAUTHORIZED|PYTHONHTTPSVERIFY)\s*=\s*['"]?0"""),
        "high", "TLS Verification Disabled",
        "TLS certificate verification disabled. Remove in production.",
    ),
    (
        re.compile(r"""(?:DEBUG|debug)\s*[:=]\s*(?:true|True|1)\b"""),
        "low", "Debug Mode Enabled",
        "Debug mode should be disabled in production builds.",
    ),
]

_AUTH_PATTERNS: List[Tuple[re.Pattern, str, str, str]] = [
    (
        re.compile(r"""(?:bcrypt|argon2|scrypt|pbkdf2).*rounds?\s*[:=]\s*[1-9]\b""", re.IGNORECASE),
        "medium", "Weak Hashing Rounds",
        "Password hashing rounds too low. Use at least 10 rounds for bcrypt.",
    ),
    (
        re.compile(r"""(?:md5|sha1)\s*\(""", re.IGNORECASE),
        "medium", "Weak Hash Algorithm",
        "MD5/SHA1 are cryptographically weak. Use SHA-256+ or bcrypt for passwords.",
    ),
    (
        re.compile(r"""Math\.random\(\).*(?:token|secret|key|password|nonce|salt)""", re.IGNORECASE),
        "high", "Insecure Randomness",
        "Math.random() is not cryptographically secure. Use crypto.randomBytes().",
    ),
]

ALL_RULES = _SECRET_PATTERNS + _INJECTION_PATTERNS + _CONFIG_PATTERNS + _AUTH_PATTERNS

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
    '.py', '.rb', '.go', '.java',
    '.json', '.yaml', '.yml', '.toml',
    '.env', '.cfg', '.conf', '.ini',
}

# Files/dirs to skip
SKIP_PATTERNS = {
    'node_modules', '.next', 'dist', 'build', '.git',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '.env.example', '.env.sample', '.env.template',
}


def scan_files(
    repo_path: Path,
    changed_files: List[str],
) -> SecurityScanResult:
    """
    Scan changed files for security vulnerabilities.

    Args:
        repo_path: Path to the repository
        changed_files: List of changed file paths (relative to repo)

    Returns:
        SecurityScanResult with findings
    """
    result = SecurityScanResult()

    for file_path in changed_files:
        # Skip non-scannable files
        if any(skip in file_path for skip in SKIP_PATTERNS):
            continue

        ext = Path(file_path).suffix.lower()
        if ext not in SCANNABLE_EXTENSIONS:
            continue

        full_path = repo_path / file_path
        if not full_path.exists():
            continue

        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            result.files_scanned += 1

            for line_num, line in enumerate(lines, 1):
                # Skip comments and very short lines
                stripped = line.strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                    continue

                for pattern, severity, category, message in ALL_RULES:
                    if pattern.search(line):
                        # Avoid false positives in test files, docs, examples
                        if _is_likely_false_positive(file_path, line, category):
                            continue

                        result.findings.append(SecurityFinding(
                            file=file_path,
                            line=line_num,
                            severity=severity,
                            category=category,
                            message=message,
                            snippet=stripped[:120],
                        ))

        except Exception as e:
            result.findings.append(SecurityFinding(
                file=file_path, line=0, severity="low",
                category="Scan Error", message=f"Could not scan: {e}",
            ))

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    result.findings.sort(key=lambda f: severity_order.get(f.severity, 4))

    return result


def _is_likely_false_positive(file_path: str, line: str, category: str) -> bool:
    """Filter out common false positives."""
    fp = file_path.lower()

    # Test/mock files often contain fake secrets
    if any(x in fp for x in [".test.", ".spec.", "__test__", "__mock__", "fixture", "seed"]):
        if category in ("Hardcoded Secret", "JWT Token in Source"):
            return True

    # Example/template files
    if any(x in fp for x in [".example", ".sample", ".template", "readme", "docs/"]):
        return True

    # Type definitions
    if fp.endswith(".d.ts"):
        return True

    # Comments that mention patterns without containing them
    if line.strip().startswith("*") or line.strip().startswith("//"):
        return True

    # Environment variable references (not hardcoded values)
    if "process.env" in line or "os.getenv" in line or "os.environ" in line:
        if category == "Hardcoded Secret":
            return True

    return False
