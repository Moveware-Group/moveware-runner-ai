"""
Lighthouse / PageSpeed integration for the AI orchestrator.

Runs Google PageSpeed Insights audits after UI changes to catch
performance regressions. Reports Core Web Vitals (LCP, CLS, FID/INP)
and provides actionable diagnostics for the LLM to fix.

Uses the free PageSpeed Insights API — no API key required for basic usage.
Optional: PAGESPEED_API_KEY for higher rate limits.

Rate limits without key: ~25 requests/day per IP.
Rate limits with key: ~25,000 requests/day.
Generate key at: https://developers.google.com/speed/docs/insights/v5/get-started
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


PAGESPEED_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

SCORE_THRESHOLDS = {
    "performance": 0.7,
    "accessibility": 0.9,
    "best-practices": 0.8,
    "seo": 0.8,
}


@dataclass
class LighthouseAuditResult:
    """Individual audit finding."""
    id: str
    title: str
    score: Optional[float] = None
    display_value: str = ""
    description: str = ""


@dataclass
class LighthouseResult:
    """Full Lighthouse audit result for a URL."""
    url: str
    strategy: str = "mobile"  # "mobile" or "desktop"
    performance_score: float = 0.0
    accessibility_score: float = 0.0
    best_practices_score: float = 0.0
    seo_score: float = 0.0
    lcp: str = ""  # Largest Contentful Paint
    cls: str = ""  # Cumulative Layout Shift
    fid: str = ""  # First Input Delay / INP
    tbt: str = ""  # Total Blocking Time
    speed_index: str = ""
    failed_audits: List[LighthouseAuditResult] = field(default_factory=list)
    passed: bool = True
    error: Optional[str] = None

    def to_prompt_context(self) -> str:
        """Format as context for LLM to fix performance issues."""
        if self.error:
            return f"**Lighthouse ({self.strategy}):** Could not audit — {self.error}"

        parts = [
            f"**Lighthouse Audit ({self.strategy}) — {self.url}**",
            f"- Performance: {self._score_str(self.performance_score)}",
            f"- Accessibility: {self._score_str(self.accessibility_score)}",
            f"- Best Practices: {self._score_str(self.best_practices_score)}",
            f"- SEO: {self._score_str(self.seo_score)}",
        ]

        if self.lcp:
            parts.append(f"- LCP: {self.lcp}")
        if self.cls:
            parts.append(f"- CLS: {self.cls}")
        if self.fid:
            parts.append(f"- FID/INP: {self.fid}")
        if self.tbt:
            parts.append(f"- TBT: {self.tbt}")

        if self.failed_audits:
            parts.append("\n**Issues to fix:**")
            for audit in self.failed_audits[:10]:
                parts.append(f"- **{audit.title}**: {audit.display_value or audit.description[:100]}")

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return f"**Lighthouse ({self.strategy}):** {self.error}"

        icon = "PASS" if self.passed else "WARN"
        lines = [
            f"**Lighthouse [{icon}] ({self.strategy}):** {self.url}\n",
            f"| Metric | Score |",
            f"|--------|-------|",
            f"| Performance | {self._score_str(self.performance_score)} |",
            f"| Accessibility | {self._score_str(self.accessibility_score)} |",
            f"| Best Practices | {self._score_str(self.best_practices_score)} |",
            f"| SEO | {self._score_str(self.seo_score)} |",
        ]

        if self.lcp or self.cls:
            lines.append(f"\nCore Web Vitals: LCP={self.lcp}, CLS={self.cls}, TBT={self.tbt}")

        if self.failed_audits:
            lines.append("\n**Opportunities:**")
            for audit in self.failed_audits[:5]:
                lines.append(f"- {audit.title}: {audit.display_value}")

        return "\n".join(lines)

    @staticmethod
    def _score_str(score: float) -> str:
        pct = int(score * 100)
        if pct >= 90:
            return f"{pct}/100 (good)"
        elif pct >= 50:
            return f"{pct}/100 (needs work)"
        else:
            return f"{pct}/100 (poor)"


def is_configured() -> bool:
    """Always available — PageSpeed API works without a key (lower rate limits)."""
    return True


def _get_api_key() -> Optional[str]:
    return os.getenv("PAGESPEED_API_KEY")


def run_audit(
    url: str,
    strategy: str = "mobile",
    categories: Optional[List[str]] = None,
) -> LighthouseResult:
    """
    Run a PageSpeed Insights / Lighthouse audit on a URL.

    Args:
        url: URL to audit (must be publicly accessible)
        strategy: "mobile" or "desktop"
        categories: List of categories to audit. Default: all four.
    """
    result = LighthouseResult(url=url, strategy=strategy)

    if categories is None:
        categories = ["performance", "accessibility", "best-practices", "seo"]

    params: Dict[str, Any] = {
        "url": url,
        "strategy": strategy,
    }

    for cat in categories:
        params.setdefault("category", [])
        if isinstance(params["category"], list):
            params["category"].append(cat)

    api_key = _get_api_key()
    if api_key:
        params["key"] = api_key

    try:
        resp = requests.get(PAGESPEED_API, params=params, timeout=60)
        if resp.status_code == 429:
            result.error = "Rate limited — set PAGESPEED_API_KEY for higher limits"
            result.passed = True
            return result
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        result.error = str(e)
        result.passed = True
        return result

    # Extract category scores
    lighthouse = data.get("lighthouseResult", {})
    cats = lighthouse.get("categories", {})

    result.performance_score = (cats.get("performance") or {}).get("score", 0) or 0
    result.accessibility_score = (cats.get("accessibility") or {}).get("score", 0) or 0
    result.best_practices_score = (cats.get("best-practices") or {}).get("score", 0) or 0
    result.seo_score = (cats.get("seo") or {}).get("score", 0) or 0

    # Extract Core Web Vitals
    audits = lighthouse.get("audits", {})

    lcp_audit = audits.get("largest-contentful-paint", {})
    result.lcp = lcp_audit.get("displayValue", "")

    cls_audit = audits.get("cumulative-layout-shift", {})
    result.cls = cls_audit.get("displayValue", "")

    fid_audit = audits.get("max-potential-fid") or audits.get("interaction-to-next-paint", {})
    result.fid = fid_audit.get("displayValue", "")

    tbt_audit = audits.get("total-blocking-time", {})
    result.tbt = tbt_audit.get("displayValue", "")

    si_audit = audits.get("speed-index", {})
    result.speed_index = si_audit.get("displayValue", "")

    # Collect failed audits (opportunities and diagnostics)
    for audit_id, audit_data in audits.items():
        score = audit_data.get("score")
        if score is not None and score < 0.9 and audit_data.get("scoreDisplayMode") != "informative":
            result.failed_audits.append(LighthouseAuditResult(
                id=audit_id,
                title=audit_data.get("title", ""),
                score=score,
                display_value=audit_data.get("displayValue", ""),
                description=audit_data.get("description", "")[:200],
            ))

    # Sort by score (worst first)
    result.failed_audits.sort(key=lambda a: a.score or 0)

    # Determine pass/fail based on thresholds
    result.passed = (
        result.performance_score >= SCORE_THRESHOLDS["performance"]
        and result.accessibility_score >= SCORE_THRESHOLDS["accessibility"]
        and result.best_practices_score >= SCORE_THRESHOLDS["best-practices"]
        and result.seo_score >= SCORE_THRESHOLDS["seo"]
    )

    return result


def audit_for_ui_changes(
    url: str,
    changed_files: List[str],
) -> Optional[LighthouseResult]:
    """
    Run a Lighthouse audit only when UI-related files were changed.

    Args:
        url: Public URL to audit
        changed_files: List of changed file paths

    Returns:
        LighthouseResult if UI files were changed, None otherwise
    """
    ui_extensions = ('.tsx', '.jsx', '.css', '.scss', '.html', '.svg')
    has_ui_changes = any(f.endswith(ui_extensions) for f in changed_files)

    if not has_ui_changes:
        return None

    print(f"Running Lighthouse audit on {url} ...")
    return run_audit(url, strategy="mobile")
