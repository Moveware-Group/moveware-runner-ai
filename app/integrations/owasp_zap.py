"""
OWASP ZAP (Zed Attack Proxy) DAST integration for the AI orchestrator.

Runs dynamic application security testing against a deployed URL to find
runtime vulnerabilities that static analysis cannot detect: injection flaws,
broken authentication, session management issues, XSS, CSRF, and more.

ZAP actively probes the application like an attacker would, testing for
OWASP Top 10 vulnerabilities in the running application.

Activation:
  - Requires ZAP running in daemon mode (Docker recommended)
  - Set ZAP_API_URL in .env (default: http://localhost:8080)
  - Optionally set ZAP_API_KEY for authenticated access

Docker quickstart:
  docker run -u zap -p 8080:8080 -d zaproxy/zap-stable \
    zap.sh -daemon -host 0.0.0.0 -port 8080 \
    -config api.addrs.addr.name=.* -config api.addrs.addr.regex=true
"""
from __future__ import annotations

import os
import time
import requests
from dataclasses import dataclass, field
from typing import List, Optional


ZAP_DEFAULT_URL = "http://localhost:8080"
SCAN_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 5


@dataclass
class ZapAlert:
    """A single ZAP security alert."""
    name: str
    risk: str  # "High", "Medium", "Low", "Informational"
    confidence: str  # "High", "Medium", "Low"
    description: str = ""
    solution: str = ""
    url: str = ""
    param: str = ""
    evidence: str = ""
    cwe_id: str = ""
    wasc_id: str = ""
    reference: str = ""
    plugin_id: str = ""
    instances: int = 1


@dataclass
class ZapScanResult:
    """Aggregated OWASP ZAP scan results."""
    alerts: List[ZapAlert] = field(default_factory=list)
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    scan_duration_s: int = 0
    target_url: str = ""
    scan_type: str = ""  # "baseline", "full", "api"
    error: Optional[str] = None

    @property
    def has_blocking_issues(self) -> bool:
        return self.high_count > 0

    @property
    def total(self) -> int:
        return self.high_count + self.medium_count + self.low_count + self.info_count

    def to_prompt_context(self) -> str:
        """Format as context for the LLM to fix vulnerabilities."""
        if self.error:
            return f"**OWASP ZAP DAST:** Could not run — {self.error}"
        if not self.alerts:
            return ""

        parts = [
            f"**OWASP ZAP DAST — {self.total} security issues found on {self.target_url}**\n"
            f"({self.high_count} high, {self.medium_count} medium, {self.low_count} low)\n",
        ]

        for risk_label in ["High", "Medium"]:
            group = [a for a in self.alerts if a.risk == risk_label]
            if not group:
                continue

            parts.append(f"**{risk_label} Risk:**")
            for a in group[:5]:
                cwe = f" (CWE-{a.cwe_id})" if a.cwe_id else ""
                parts.append(f"- **{a.name}**{cwe}")
                parts.append(f"  URL: `{a.url}`")
                if a.param:
                    parts.append(f"  Parameter: `{a.param}`")
                if a.evidence:
                    parts.append(f"  Evidence: `{a.evidence[:200]}`")
                if a.solution:
                    parts.append(f"  **Fix:** {a.solution[:300]}")

        parts.append(
            "\n**Fix all High-risk issues. These are real vulnerabilities found "
            "by actively probing the running application.**"
        )

        return "\n".join(parts)

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return f"**OWASP ZAP:** {self.error}"
        if not self.alerts:
            return (
                f"**OWASP ZAP [{self.scan_type}]:** No vulnerabilities found "
                f"on {self.target_url} ({self.scan_duration_s}s scan)."
            )

        icon = "FAIL" if self.has_blocking_issues else "WARN"
        lines = [
            f"**OWASP ZAP [{icon}] ({self.scan_type} scan):** "
            f"{self.total} alerts on `{self.target_url}`\n",
            "| Risk | Alert | CWE | URL |",
            "|------|-------|-----|-----|",
        ]

        for a in self.alerts[:15]:
            cwe = f"CWE-{a.cwe_id}" if a.cwe_id else "-"
            url_short = a.url[:60] + "..." if len(a.url) > 60 else a.url
            lines.append(f"| {a.risk} | {a.name} | {cwe} | `{url_short}` |")

        if len(self.alerts) > 15:
            lines.append(f"\n_...and {len(self.alerts) - 15} more alerts_")

        lines.append(f"\nScan time: {self.scan_duration_s}s")

        return "\n".join(lines)


def is_configured() -> bool:
    """Check if ZAP is configured and reachable."""
    api_url = os.environ.get("ZAP_API_URL", ZAP_DEFAULT_URL)
    try:
        resp = requests.get(f"{api_url}/JSON/core/view/version/", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _zap_request(endpoint: str, params: Optional[dict] = None) -> dict:
    """Make an authenticated request to the ZAP API."""
    api_url = os.environ.get("ZAP_API_URL", ZAP_DEFAULT_URL)
    api_key = os.environ.get("ZAP_API_KEY", "")

    params = params or {}
    if api_key:
        params["apikey"] = api_key

    resp = requests.get(f"{api_url}{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def run_baseline_scan(target_url: str) -> ZapScanResult:
    """
    Run a ZAP baseline (passive) scan against a target URL.

    This is a lightweight scan: ZAP spiders the target and applies
    passive rules (no active attacks). Safe for production. Takes 1-2 min.

    Args:
        target_url: The URL to scan (must be reachable from ZAP)

    Returns:
        ZapScanResult with passive scan findings
    """
    result = ZapScanResult(target_url=target_url, scan_type="baseline")

    if not is_configured():
        result.error = "ZAP not configured or not reachable (set ZAP_API_URL)"
        return result

    start = time.time()

    try:
        # Open the URL to seed ZAP's site tree
        print(f"ZAP baseline scan: opening {target_url}...")
        _zap_request("/JSON/core/action/accessUrl/", {"url": target_url, "followRedirects": "true"})

        # Start the spider to discover pages
        print("ZAP: spidering target...")
        spider_resp = _zap_request("/JSON/spider/action/scan/", {
            "url": target_url,
            "maxChildren": "10",
            "recurse": "true",
            "subtreeOnly": "true",
        })
        spider_id = spider_resp.get("scan", "0")

        # Wait for spider to complete
        _wait_for_scan(
            status_endpoint="/JSON/spider/view/status/",
            scan_id=spider_id,
            scan_id_param="scanId",
            timeout=120,
        )

        # Wait for passive scanner to finish processing
        print("ZAP: waiting for passive scan to complete...")
        _wait_for_passive_scan(timeout=60)

        # Collect alerts
        result.alerts = _get_alerts(target_url)
        _count_alerts(result)

        result.scan_duration_s = int(time.time() - start)
        print(f"ZAP baseline scan complete: {result.total} alerts in {result.scan_duration_s}s")

    except Exception as e:
        result.error = str(e)
        result.scan_duration_s = int(time.time() - start)

    return result


def run_active_scan(target_url: str) -> ZapScanResult:
    """
    Run a ZAP active scan against a target URL.

    This performs active attacks (injection probes, fuzzing) to find
    deeper vulnerabilities. MORE THOROUGH but takes longer (5-15 min)
    and should NOT be run against production.

    Args:
        target_url: The URL to scan (staging/preview only!)

    Returns:
        ZapScanResult with active + passive findings
    """
    result = ZapScanResult(target_url=target_url, scan_type="active")

    if not is_configured():
        result.error = "ZAP not configured or not reachable (set ZAP_API_URL)"
        return result

    start = time.time()

    try:
        # Spider first
        print(f"ZAP active scan: spidering {target_url}...")
        _zap_request("/JSON/core/action/accessUrl/", {"url": target_url, "followRedirects": "true"})

        spider_resp = _zap_request("/JSON/spider/action/scan/", {
            "url": target_url,
            "maxChildren": "10",
            "recurse": "true",
            "subtreeOnly": "true",
        })
        spider_id = spider_resp.get("scan", "0")
        _wait_for_scan("/JSON/spider/view/status/", spider_id, "scanId", timeout=120)

        # Start active scan
        print("ZAP: starting active scan (injection probes, fuzzing)...")
        ascan_resp = _zap_request("/JSON/ascan/action/scan/", {
            "url": target_url,
            "recurse": "true",
            "inScopeOnly": "true",
            "scanPolicyName": "",  # default policy
        })
        ascan_id = ascan_resp.get("scan", "0")

        _wait_for_scan("/JSON/ascan/view/status/", ascan_id, "scanId", timeout=SCAN_TIMEOUT_SECONDS)

        # Collect all alerts
        result.alerts = _get_alerts(target_url)
        _count_alerts(result)

        result.scan_duration_s = int(time.time() - start)
        print(f"ZAP active scan complete: {result.total} alerts in {result.scan_duration_s}s")

    except Exception as e:
        result.error = str(e)
        result.scan_duration_s = int(time.time() - start)

    return result


def run_api_scan(openapi_url: str, target_url: str) -> ZapScanResult:
    """
    Run a ZAP API scan using an OpenAPI/Swagger specification.

    Imports the API definition so ZAP can test all endpoints
    with proper parameter types and authentication.

    Args:
        openapi_url: URL to the OpenAPI/Swagger JSON spec
        target_url: Base URL of the API

    Returns:
        ZapScanResult with API-specific findings
    """
    result = ZapScanResult(target_url=target_url, scan_type="api")

    if not is_configured():
        result.error = "ZAP not configured or not reachable (set ZAP_API_URL)"
        return result

    start = time.time()

    try:
        # Import the OpenAPI spec
        print(f"ZAP API scan: importing OpenAPI spec from {openapi_url}...")
        _zap_request("/JSON/openapi/action/importUrl/", {
            "url": openapi_url,
            "hostOverride": target_url,
        })

        # Wait for import processing
        time.sleep(5)

        # Start active scan on the API
        print("ZAP: actively scanning API endpoints...")
        ascan_resp = _zap_request("/JSON/ascan/action/scan/", {
            "url": target_url,
            "recurse": "true",
        })
        ascan_id = ascan_resp.get("scan", "0")

        _wait_for_scan("/JSON/ascan/view/status/", ascan_id, "scanId", timeout=SCAN_TIMEOUT_SECONDS)

        result.alerts = _get_alerts(target_url)
        _count_alerts(result)

        result.scan_duration_s = int(time.time() - start)
        print(f"ZAP API scan complete: {result.total} alerts in {result.scan_duration_s}s")

    except Exception as e:
        result.error = str(e)
        result.scan_duration_s = int(time.time() - start)

    return result


def _wait_for_scan(
    status_endpoint: str,
    scan_id: str,
    scan_id_param: str,
    timeout: int,
) -> None:
    """Poll ZAP until a scan reaches 100% or times out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = _zap_request(status_endpoint, {scan_id_param: scan_id})
        status = int(resp.get("status", "0"))
        if status >= 100:
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"ZAP scan timed out after {timeout}s")


def _wait_for_passive_scan(timeout: int) -> None:
    """Wait for the passive scanner queue to drain."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = _zap_request("/JSON/pscan/view/recordsToScan/")
        remaining = int(resp.get("recordsToScan", "0"))
        if remaining == 0:
            return
        time.sleep(2)


def _get_alerts(target_url: str) -> List[ZapAlert]:
    """Fetch and deduplicate all alerts for a target URL."""
    resp = _zap_request("/JSON/alert/view/alertsSummary/", {"baseurl": target_url})
    # Get detailed alerts
    alerts_resp = _zap_request("/JSON/core/view/alerts/", {
        "baseurl": target_url,
        "start": "0",
        "count": "100",
    })

    alerts = []
    seen_rules: dict[str, ZapAlert] = {}

    for item in alerts_resp.get("alerts", []):
        name = item.get("name", "")
        risk = item.get("risk", "Informational")
        key = f"{name}|{risk}"

        if key in seen_rules:
            seen_rules[key].instances += 1
            continue

        alert = ZapAlert(
            name=name,
            risk=risk,
            confidence=item.get("confidence", ""),
            description=item.get("description", "")[:300],
            solution=item.get("solution", "")[:300],
            url=item.get("url", ""),
            param=item.get("param", ""),
            evidence=item.get("evidence", "")[:200],
            cwe_id=str(item.get("cweid", "")),
            wasc_id=str(item.get("wascid", "")),
            reference=item.get("reference", "")[:200],
            plugin_id=str(item.get("pluginId", "")),
        )
        alerts.append(alert)
        seen_rules[key] = alert

    # Sort by risk
    risk_order = {"High": 0, "Medium": 1, "Low": 2, "Informational": 3}
    alerts.sort(key=lambda a: risk_order.get(a.risk, 4))

    return alerts


def _count_alerts(result: ZapScanResult) -> None:
    """Tally alert counts by risk level."""
    for a in result.alerts:
        if a.risk == "High":
            result.high_count += 1
        elif a.risk == "Medium":
            result.medium_count += 1
        elif a.risk == "Low":
            result.low_count += 1
        else:
            result.info_count += 1
