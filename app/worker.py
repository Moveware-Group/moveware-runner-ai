from __future__ import annotations

import json
import time
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import settings, PARENT_PLAN_COMMENT_PREFIX
from .db import claim_next_run, init_db, update_run, add_event, save_plan, get_plan, add_progress_event, enqueue_run
from .executor import ExecutionResult, execute_subtask
from .jira import JiraClient
from .jira_adf import adf_to_plain_text
from .models import JiraIssue, parse_issue
from .planner import PlanResult, build_plan
from .router import Action, Router
from .repo_config import get_repo_for_issue
from .logger import ContextLogger, get_logger


def verify_code_integrity() -> None:
    """
    Verify critical files are valid Python before starting worker.
    
    This prevents the worker from starting if core files are corrupted,
    which can happen due to deployment errors or manual editing mistakes.
    
    Raises:
        RuntimeError: If any critical file has syntax errors
    """
    from pathlib import Path
    
    # Critical files that must be valid Python
    critical_files = [
        'app/git_ops.py',
        'app/executor.py', 
        'app/worker.py',
        'app/main.py',
        'app/db.py',
        'app/jira.py'
    ]
    
    project_root = Path(__file__).parent.parent
    
    for file_path in critical_files:
        full_path = project_root / file_path
        
        if not full_path.exists():
            raise RuntimeError(f"Code integrity check failed: {file_path} does not exist")
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                code = f.read()
                compile(code, str(full_path), 'exec')
        except SyntaxError as e:
            raise RuntimeError(
                f"Code integrity check failed: {file_path} has syntax error at line {e.lineno}: {e.msg}\n"
                f"This usually means the file was corrupted during deployment.\n"
                f"Fix: Run 'git checkout HEAD -- {file_path}' to restore from git."
            )
        except Exception as e:
            raise RuntimeError(f"Code integrity check failed: {file_path} could not be read: {e}")
    
    print(f"✓ Code integrity check passed ({len(critical_files)} files verified)")


@dataclass
class Context:
    jira: JiraClient
    router: Router


def _get_repo_settings(issue_key: str) -> dict:
    """
    Get repository settings for an issue.
    Falls back to environment variables if multi-repo config not found.
    
    Returns dict with: repo_ssh, repo_workdir, base_branch, repo_owner_slug, repo_name
    """
    repo = get_repo_for_issue(issue_key)
    
    if repo:
        return {
            "repo_ssh": repo.repo_ssh,
            "repo_workdir": repo.repo_workdir,
            "base_branch": repo.base_branch,
            "repo_owner_slug": repo.repo_owner_slug,
            "repo_name": repo.repo_name,
        }
    else:
        # Fallback to environment variables (legacy single-repo mode)
        return {
            "repo_ssh": settings.REPO_SSH,
            "repo_workdir": settings.REPO_WORKDIR,
            "base_branch": settings.BASE_BRANCH,
            "repo_owner_slug": settings.REPO_OWNER_SLUG,
            "repo_name": settings.REPO_NAME,
        }


def _to_issue(payload: Dict[str, Any]) -> Optional[JiraIssue]:
    issue = payload.get("issue") or {}
    fields = issue.get("fields") or {}
    key = issue.get("key")
    if not key:
        return None

    desc = fields.get("description")
    # Jira Cloud v3 returns description as Atlassian Document Format (ADF) object.
    # Convert ADF to plain text so Claude can understand it.
    if isinstance(desc, dict):
        desc_text = adf_to_plain_text(desc)
    elif isinstance(desc, str):
        desc_text = desc
    else:
        desc_text = ""

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


def _extract_all_human_feedback(jira: JiraClient, parent_key: str) -> str:
    """Extract ALL human comments from the Epic to provide full conversation context."""
    comments = jira.get_comments(parent_key)
    
    feedback_parts = []
    for c in comments:
        author = c.get("author", {})
        author_id = author.get("accountId") if isinstance(author, dict) else None
        
        # Skip AI's own comments
        if author_id == settings.JIRA_AI_ACCOUNT_ID:
            continue
        
        # Get comment body
        body = c.get("body", "")
        if isinstance(body, dict):
            body_text = adf_to_plain_text(body)
        else:
            body_text = body
            
        if body_text.strip():
            # Get timestamp for context
            created = c.get("created", "")
            author_name = author.get("displayName", "User") if isinstance(author, dict) else "User"
            
            feedback_parts.append(f"[{created}] {author_name}:\n{body_text.strip()}")
    
    if not feedback_parts:
        return ""
    
    return "\n\n---\n\n".join(feedback_parts)


def _create_stories_from_plan(ctx: Context, epic: JiraIssue) -> bool:
    """Create Stories from Epic plan. Returns True if successful."""
    # Retrieve plan from database
    plan = get_plan(epic.key)
    if not plan:
        ctx.jira.add_comment(epic.key, "AI Runner could not find a plan for this Epic. Please move to Backlog to generate a plan.")
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
            body_text = adf_to_plain_text(body)
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
    # pick first Backlog or Selected for Development assigned to AI
    for st in subtasks:
        fields = st.get("fields") or {}
        status = (fields.get("status") or {}).get("name")
        assignee = fields.get("assignee") or {}
        assignee_id = assignee.get("accountId") if isinstance(assignee, dict) else None
        if status in (settings.JIRA_STATUS_BACKLOG, settings.JIRA_STATUS_SELECTED_FOR_DEV) and assignee_id == settings.JIRA_AI_ACCOUNT_ID:
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


def _handle_plan_parent(ctx: Context, issue: JiraIssue, run_id: Optional[int] = None) -> None:
    if not _is_parent(issue):
        return
    if not issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID:
        return

    try:
        plan_res: PlanResult = build_plan(issue, run_id=run_id)
        # Save plan to database
        save_plan(issue.key, plan_res.plan_data)
        ctx.jira.add_comment(issue.key, plan_res.comment)
        ctx.jira.transition_to_status(issue.key, settings.JIRA_STATUS_PLAN_REVIEW)
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
    except Exception as e:
        print(f"ERROR in _handle_plan_parent: {e}")
        ctx.jira.add_comment(issue.key, f"AI Runner failed to generate plan: {e}")
        ctx.jira.transition_to_status(issue.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        raise


def _handle_revise_plan(ctx: Context, issue: JiraIssue, run_id: Optional[int] = None) -> None:
    """Handle plan revision request - human added feedback and assigned back to AI."""
    if not _is_parent(issue):
        return
    if issue.status != settings.JIRA_STATUS_PLAN_REVIEW:
        return
    if issue.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    
    # Extract ALL human feedback from the entire conversation
    feedback = _extract_all_human_feedback(ctx.jira, issue.key)
    
    if not feedback:
        # No feedback found - just acknowledge
        ctx.jira.add_comment(
            issue.key,
            "AI Runner did not find any feedback comments to revise the plan. Please add a comment with your requested changes."
        )
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return
    
    # Load previous plan so the AI knows which questions were already asked and answered
    previous_plan = get_plan(issue.key)
    
    # Generate revised plan with feedback and previous questions (so it doesn't re-ask)
    plan_res: PlanResult = build_plan(
        issue,
        revision_feedback=feedback,
        previous_plan=previous_plan,
        run_id=run_id,
    )
    
    # Save revised plan to database
    save_plan(issue.key, plan_res.plan_data)
    
    # Post revised plan
    ctx.jira.add_comment(issue.key, plan_res.comment)
    
    # Keep in Plan Review and reassign to human
    ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)


def _handle_epic_approved(ctx: Context, epic: JiraIssue) -> None:
    """Handle Epic approval - creates Stories from plan."""
    # Accept both Selected for Dev and In Progress (user may have moved directly to In Progress)
    if epic.status not in (settings.JIRA_STATUS_SELECTED_FOR_DEV, settings.JIRA_STATUS_IN_PROGRESS):
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

    # Transition Story to In Progress first
    ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_IN_PROGRESS)
    ctx.jira.add_comment(story.key, "AI Runner has started processing this Story. PR will be created after first subtask commits.")

    # Create Story branch (but don't create PR yet - need commits first)
    from .git_ops import checkout_repo, create_branch
    
    # Get repository configuration for this issue (supports multi-repo)
    repo_settings = _get_repo_settings(story.key)
    
    story_branch = f"story/{story.key.lower()}"
    
    try:
        # Checkout repo and create Story branch
        checkout_repo(repo_settings["repo_workdir"], repo_settings["repo_ssh"], repo_settings["base_branch"])
        create_branch(repo_settings["repo_workdir"], story_branch)
        ctx.jira.add_comment(story.key, f"Created Story branch: {story_branch} in {repo_settings['repo_name']}")
    except Exception as e:
        error_msg = f"Warning: Could not create Story branch: {e}"
        print(f"ERROR in _handle_story_approved: {error_msg}")
        ctx.jira.add_comment(story.key, error_msg)

    # Start first subtask: transition to In Progress, assign to AI, and enqueue a run
    # (Jira "Issue assigned" only fires on assignee change, so we enqueue to ensure work starts)
    next_key = _pick_next_subtask_to_start(ctx, story.key)
    if next_key:
        ctx.jira.transition_to_status(next_key, settings.JIRA_STATUS_IN_PROGRESS)
        ctx.jira.assign_issue(next_key, settings.JIRA_AI_ACCOUNT_ID)
        ctx.jira.add_comment(story.key, f"AI starting work on {next_key}.")
        # Enqueue run so worker picks up the subtask (avoids relying on Jira webhook for status change)
        enqueue_run(issue_key=next_key, payload={"issue_key": next_key})
    else:
        ctx.jira.add_comment(story.key, "Warning: No subtasks found to start.")


def _handle_execute_subtask(ctx: Context, subtask: JiraIssue, run_id: Optional[int] = None) -> None:
    if not subtask.is_subtask:
        return
    if subtask.status != settings.JIRA_STATUS_IN_PROGRESS:
        return
    if subtask.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    if not subtask.parent_key:
        return

    # Execute
    result: ExecutionResult = execute_subtask(subtask, run_id)

    # Comment + transition + assign
    ctx.jira.add_comment(subtask.key, result.jira_comment)
    ctx.jira.transition_to_status(subtask.key, settings.JIRA_STATUS_IN_TESTING)
    ctx.jira.assign_issue(subtask.key, settings.JIRA_HUMAN_ACCOUNT_ID)

    # Check if parent is a Story and if PR needs to be created
    parent = _fetch_issue(ctx.jira, subtask.parent_key)
    if parent and parent.issue_type == "Story" and result.branch.startswith("story/"):
        # Check if PR already exists for this Story
        from .git_ops import create_pr
        
        # Get repository configuration for the parent Story
        repo_settings = _get_repo_settings(parent.key)
        
        try:
            # Get all subtasks for the Story to build checklist
            all_subtasks = ctx.jira.get_subtasks(subtask.parent_key)
            subtask_list = "\n".join([
                f"- [ ] {st.get('key')}: {(st.get('fields') or {}).get('summary')}" 
                for st in all_subtasks
            ])
            
            pr_body = f"""## Story: {parent.key}

{parent.description[:500] if parent.description else 'No description'}

### Sub-tasks:
{subtask_list}

---
*This PR will be updated as sub-tasks are completed.*
"""
            
            # Try to create PR (will succeed only on first subtask)
            pr_url = create_pr(
                repo_settings["repo_workdir"],
                title=f"{parent.key}: {parent.summary}",
                body=pr_body,
                base=repo_settings["base_branch"],
            )
            
            if pr_url and "already exists" not in pr_url.lower():
                ctx.jira.add_comment(parent.key, f"Story PR created: {pr_url}")
        except Exception as e:
            # PR might already exist or other error - log but don't fail
            error_msg = str(e).lower()
            if "already exists" not in error_msg and "no commits" not in error_msg:
                print(f"Note: Could not create/update Story PR: {e}")

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
    add_progress_event(run_id, "claimed", f"Processing {issue_key}", {})
    
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
    
    add_progress_event(run_id, "analyzing", f"Determining action for {issue_key}", {"issue_type": issue.issue_type})
    action: Action = ctx.router.decide(issue)
    add_event(run_id, "info", f"Router decided action: {action.name}", {"reason": action.reason})

    if action.name == "NOOP":
        diag = {
            "issue_type": issue.issue_type,
            "status": issue.status,
            "expected_status_for_story": settings.JIRA_STATUS_SELECTED_FOR_DEV,
            "assignee_match": issue.assignee_account_id == settings.JIRA_AI_ACCOUNT_ID,
            "assignee_id": str(issue.assignee_account_id)[:8] + "..." if issue.assignee_account_id else None,
            "expected_ai_id": str(settings.JIRA_AI_ACCOUNT_ID)[:8] + "..." if settings.JIRA_AI_ACCOUNT_ID else None,
        }
        add_event(run_id, "info", "No action taken - router conditions not met", diag)
        print(f"[NOOP] {issue_key}: type={issue.issue_type} status={issue.status!r} (expected {settings.JIRA_STATUS_SELECTED_FOR_DEV!r}) "
              f"assignee_match={diag['assignee_match']}")

    if action.name == "PLAN_EPIC":
        add_progress_event(run_id, "planning", "Generating Epic plan", {})
        _handle_plan_parent(ctx, issue, run_id)  # Reuse existing Epic planning
    elif action.name == "REVISE_PLAN":
        add_progress_event(run_id, "planning", "Revising plan based on feedback", {})
        _handle_revise_plan(ctx, issue, run_id)
    elif action.name == "EPIC_APPROVED":
        add_progress_event(run_id, "executing", "Creating Stories from Epic plan", {})
        _handle_epic_approved(ctx, issue)
    elif action.name == "STORY_APPROVED":
        add_progress_event(run_id, "executing", "Creating sub-tasks and Story PR", {})
        _handle_story_approved(ctx, issue)
    elif action.name == "CHECK_STORY_COMPLETION":
        add_progress_event(run_id, "analyzing", "Checking Story completion", {})
        _check_story_completion(ctx, issue)
    elif action.name == "EXECUTE_SUBTASK":
        add_progress_event(run_id, "executing", f"Implementing {issue_key}", {})
        _handle_execute_subtask(ctx, issue, run_id)
    elif action.name == "SUBTASK_DONE":
        add_progress_event(run_id, "analyzing", "Checking parent Story status", {})
        _handle_subtask_done(ctx, issue)
    
    add_progress_event(run_id, "completed", "Run completed successfully", {})
    update_run(run_id, status="completed", locked_by=None, locked_at=None)


def worker_loop(poll_interval_seconds: float = 2.0, worker_id: str = "worker-1", use_smart_queue: Optional[bool] = None) -> None:
    """
    Main worker loop that claims and processes runs.
    
    Args:
        poll_interval_seconds: Seconds between polls
        worker_id: Worker identifier
        use_smart_queue: If True, use priority queue. If None, reads from USE_SMART_QUEUE env var (default: True)
    """
    # Verify code integrity before starting (prevents startup with corrupted files)
    verify_code_integrity()
    
    init_db()
    ctx = Context(jira=JiraClient(), router=Router())
    
    # Initialize logger
    logger = get_logger()
    
    # Determine which claim function to use
    if use_smart_queue is None:
        use_smart_queue = os.getenv("USE_SMART_QUEUE", "true").lower() in ("true", "1", "yes")
    
    if use_smart_queue:
        from .queue_manager import claim_next_run_smart
        claim_func = lambda w: claim_next_run_smart(w, max_concurrent_per_repo=1, respect_priorities=True)
        logger.info(f"Worker {worker_id} started with SMART QUEUE (priorities + conflict avoidance), polling every {poll_interval_seconds}s")
    else:
        claim_func = claim_next_run
        logger.info(f"Worker {worker_id} started with BASIC QUEUE (FIFO), polling every {poll_interval_seconds}s")

    poll_skips = 0
    while True:
        result = claim_func(worker_id)
        if not result:
            poll_skips += 1
            # Log every ~60s so we know worker is alive when queue appears stuck
            if poll_skips % max(1, int(60 / poll_interval_seconds)) == 0:
                logger.info(f"Polling (no run to claim yet, {poll_skips} skips)")
            time.sleep(poll_interval_seconds)
            continue

        poll_skips = 0
        run_id, issue_key, payload = result
        
        # Create context logger for this run
        run_logger = ContextLogger(run_id=run_id, issue_key=issue_key, worker_id=worker_id)
        run_logger.info(f"Claimed run for processing")
        
        try:
            process_run(ctx, run_id, issue_key, payload)
            run_logger.info(f"Run completed successfully")
        except Exception as e:
            error_msg = f"ERROR processing run {run_id}: {e}"
            run_logger.error(error_msg, exc_info=True)
            add_progress_event(run_id, "failed", f"Error: {str(e)[:100]}", {})
            add_event(run_id, "error", str(e), {})
            update_run(run_id, status="failed", last_error=str(e), locked_by=None, locked_at=None)


if __name__ == "__main__":
    worker_loop()
