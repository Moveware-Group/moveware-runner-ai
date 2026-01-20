from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import (
    STATUS_BACKLOG,
    STATUS_PLAN_REVIEW,
    STATUS_IN_PROGRESS,
    STATUS_IN_TESTING,
    STATUS_DONE,
    STATUS_BLOCKED,
    JIRA_AI_ACCOUNT_ID,
    JIRA_HUMAN_ACCOUNT_ID,
)
from .models import JiraIssue


@dataclass
class RouteDecision:
    action: str
    issue_key: str
    parent_key: Optional[str] = None
    reason: str = ""
    payload: Optional[Dict[str, Any]] = None


def decide(issue: JiraIssue) -> Optional[RouteDecision]:
    """Decide what (if any) background action should run for a Jira issue state."""

    # Parent ticket behaviour
    if not issue.is_subtask:
        if issue.status == STATUS_BACKLOG and issue.assignee_account_id == JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="PLAN_PARENT", issue_key=issue.key, reason="Parent in Backlog and assigned to AI")

        # After human approval, parent is moved to In Progress and assigned to AI
        if issue.status == STATUS_IN_PROGRESS and issue.assignee_account_id == JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="ENSURE_SUBTASKS", issue_key=issue.key, reason="Parent approved, ensure subtasks exist")

        # When parent is Done and assigned to AI, nothing further.
        return None

    # Subtask behaviour
    if issue.is_subtask:
        # Start execution only when a subtask is In Progress and assigned to AI.
        if issue.status == STATUS_IN_PROGRESS and issue.assignee_account_id == JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="EXECUTE_SUBTASK", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask in progress assigned to AI")

        # When a subtask is moved to Done, check if parent can be closed.
        if issue.status == STATUS_DONE and issue.parent_key:
            return RouteDecision(action="MAYBE_CLOSE_PARENT", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask done, maybe close parent")

    return None
