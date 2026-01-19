from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import (
    JIRA_AI_ACCOUNT_ID,
    JIRA_HUMAN_ACCOUNT_ID,
    REPO_OWNER_SLUG,
    REPO_NAME,
    BASE_BRANCH,
    STATUS_BACKLOG,
    STATUS_PLAN_REVIEW,
    STATUS_IN_PROGRESS,
    STATUS_IN_TESTING,
    STATUS_DONE,
    STATUS_BLOCKED,
    PARENT_PLAN_COMMENT_PREFIX,
)
from .db import dequeue_event, enqueue_job, init_db, mark_event_processed
from .executor import ExecutionResult, execute_subtask
from .jira import JiraClient
from .models import JiraIssue
from .planner import PlanResult, build_plan
from .router import Action, Router


@dataclass
class Context:
    jira: JiraClient
    router: Router


def _to_issue(payload: Dict[str, Any]) -> Optional[JiraIssue]:
    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    key = issue.get("key")
    if not key:
        return None

    desc = fields.get("description")
    # Jira Cloud v3 returns description as Atlassian Document Format (ADF) object.
    if isinstance(desc, dict):
        desc_text = json.dumps(desc)
    else:
        desc_text = desc or ""

    issuetype = fields.get("issuetype") or {}
    status = (fields.get("status") or {}).get("name", "")
    assignee = fields.get("assignee")
    assignee_id = assignee.get("accountId") if isinstance(assignee, dict) else None

    parent = fields.get("parent") or {}
    parent_key = parent.get("key") if isinstance(parent, dict) else None

    return JiraIssue(
        key=key,
        summary=fields.get("summary", ""),
        description=desc_text,
        issue_type=(issuetype.get("name") or ""),
        is_subtask=bool(issuetype.get("subtask")),
        status=status,
        assignee_account_id=assignee_id,
        parent_key=parent_key,
    )


def _fetch_issue(jira: JiraClient, issue_key: str) -> JiraIssue:
    raw = jira.get_issue(issue_key)
    # Wrap into webhook-like shape for reuse
    return _to_issue({"issue": raw})  # type: ignore


def _is_parent(issue: JiraIssue) -> bool:
    return not issue.is_subtask


def _has_plan_comment(jira: JiraClient, parent_key: str) -> bool:
    try:
        comments = jira.get_comments(parent_key)
        for c in comments:
            body = c.get("body")
            if isinstance(body, str) and body.startswith(PARENT_PLAN_COMMENT_PREFIX):
                return True
        return False
    except Exception:
        return False


def _extract_plan_json_from_comments(jira: JiraClient, parent_key: str) -> Optional[Dict[str, Any]]:
    comments = jira.get_comments(parent_key)
    for c in reversed(comments):
        body = c.get("body")
        if isinstance(body, str) and body.startswith(PARENT_PLAN_COMMENT_PREFIX):
            # body = "[AI PLAN v1]\n```json\n{...}\n```"
            try:
                start = body.index("```json") + len("```json")
                end = body.index("```", start)
                return json.loads(body[start:end].strip())
            except Exception:
                return None
    return None


def _create_subtasks_from_plan(ctx: Context, parent: JiraIssue) -> None:
    plan = _extract_plan_json_from_comments(ctx.jira, parent.key)
    if not plan:
        ctx.jira.add_comment(parent.key, "AI Runner could not read the plan JSON from the ticket comments.")
        ctx.jira.transition_to_status(parent.key, STATUS_BLOCKED)
        ctx.jira.assign_issue(parent.key, JIRA_HUMAN_ACCOUNT_ID)
        return

    subtasks = plan.get("subtasks") or []
    if not isinstance(subtasks, list) or not subtasks:
        ctx.jira.add_comment(parent.key, "AI plan did not include subtasks. Please update the plan.")
        ctx.jira.transition_to_status(parent.key, STATUS_BLOCKED)
        ctx.jira.assign_issue(parent.key, JIRA_HUMAN_ACCOUNT_ID)
        return

    created_keys = []
    for s in subtasks:
        summary = (s.get("summary") or "").strip()
        if not summary:
            continue
        desc = s.get("description") or ""
        key = ctx.jira.create_subtask(
            project_key=None,
            parent_key=parent.key,
            summary=summary,
            description=str(desc),
            labels=s.get("labels") if isinstance(s.get("labels"), list) else None,
        )
        created_keys.append(key)
        # leave subtask in Backlog and assign AI; worker will pull one into In Progress
        ctx.jira.assign_issue(key, JIRA_AI_ACCOUNT_ID)

    ctx.jira.add_comment(
        parent.key,
        "AI created sub-tasks from the approved plan:\n" + "\n".join([f"- {k}" for k in created_keys]),
    )


def _pick_next_subtask_to_start(ctx: Context, parent_key: str) -> Optional[str]:
    subtasks = ctx.jira.get_subtasks(parent_key)
    # pick first Backlog assigned to AI
    for st in subtasks:
        fields = st.get("fields") or {}
        status = (fields.get("status") or {}).get("name")
        assignee = fields.get("assignee") or {}
        assignee_id = assignee.get("accountId") if isinstance(assignee, dict) else None
        if status == STATUS_BACKLOG and assignee_id == JIRA_AI_ACCOUNT_ID:
            return st.get("key")
    return None


def _all_subtasks_done(ctx: Context, parent_key: str) -> bool:
    subtasks = ctx.jira.get_subtasks(parent_key)
    if not subtasks:
        return False
    for st in subtasks:
        status = ((st.get("fields") or {}).get("status") or {}).get("name")
        if status != STATUS_DONE:
            return False
    return True


def _handle_plan_parent(ctx: Context, issue: JiraIssue) -> None:
    if not _is_parent(issue):
        return
    if not issue.assignee_account_id == JIRA_AI_ACCOUNT_ID:
        return

    plan_res: PlanResult = build_plan(issue)
    ctx.jira.add_comment(issue.key, plan_res.comment)
    ctx.jira.transition_to_status(issue.key, STATUS_PLAN_REVIEW)
    ctx.jira.assign_issue(issue.key, JIRA_HUMAN_ACCOUNT_ID)


def _handle_parent_approved(ctx: Context, parent: JiraIssue) -> None:
    # Parent moved to In Progress (approval signal) and assigned to AI Runner.
    if parent.status != STATUS_IN_PROGRESS:
        return
    if parent.assignee_account_id != JIRA_AI_ACCOUNT_ID:
        return

    # Create subtasks once.
    subtasks = ctx.jira.get_subtasks(parent.key)
    if not subtasks:
        _create_subtasks_from_plan(ctx, parent)

    # Start first subtask.
    next_key = _pick_next_subtask_to_start(ctx, parent.key)
    if next_key:
        ctx.jira.transition_to_status(next_key, STATUS_IN_PROGRESS)
        ctx.jira.add_comment(parent.key, f"AI starting work on {next_key}.")


def _handle_execute_subtask(ctx: Context, subtask: JiraIssue) -> None:
    if not subtask.is_subtask:
        return
    if subtask.status != STATUS_IN_PROGRESS:
        return
    if subtask.assignee_account_id != JIRA_AI_ACCOUNT_ID:
        return
    if not subtask.parent_key:
        return

    # Execute
    result: ExecutionResult = execute_subtask(subtask)

    # Comment + transition + assign
    ctx.jira.add_comment(subtask.key, result.jira_comment)
    ctx.jira.transition_to_status(subtask.key, STATUS_IN_TESTING)
    ctx.jira.assign_issue(subtask.key, JIRA_HUMAN_ACCOUNT_ID)

    # Kick off next subtask sequentially
    next_key = _pick_next_subtask_to_start(ctx, subtask.parent_key)
    if next_key:
        ctx.jira.transition_to_status(next_key, STATUS_IN_PROGRESS)
        ctx.jira.add_comment(subtask.parent_key, f"AI moving to next sub-task {next_key}.")


def _handle_subtask_done(ctx: Context, subtask: JiraIssue) -> None:
    if not subtask.is_subtask or not subtask.parent_key:
        return
    if subtask.status != STATUS_DONE:
        return
    if _all_subtasks_done(ctx, subtask.parent_key):
        ctx.jira.transition_to_status(subtask.parent_key, STATUS_DONE)
        ctx.jira.add_comment(subtask.parent_key, "All sub-tasks are Done. Marking parent ticket Done.")


def process_webhook_event(ctx: Context, event: Dict[str, Any]) -> None:
    issue = _to_issue(event)
    if not issue:
        return

    action: Action = ctx.router.decide(issue)

    if action.name == "PLAN_PARENT":
        _handle_plan_parent(ctx, issue)
    elif action.name == "PARENT_APPROVED":
        _handle_parent_approved(ctx, issue)
    elif action.name == "EXECUTE_SUBTASK":
        _handle_execute_subtask(ctx, issue)
    elif action.name == "SUBTASK_DONE":
        _handle_subtask_done(ctx, issue)


def worker_loop(poll_interval_seconds: float = 1.0) -> None:
    init_db()
    ctx = Context(jira=JiraClient(), router=Router())

    while True:
        row = dequeue_event()
        if not row:
            time.sleep(poll_interval_seconds)
            continue

        event_id = row["id"]
        payload = json.loads(row["payload"])
        try:
            process_webhook_event(ctx, payload)
            mark_event_processed(event_id)
        except Exception as e:
            # Don't lose the event; mark processed but leave trace in logs.
            # In production you may prefer a retry + dead-letter queue.
            print(f"ERROR processing event {event_id}: {e}")
            mark_event_processed(event_id)


if __name__ == "__main__":
    worker_loop()
