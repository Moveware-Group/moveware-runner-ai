from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import settings
from .git_ops import checkout_repo, create_branch, commit_and_push, create_pr
from .llm_anthropic import AnthropicClient
from .models import JiraIssue


@dataclass
class ExecutionResult:
    branch: str
    pr_url: Optional[str]
    summary: str
    jira_comment: str


def _system_prompt() -> str:
    return (
        "You are a software engineer working inside a repository checked out on disk. "
        "You will be given a Jira sub-task with requirements. "
        "Return a JSON object with: {\"files_changed\": [...], \"notes\": \"...\"}. "
        "IMPORTANT: For this pilot, do not attempt complex multi-file refactors. "
        "Keep changes small and safe. If requirements are unclear, output JSON with an \"questions\" array instead."
    )


def execute_subtask(issue: JiraIssue) -> ExecutionResult:
    """Executes a single Jira *sub-task*.

    New behavior (Story-based):
    - If subtask has "independent-pr" label: creates own branch/PR (old behavior)
    - Otherwise: commits to parent Story's branch (story/STORY-KEY)
    
    Pilot behaviour:
    - Ensures repo is checked out.
    - Creates/uses appropriate branch.
    - Adds/updates implementation.
    - Commits and pushes.
    - Creates PR only if independent.
    """

    # Check if this subtask should have its own PR
    is_independent = "independent-pr" in (issue.labels or [])

    # 1) Checkout/update repo
    checkout_repo(settings.REPO_WORKDIR, settings.REPO_SSH, settings.BASE_BRANCH)

    # 2) Determine branch
    if is_independent:
        # Independent subtask: create its own branch
        branch = f"ai/{issue.key.lower()}"
        create_branch(settings.REPO_WORKDIR, branch)
    else:
        # Part of Story: use Story branch (story/STORY-KEY)
        if not issue.parent_key:
            raise RuntimeError(f"Subtask {issue.key} has no parent Story")
        
        story_branch = f"story/{issue.parent_key.lower()}"
        # Check if Story branch exists, create if not
        try:
            checkout_or_create_story_branch(settings.REPO_WORKDIR, story_branch, settings.BASE_BRANCH)
        except Exception:
            # If Story branch doesn't exist, create it
            create_branch(settings.REPO_WORKDIR, story_branch)
        branch = story_branch

    # 3) Ask Claude to produce implementation notes (and optionally questions)
    client = AnthropicClient(api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    prompt = (
        f"Jira Sub-task: {issue.key}\n"
        f"Summary: {issue.summary}\n\n"
        f"Description:\n{issue.description}\n"
    )
    raw = client.messages_create({
        "model": settings.ANTHROPIC_MODEL,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.2,
    })

    # Extract assistant text and try to parse JSON
    text = AnthropicClient.extract_text(raw)
    payload: Dict[str, Any]
    try:
        payload = json.loads(text)
    except Exception:
        payload = {"notes": text}

    questions = payload.get("questions")
    notes = payload.get("notes") or ""

    # 4) Write a small artefact in-repo
    out_dir = Path(settings.REPO_WORKDIR) / "docs" / "ai-pilot"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{issue.key}.md"
    content = [f"# {issue.key}: {issue.summary}", ""]
    if questions:
        content += ["## Questions", ""]
        for q in questions:
            content += [f"- {q}"]
        content += [""]
    if notes:
        content += ["## Notes", "", notes, ""]
    p.write_text("\n".join(content), encoding="utf-8")

    # 5) Commit with subtask key in message
    commit_message = f"{issue.key}: {issue.summary}"
    commit_and_push(settings.REPO_WORKDIR, commit_message)
    
    # 6) Create PR only if independent
    pr_url = None
    if is_independent:
        try:
            pr_url = create_pr(
                settings.REPO_WORKDIR,
                title=f"{issue.key}: {issue.summary}",
                body=f"Automated pilot PR for {issue.key}.\n\n{notes[:800]}",
                base=settings.BASE_BRANCH,
            )
        except Exception as e:
            # Don't fail the whole run if PR creation errors
            pr_url = None
            notes += f"\n\nPR creation failed: {e}"
        summary = "Created branch, committed changes, and opened PR." if pr_url else "Created branch and committed changes."
    else:
        # Not independent: committed to Story branch, PR already exists or will be created by Story
        summary = f"Committed to Story branch ({branch}). Story PR will be updated automatically."
        pr_url = None  # Story owns the PR
    
    # Build Jira comment
    jira_comment_lines = [
        f"AI Runner has completed work on this sub-task.",
        f"",
        f"*Branch:* {branch}",
    ]
    if pr_url:
        jira_comment_lines.append(f"*PR:* {pr_url}")
    if notes:
        jira_comment_lines.append(f"")
        jira_comment_lines.append(f"*Notes:*")
        jira_comment_lines.append(notes[:500])
    
    jira_comment = "\n".join(jira_comment_lines)
    
    return ExecutionResult(branch=branch, pr_url=pr_url, summary=summary, jira_comment=jira_comment)
