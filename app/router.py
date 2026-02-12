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

    # Epic ticket behaviour - Epics create Stories
    if issue.issue_type == "Epic":
        if issue.status == settings.JIRA_STATUS_BACKLOG and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="PLAN_EPIC", issue_key=issue.key, reason="Epic in Backlog and assigned to AI")

        # Plan revision: human added comments in Plan Review and assigned back to AI
        if issue.status == settings.JIRA_STATUS_PLAN_REVIEW and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="REVISE_PLAN", issue_key=issue.key, reason="Epic in Plan Review and assigned to AI - revise plan based on comments")

        # After human approval, Epic is moved to Selected for Development and assigned to AI
        if issue.status == settings.JIRA_STATUS_SELECTED_FOR_DEV and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="EPIC_APPROVED", issue_key=issue.key, reason="Epic approved, create Stories")

        # Fallback: Epic in In Progress with plan but no Stories yet (user may have skipped Selected for Dev)
        if issue.status == settings.JIRA_STATUS_IN_PROGRESS and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="EPIC_APPROVED", issue_key=issue.key, reason="Epic in In Progress, create Stories if plan exists")

        # When Epic is Done and assigned to AI, nothing further.
        return None

    # Story ticket behaviour - Stories create sub-tasks and own the PR
    if issue.issue_type == "Story":
        # Story approval: move to Selected for Development to trigger breakdown
        if issue.status == settings.JIRA_STATUS_SELECTED_FOR_DEV and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="STORY_APPROVED", issue_key=issue.key, reason="Story approved, create sub-tasks and PR")

        # When all sub-tasks are Done, mark Story PR as ready
        if issue.status == settings.JIRA_STATUS_IN_PROGRESS and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="CHECK_STORY_COMPLETION", issue_key=issue.key, reason="Check if all Story sub-tasks are complete")

        return None

    # Subtask behaviour - subtasks commit to Story branch
    if issue.is_subtask:
        # Start execution when subtask is In Progress and assigned to AI.
        if issue.status == settings.JIRA_STATUS_IN_PROGRESS and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="EXECUTE_SUBTASK", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask in progress assigned to AI")
        # Also execute when Blocked + assigned to AI (human answered questions, ready to retry).
        if issue.status == settings.JIRA_STATUS_BLOCKED and issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
            return RouteDecision(action="EXECUTE_SUBTASK", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask unblocked, assigned to AI for retry")

        # When a subtask is moved to Done, check if parent Story can be completed.
        if issue.status == settings.JIRA_STATUS_DONE and issue.parent_key:
            return RouteDecision(action="SUBTASK_DONE", issue_key=issue.key, parent_key=issue.parent_key, reason="Subtask done, check Story completion")

    return None
