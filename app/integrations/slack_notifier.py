"""
Slack notification integration for the AI orchestrator.

Sends real-time notifications to a Slack channel when:
- A subtask is completed (with PR link)
- A subtask fails (with error summary)
- A Story is completed (all subtasks done)
- An Epic is completed (all stories done)
- A task needs human review or is blocked

Uses Slack Incoming Webhooks — no bot token or OAuth needed.

Requires environment variable:
  SLACK_WEBHOOK_URL - Incoming Webhook URL from Slack App configuration

Setup:
  1. Go to https://api.slack.com/apps → Create New App → From scratch
  2. Enable "Incoming Webhooks" → Add New Webhook to Workspace
  3. Select the channel → Copy the Webhook URL
"""
from __future__ import annotations

import os
from typing import Optional

import requests


def _get_webhook_url() -> Optional[str]:
    return os.getenv("SLACK_WEBHOOK_URL")


def is_configured() -> bool:
    """Check whether Slack notifications are configured."""
    return bool(_get_webhook_url())


def _send(payload: dict) -> bool:
    """Send a message payload to the Slack webhook."""
    url = _get_webhook_url()
    if not url:
        return False

    try:
        resp = requests.post(url, json=payload, timeout=5)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"Slack notification failed: {e}")
        return False


def notify_subtask_completed(
    issue_key: str,
    summary: str,
    branch: str,
    pr_url: Optional[str] = None,
    story_key: Optional[str] = None,
) -> bool:
    """Notify that a subtask was completed successfully."""
    if not is_configured():
        return False

    pr_link = f"<{pr_url}|View PR>" if pr_url else "_(committed to story branch)_"
    parent = f" (Story: {story_key})" if story_key else ""

    return _send({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":white_check_mark: *Subtask Completed:* {issue_key}{parent}\n"
                        f">{summary}\n"
                        f"Branch: `{branch}` | {pr_link}"
                    ),
                },
            },
        ],
    })


def notify_subtask_failed(
    issue_key: str,
    summary: str,
    error: str,
    story_key: Optional[str] = None,
) -> bool:
    """Notify that a subtask failed."""
    if not is_configured():
        return False

    parent = f" (Story: {story_key})" if story_key else ""
    error_preview = error[:300] + "..." if len(error) > 300 else error

    return _send({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":x: *Subtask Failed:* {issue_key}{parent}\n"
                        f">{summary}\n"
                        f"```{error_preview}```"
                    ),
                },
            },
        ],
    })


def notify_story_completed(
    story_key: str,
    summary: str,
    subtask_count: int,
    pr_url: Optional[str] = None,
    epic_key: Optional[str] = None,
) -> bool:
    """Notify that all subtasks in a Story are done."""
    if not is_configured():
        return False

    pr_link = f" | <{pr_url}|Story PR>" if pr_url else ""
    parent = f" (Epic: {epic_key})" if epic_key else ""

    return _send({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":tada: *Story Completed:* {story_key}{parent}\n"
                        f">{summary}\n"
                        f"{subtask_count} subtask(s) completed{pr_link}\n"
                        f"_Ready for testing_"
                    ),
                },
            },
        ],
    })


def notify_epic_completed(
    epic_key: str,
    summary: str,
    story_count: int,
) -> bool:
    """Notify that all Stories in an Epic are done."""
    if not is_configured():
        return False

    return _send({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":rocket: *Epic Completed:* {epic_key}\n"
                        f">{summary}\n"
                        f"All {story_count} Stories implemented and ready for review."
                    ),
                },
            },
        ],
    })


def notify_needs_review(
    issue_key: str,
    summary: str,
    reason: str,
) -> bool:
    """Notify that a task needs human attention."""
    if not is_configured():
        return False

    return _send({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":eyes: *Needs Review:* {issue_key}\n"
                        f">{summary}\n"
                        f"Reason: {reason}"
                    ),
                },
            },
        ],
    })


def notify_blocked(
    issue_key: str,
    summary: str,
    reason: str,
) -> bool:
    """Notify that a task is blocked and needs human intervention."""
    if not is_configured():
        return False

    return _send({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":no_entry_sign: *Blocked:* {issue_key}\n"
                        f">{summary}\n"
                        f"Reason: {reason}"
                    ),
                },
            },
        ],
    })
