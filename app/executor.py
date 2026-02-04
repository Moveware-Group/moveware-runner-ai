from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import settings
from .git_ops import checkout_repo, create_branch, commit_and_push, create_pr, checkout_or_create_story_branch
from .jira import JiraClient
from .llm_anthropic import AnthropicClient
from .models import JiraIssue


@dataclass
class ExecutionResult:
    branch: str
    pr_url: Optional[str]
    summary: str
    jira_comment: str


def _get_repo_context(repo_path: Path, issue: JiraIssue) -> str:
    """Get comprehensive repository context for Claude, including code and history."""
    context = []
    
    # 1. Git commit history (last 10 commits)
    try:
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout:
            context.append("Recent commits:")
            context.append("```")
            context.append(result.stdout.strip())
            context.append("```")
            context.append("")
    except Exception:
        pass
    
    # 2. Repository structure (comprehensive for src/)
    context.append("Repository structure:")
    try:
        # Top-level
        items = sorted(repo_path.iterdir())
        for item in items[:30]:
            if item.name.startswith('.') and item.name not in ['.env.example', '.eslintrc']:
                continue
            if item.is_dir():
                context.append(f"  📁 {item.name}/")
                # Expand key directories
                if item.name in ['src', 'app', 'components', 'lib', 'pages']:
                    try:
                        for subitem in sorted(item.rglob('*'))[:50]:
                            if subitem.is_file() and not subitem.name.startswith('.'):
                                rel_path = subitem.relative_to(repo_path)
                                context.append(f"    📄 {rel_path}")
                    except Exception:
                        pass
            else:
                context.append(f"  📄 {item.name}")
    except Exception:
        context.append("  (Unable to list directory)")
    
    context.append("")
    
    # 3. Always include package.json for Node/Next.js projects
    package_json_path = repo_path / "package.json"
    if package_json_path.exists():
        try:
            package_json_content = package_json_path.read_text(encoding="utf-8")
            context.append("Current package.json:")
            context.append("```json")
            context.append(package_json_content)
            context.append("```")
            context.append("")
        except Exception as e:
            context.append(f"Note: Could not read package.json: {e}\n")
    
    # 4. Read relevant source files based on task keywords
    summary_lower = issue.summary.lower()
    desc_lower = (issue.description or "").lower()
    combined_text = f"{summary_lower} {desc_lower}"
    
    # Map keywords to files
    keyword_files = {
        'layout': ['app/layout.tsx', 'src/app/layout.tsx', 'components/layout.tsx'],
        'theme': ['styles/theme.ts', 'lib/theme.ts', 'src/styles/theme.ts', 'app/theme.ts'],
        'config': ['next.config.js', 'next.config.mjs', 'tailwind.config.js', 'tsconfig.json'],
        'api': ['app/api/**/*.ts', 'pages/api/**/*.ts'],
        'auth': ['lib/auth.ts', 'middleware.ts', 'app/api/auth/**/*.ts'],
        'database': ['lib/db.ts', 'lib/prisma.ts', 'prisma/schema.prisma'],
    }
    
    files_to_read = set()
    for keyword, file_patterns in keyword_files.items():
        if keyword in combined_text:
            files_to_read.update(file_patterns)
    
    # Read matched files
    for file_pattern in files_to_read:
        if '**' in file_pattern:
            # Handle glob patterns
            try:
                from pathlib import Path
                pattern_parts = file_pattern.split('**/')
                if len(pattern_parts) == 2:
                    base_dir = repo_path / pattern_parts[0].rstrip('/')
                    if base_dir.exists():
                        for file_path in base_dir.rglob(pattern_parts[1]):
                            if file_path.is_file():
                                try:
                                    content = file_path.read_text(encoding="utf-8")
                                    rel_path = file_path.relative_to(repo_path)
                                    context.append(f"Current {rel_path}:")
                                    context.append("```")
                                    context.append(content[:5000])  # Limit per file
                                    if len(content) > 5000:
                                        context.append("... (truncated)")
                                    context.append("```")
                                    context.append("")
                                except Exception:
                                    pass
            except Exception:
                pass
        else:
            # Handle simple paths
            file_path = repo_path / file_pattern
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    context.append(f"Current {file_pattern}:")
                    context.append("```")
                    context.append(content[:5000])  # Limit per file
                    if len(content) > 5000:
                        context.append("... (truncated)")
                    context.append("```")
                    context.append("")
                except Exception:
                    pass
    
    # 5. Include env example if it exists
    env_example = repo_path / ".env.example"
    if env_example.exists():
        try:
            content = env_example.read_text(encoding="utf-8")
            context.append("Current .env.example:")
            context.append("```")
            context.append(content)
            context.append("```")
            context.append("")
        except Exception:
            pass
    
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
    
    # Get repository context (includes file contents)
    repo_path = Path(settings.REPO_WORKDIR)
    context_info = _get_repo_context(repo_path, issue)
    
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
        "max_tokens": 16000,  # Increased for large file contents
        "temperature": 1,  # Required when thinking is enabled
        "thinking": {
            "type": "enabled",
            "budget_tokens": 5000
        }
    })

    # Extract assistant text and parse JSON
    text = AnthropicClient.extract_text(raw)
    
    # Remove markdown code fence if present
    json_text = text.strip()
    
    # Handle ```json or ``` at the start
    lines = json_text.split('\n')
    if lines[0].strip().startswith('```'):
        # Remove first line (opening fence)
        lines = lines[1:]
        # Find and remove closing fence
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == '```':
                lines = lines[:i]
                break
        json_text = '\n'.join(lines)
    
    try:
        payload = json.loads(json_text)
    except Exception as e:
        # Log more context for debugging
        print(f"Failed to parse JSON. Error: {e}")
        print(f"Extracted text (first 2000 chars): {json_text[:2000]}")
        raise RuntimeError(f"Failed to parse Claude response as JSON: {e}")

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
        # Claude decided no changes were needed - this might be an error
        implementation_plan = payload.get("implementation_plan", "")
        summary = payload.get("summary", "")
        
        error_msg = f"No file changes were made by Claude.\n\nClaude's response:\n"
        if implementation_plan:
            error_msg += f"Plan: {implementation_plan}\n"
        if summary:
            error_msg += f"Summary: {summary}\n"
        if "questions" in payload:
            error_msg += f"Questions: {json.dumps(payload['questions'])}\n"
        
        print(error_msg)
        
        # Add this to Jira so the user can see Claude's reasoning
        jira_comment = (
            "⚠️ No file changes were made\n\n"
            "*Claude's Analysis:*\n"
        )
        if summary:
            jira_comment += f"{summary}\n\n"
        if implementation_plan:
            jira_comment += f"*Plan:* {implementation_plan}\n\n"
        jira_comment += (
            "If changes are actually needed, please:\n"
            "1. Add a comment explaining what's wrong or missing\n"
            "2. Move back to 'In Progress' and assign to AI Runner"
        )
        
        # Create Jira client to post comment
        jira_client = JiraClient(
            base_url=settings.JIRA_BASE_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN
        )
        jira_client.add_comment(issue.key, jira_comment)
        
        raise RuntimeError(error_msg)

    # 5) Verify the changes (run npm install for Node projects)
    verification_errors = []
    package_json_path = repo_path / "package.json"
    if package_json_path.exists() and any("package.json" in fc for fc in files_changed):
        # package.json was modified, verify dependencies
        try:
            import subprocess
            print("Running npm install to verify dependencies...")
            result = subprocess.run(
                ["npm", "install", "--no-audit", "--prefer-offline"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60  # 1 minute timeout
            )
            if result.returncode != 0:
                verification_errors.append(f"npm install failed:\n{result.stderr[:800]}")
                print(f"npm install failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            verification_errors.append("npm install timed out after 60 seconds")
            print("npm install timed out")
        except Exception as e:
            verification_errors.append(f"Could not run npm install: {e}")
            print(f"npm install exception: {e}")
    
    # If verification failed, add error to notes
    if verification_errors:
        notes += "\n\n⚠️ Build Verification Issues:\n" + "\n".join(verification_errors)
    
    # 6) Commit with subtask key in message
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
    
    # Add verification warnings if present
    if verification_errors:
        jira_comment_lines.append(f"")
        jira_comment_lines.append(f"⚠️ *Build Verification:*")
        for error in verification_errors:
            # Truncate long errors
            error_preview = error[:300] + "..." if len(error) > 300 else error
            jira_comment_lines.append(error_preview)
    
    jira_comment = "\n".join(jira_comment_lines)
    
    return ExecutionResult(branch=branch, pr_url=pr_url, summary=summary, jira_comment=jira_comment)
