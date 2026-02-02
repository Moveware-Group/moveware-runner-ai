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
    """A parent is an Epic that should be broken down into subtasks."""
    return issue.issue_type == "Epic"


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
        
        # Handle both plain text and ADF format
        if isinstance(body, dict):
            # ADF format - check if it contains plan marker and extract code block
            content = body.get("content", [])
            has_plan_marker = False
            code_block_text = None
            
            for node in content:
                if not isinstance(node, dict):
                    continue
                    
                # Check for plan marker in paragraph/heading
                if node.get("type") in ("paragraph", "heading"):
                    text_content = _extract_text_from_adf({"content": [node]})
                    if text_content.startswith(PARENT_PLAN_COMMENT_PREFIX):
                        has_plan_marker = True
                
                # Extract JSON from codeBlock
                if node.get("type") == "codeBlock" and node.get("attrs", {}).get("language") == "json":
                    code_content = node.get("content", [])
                    if code_content and isinstance(code_content[0], dict):
                        code_block_text = code_content[0].get("text", "")
            
            if has_plan_marker and code_block_text:
                try:
                    return json.loads(code_block_text.strip())
                except Exception as e:
                    print(f"Failed to parse plan JSON from ADF comment: {e}")
                    continue
                    
        elif isinstance(body, str):
            # Plain text format
            if body.startswith(PARENT_PLAN_COMMENT_PREFIX):
                try:
                    # Try Jira's {code:json}...{code} format first
                    if "{code:json}" in body:
                        start = body.index("{code:json}") + len("{code:json}")
                        end = body.index("{code}", start)
                        return json.loads(body[start:end].strip())
                    # Fall back to markdown ```json format
                    elif "```json" in body:
                        start = body.index("```json") + len("```json")
                        end = body.index("```", start)
                        return json.loads(body[start:end].strip())
                except Exception as e:
                    print(f"Failed to parse plan JSON from text comment: {e}")
                    continue
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


def _create_stories_from_plan(ctx: Context, epic: JiraIssue) -> bool:
    """Create Stories from Epic plan (v2 format). Returns True if successful."""
    plan = _extract_plan_json_from_comments(ctx.jira, epic.key)
    if not plan:
        ctx.jira.add_comment(epic.key, "AI Runner could not read the plan JSON from the ticket comments.")
        ctx.jira.transition_to_status(epic.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(epic.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return False

    # Validate plan has stories
    stories = plan.get("stories") or []
    if not isinstance(stories, list) or not stories:
        # Check if plan has old format with top-level subtasks
        if plan.get("subtasks"):
            ctx.jira.add_comment(
                epic.key,
                "⚠️ This plan has top-level subtasks instead of Stories.\n\n"
                "The plan must have a 'stories' array where each story contains nested 'subtasks'.\n"
                "Move Epic back to Backlog and the AI will regenerate in the correct format."
            )
        else:
            ctx.jira.add_comment(epic.key, "AI plan did not include stories. Please move back to Backlog to regenerate.")
        ctx.jira.transition_to_status(epic.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(epic.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return False

    created_keys = []
    for story_data in stories:
        summary = (story_data.get("summary") or "").strip()
        if not summary:
            continue
        desc = story_data.get("description") or ""
        labels = story_data.get("labels") if isinstance(story_data.get("labels"), list) else None
        
        # Create Story
        story_key = ctx.jira.create_story(
            epic_key=epic.key,
            summary=summary,
            description=str(desc),
            labels=labels,
        )
        created_keys.append(story_key)
        
        # Store subtasks in Story description or as a comment for later processing
        subtasks_data = story_data.get("subtasks") or []
        if subtasks_data:
            # Add subtasks as a structured comment that we can parse later
            subtasks_json = json.dumps(subtasks_data, indent=2)
            ctx.jira.add_comment(
                story_key,
                f"[STORY BREAKDOWN]\n```json\n{subtasks_json}\n```"
            )
        
        # Assign Story to AI in Backlog - it will be picked up for breakdown
        ctx.jira.assign_issue(story_key, settings.JIRA_AI_ACCOUNT_ID)

    if created_keys:
        ctx.jira.add_comment(
            epic.key,
            "AI created Stories from the approved plan:\n" + "\n".join([f"- {k}" for k in created_keys]),
        )
        return True
    
    return False


def _create_subtasks_from_story(ctx: Context, story: JiraIssue) -> None:
    """Create sub-tasks from Story breakdown comment."""
    # Look for [STORY BREAKDOWN] comment
    comments = ctx.jira.get_comments(story.key)
    subtasks_data = None
    
    for c in comments:
        body = c.get("body")
        if isinstance(body, dict):
            body_text = _extract_text_from_adf(body)
        elif isinstance(body, str):
            body_text = body
        else:
            continue
            
        if "[STORY BREAKDOWN]" in body_text:
            try:
                start = body_text.index("```json") + len("```json")
                end = body_text.index("```", start)
                subtasks_data = json.loads(body_text[start:end].strip())
                break
            except Exception:
                continue
    
    if not subtasks_data:
        ctx.jira.add_comment(story.key, "AI Runner could not find Story breakdown. Please add sub-tasks manually.")
        ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return

    created_keys = []
    for task in subtasks_data:
        summary = (task.get("summary") or "").strip()
        if not summary:
            continue
        desc = task.get("description") or ""
        is_independent = task.get("independent", False)
        
        labels = []
        if is_independent:
            labels.append("independent-pr")
        
        # Create subtask under Story
        key = ctx.jira.create_subtask(
            project_key=None,
            parent_key=story.key,
            summary=summary,
            description=str(desc),
            labels=labels if labels else None,
        )
        created_keys.append(key)
        # Assign to AI in Backlog
        ctx.jira.assign_issue(key, settings.JIRA_AI_ACCOUNT_ID)

    ctx.jira.add_comment(
        story.key,
        "AI created sub-tasks for this Story:\n" + "\n".join([f"- {k}" for k in created_keys]),
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

    try:
        plan_res: PlanResult = build_plan(issue)
        ctx.jira.add_comment(issue.key, plan_res.comment)
        ctx.jira.transition_to_status(issue.key, settings.JIRA_STATUS_PLAN_REVIEW)
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
    except Exception as e:
        print(f"ERROR in _handle_plan_parent: {e}")
        ctx.jira.add_comment(issue.key, f"AI Runner failed to generate plan: {e}")
        ctx.jira.transition_to_status(issue.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        raise


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


def _handle_epic_approved(ctx: Context, epic: JiraIssue) -> None:
    """Handle Epic approval - creates Stories from plan."""
    if epic.status != settings.JIRA_STATUS_SELECTED_FOR_DEV:
        return
    if epic.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return

    # Create Stories from Epic plan (v2 format)
    success = _create_stories_from_plan(ctx, epic)
    
    # Only transition if Stories were created successfully
    if success:
        ctx.jira.transition_to_status(epic.key, settings.JIRA_STATUS_IN_PROGRESS)
        ctx.jira.add_comment(epic.key, "AI Runner created Stories from the plan. Stories will be broken down into sub-tasks when approved.")


def _handle_story_approved(ctx: Context, story: JiraIssue) -> None:
    """Handle Story approval - creates sub-tasks and Story PR."""
    if story.status != settings.JIRA_STATUS_SELECTED_FOR_DEV:
        return
    if story.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return

    # Check for existing active subtasks
    all_subtasks = ctx.jira.get_subtasks(story.key)
    active_subtasks = [
        st for st in all_subtasks
        if ((st.get("fields") or {}).get("status") or {}).get("name") not in [settings.JIRA_STATUS_BLOCKED, settings.JIRA_STATUS_DONE]
    ]
    
    if not active_subtasks:
        # Create sub-tasks from Story breakdown
        _create_subtasks_from_story(ctx, story)
        
        # Refresh subtasks after creation
        all_subtasks = ctx.jira.get_subtasks(story.key)

    # Create Story branch and draft PR
    from .git_ops import checkout_repo, create_branch, create_pr
    
    story_branch = f"story/{story.key.lower()}"
    
    try:
        # Checkout repo and create Story branch
        checkout_repo(settings.REPO_WORKDIR, settings.REPO_SSH, settings.BASE_BRANCH)
        create_branch(settings.REPO_WORKDIR, story_branch)
        
        # Create draft PR with checklist of subtasks
        subtask_list = "\n".join([
            f"- [ ] {st.get('key')}: {(st.get('fields') or {}).get('summary')}" 
            for st in all_subtasks
        ])
        
        pr_body = f"""## Story: {story.key}

{story.description[:500] if story.description else 'No description'}

### Sub-tasks:
{subtask_list}

---
*This PR will be updated as sub-tasks are completed.*
"""
        
        pr_url = create_pr(
            settings.REPO_WORKDIR,
            title=f"{story.key}: {story.summary}",
            body=pr_body,
            base=settings.BASE_BRANCH,
        )
        
        if pr_url:
            ctx.jira.add_comment(story.key, f"Story PR created: {pr_url}")
    except Exception as e:
        ctx.jira.add_comment(story.key, f"Warning: Could not create Story PR: {e}")

    # Transition Story to In Progress
    ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_IN_PROGRESS)
    ctx.jira.add_comment(story.key, "AI Runner has started processing this Story.")

    # Start first subtask
    next_key = _pick_next_subtask_to_start(ctx, story.key)
    if next_key:
        ctx.jira.transition_to_status(next_key, settings.JIRA_STATUS_IN_PROGRESS)
        ctx.jira.add_comment(story.key, f"AI starting work on {next_key}.")


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


def _check_story_completion(ctx: Context, story: JiraIssue) -> None:
    """Check if all sub-tasks are done and mark Story PR as ready."""
    if story.issue_type != "Story":
        return
    
    if _all_subtasks_done(ctx, story.key):
        # TODO: Mark PR as ready for review via GitHub API
        # For now, just comment on the Story
        ctx.jira.add_comment(
            story.key,
            "✅ All sub-tasks completed! Story PR is ready for review."
        )
        ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_IN_TESTING)
        ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)


def _handle_subtask_done(ctx: Context, subtask: JiraIssue) -> None:
    if not subtask.is_subtask or not subtask.parent_key:
        return
    if subtask.status != settings.JIRA_STATUS_DONE:
        return
    
    # Check if parent is a Story - handle Story completion
    parent = _fetch_issue(ctx.jira, subtask.parent_key)
    if parent and parent.issue_type == "Story":
        _check_story_completion(ctx, parent)
    elif _all_subtasks_done(ctx, subtask.parent_key):
        # Legacy behavior for non-Story parents (Epics, etc.)
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

    if action.name == "PLAN_EPIC":
        _handle_plan_parent(ctx, issue)  # Reuse existing Epic planning
    elif action.name == "REVISE_PLAN":
        _handle_revise_plan(ctx, issue)
    elif action.name == "EPIC_APPROVED":
        _handle_epic_approved(ctx, issue)
    elif action.name == "STORY_APPROVED":
        _handle_story_approved(ctx, issue)
    elif action.name == "CHECK_STORY_COMPLETION":
        _check_story_completion(ctx, issue)
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
