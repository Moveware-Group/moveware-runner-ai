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

    Pilot behaviour:
    - Ensures repo is checked out.
    - Creates a branch named with the issue key.
    - Adds/updates a docs note under /docs/ai-pilot/<ISSUE_KEY>.md.
    - Commits and pushes.
    - Creates a PR via `gh`.

    This is production-grade scaffolding, but intentionally conservative for the pilot.
    """

    # 1) Checkout/update repo (git_ops will use settings.GH_TOKEN by default)
    checkout_repo(settings.REPO_WORKDIR, settings.REPO_SSH, settings.BASE_BRANCH)

    # 2) Branch per sub-task
    branch = f"ai/{issue.key.lower()}"
    create_branch(settings.REPO_WORKDIR, branch)

    # 3) Ask Claude to produce implementation notes (and optionally questions)
    client = AnthropicClient(api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    prompt = (
        f"Jira Sub-task: {issue.key}\n"
        f"Summary: {issue.summary}\n\n"
        f"Description:\n{issue.description}\n"
    )
    raw = client.messages_json(
        model=settings.ANTHROPIC_MODEL,
        system=_system_prompt(),
        user=prompt,
        max_tokens=900,
        temperature=0.2,
    )

    # Extract assistant text and try to parse JSON
    text = "".join([b.get("text", "") for b in raw.get("content", []) if b.get("type") == "text"]).strip()
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

    # 5) Commit/push and PR
    commit_and_push(settings.REPO_WORKDIR, issue.key)
    pr_url = None
    try:
        pr_url = create_pr(
            settings.REPO_WORKDIR,
            title=f"{issue.key}: {issue.summary}",
            body=f"Automated pilot PR for {issue.key}.\n\n{notes[:800]}",
            base=settings.BASE_BRANCH,
        )
    except Exception as e:
        # Don't fail the whole run if PR creation errors (e.g. gh not authed yet)
        pr_url = None
        notes += f"\n\nPR creation failed: {e}"

    summary = "Created branch, committed changes, and opened PR." if pr_url else "Created branch and committed changes."
    
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
