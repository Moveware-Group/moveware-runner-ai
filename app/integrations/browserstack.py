"""
BrowserStack integration for the AI orchestrator.

Runs cross-browser responsive design checks after the executor commits
changes. Results are reported back as Jira comments with pass/fail status
per viewport/browser combination.

Requires environment variables:
  BROWSERSTACK_USERNAME   - BrowserStack username
  BROWSERSTACK_ACCESS_KEY - BrowserStack access key
"""
from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


AUTOMATE_API = "https://api.browserstack.com"
SCREENSHOTS_API = "https://www.browserstack.com/screenshots"

RESPONSIVE_VIEWPORTS = [
    {"label": "Mobile (375px)", "width": 375, "os": "ios", "device": "iPhone 15"},
    {"label": "Tablet (768px)", "width": 768, "os": "ios", "device": "iPad Air 6th"},
    {"label": "Desktop (1440px)", "width": 1440, "os": "Windows", "os_version": "11", "browser": "chrome", "browser_version": "latest"},
]


@dataclass
class ScreenshotResult:
    """Result of a single screenshot/viewport test."""
    label: str
    status: str  # "done", "failed", "timed_out"
    image_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ResponsiveTestResult:
    """Aggregate responsive test results."""
    url_tested: str
    passed: bool
    screenshots: List[ScreenshotResult] = field(default_factory=list)
    error: Optional[str] = None

    def to_jira_comment(self) -> str:
        """Format as a Jira comment."""
        if self.error:
            return (
                f"**BrowserStack Responsive Test:** {self.url_tested}\n\n"
                f"Test could not run: {self.error}"
            )

        status_icon = "pass" if self.passed else "FAIL"
        lines = [
            f"**BrowserStack Responsive Test [{status_icon}]:** {self.url_tested}",
            "",
            "| Viewport | Status | Screenshot |",
            "|----------|--------|------------|",
        ]

        for ss in self.screenshots:
            icon = "pass" if ss.status == "done" else "FAIL"
            link = f"[View]({ss.image_url})" if ss.image_url else ss.error or "N/A"
            lines.append(f"| {ss.label} | {icon} | {link} |")

        return "\n".join(lines)


def _get_auth() -> Optional[tuple]:
    username = os.getenv("BROWSERSTACK_USERNAME", "")
    access_key = os.getenv("BROWSERSTACK_ACCESS_KEY", "")
    if not username or not access_key:
        return None
    return (username, access_key)


def is_configured() -> bool:
    """Check whether BrowserStack integration is configured."""
    return _get_auth() is not None


def check_account_status() -> Dict[str, Any]:
    """Verify BrowserStack credentials and return plan info."""
    auth = _get_auth()
    if not auth:
        return {"error": "BROWSERSTACK_USERNAME or BROWSERSTACK_ACCESS_KEY not set"}

    try:
        resp = requests.get(
            f"{AUTOMATE_API}/automate/plan.json",
            auth=auth,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def take_screenshots(
    url: str,
    browsers: Optional[List[Dict[str, str]]] = None,
    wait_time: int = 10,
    quality: str = "compressed",
) -> Optional[str]:
    """
    Request screenshots from BrowserStack Screenshots API.

    Args:
        url: URL to screenshot
        browsers: Browser/device configurations (defaults to RESPONSIVE_VIEWPORTS)
        wait_time: Seconds to wait for page load before screenshot
        quality: "original" or "compressed"

    Returns:
        Job ID string, or None on failure
    """
    auth = _get_auth()
    if not auth:
        print("BrowserStack integration skipped: credentials not set")
        return None

    if browsers is None:
        browsers = [
            {
                "os": "Windows",
                "os_version": "11",
                "browser": "chrome",
                "browser_version": "latest",
            },
            {
                "os": "Windows",
                "os_version": "11",
                "browser": "firefox",
                "browser_version": "latest",
            },
            {
                "os": "OS X",
                "os_version": "Sonoma",
                "browser": "safari",
                "browser_version": "latest",
            },
        ]

    payload = {
        "url": url,
        "browsers": browsers,
        "wait_time": wait_time,
        "quality": quality,
        "local": False,
        "mac_res": "1024x768",
        "win_res": "1366x768",
    }

    try:
        resp = requests.post(
            f"{SCREENSHOTS_API}",
            auth=auth,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("job_id")
    except requests.RequestException as e:
        print(f"BrowserStack screenshot API error: {e}")
        return None


def poll_screenshot_job(job_id: str, max_wait: int = 120) -> List[ScreenshotResult]:
    """
    Poll a screenshot job until complete.

    Args:
        job_id: Job ID from take_screenshots()
        max_wait: Maximum seconds to wait

    Returns:
        List of ScreenshotResult objects
    """
    auth = _get_auth()
    if not auth:
        return []

    start = time.time()
    while time.time() - start < max_wait:
        try:
            resp = requests.get(
                f"{SCREENSHOTS_API}/{job_id}.json",
                auth=auth,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            state = data.get("state", "")
            if state == "done":
                results = []
                for ss in data.get("screenshots", []):
                    browser = ss.get("browser", "")
                    os_name = ss.get("os", "")
                    device = ss.get("device", "")
                    label = device if device else f"{browser} on {os_name}"

                    results.append(ScreenshotResult(
                        label=label,
                        status="done" if ss.get("image_url") else "failed",
                        image_url=ss.get("image_url"),
                        error=ss.get("error_message"),
                    ))
                return results

            if state in ("queue_error", "error"):
                return [ScreenshotResult(
                    label="All",
                    status="failed",
                    error=f"Job failed with state: {state}",
                )]

        except requests.RequestException as e:
            print(f"BrowserStack poll error: {e}")

        time.sleep(5)

    return [ScreenshotResult(
        label="All",
        status="timed_out",
        error=f"Screenshot job timed out after {max_wait}s",
    )]


def run_responsive_check(
    url: str,
    viewports: Optional[List[Dict]] = None,
) -> ResponsiveTestResult:
    """
    Run a responsive design check across multiple viewports.

    This is the main entry point for post-execution verification.

    Args:
        url: URL to test (must be publicly accessible or via BrowserStack Local)
        viewports: Optional viewport configurations

    Returns:
        ResponsiveTestResult with pass/fail and screenshot URLs
    """
    if not is_configured():
        return ResponsiveTestResult(
            url_tested=url,
            passed=True,
            error="BrowserStack not configured (BROWSERSTACK_USERNAME/ACCESS_KEY not set)",
        )

    # Build browser configs for the viewports
    browsers = []
    if viewports:
        for vp in viewports:
            if "device" in vp:
                browsers.append({
                    "device": vp["device"],
                    "os": vp.get("os", "ios"),
                    "os_version": vp.get("os_version", ""),
                })
            else:
                browsers.append({
                    "os": vp.get("os", "Windows"),
                    "os_version": vp.get("os_version", "11"),
                    "browser": vp.get("browser", "chrome"),
                    "browser_version": vp.get("browser_version", "latest"),
                })

    job_id = take_screenshots(url, browsers=browsers or None)
    if not job_id:
        return ResponsiveTestResult(
            url_tested=url,
            passed=False,
            error="Failed to start screenshot job",
        )

    screenshots = poll_screenshot_job(job_id)

    all_passed = all(ss.status == "done" for ss in screenshots)

    return ResponsiveTestResult(
        url_tested=url,
        passed=all_passed,
        screenshots=screenshots,
    )
