from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import settings, PARENT_PLAN_COMMENT_PREFIX
from .db import claim_next_run, init_db, update_run, add_event
from .executor import ExecutionResult, execute_subtask
from .jira import JiraClient
from .models import JiraIssue, parse_issue
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
        labels=list(fields.get("labels") or []),
        raw=payload,
    )


def _fetch_issue(jira: JiraClient, issue_key: str) -> JiraIssue:
    raw = jira.get_issue(issue_key)
    return parse_issue(raw)


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


def _extract_human_feedback_after_plan(jira: JiraClient, parent_key: str) -> str:
    """Extract human comments added after the most recent AI plan comment."""
    comments = jira.get_comments(parent_key)
    
    # Find the index of the last AI plan comment
    last_plan_idx = -1
    for i, c in enumerate(comments):
        body = c.get("body", "")
        # Handle ADF format (dict) or plain text (str)
        if isinstance(body, dict):
            # Extract text from ADF format
            body_text = _extract_text_from_adf(body)
        else:
            body_text = body
            
        if body_text.startswith(PARENT_PLAN_COMMENT_PREFIX):
            last_plan_idx = i
    
    if last_plan_idx == -1:
        return ""
    
    # Collect all human comments after the last plan
    feedback_parts = []
    for c in comments[last_plan_idx + 1:]:
        author = c.get("author", {})
        author_id = author.get("accountId") if isinstance(author, dict) else None
        
        # Skip AI's own comments
        if author_id == settings.JIRA_AI_ACCOUNT_ID:
            continue
        
        body = c.get("body", "")
        if isinstance(body, dict):
            body_text = _extract_text_from_adf(body)
        else:
            body_text = body
            
        if body_text.strip():
            feedback_parts.append(body_text.strip())
    
    return "\n\n".join(feedback_parts)


def _extract_text_from_adf(adf: Dict[str, Any]) -> str:
    """Extract plain text from Atlassian Document Format."""
    if not isinstance(adf, dict):
        return str(adf)
    
    content = adf.get("content", [])
    if not isinstance(content, list):
        return ""
    
    parts = []
    for node in content:
        if not isinstance(node, dict):
            continue
        
        node_type = node.get("type")
        if node_type == "paragraph":
            para_content = node.get("content", [])
            text_parts = []
            for item in para_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            parts.append(" ".join(text_parts))
        elif node_type == "heading":
            heading_content = node.get("content", [])
            for item in heading_content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
        elif node_type in ("bulletList", "orderedList"):
            list_items = node.get("content", [])
            for list_item in list_items:
                if isinstance(list_item, dict) and list_item.get("type") == "listItem":
                    item_text = _extract_text_from_adf(list_item)
                    parts.append(f"- {item_text}")
    
    return "\n".join(parts)


def _create_subtasks_from_plan(ctx: Context, parent: JiraIssue) -> None:
    plan = _extract_plan_json_from_comments(ctx.jira, parent.key)
    if not plan:
        ctx.jira.add_comment(parent.key, "AI Runner could not read the plan JSON from the ticket comments.")
        ctx.jira.transition_to_status(parent.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(parent.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return

    subtasks = plan.get("subtasks") or []
    if not isinstance(subtasks, list) or not subtasks:
        ctx.jira.add_comment(parent.key, "AI plan did not include subtasks. Please update the plan.")
        ctx.jira.transition_to_status(parent.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(parent.key, settings.JIRA_HUMAN_ACCOUNT_ID)
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
        ctx.jira.assign_issue(key, settings.JIRA_AI_ACCOUNT_ID)

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
        if status == settings.JIRA_STATUS_BACKLOG and assignee_id == settings.JIRA_AI_ACCOUNT_ID:
            return st.get("key")
    return None


def _all_subtasks_done(ctx: Context, parent_key: str) -> bool:
    subtasks = ctx.jira.get_subtasks(parent_key)
    if not subtasks:
        return False
    for st in subtasks:
        status = ((st.get("fields") or {}).get("status") or {}).get("name")
        if status != settings.JIRA_STATUS_DONE:
            return False
    return True


def _handle_plan_parent(ctx: Context, issue: JiraIssue) -> None:
    if not _is_parent(issue):
        return
    if not issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
        return

    plan_res: PlanResult = build_plan(issue)
    ctx.jira.add_comment(issue.key, plan_res.comment)
    ctx.jira.transition_to_status(issue.key, settings.JIRA_STATUS_PLAN_REVIEW)
    ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)


def _handle_revise_plan(ctx: Context, issue: JiraIssue) -> None:
    """Handle plan revision request - human added feedback and assigned back to AI."""
    if not _is_parent(issue):
        return
    if issue.status != settings.JIRA_STATUS_PLAN_REVIEW:
        return
    if issue.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    
    # Extract human feedback from comments
    feedback = _extract_human_feedback_after_plan(ctx.jira, issue.key)
    
    if not feedback:
        # No feedback found - just acknowledge
        ctx.jira.add_comment(
            issue.key,
            "AI Runner did not find any feedback comments to revise the plan. Please add a comment with your requested changes."
        )
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return
    
    # Generate revised plan with feedback
    plan_res: PlanResult = build_plan(issue, revision_feedback=feedback)
    
    # Post revised plan
    ctx.jira.add_comment(issue.key, plan_res.comment)
    
    # Keep in Plan Review and reassign to human
    ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)


def _handle_parent_approved(ctx: Context, parent: JiraIssue) -> None:
    # Parent moved to Selected for Development (approval signal) and assigned to AI Runner.
    if parent.status != settings.JIRA_STATUS_SELECTED_FOR_DEV:
        return
    if parent.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return

    # Create subtasks once.
    subtasks = ctx.jira.get_subtasks(parent.key)
    if not subtasks:
        _create_subtasks_from_plan(ctx, parent)

    # Transition parent to In Progress to show AI has started work.
    ctx.jira.transition_to_status(parent.key, settings.JIRA_STATUS_IN_PROGRESS)
    ctx.jira.add_comment(parent.key, "AI Runner has started processing this ticket.")

    # Start first subtask.
    next_key = _pick_next_subtask_to_start(ctx, parent.key)
    if next_key:
        ctx.jira.transition_to_status(next_key, settings.JIRA_STATUS_IN_PROGRESS)
        ctx.jira.add_comment(parent.key, f"AI starting work on {next_key}.")


def _handle_execute_subtask(ctx: Context, subtask: JiraIssue) -> None:
    if not subtask.is_subtask:
        return
    if subtask.status != settings.JIRA_STATUS_IN_PROGRESS:
        return
    if subtask.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    if not subtask.parent_key:
        return

    # Execute
    result: ExecutionResult = execute_subtask(subtask)

    # Comment + transition + assign
    ctx.jira.add_comment(subtask.key, result.jira_comment)
    ctx.jira.transition_to_status(subtask.key, settings.JIRA_STATUS_IN_TESTING)
    ctx.jira.assign_issue(subtask.key, settings.JIRA_HUMAN_ACCOUNT_ID)

    # Kick off next subtask sequentially
    next_key = _pick_next_subtask_to_start(ctx, subtask.parent_key)
    if next_key:
        ctx.jira.transition_to_status(next_key, settings.JIRA_STATUS_IN_PROGRESS)
        ctx.jira.add_comment(subtask.parent_key, f"AI moving to next sub-task {next_key}.")


def _handle_subtask_done(ctx: Context, subtask: JiraIssue) -> None:
    if not subtask.is_subtask or not subtask.parent_key:
        return
    if subtask.status != settings.JIRA_STATUS_DONE:
        return
    if _all_subtasks_done(ctx, subtask.parent_key):
        ctx.jira.transition_to_status(subtask.parent_key, settings.JIRA_STATUS_DONE)
        ctx.jira.add_comment(subtask.parent_key, "All sub-tasks are Done. Marking parent ticket Done.")


def process_run(ctx: Context, run_id: int, issue_key: str, payload: Dict[str, Any]) -> None:
    """Process a single run by fetching the issue and taking appropriate action."""
    add_event(run_id, "info", f"Processing run for {issue_key}", {})
    
    # Fetch current issue state from Jira
    issue = _fetch_issue(ctx.jira, issue_key)
    if not issue:
        add_event(run_id, "error", f"Could not fetch issue {issue_key}", {})
        update_run(run_id, status="failed", last_error="Could not fetch issue from Jira")
        return

    # Log issue state for debugging
    add_event(run_id, "info", f"Issue state check", {
        "key": issue.key,
        "status": issue.status,
        "assignee_id": issue.assignee_account_id,
        "is_subtask": issue.is_subtask,
        "expected_ai_id": settings.JIRA_AI_ACCOUNT_ID,
        "expected_backlog_status": settings.JIRA_STATUS_BACKLOG
    })
    
    action: Action = ctx.router.decide(issue)
    add_event(run_id, "info", f"Router decided action: {action.name}", {"reason": action.reason})

    if action.name == "PLAN_PARENT":
        _handle_plan_parent(ctx, issue)
    elif action.name == "REVISE_PLAN":
        _handle_revise_plan(ctx, issue)
    elif action.name == "PARENT_APPROVED":
        _handle_parent_approved(ctx, issue)
    elif action.name == "EXECUTE_SUBTASK":
        _handle_execute_subtask(ctx, issue)
    elif action.name == "SUBTASK_DONE":
        _handle_subtask_done(ctx, issue)
    
    add_event(run_id, "info", "Run completed successfully", {})
    update_run(run_id, status="completed", locked_by=None, locked_at=None)


def worker_loop(poll_interval_seconds: float = 2.0, worker_id: str = "worker-1") -> None:
    """Main worker loop that claims and processes runs."""
    init_db()
    ctx = Context(jira=JiraClient(), router=Router())
    
    print(f"Worker {worker_id} started, polling every {poll_interval_seconds}s")

    while True:
        result = claim_next_run(worker_id)
        if not result:
            time.sleep(poll_interval_seconds)
            continue

        run_id, issue_key, payload = result
        print(f"Claimed run {run_id} for issue {issue_key}")
        
        try:
            process_run(ctx, run_id, issue_key, payload)
        except Exception as e:
            error_msg = f"ERROR processing run {run_id}: {e}"
            print(error_msg)
            add_event(run_id, "error", str(e), {})
            update_run(run_id, status="failed", last_error=str(e), locked_by=None, locked_at=None)


if __name__ == "__main__":
    worker_loop()
