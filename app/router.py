from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import settings
from .models import JiraIssue


@dataclass
class Action:
    """Action to take for an issue."""
    name: str
    reason: str = ""
    

@dataclass
class RouteDecision:
    action: str
    issue_key: str
    parent_key: Optional[str] = None
    reason: str = ""
    payload: Optional[Dict[str, Any]] = None


class Router:
    """Router decides what action to take for a given issue."""
    
    def decide(self, issue: JiraIssue) -> Action:
        """Decide what action to take for this issue."""
        decision = _decide_internal(issue)
        if decision:
            return Action(name=decision.action, reason=decision.reason)
        return Action(name="NOOP", reason="No action needed")


def _decide_internal(issue: JiraIssue) -> Optional[RouteDecision]:
    """Decide what (if any) background action should run for a Jira issue state."""

    # Parent ticket behaviour
    if not issue.is_subtask:
        if issue.status == settings.JIRA_STATUS_BACKLOG and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="PLAN_PARENT", issue_key=issue.key, reason="Parent in Backlog and assigned to AI")

        # Plan revision: human added comments in Plan Review and assigned back to AI
        if issue.status == settings.JIRA_STATUS_PLAN_REVIEW and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="REVISE_PLAN", issue_key=issue.key, reason="Parent in Plan Review and assigned to AI - revise plan based on comments")

        # After human approval, parent is moved to Selected for Development and assigned to AI
        if issue.status == settings.JIRA_STATUS_SELECTED_FOR_DEV and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="PARENT_APPROVED", issue_key=issue.key, reason="Parent approved, ensure subtasks exist")

        # When parent is Done and assigned to AI, nothing further.
        return None

    # Subtask behaviour
    if issue.is_subtask:
        # Start execution only when a subtask is In Progress and assigned to AI.
        if issue.status == settings.JIRA_STATUS_IN_PROGRESS and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="EXECUTE_SUBTASK", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask in progress assigned to AI")

        # When a subtask is moved to Done, check if parent can be closed.
        if issue.status == settings.JIRA_STATUS_DONE and issue.parent_key:
            return RouteDecision(action="SUBTASK_DONE", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask done, maybe close parent")

    return None
