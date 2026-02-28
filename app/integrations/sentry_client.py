"""
Sentry integration for the AI orchestrator.

Provides error querying, issue analysis, and context enrichment for
AI-assisted remediation. When the orchestrator processes a bug-fix task,
it can query Sentry for related errors to give the LLM precise stack
traces and breadcrumbs.

Requires environment variables:
  SENTRY_ACCESS_TOKEN - Auth token with event:read, project:read, org:read scopes
  SENTRY_ORG         - Organization slug
  SENTRY_HOST        - API host (default: https://sentry.io)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


@dataclass
class SentryIssue:
    """A Sentry issue with relevant context for remediation."""
    issue_id: str
    title: str
    culprit: str = ""
    level: str = "error"
    count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    project_slug: str = ""
    stack_trace: str = ""
    breadcrumbs: List[str] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)
    permalink: str = ""

    def to_prompt_context(self) -> str:
        """Format as context for injection into LLM prompts."""
        parts = [
            f"**Sentry Error: {self.title}**",
            f"- Level: {self.level} | Occurrences: {self.count}",
            f"- Culprit: {self.culprit}" if self.culprit else None,
            f"- First seen: {self.first_seen}" if self.first_seen else None,
            f"- Last seen: {self.last_seen}" if self.last_seen else None,
            f"- Link: {self.permalink}" if self.permalink else None,
        ]

        if self.tags:
            tag_str = ", ".join(f"{k}={v}" for k, v in list(self.tags.items())[:10])
            parts.append(f"- Tags: {tag_str}")

        if self.stack_trace:
            parts.append(f"\nStack trace:\n```\n{self.stack_trace[:3000]}\n```")

        if self.breadcrumbs:
            parts.append("\nBreadcrumbs (last 10):")
            for bc in self.breadcrumbs[-10:]:
                parts.append(f"  - {bc}")

        return "\n".join(p for p in parts if p)


def _get_config() -> Dict[str, str]:
    return {
        "token": os.getenv("SENTRY_ACCESS_TOKEN", ""),
        "org": os.getenv("SENTRY_ORG", ""),
        "host": os.getenv("SENTRY_HOST", "https://sentry.io"),
    }


def _headers() -> dict:
    cfg = _get_config()
    if not cfg["token"]:
        return {}
    return {"Authorization": f"Bearer {cfg['token']}"}


def is_configured() -> bool:
    """Check whether Sentry integration is configured."""
    cfg = _get_config()
    return bool(cfg["token"] and cfg["org"])


def _api_url(path: str) -> str:
    cfg = _get_config()
    host = cfg["host"].rstrip("/")
    return f"{host}/api/0/{path}"


def search_issues(
    project_slug: str,
    query: str = "is:unresolved",
    limit: int = 5,
) -> List[SentryIssue]:
    """
    Search Sentry issues for a project.

    Args:
        project_slug: Sentry project slug
        query: Sentry search query (default: unresolved issues)
        limit: Max results to return

    Returns:
        List of SentryIssue objects
    """
    if not is_configured():
        return []

    cfg = _get_config()
    url = _api_url(f"projects/{cfg['org']}/{project_slug}/issues/")

    try:
        resp = requests.get(
            url,
            headers=_headers(),
            params={"query": query, "limit": limit, "sort": "freq"},
            timeout=10,
        )
        resp.raise_for_status()
        issues_data = resp.json()

        results = []
        for issue in issues_data[:limit]:
            results.append(SentryIssue(
                issue_id=str(issue.get("id", "")),
                title=issue.get("title", ""),
                culprit=issue.get("culprit", ""),
                level=issue.get("level", "error"),
                count=int(issue.get("count", 0)),
                first_seen=issue.get("firstSeen", ""),
                last_seen=issue.get("lastSeen", ""),
                project_slug=project_slug,
                permalink=issue.get("permalink", ""),
            ))
        return results

    except requests.RequestException as e:
        print(f"Sentry API error: {e}")
        return []


def get_issue_details(issue_id: str) -> Optional[SentryIssue]:
    """
    Fetch detailed information for a Sentry issue, including
    the latest event's stack trace and breadcrumbs.
    """
    if not is_configured():
        return None

    try:
        # Get issue metadata
        url = _api_url(f"issues/{issue_id}/")
        resp = requests.get(url, headers=_headers(), timeout=10)
        resp.raise_for_status()
        issue_data = resp.json()

        sentry_issue = SentryIssue(
            issue_id=str(issue_data.get("id", "")),
            title=issue_data.get("title", ""),
            culprit=issue_data.get("culprit", ""),
            level=issue_data.get("level", "error"),
            count=int(issue_data.get("count", 0)),
            first_seen=issue_data.get("firstSeen", ""),
            last_seen=issue_data.get("lastSeen", ""),
            project_slug=issue_data.get("project", {}).get("slug", ""),
            permalink=issue_data.get("permalink", ""),
        )

        # Get latest event for stack trace
        events_url = _api_url(f"issues/{issue_id}/events/latest/")
        events_resp = requests.get(events_url, headers=_headers(), timeout=10)
        if events_resp.ok:
            event = events_resp.json()

            # Extract stack trace
            entries = event.get("entries", [])
            for entry in entries:
                if entry.get("type") == "exception":
                    exc_data = entry.get("data", {})
                    values = exc_data.get("values", [])
                    trace_parts = []
                    for val in values:
                        exc_type = val.get("type", "")
                        exc_value = val.get("value", "")
                        trace_parts.append(f"{exc_type}: {exc_value}")

                        stacktrace = val.get("stacktrace", {})
                        frames = stacktrace.get("frames", [])
                        for frame in frames[-10:]:  # Last 10 frames
                            filename = frame.get("filename", "?")
                            lineno = frame.get("lineNo", "?")
                            func = frame.get("function", "?")
                            context_line = frame.get("context_line", "").strip()
                            trace_parts.append(
                                f"  {filename}:{lineno} in {func}"
                                + (f"\n    {context_line}" if context_line else "")
                            )

                    sentry_issue.stack_trace = "\n".join(trace_parts)

            # Extract breadcrumbs
            for entry in entries:
                if entry.get("type") == "breadcrumbs":
                    crumbs = entry.get("data", {}).get("values", [])
                    for crumb in crumbs[-15:]:
                        category = crumb.get("category", "")
                        message = crumb.get("message", "")
                        level = crumb.get("level", "")
                        if message:
                            sentry_issue.breadcrumbs.append(
                                f"[{level}] {category}: {message}"
                            )

            # Extract tags
            tags = event.get("tags", [])
            for tag in tags:
                key = tag.get("key", "")
                value = tag.get("value", "")
                if key and value:
                    sentry_issue.tags[key] = value

        return sentry_issue

    except requests.RequestException as e:
        print(f"Sentry API error: {e}")
        return None


# Patterns that indicate a Sentry issue reference in Jira descriptions
SENTRY_REF_PATTERN = re.compile(
    r"(?:sentry[:\s]+(?:https?://\S+/issues/|#?)(\d+))"
    r"|(?:SENTRY-(\d+))",
    re.IGNORECASE,
)


def extract_sentry_refs(text: str) -> List[str]:
    """Extract Sentry issue IDs referenced in text."""
    ids = []
    for m in SENTRY_REF_PATTERN.finditer(text or ""):
        issue_id = m.group(1) or m.group(2)
        if issue_id:
            ids.append(issue_id)
    return ids


def get_error_context_for_issue(
    description: str,
    project_slug: Optional[str] = None,
) -> str:
    """
    Extract Sentry context for an issue.

    Checks for Sentry issue references in the description. If found,
    fetches full error details. If project_slug is provided and no
    explicit references exist, searches for recent unresolved errors.

    Returns formatted context string for LLM prompt injection.
    """
    if not is_configured():
        return ""

    contexts = []

    # Check for explicit Sentry references
    refs = extract_sentry_refs(description or "")
    for ref_id in refs[:3]:
        issue = get_issue_details(ref_id)
        if issue:
            contexts.append(issue.to_prompt_context())

    # If no explicit refs but we have a project, search for recent errors
    if not contexts and project_slug:
        # Extract keywords from description for targeted search
        keywords = _extract_error_keywords(description or "")
        if keywords:
            query = f"is:unresolved {keywords}"
            issues = search_issues(project_slug, query=query, limit=3)
            for issue in issues:
                detailed = get_issue_details(issue.issue_id)
                if detailed:
                    contexts.append(detailed.to_prompt_context())

    if not contexts:
        return ""

    return (
        "\n\n---\n\n"
        "**Sentry Error Context (for bug fix reference):**\n\n"
        + "\n\n---\n\n".join(contexts)
        + "\n\n**IMPORTANT:** Use the stack traces and breadcrumbs above to "
        "pinpoint the root cause. Fix the underlying issue, not just the symptom.\n"
    )


def _extract_error_keywords(text: str) -> str:
    """Extract likely error-related keywords from issue description."""
    error_patterns = [
        r"(?:TypeError|ReferenceError|SyntaxError|RangeError)\b",
        r"(?:500|502|503|504)\s*(?:error|status)",
        r"(?:crash|exception|traceback|stack\s*trace)",
        r"Cannot\s+read\s+propert",
        r"undefined\s+is\s+not",
        r"null\s+reference",
    ]

    for pattern in error_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return ""
