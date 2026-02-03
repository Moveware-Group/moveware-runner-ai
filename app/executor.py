from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import settings
from .git_ops import checkout_repo, create_branch, commit_and_push, create_pr, checkout_or_create_story_branch
from .llm_anthropic import AnthropicClient
from .models import JiraIssue


@dataclass
class ExecutionResult:
    branch: str
    pr_url: Optional[str]
    summary: str
    jira_comment: str


def _get_repo_context(repo_path: Path) -> str:
    """Get basic repository context for Claude."""
    context = []
    
    # List key files and directories
    context.append("Repository structure:")
    try:
        # Get top-level items
        items = sorted(repo_path.iterdir())
        for item in items[:20]:  # Limit to first 20 items
            if item.name.startswith('.'):
                continue
            if item.is_dir():
                context.append(f"  📁 {item.name}/")
            else:
                context.append(f"  📄 {item.name}")
    except Exception:
        context.append("  (Unable to list directory)")
    
    # Check for common config files
    config_files = ["package.json", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml"]
    found_configs = [f for f in config_files if (repo_path / f).exists()]
    if found_configs:
        context.append(f"\nDetected project type from: {', '.join(found_configs)}")
    
    return "\n".join(context)


def _system_prompt() -> str:
    return (
        "You are an expert software engineer implementing a Jira sub-task. "
        "You will be given the task requirements and must implement the actual code changes.\n\n"
        "Working directory: The repository is already checked out and you're on the correct branch.\n\n"
        "Your response MUST be valid JSON with this structure:\n"
        "{\n"
        '  "implementation_plan": "Brief plan of what you\'ll implement",\n'
        '  "files": [\n'
        '    {\n'
        '      "path": "relative/path/to/file.ext",\n'
        '      "action": "create|update|delete",\n'
        '      "content": "Full file content for create/update"\n'
        '    }\n'
        '  ],\n'
        '  "summary": "Brief summary of changes made"\n'
        "}\n\n"
        "Guidelines:\n"
        "- Implement production-quality code with proper error handling\n"
        "- Follow best practices and conventions for the language/framework\n"
        "- Include comments where helpful\n"
        "- For updates, provide the COMPLETE file content (not diffs)\n"
        "- Keep changes focused on the specific sub-task requirements\n"
        "- If requirements are unclear, include an 'questions' array in JSON instead of 'files'"
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

    # 3) Ask Claude to implement the code changes
    client = AnthropicClient(api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    
    # Get repository context
    repo_path = Path(settings.REPO_WORKDIR)
    context_info = _get_repo_context(repo_path)
    
    prompt = (
        f"Implement this Jira sub-task:\n\n"
        f"**Task:** {issue.key}\n"
        f"**Summary:** {issue.summary}\n\n"
        f"**Requirements:**\n{issue.description}\n\n"
        f"**Repository Context:**\n{context_info}\n\n"
        f"Provide your implementation as JSON following the specified format."
    )
    
    raw = client.messages_create({
        "model": settings.ANTHROPIC_MODEL,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8000,
        "temperature": 1,  # Required when thinking is enabled
        "thinking": {
            "type": "enabled",
            "budget_tokens": 5000
        }
    })

    # Extract assistant text and parse JSON
    text = AnthropicClient.extract_text(raw)
    
    # Try to extract JSON from response (handle markdown code blocks)
    json_text = text.strip()
    
    # Remove markdown code fence if present
    if json_text.startswith("```"):
        # Find the first newline after opening fence
        first_newline = json_text.find("\n")
        if first_newline != -1:
            # Find the closing fence
            closing_fence = json_text.rfind("```")
            if closing_fence > first_newline:
                json_text = json_text[first_newline + 1:closing_fence].strip()
    
    try:
        payload = json.loads(json_text)
    except Exception as e:
        # Log more context for debugging
        print(f"Failed to parse JSON. Error: {e}")
        print(f"Extracted text (first 1000 chars): {json_text[:1000]}")
        raise RuntimeError(f"Failed to parse Claude response as JSON: {e}\n\nResponse: {text[:500]}")

    # Check if there are questions instead of implementation
    if "questions" in payload:
        questions = payload["questions"]
        questions_text = "\n".join([f"- {q}" for q in questions])
        raise RuntimeError(f"Implementation blocked by questions:\n{questions_text}")

    # 4) Apply file changes
    files_changed = []
    files = payload.get("files", [])
    
    for file_op in files:
        file_path = repo_path / file_op["path"]
        action = file_op.get("action", "update")
        
        if action == "delete":
            if file_path.exists():
                file_path.unlink()
                files_changed.append(f"Deleted {file_op['path']}")
        elif action in ("create", "update"):
            content = file_op.get("content", "")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            action_word = "Created" if action == "create" else "Updated"
            files_changed.append(f"{action_word} {file_op['path']}")
    
    notes = payload.get("summary", "") or payload.get("implementation_plan", "")
    
    if not files_changed:
        raise RuntimeError("No file changes were made by Claude")

    # 5) Commit with subtask key in message
    files_summary = ", ".join(files_changed[:5])  # Limit to first 5 files
    if len(files_changed) > 5:
        files_summary += f" (+{len(files_changed) - 5} more)"
    
    commit_message = f"{issue.key}: {issue.summary}"
    commit_and_push(settings.REPO_WORKDIR, commit_message)
    
    # 6) Create PR only if independent
    pr_url = None
    if is_independent:
        try:
            pr_body = f"""## {issue.key}: {issue.summary}

{notes}

### Files Changed:
{chr(10).join(['- ' + fc for fc in files_changed])}
"""
            pr_url = create_pr(
                settings.REPO_WORKDIR,
                title=f"{issue.key}: {issue.summary}",
                body=pr_body,
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
    
    # Build Jira comment (keep it clean and concise)
    jira_comment_lines = [
        f"✅ Implementation complete",
        f"",
        f"*Branch:* `{branch}`",
    ]
    if pr_url:
        jira_comment_lines.append(f"*PR:* {pr_url}")
    
    jira_comment_lines.append(f"")
    jira_comment_lines.append(f"*Changes:* {files_summary}")
    
    jira_comment = "\n".join(jira_comment_lines)
    
    return ExecutionResult(branch=branch, pr_url=pr_url, summary=summary, jira_comment=jira_comment)
