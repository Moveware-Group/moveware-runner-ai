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
    worker_id: str = "worker-1"


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
    from .story_creation_tracker import were_stories_already_created, mark_stories_created
    
    # CRITICAL: Check database first (more reliable than Jira API)
    already_created, existing_count = were_stories_already_created(epic.key)
    if already_created:
        print(f"🛑 Epic {epic.key} already has Stories created (DB flag set, {existing_count} Stories)")
        print(f"   Skipping creation to prevent infinite loop")
        ctx.jira.add_comment(
            epic.key,
            f"✅ Stories were already created for this Epic ({existing_count} Stories).\n\n"
            "This is a duplicate Story creation request (webhook retry or worker restart).\n"
            "If you need to regenerate Stories, please:\n"
            "1. Delete all existing Stories manually\n"
            "2. Contact admin to clear the Epic flag in the database"
        )
        return True  # Return True because Stories exist
    
    # FALLBACK: Also check via Jira API (in case DB flag was cleared)
    existing_stories = ctx.jira.get_stories_for_epic(epic.key)
    if existing_stories and len(existing_stories) > 0:
        print(f"⚠️  Epic {epic.key} already has {len(existing_stories)} Stories (found via Jira API)")
        print(f"   Marking in database and skipping creation")
        # Mark in database for future checks
        mark_stories_created(epic.key, len(existing_stories), ctx.worker_id)
        ctx.jira.add_comment(
            epic.key,
            f"Stories already exist for this Epic ({len(existing_stories)} found). "
            "Skipping creation to prevent duplicates."
        )
        return True
    
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
    
    # Add safety limit to prevent runaway creation
    MAX_STORIES_PER_EPIC = 50
    if len(stories) > MAX_STORIES_PER_EPIC:
        print(f"⚠️  Plan has {len(stories)} stories, which exceeds safety limit of {MAX_STORIES_PER_EPIC}")
        ctx.jira.add_comment(
            epic.key,
            f"⚠️ Plan has {len(stories)} stories, which seems excessive (limit: {MAX_STORIES_PER_EPIC}).\n\n"
            "This might indicate a plan generation error. Please review the plan and regenerate if needed."
        )
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
            try:
                ctx.jira.add_comment(
                    story_key,
                    f"[STORY BREAKDOWN]\n```json\n{subtasks_json}\n```"
                )
                print(f"✅ Added subtasks breakdown comment to {story_key} ({len(subtasks_data)} subtasks)")
            except Exception as e:
                print(f"⚠️  Warning: Could not add subtasks comment to {story_key}: {e}")
                # Fallback: Store in database for later retrieval
                from .planner import save_story_breakdown
                save_story_breakdown(story_key, subtasks_data)
                print(f"✅ Stored subtasks in database as fallback for {story_key}")
        else:
            print(f"⚠️  Warning: No subtasks in plan for Story {story_key}")
        
        # Assign Story to AI in Backlog - it will be picked up for breakdown
        ctx.jira.assign_issue(story_key, settings.JIRA_AI_ACCOUNT_ID)

    if created_keys:
        # Mark Stories created in database to prevent duplicates
        from .story_creation_tracker import mark_stories_created
        mark_stories_created(epic.key, len(created_keys), ctx.worker_id)
        
        ctx.jira.add_comment(
            epic.key,
            "AI created Stories from the approved plan:\n" + "\n".join([f"- {k}" for k in created_keys]),
        )
        
        # 🚀 AUTO-START FIRST STORY (Sequential Processing) - if enabled
        if settings.AUTO_START_NEXT_STORY and created_keys:
            first_story_key = created_keys[0]
            print(f"🚀 Auto-starting first Story: {first_story_key}")
            
            try:
                # Move first Story to Selected for Development
                ctx.jira.transition_to_status(first_story_key, settings.JIRA_STATUS_SELECTED_FOR_DEV)
                ctx.jira.assign_issue(first_story_key, settings.JIRA_AI_ACCOUNT_ID)
                
                # Enqueue it for processing
                from .db import enqueue_run
                enqueue_run(issue_key=first_story_key, payload={"issue_key": first_story_key})
                
                ctx.jira.add_comment(
                    epic.key,
                    f"🚀 **Automatic Sequential Processing Started**\n\n"
                    f"Starting with {first_story_key}. Other Stories will be processed automatically "
                    f"when this one completes.\n\n"
                    f"Progress: 1/{len(created_keys)} Stories"
                )
                
                print(f"✅ Enqueued {first_story_key} for automatic processing")
            except Exception as e:
                print(f"⚠️  Could not auto-start first Story: {e}")
                ctx.jira.add_comment(
                    epic.key,
                    f"⚠️ Could not auto-start first Story ({first_story_key}): {e}\n\n"
                    f"Please manually move it to 'Selected for Development'."
                )
        elif not settings.AUTO_START_NEXT_STORY and created_keys:
            # Auto-start disabled - notify user to manually start
            ctx.jira.add_comment(
                epic.key,
                f"✅ Stories created. Auto-start is disabled.\n\n"
                f"To begin processing, manually move {created_keys[0]} to 'Selected for Development'."
            )
        
        return True
    
    return False


def _create_subtasks_from_story(ctx: Context, story: JiraIssue) -> None:
    """Create sub-tasks from Story breakdown comment."""
    # Try to get from Jira comment first
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
                print(f"✅ Found Story breakdown in Jira comment for {story.key}")
                break
            except Exception as e:
                print(f"⚠️  Failed to parse Story breakdown from comment: {e}")
                continue
    
    # Fallback: Try database
    if not subtasks_data:
        print(f"⚠️  No breakdown comment found for {story.key}, checking database...")
        from .planner import get_story_breakdown
        subtasks_data = get_story_breakdown(story.key)
        if subtasks_data:
            print(f"✅ Found Story breakdown in database for {story.key}")
    
    if not subtasks_data:
        print(f"⚠️  No Story breakdown found for {story.key}. Generating plan now...")
        # Generate a plan for this Story (treating it like a standalone task)
        from .planner import build_plan
        try:
            plan_result = build_plan(story)
            
            # Extract subtasks from the generated plan
            plan_data = plan_result.plan_data
            if "stories" in plan_data and len(plan_data["stories"]) > 0:
                # Plan has stories - use the first story's subtasks
                subtasks_data = plan_data["stories"][0].get("subtasks", [])
            elif "subtasks" in plan_data:
                # Plan has direct subtasks
                subtasks_data = plan_data["subtasks"]
            else:
                # No subtasks in plan - block the Story
                ctx.jira.add_comment(story.key, "⚠️ AI Runner could not generate a valid plan for this Story. Please add sub-tasks manually.")
                ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_BLOCKED)
                ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
                return
            
            # Save the breakdown to both Jira and database
            from .planner import save_story_breakdown
            save_story_breakdown(story.key, subtasks_data)
            
            # Also add as comment to Jira
            subtasks_json = json.dumps(subtasks_data, indent=2)
            ctx.jira.add_comment(story.key, f"[STORY BREAKDOWN]\n\n```json\n{subtasks_json}\n```")
            
            print(f"✅ Generated plan for {story.key} with {len(subtasks_data)} subtasks")
            
        except Exception as e:
            print(f"❌ Failed to generate plan for {story.key}: {e}")
            ctx.jira.add_comment(story.key, f"⚠️ AI Runner failed to generate plan: {e}\n\nPlease add sub-tasks manually.")
            ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_BLOCKED)
            ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
            return
    
    # Now we should have subtasks_data (either from comment, database, or newly generated)
    if not subtasks_data:
        ctx.jira.add_comment(story.key, "⚠️ AI Runner could not find or generate Story breakdown. Please add sub-tasks manually.")
        ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return
    
    # Add safety limit to prevent runaway creation
    MAX_SUBTASKS_PER_STORY = 30
    if len(subtasks_data) > MAX_SUBTASKS_PER_STORY:
        print(f"⚠️  Story breakdown has {len(subtasks_data)} subtasks, which exceeds safety limit of {MAX_SUBTASKS_PER_STORY}")
        ctx.jira.add_comment(
            story.key,
            f"⚠️ Story breakdown has {len(subtasks_data)} subtasks, which seems excessive (limit: {MAX_SUBTASKS_PER_STORY}).\n\n"
            "This might indicate a breakdown error. Please review and regenerate if needed."
        )
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

    # Check if this is a restoration task and warn if missing critical info
    from .restoration_detector import detect_restoration_task, check_restoration_quality
    
    restoration_context = detect_restoration_task(issue.summary, issue.description or "")
    
    if restoration_context.is_restoration and restoration_context.warnings:
        warning_comment = (
            "## ⚠️ Restoration Task Detected - Missing Information\n\n"
            "This appears to be a restoration task (bringing back removed functionality), "
            "but some critical information is missing that could help the AI succeed:\n\n"
        )
        for warning in restoration_context.warnings:
            warning_comment += f"- {warning}\n"
        
        recommendations = check_restoration_quality(issue.description or "", restoration_context)
        if recommendations:
            warning_comment += "\n**Recommendations:**\n"
            for rec in recommendations:
                warning_comment += f"- {rec}\n"
        
        warning_comment += (
            "\n\n*The AI will still attempt to generate a plan, but providing the above "
            "information will significantly improve the results.*"
        )
        
        # Post warning comment but continue with planning
        try:
            ctx.jira.add_comment(issue.key, warning_comment)
        except Exception as e:
            print(f"⚠️  Could not post restoration warning: {e}")
    
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


def _handle_story_approved(ctx: Context, story: JiraIssue, skip_rework_detection: bool = False) -> None:
    """
    Handle Story approval - creates sub-tasks and Story PR.
    Also handles Story-level rework (when subtasks exist but Story moved back for fixes).
    
    Args:
        skip_rework_detection: If True, skip rework detection (used when called from _handle_rework_story)
    """
    # Accept both Selected for Dev and In Progress (user may have moved directly to In Progress)
    if story.status not in (settings.JIRA_STATUS_SELECTED_FOR_DEV, settings.JIRA_STATUS_IN_PROGRESS):
        return
    if story.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return

    # Check for existing subtasks (including Done and Blocked)
    all_subtasks = ctx.jira.get_subtasks(story.key)
    
    # Check if this is a REWORK scenario (subtasks exist AND Story was moved back)
    # Detect by: subtasks exist AND at least one is in "In Testing" or "Done"
    # Skip this check if called from rework handler to prevent infinite loop
    if not skip_rework_detection and all_subtasks and len(all_subtasks) > 0:
        statuses = [
            ((st.get("fields") or {}).get("status") or {}).get("name")
            for st in all_subtasks
        ]
        
        # If ANY subtask is in In Testing or Done, this is likely a rework
        is_rework = any(s in [settings.JIRA_STATUS_IN_TESTING, settings.JIRA_STATUS_DONE] for s in statuses)
        
        if is_rework:
            print(f"🔄 REWORK DETECTED for Story {story.key} - subtasks exist and were previously completed")
            # Delegate to rework handler
            _handle_rework_story(ctx, story, run_id=None)
            return
        else:
            # Subtasks exist but all in Backlog/In Progress - just continue normal flow
            print(f"Story {story.key} already has {len(all_subtasks)} sub-task(s), checking progress")
    
    if not all_subtasks or len(all_subtasks) == 0:
        # No subtasks exist yet - create them from Story breakdown
        _create_subtasks_from_story(ctx, story)
        
        # Refresh subtasks after creation
        all_subtasks = ctx.jira.get_subtasks(story.key)
    
    # Find active (not Done, not Blocked) subtasks
    active_subtasks = [
        st for st in all_subtasks
        if ((st.get("fields") or {}).get("status") or {}).get("name") not in [settings.JIRA_STATUS_BLOCKED, settings.JIRA_STATUS_DONE]
    ]

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
    # Allow In Progress (normal) or Blocked (human answered questions, AI retrying)
    if subtask.status not in (settings.JIRA_STATUS_IN_PROGRESS, settings.JIRA_STATUS_BLOCKED):
        return
    if subtask.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    if not subtask.parent_key:
        return

    # If Blocked, move to In Progress so the workflow is correct
    if subtask.status == settings.JIRA_STATUS_BLOCKED:
        ctx.jira.transition_to_status(subtask.key, settings.JIRA_STATUS_IN_PROGRESS)

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
    """
    Check if all sub-tasks are done and mark Story PR as ready.
    If Story is part of an Epic, automatically start next Story in sequence.
    """
    if story.issue_type != "Story":
        return
    
    if _all_subtasks_done(ctx, story.key):
        # Mark this Story as complete
        ctx.jira.add_comment(
            story.key,
            "✅ All sub-tasks completed! Story PR is ready for review."
        )
        ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_IN_TESTING)
        ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        
        # 🚀 AUTO-START NEXT STORY (Sequential Processing) - if enabled
        # Check if this Story is part of an Epic
        if settings.AUTO_START_NEXT_STORY and story.parent_key:
            epic_key = story.parent_key
            print(f"🔄 Story {story.key} completed, checking for next Story in Epic {epic_key}")
            
            try:
                # Get all Stories in this Epic
                all_stories = ctx.jira.get_stories_for_epic(epic_key)
                
                if all_stories:
                    # Find Stories that are still in Backlog (not started yet)
                    backlog_stories = [
                        s for s in all_stories
                        if ((s.get("fields") or {}).get("status") or {}).get("name") == settings.JIRA_STATUS_BACKLOG
                    ]
                    
                    # Also check for Stories assigned to AI (in case status is different)
                    ai_assignee = settings.JIRA_AI_ACCOUNT_ID
                    pending_stories = [
                        s for s in backlog_stories
                        if ((s.get("fields") or {}).get("assignee") or {}).get("accountId") == ai_assignee
                    ]
                    
                    if pending_stories:
                        # Start the next Story
                        next_story = pending_stories[0]
                        next_story_key = next_story.get("key")
                        
                        print(f"🚀 Auto-starting next Story: {next_story_key}")
                        
                        # Move to Selected for Development
                        ctx.jira.transition_to_status(next_story_key, settings.JIRA_STATUS_SELECTED_FOR_DEV)
                        ctx.jira.assign_issue(next_story_key, settings.JIRA_AI_ACCOUNT_ID)
                        
                        # Enqueue for processing
                        from .db import enqueue_run
                        enqueue_run(issue_key=next_story_key, payload={"issue_key": next_story_key})
                        
                        # Calculate progress
                        total_stories = len(all_stories)
                        completed_stories = len([
                            s for s in all_stories
                            if ((s.get("fields") or {}).get("status") or {}).get("name") in [
                                settings.JIRA_STATUS_IN_TESTING,
                                settings.JIRA_STATUS_DONE
                            ]
                        ])
                        
                        # Update Epic with progress
                        ctx.jira.add_comment(
                            epic_key,
                            f"📊 **Sequential Processing Progress**\n\n"
                            f"✅ Completed: {story.key}\n"
                            f"🚀 Starting: {next_story_key}\n\n"
                            f"Progress: {completed_stories}/{total_stories} Stories completed"
                        )
                        
                        print(f"✅ Next Story {next_story_key} queued ({completed_stories}/{total_stories} complete)")
                        
                    else:
                        # No more Stories to process - Epic is complete!
                        print(f"🎉 All Stories completed for Epic {epic_key}")
                        
                        # Check if ALL Stories are done (not just in testing)
                        all_done = all(
                            ((s.get("fields") or {}).get("status") or {}).get("name") == settings.JIRA_STATUS_DONE
                            for s in all_stories
                        )
                        
                        total_stories = len(all_stories)
                        in_testing = len([
                            s for s in all_stories
                            if ((s.get("fields") or {}).get("status") or {}).get("name") == settings.JIRA_STATUS_IN_TESTING
                        ])
                        
                        if all_done:
                            # All Stories are Done - mark Epic as Done
                            ctx.jira.transition_to_status(epic_key, settings.JIRA_STATUS_DONE)
                            ctx.jira.add_comment(
                                epic_key,
                                f"🎉 **Epic Complete!**\n\n"
                                f"All {total_stories} Stories have been completed and tested.\n\n"
                                f"Epic is now marked as Done."
                            )
                            print(f"✅ Epic {epic_key} marked as Done")
                        else:
                            # Stories in testing - Epic stays in In Progress
                            ctx.jira.add_comment(
                                epic_key,
                                f"📊 **All Stories Processed**\n\n"
                                f"All {total_stories} Stories have been implemented.\n"
                                f"{in_testing} Story/Stories currently in testing.\n\n"
                                f"Epic will be marked Done once all Stories are approved."
                            )
                            print(f"ℹ️  Epic {epic_key} - all Stories processed, {in_testing} in testing")
                
            except Exception as e:
                print(f"⚠️  Could not auto-start next Story: {e}")
                # Don't fail - just log the error
        elif not settings.AUTO_START_NEXT_STORY and story.parent_key:
            # Auto-start disabled but Story is part of Epic - just update progress
            epic_key = story.parent_key
            try:
                all_stories = ctx.jira.get_stories_for_epic(epic_key)
                if all_stories:
                    total_stories = len(all_stories)
                    completed_stories = len([
                        s for s in all_stories
                        if ((s.get("fields") or {}).get("status") or {}).get("name") in [
                            settings.JIRA_STATUS_IN_TESTING,
                            settings.JIRA_STATUS_DONE
                        ]
                    ])
                    
                    # Find remaining backlog stories
                    backlog_stories = [
                        s for s in all_stories
                        if ((s.get("fields") or {}).get("status") or {}).get("name") == settings.JIRA_STATUS_BACKLOG
                    ]
                    
                    if backlog_stories:
                        next_story_key = backlog_stories[0].get("key")
                        ctx.jira.add_comment(
                            epic_key,
                            f"📊 **Story Progress Update**\n\n"
                            f"✅ Completed: {story.key}\n\n"
                            f"Progress: {completed_stories}/{total_stories} Stories completed\n\n"
                            f"Next Story: {next_story_key} (awaiting manual start)"
                        )
            except Exception as e:
                print(f"⚠️  Could not update Epic progress: {e}")


def _handle_rework_story(ctx: Context, story: JiraIssue, run_id: Optional[int] = None) -> None:
    """
    Handle when tester finds issues with entire Story and moves it back for rework.
    
    Workflow:
    1. Tester moves Story from "In Testing" to "Selected for Development"
    2. Tester assigns back to AI Runner
    3. Tester adds comment explaining what's wrong with the Story
    4. AI Runner can either:
       - Create new subtasks with different approach
       - Mark specific subtasks to redo
       - Fix existing implementation
    """
    if story.issue_type != "Story":
        return
    
    # Handle if in Needs Rework or Selected for Dev (backward compatibility)
    if story.status not in (settings.JIRA_STATUS_NEEDS_REWORK, settings.JIRA_STATUS_SELECTED_FOR_DEV):
        return
    if story.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    
    print(f"🔄 Story-level rework request detected for {story.key}")
    
    # Get human feedback from comments
    from app.jira_adf import adf_to_plain_text
    comments = ctx.jira.get_comments(story.key)
    
    # Check if rework was already processed (to prevent infinite loop)
    rework_already_processed = False
    for comment in comments:
        author = comment.get("author", {})
        author_id = author.get("accountId") if isinstance(author, dict) else None
        
        # Check AI's own comments for the marker
        if author_id == settings.JIRA_AI_ACCOUNT_ID:
            body = comment.get("body")
            if isinstance(body, dict):
                text = adf_to_plain_text(body)
            elif isinstance(body, str):
                text = body
            else:
                continue
            
            if "[REWORK_PROCESSED]" in text:
                rework_already_processed = True
                print(f"⚠️  Rework was already processed for {story.key}, skipping to prevent loop")
                break
    
    if rework_already_processed:
        # Rework was already processed - assign back to human to review progress
        ctx.jira.add_comment(
            story.key,
            f"ℹ️  Rework was already initiated. Please review the new subtasks or provide additional feedback if needed."
        )
        ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        return
    
    human_feedback = []
    for comment in comments:
        author = comment.get("author", {})
        author_id = author.get("accountId") if isinstance(author, dict) else None
        
        # Skip AI's own comments
        if author_id == settings.JIRA_AI_ACCOUNT_ID:
            continue
        
        body = comment.get("body")
        if isinstance(body, dict):
            text = adf_to_plain_text(body)
        elif isinstance(body, str):
            text = body
        else:
            continue
        
        human_feedback.append(text)
    
    rework_feedback = ""
    if human_feedback:
        # Take last 2 comments as feedback
        rework_feedback = "\n\n---\n\n".join(human_feedback[-2:])
        print(f"📝 Found Story rework feedback ({len(human_feedback)} comments)")
    
    # Post acknowledgment
    ctx.jira.add_comment(
        story.key,
        f"🔄 **Story Rework Initiated**\n\n"
        f"I'll review the feedback and determine the best approach:\n"
        f"- If specific subtasks need fixes, I'll mark them for rework\n"
        f"- If the approach was wrong, I'll create new subtasks\n"
        f"- If just missing features, I'll add new subtasks\n\n"
        f"Working on this now..."
    )
    
    # Analyze feedback to determine if we need NEW subtasks or to fix existing ones
    feedback_lower = rework_feedback.lower() if rework_feedback else ""
    keywords = [
        "missing", "wasn't implemented", "not implemented", "didn't implement",
        "no ui", "no interface", "where is", "don't see", "dont see", "not seeing",
        "doesnt have", "doesn't have", "no button", "no tab", "no form"
    ]
    needs_new_subtasks = any(keyword in feedback_lower for keyword in keywords)
    
    # Debug logging
    if needs_new_subtasks:
        matched_keywords = [kw for kw in keywords if kw in feedback_lower]
        print(f"🔍 Detected missing features (matched: {matched_keywords})")
    
    if needs_new_subtasks:
        # Feedback indicates missing features - generate new subtasks
        print(f"📋 Feedback indicates missing features - generating new subtasks for Story {story.key}")
        
        # Mark that we're processing this rework to prevent re-processing
        ctx.jira.add_comment(
            story.key,
            f"🔄 **Analyzing Missing Requirements**\n\n"
            f"Your feedback indicates features that weren't implemented:\n\n{rework_feedback[:800]}\n\n"
            f"I'll now generate additional subtasks to implement the missing functionality.\n\n"
            f"[REWORK_PROCESSED]"  # Marker to prevent re-processing
        )
        
        # Generate FRESH plan incorporating the rework feedback
        # Temporarily update Story description in Jira to include feedback
        try:
            # Create a modified version of the Story for planning
            from copy import deepcopy
            story_for_planning = deepcopy(story)
            
            # Enhance Story description to include the feedback
            original_desc = story.description or ""
            enhanced_desc = (
                f"{original_desc}\n\n"
                f"---\n\n"
                f"**REWORK FEEDBACK - Missing Features:**\n\n{rework_feedback}\n\n"
                f"**IMPORTANT:** Generate NEW subtasks ONLY for the missing functionality described above. "
                f"DO NOT regenerate existing subtasks."
            )
            story_for_planning.description = enhanced_desc
            
            # Generate plan with the enhanced description
            from .planner import build_plan
            plan_result = build_plan(story_for_planning)
            
            # Extract subtasks from the generated plan
            plan_data = plan_result.plan_data
            new_subtasks_data = []
            
            if "stories" in plan_data and len(plan_data["stories"]) > 0:
                # Plan has stories - use the first story's subtasks
                new_subtasks_data = plan_data["stories"][0].get("subtasks", [])
            elif "subtasks" in plan_data:
                # Plan has direct subtasks
                new_subtasks_data = plan_data["subtasks"]
            
            if new_subtasks_data:
                # Create the new subtasks in Jira
                created_keys = []
                for task in new_subtasks_data:
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
                    f"✅ **Created {len(created_keys)} new subtask(s) to implement missing features:**\n\n" + 
                    "\n".join([f"- {k}" for k in created_keys]) +
                    f"\n\nReview the subtasks and let me know if any adjustments are needed."
                )
                
                # Transition Story to In Progress and start first new subtask
                ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_IN_PROGRESS)
                
                if created_keys:
                    next_key = created_keys[0]
                    ctx.jira.transition_to_status(next_key, settings.JIRA_STATUS_IN_PROGRESS)
                    ctx.jira.assign_issue(next_key, settings.JIRA_AI_ACCOUNT_ID)
                    enqueue_run(issue_key=next_key, payload={"issue_key": next_key})
                    ctx.jira.add_comment(story.key, f"🚀 Starting work on {next_key}")
            else:
                # No subtasks generated
                ctx.jira.add_comment(
                    story.key,
                    f"⚠️  I couldn't generate subtasks from the feedback. Please provide more specific details about what's missing, "
                    f"or manually create subtasks for the missing features."
                )
                ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
                
        except Exception as e:
            print(f"⚠️  Could not create new subtasks: {e}")
            import traceback
            traceback.print_exc()
            ctx.jira.add_comment(
                story.key,
                f"⚠️  I had trouble generating subtasks automatically. Error: {str(e)}\n\n"
                f"Please manually create subtasks for the missing features or provide more detail."
            )
            ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
    else:
        # Feedback is about fixing existing implementation
        ctx.jira.add_comment(
            story.key,
            f"📋 **Rework Feedback Received:**\n\n{rework_feedback}\n\n"
            f"---\n\n"
            f"**Next steps:**\n"
            f"Please manually move the specific subtasks that need fixing to \"Needs Rework\" status.\n"
            f"I'll then apply your feedback to fix those specific issues."
        )
        
        ctx.jira.assign_issue(story.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        print(f"✅ Story rework acknowledged. Waiting for human to mark specific subtasks for rework.")


def _handle_rework_subtask(ctx: Context, subtask: JiraIssue, run_id: Optional[int] = None) -> None:
    """
    Handle when tester finds issues and moves subtask back for rework.
    
    Workflow:
    1. Tester moves subtask from "In Testing" to "Selected for Development"
    2. Tester assigns back to AI Runner
    3. Tester adds comment explaining what's wrong/missing
    4. AI Runner re-executes with the feedback
    """
    if not subtask.is_subtask:
        return
    
    # Handle if in Needs Rework, Selected for Development, or In Progress (assigned to AI)
    if subtask.status not in (settings.JIRA_STATUS_NEEDS_REWORK, settings.JIRA_STATUS_SELECTED_FOR_DEV, settings.JIRA_STATUS_IN_PROGRESS):
        return
    if subtask.assignee_account_id != settings.JIRA_AI_ACCOUNT_ID:
        return
    if not subtask.parent_key:
        return
    
    # Check if this is a rework scenario (was previously in In Testing)
    # We can detect this by checking comments or just proceed with execution
    
    print(f"🔄 Rework request detected for {subtask.key}")
    
    # Get human feedback from comments
    from app.jira_adf import adf_to_plain_text
    comments = ctx.jira.get_comments(subtask.key)
    
    human_feedback = []
    for comment in comments:
        author = comment.get("author", {})
        author_id = author.get("accountId") if isinstance(author, dict) else None
        
        # Skip AI's own comments
        if author_id == settings.JIRA_AI_ACCOUNT_ID:
            continue
        
        body = comment.get("body")
        if isinstance(body, dict):
            text = adf_to_plain_text(body)
        elif isinstance(body, str):
            text = body
        else:
            continue
        
        # Only include recent comments (likely the rework feedback)
        human_feedback.append(text)
    
    if human_feedback:
        # Take last 3 comments as feedback (most recent)
        recent_feedback = "\n\n---\n\n".join(human_feedback[-3:])
        print(f"📝 Found rework feedback ({len(human_feedback)} comments)")
        
        # Add feedback as a note in the subtask description (temporary)
        # This will be picked up by execute_subtask's context gathering
        original_desc = subtask.description or ""
        enhanced_desc = (
            f"{original_desc}\n\n"
            f"---\n\n"
            f"**REWORK REQUESTED - Issues Found in Testing:**\n\n"
            f"{recent_feedback}\n\n"
            f"**Please fix the above issues while preserving the existing implementation.**"
        )
        
        # Update description temporarily
        try:
            ctx.jira.update_issue_description(subtask.key, enhanced_desc)
        except Exception as e:
            print(f"⚠️  Could not update description, feedback will be in comments: {e}")
    
    # Transition to In Progress
    if subtask.status in (settings.JIRA_STATUS_NEEDS_REWORK, settings.JIRA_STATUS_SELECTED_FOR_DEV):
        ctx.jira.transition_to_status(subtask.key, settings.JIRA_STATUS_IN_PROGRESS)
    
    # Execute the subtask (will incorporate feedback from description/comments)
    result: ExecutionResult = execute_subtask(subtask, run_id)
    
    # Comment + transition + assign
    rework_comment = (
        "## 🔄 Rework Complete\n\n"
        "I've addressed the issues found in testing and updated the implementation.\n\n"
        f"{result.jira_comment}"
    )
    
    ctx.jira.add_comment(subtask.key, rework_comment)
    ctx.jira.transition_to_status(subtask.key, settings.JIRA_STATUS_IN_TESTING)
    ctx.jira.assign_issue(subtask.key, settings.JIRA_HUMAN_ACCOUNT_ID)
    
    # Update parent Story PR if needed
    parent = _fetch_issue(ctx.jira, subtask.parent_key)
    if parent and parent.issue_type == "Story" and result.branch.startswith("story/"):
        ctx.jira.add_comment(
            parent.key,
            f"Sub-task {subtask.key} rework completed. Story PR updated with fixes."
        )


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
    elif action.name == "REWORK_STORY":
        add_progress_event(run_id, "executing", f"Processing Story-level rework for {issue_key}", {})
        _handle_rework_story(ctx, issue, run_id)
    elif action.name == "STORY_APPROVED":
        add_progress_event(run_id, "executing", "Creating sub-tasks and Story PR", {})
        _handle_story_approved(ctx, issue)
    elif action.name == "CHECK_STORY_COMPLETION":
        add_progress_event(run_id, "analyzing", "Checking Story completion", {})
        _check_story_completion(ctx, issue)
    elif action.name == "REWORK_SUBTASK":
        add_progress_event(run_id, "executing", f"Reworking {issue_key} based on testing feedback", {})
        _handle_rework_subtask(ctx, issue, run_id)
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
    ctx = Context(jira=JiraClient(), router=Router(), worker_id=worker_id)
    
    # Initialize logger
    logger = get_logger()
    
    # Determine which claim function to use
    if use_smart_queue is None:
        use_smart_queue = os.getenv("USE_SMART_QUEUE", "true").lower() in ("true", "1", "yes")
    
    if use_smart_queue:
        from .queue_manager import claim_next_run_smart
        claim_func = lambda w: claim_next_run_smart(w, max_concurrent_per_repo=2, respect_priorities=True)
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
            add_progress_event(run_id, "failed", f"Error: {str(e)[:2000]}", {})
            add_event(run_id, "error", str(e), {})
            update_run(run_id, status="failed", last_error=str(e), locked_by=None, locked_at=None)


if __name__ == "__main__":
    worker_loop()
