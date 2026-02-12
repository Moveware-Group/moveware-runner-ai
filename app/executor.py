from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import settings
from .git_ops import checkout_repo, create_branch, commit_and_push, create_pr, checkout_or_create_story_branch, create_rollback_tag
from .jira import JiraClient
from .jira_adf import adf_to_plain_text
from .llm_anthropic import AnthropicClient
from .models import JiraIssue
from .db import add_progress_event
from .repo_config import get_repo_for_issue
from .error_classifier import classify_error, get_comprehensive_hint, extract_error_context
from .verifier import run_all_verifications
from .metrics import ExecutionMetrics, calculate_cost, save_metrics
from datetime import datetime


@dataclass
class ExecutionResult:
    branch: str
    pr_url: Optional[str]
    summary: str
    jira_comment: str


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
            "skills": getattr(repo, "skills", ["nextjs-fullstack-dev"]),
        }
    else:
        # Fallback to environment variables (legacy single-repo mode)
        return {
            "repo_ssh": settings.REPO_SSH,
            "repo_workdir": settings.REPO_WORKDIR,
            "base_branch": settings.BASE_BRANCH,
            "repo_owner_slug": settings.REPO_OWNER_SLUG,
            "repo_name": settings.REPO_NAME,
            "skills": ["nextjs-fullstack-dev"],
        }


def _get_repo_context(repo_path: Path, issue: JiraIssue, include_all_code: bool = False) -> str:
    """Get comprehensive repository context for Claude, including code and history.
    
    Args:
        repo_path: Path to repository
        issue: Jira issue being processed
        include_all_code: If True, includes all source files (used for error fixing)
    """
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
    
    files_to_read = set()
    
    if include_all_code:
        # For error fixing: include ALL source files for full context
        context.append("\n**=== COMPREHENSIVE CODE CONTEXT ===**\n")
        try:
            # Include all TypeScript/JavaScript/CSS files in key directories
            for pattern in ['lib/**/*.ts', 'lib/**/*.tsx', 'app/**/*.ts', 'app/**/*.tsx', 
                           'app/**/*.css', 'components/**/*.ts', 'components/**/*.tsx']:
                pattern_parts = pattern.split('**/')
                if len(pattern_parts) == 2:
                    base_dir = repo_path / pattern_parts[0].rstrip('/')
                    if base_dir.exists():
                        for file_path in base_dir.rglob(pattern_parts[1]):
                            if file_path.is_file():
                                files_to_read.add(str(file_path.relative_to(repo_path)))
        except Exception:
            pass
    else:
        # Normal mode: keyword-based file selection
        # Map keywords to files
        keyword_files = {
            'layout': ['app/layout.tsx', 'src/app/layout.tsx', 'components/layout.tsx'],
            'theme': ['styles/theme.ts', 'lib/theme.ts', 'src/styles/theme.ts', 'app/theme.ts'],
            'config': ['next.config.js', 'next.config.mjs', 'tailwind.config.js', 'tsconfig.json'],
            'api': ['app/api/**/*.ts', 'pages/api/**/*.ts'],
            'auth': ['lib/auth.ts', 'middleware.ts', 'app/api/auth/**/*.ts'],
            'database': ['lib/db.ts', 'lib/prisma.ts', 'prisma/schema.prisma'],
        }
        
        for keyword, file_patterns in keyword_files.items():
            if keyword in combined_text:
                files_to_read.update(file_patterns)
    
    # Read matched files
    for file_pattern in files_to_read:
        if '**' in file_pattern:
            # Handle glob patterns
            try:
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
    
    # 6. Always include DESIGN.md if it exists (design system)
    design_md_path = repo_path / "DESIGN.md"
    if design_md_path.exists():
        try:
            content = design_md_path.read_text(encoding="utf-8")
            context.append("Design System (DESIGN.md):")
            context.append("```markdown")
            context.append(content[:10000])  # Include full design system (up to 10KB)
            if len(content) > 10000:
                context.append("... (truncated)")
            context.append("```")
            context.append("")
            context.append("**IMPORTANT:** Follow the design system patterns above for all UI components.")
            context.append("")
        except Exception:
            pass
    else:
        # If no DESIGN.md exists in repo, include the template for UI-related tasks
        is_ui_task = any(keyword in combined_text for keyword in [
            'ui', 'page', 'component', 'layout', 'form', 'button', 'style', 
            'design', 'interface', 'frontend', 'react', 'next.js', 'tailwind'
        ])
        
        if is_ui_task:
            # Load design template from runner repo
            try:
                runner_repo_path = Path(__file__).parent.parent
                template_path = runner_repo_path / "docs" / "DESIGN-TEMPLATE.md"
                if template_path.exists():
                    template_content = template_path.read_text(encoding="utf-8")
                    context.append("Design System Template (for UI consistency):")
                    context.append("```markdown")
                    context.append(template_content[:10000])
                    if len(template_content) > 10000:
                        context.append("... (truncated)")
                    context.append("```")
                    context.append("")
                    context.append("**IMPORTANT:** Follow the design patterns above. Consider creating DESIGN.md in the repo root.")
                    context.append("")
            except Exception as e:
                print(f"Note: Could not load design template: {e}")
    
    return "\n".join(context)


def _get_human_comments(issue_key: str) -> str:
    """Fetch human comments from the Jira issue to provide clarifications and context."""
    try:
        jira = JiraClient(
            base_url=settings.JIRA_BASE_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN
        )
        comments = jira.get_comments(issue_key)
        
        human_comments = []
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
                author_name = author.get("displayName", "User") if isinstance(author, dict) else "User"
                created = c.get("created", "")
                human_comments.append(f"[{created}] {author_name}:\n{body_text.strip()}")
        
        if not human_comments:
            return ""
        
        return "\n\n".join(human_comments)
    except Exception as e:
        print(f"Warning: Could not fetch comments for {issue_key}: {e}")
        return ""


def _build_system_with_cache(repo_context: str, skills_content: str = "") -> list:
    """
    Build system prompt with prompt caching for repository context.
    
    Includes optional project-specific skills (e.g., Next.js vs Flutter conventions).
    
    Returns array of system message blocks with cache_control markers.
    This reduces costs by 90% and speeds up responses 5x for repeated context.
    """
    cached_parts = []
    if skills_content:
        cached_parts.append(skills_content)
    cached_parts.append(f"\n\n**Repository Context (cached for performance):**\n\n{repo_context}")
    
    return [
        {
            "type": "text",
            "text": _system_prompt()
        },
        {
            "type": "text",
            "text": "\n\n".join(cached_parts),
            "cache_control": {"type": "ephemeral"}  # Cache this expensive part!
        }
    ]


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
        "- If requirements are unclear, include an 'questions' array in JSON instead of 'files'\n\n"
        "**🚨 CRITICAL SCOPE RULES - MUST FOLLOW:**\n"
        "- ONLY implement what is EXPLICITLY stated in the task requirements\n"
        "- Do NOT add features, pages, or components that are not mentioned in the requirements\n"
        "- Do NOT add 'nice to have' functionality or try to be 'helpful' by adding extras\n"
        "- Do NOT create dashboard pages, admin panels, or analytics unless specifically requested\n"
        "- Do NOT add authentication, logging, or monitoring unless explicitly required\n"
        "- If you think something is missing from the requirements:\n"
        "  * DO NOT implement it\n"
        "  * Instead, add a question in the 'questions' array asking for clarification\n"
        "- Every file you create or modify MUST be directly mentioned or implied by the task\n"
        "- When in doubt, implement LESS rather than MORE\n"
        "- Remember: Adding unauthorized features wastes time and creates bugs\n\n"
        "**CRITICAL BUILD VERIFICATION:**\n"
        "- For Next.js/React projects, your code will be verified with `npm run build`\n"
        "- If the build fails, the task will FAIL and you'll need to fix it\n"
        "- Common build failures to avoid:\n"
        "  * Missing exports (e.g., declaring `const x` but not exporting it)\n"
        "  * Invalid Tailwind CSS classes (use only standard Tailwind classes)\n"
        "  * Import errors (importing functions that don't exist)\n"
        "  * TypeScript errors (wrong types, missing properties)\n"
        "  * Using Node.js modules (fs, path) in client components\n"
        "- TEST YOUR MENTAL MODEL: Before finishing, mentally trace each import/export\n"
        "- Double-check that every exported function/variable is actually defined\n"
        "- Verify Tailwind classes match the design system or use standard Tailwind\n\n"
        "UI/Frontend Requirements (for React/Next.js tasks):\n"
        "- **CRITICAL:** If a Design System (DESIGN.md) is provided in the repository context, YOU MUST follow it exactly\n"
        "  * Use the exact color classes, spacing, and component patterns specified\n"
        "  * Copy button styles, card styles, and layout patterns from the design system\n"
        "  * Match the typography scale and font weights\n"
        "  * Use the specified icons library and interaction patterns\n"
        "- Create COMPLETE, production-ready user interfaces with proper styling\n"
        "- Use Tailwind CSS for styling with responsive design (mobile-first)\n"
        "- Implement proper component structure with TypeScript types\n"
        "- Include loading states, error handling, and empty states in UI\n"
        "- Create visually appealing layouts with proper spacing, typography, and colors\n"
        "- Add interactive elements (hover states, focus states, transitions)\n"
        "- Ensure accessibility (ARIA labels, keyboard navigation, semantic HTML)\n"
        "- For pages, create a complete user experience, not just placeholder text\n"
        "- Reference modern design patterns (cards, grids, forms, navigation)\n"
        "- If implementing a form, include validation and user feedback\n"
        "- Use the project's theme/branding consistently across all components\n\n"
        "Project Initialization:\n"
        "- When creating a new Next.js/React project structure, ALWAYS include DESIGN.md in the files array\n"
        "- Copy the design system template provided in context and customize it for the project\n"
        "- This ensures consistent UI patterns from the start"
    )


def execute_subtask(issue: JiraIssue, run_id: Optional[int] = None) -> ExecutionResult:
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
    
    # Initialize metrics tracking
    start_time = datetime.now()
    metrics = None
    if run_id:
        metrics = ExecutionMetrics(
            run_id=run_id,
            issue_key=issue.key,
            issue_type="subtask",
            start_time=start_time,
            end_time=start_time,  # Will update at end
            duration_seconds=0.0,
            success=False,
            status="running",
            metadata={}
        )
    
    # Wrap execution in try-except to ensure metrics are always saved
    try:
        return _execute_subtask_impl(issue, run_id, metrics, start_time)
    except Exception as e:
        # Save metrics even on failure
        if metrics:
            end_time = datetime.now()
            metrics.end_time = end_time
            metrics.duration_seconds = (end_time - start_time).total_seconds()
            metrics.success = False
            metrics.status = "failed"
            metrics.error_message = str(e)
            
            # Try to extract error category
            from .error_classifier import classify_error
            error_category, _, _ = classify_error(str(e))
            metrics.error_category = error_category
            
            # Save metrics before re-raising
            try:
                save_metrics(metrics)
            except Exception as save_error:
                print(f"Warning: Could not save error metrics: {save_error}")
        
        # Re-raise the original error
        raise


def _execute_subtask_impl(issue: JiraIssue, run_id: Optional[int], metrics: Optional[ExecutionMetrics], start_time: datetime) -> ExecutionResult:
    """Internal implementation of execute_subtask with metrics tracking."""
    
    if run_id:
        add_progress_event(run_id, "executing", f"Preparing repository for {issue.key}", {})

    # Get repository configuration for this issue (supports multi-repo)
    repo_settings = _get_repo_settings(issue.key)

    # Check if this subtask should have its own PR
    is_independent = "independent-pr" in (issue.labels or [])

    # 1) Checkout/update repo
    checkout_repo(repo_settings["repo_workdir"], repo_settings["repo_ssh"], repo_settings["base_branch"])

    # 2) Determine branch
    if is_independent:
        # Independent subtask: create its own branch
        branch = f"ai/{issue.key.lower()}"
        create_branch(repo_settings["repo_workdir"], branch)
    else:
        # Part of Story: use Story branch (story/STORY-KEY)
        if not issue.parent_key:
            raise RuntimeError(f"Subtask {issue.key} has no parent Story")
        
        story_branch = f"story/{issue.parent_key.lower()}"
        # Check if Story branch exists, create if not
        try:
            checkout_or_create_story_branch(repo_settings["repo_workdir"], story_branch, repo_settings["base_branch"])
        except Exception:
            # If Story branch doesn't exist, create it
            create_branch(repo_settings["repo_workdir"], story_branch)
        branch = story_branch
    
    if run_id:
        add_progress_event(run_id, "executing", f"Analyzing task and planning implementation", {"branch": branch})

    # 3) Ask Claude to implement the code changes
    client = AnthropicClient(api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    
    # Get repository context (includes file contents)
    repo_path = Path(repo_settings["repo_workdir"])
    context_info = _get_repo_context(repo_path, issue)
    
    # Load project-specific skills (e.g., Next.js vs Flutter)
    from app.skill_loader import load_skills
    skills_content = load_skills(repo_settings.get("skills", ["nextjs-fullstack-dev"]))
    
    # Get human comments for additional context/clarifications
    human_comments = _get_human_comments(issue.key)
    
    prompt = (
        f"Implement this Jira sub-task:\n\n"
        f"**Task:** {issue.key}\n"
        f"**Summary:** {issue.summary}\n\n"
        f"**Requirements:**\n{issue.description}\n\n"
    )
    
    if human_comments:
        prompt += (
            f"**Additional Clarifications from Comments:**\n"
            f"{human_comments}\n\n"
        )
    
    prompt += (
        f"**Repository Context:**\n{context_info}\n\n"
        f"**REMINDER - SCOPE CHECK:**\n"
        f"Before implementing, verify that EVERY file you create is explicitly mentioned in the requirements above.\n"
        f"If you're creating a file that isn't directly requested, STOP and ask a question instead.\n\n"
        f"Provide your implementation as JSON following the specified format."
    )
    
    if run_id:
        add_progress_event(run_id, "executing", f"Calling Claude to generate implementation", {})
    
    # Use prompt caching for repository context (90% cost reduction!)
    raw = client.messages_create({
        "model": settings.ANTHROPIC_MODEL,
        "system": _build_system_with_cache(context_info, skills_content),  # Cached!
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 16000,  # Increased for large file contents
        "temperature": 1,  # Required when thinking is enabled
        "thinking": {
            "type": "enabled",
            "budget_tokens": 8000  # Increased for complex problems
        }
    })

    # Extract token usage from response
    if metrics and raw.get("usage"):
        usage = raw["usage"]
        metrics.total_input_tokens = usage.get("input_tokens", 0)
        metrics.total_output_tokens = usage.get("output_tokens", 0)
        metrics.cached_tokens = usage.get("cache_read_input_tokens", 0)
        # Calculate cost
        metrics.estimated_cost = calculate_cost(
            settings.ANTHROPIC_MODEL,
            metrics.total_input_tokens,
            metrics.total_output_tokens,
            metrics.cached_tokens
        )
        print(f"Token usage: {metrics.total_input_tokens} input, {metrics.total_output_tokens} output, {metrics.cached_tokens} cached")
        print(f"Estimated cost: ${metrics.estimated_cost:.4f}")

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
    if "questions" in payload and payload["questions"]:
        questions = payload["questions"]
        questions_text = "\n".join([f"- {q}" for q in questions])
        # Post to Jira so the human can answer and re-assign
        summary = payload.get("summary", "") or payload.get("implementation_plan", "")
        jira_comment = (
            "❓ *Implementation blocked – clarification needed*\n\n"
            "The AI Runner needs answers before it can implement:\n\n"
            f"{questions_text}\n\n"
            "----\n"
            "*To unblock:* Add a comment below with your answers, then re-assign this sub-task to AI Runner."
        )
        if summary:
            jira_comment = f"*Context:* {summary}\n\n" + jira_comment
        try:
            jira_client = JiraClient(
                base_url=settings.JIRA_BASE_URL,
                email=settings.JIRA_EMAIL,
                api_token=settings.JIRA_API_TOKEN,
            )
            jira_client.add_comment(issue.key, jira_comment)
            jira_client.assign(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
            jira_client.transition_to_status(issue.key, settings.JIRA_STATUS_BLOCKED)
        except Exception as e:
            print(f"Could not post questions to Jira: {e}")
        raise RuntimeError(f"Implementation blocked by questions:\n{questions_text}")

    # 4) Apply file changes
    files_changed = []
    files = payload.get("files", [])
    
    if run_id:
        add_progress_event(run_id, "executing", f"Applying {len(files)} file changes", {"file_count": len(files)})
    
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

    # 5) Pre-commit verification (catch errors early!)
    if run_id:
        add_progress_event(run_id, "verifying", "Running pre-commit checks", {})
    
    # Pass actual file paths to verifier (not "Created path" format - ESLint/tsc need real paths)
    file_paths_for_verify = [f["path"] for f in files if f.get("action", "update") != "delete"]
    pre_commit_result = run_all_verifications(repo_path, file_paths_for_verify)
    
    # Start with any pre-commit errors
    verification_errors = list(pre_commit_result.errors)
    
    # Show warnings but don't fail
    if pre_commit_result.warnings:
        print("\n⚠️  Pre-commit warnings:")
        for warning in pre_commit_result.warnings[:5]:  # Limit output
            print(f"  - {warning}")
    
    # 6) Build verification (run npm install and build for Node projects)
    if run_id and not verification_errors:  # Only if pre-commit passed
        add_progress_event(run_id, "verifying", "Running build verification", {})
    
    package_json_path = repo_path / "package.json"
    is_node_project = package_json_path.exists()
    
    if is_node_project:
        # Check if package.json was modified or if this is a code change
        needs_verification = (
            any("package.json" in fc for fc in files_changed) or  # package.json changed
            any(fc.endswith(('.ts', '.tsx', '.js', '.jsx', '.css')) for fc in files_changed)  # code changed
        )
        
        if needs_verification:
            import subprocess
            
            # Step 1: Install dependencies
            if run_id:
                add_progress_event(run_id, "verifying", "Running npm install to verify dependencies", {})
            try:
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
            
            # Step 2: Run build for Next.js/React projects (CRITICAL for catching errors)
            if not verification_errors:  # Only build if install succeeded
                # Check if this is a Next.js project
                try:
                    package_json_content = package_json_path.read_text(encoding="utf-8")
                    is_nextjs = '"next"' in package_json_content or "'next'" in package_json_content
                    
                    if is_nextjs:
                        if run_id:
                            add_progress_event(run_id, "verifying", "Running production build to verify code", {})
                        
                        # Clean up any existing build artifacts/locks
                        try:
                            next_dir = repo_path / ".next"
                            if next_dir.exists():
                                lock_file = next_dir / "lock"
                                if lock_file.exists():
                                    lock_file.unlink()
                                    print("Removed stale .next/lock file")
                        except Exception as e:
                            print(f"Warning: Could not clean build locks: {e}")
                        
                        print("Running production build to verify code...")
                        result = subprocess.run(
                            ["npm", "run", "build"],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            timeout=180  # 3 minute timeout for build
                        )
                        
                        if result.returncode != 0:
                            # Build failed - this is a CRITICAL error
                            error_output = result.stderr if result.stderr else result.stdout
                            verification_errors.append(
                                f"❌ CRITICAL: Production build failed\n\n"
                                f"Build output:\n{error_output[:2000]}\n\n"
                                f"Common fixes:\n"
                                f"- Check for missing exports in service files\n"
                                f"- Verify all imported functions/types exist\n"
                                f"- Check Tailwind CSS classes are valid\n"
                                f"- Ensure 'use client' directive is added for client components\n"
                                f"- Fix TypeScript type errors"
                            )
                            print(f"Build failed:\n{error_output[:1000]}")
                        else:
                            print("✅ Build succeeded!")
                            
                except subprocess.TimeoutExpired:
                    verification_errors.append("Build timed out after 3 minutes")
                    print("Build timed out")
                except Exception as e:
                    verification_errors.append(f"Could not run build: {e}")
                    print(f"Build exception: {e}")
    
    # If verification failed, try to fix the errors (self-healing) with multi-attempt strategy
    MAX_FIX_ATTEMPTS = 3
    fix_attempt = 0
    
    # Auto-fix missing npm packages (e.g. "Cannot find module 'autoprefixer'") before AI
    import subprocess
    _cannot_find = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", "\n".join(verification_errors))
    if _cannot_find and is_node_project:
        missing_pkg = _cannot_find.group(1).strip()
        # Only try for package names (no path separators, no file extensions)
        if "/" not in missing_pkg and "\\" not in missing_pkg and not missing_pkg.endswith((".ts", ".tsx", ".js", ".jsx")):
            try:
                print(f"Auto-installing missing npm package: {missing_pkg}")
                if run_id:
                    add_progress_event(run_id, "verifying", f"Installing missing package: {missing_pkg}", {})
                subprocess.run(
                    ["npm", "install", missing_pkg, "--no-audit", "--prefer-offline"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                # Re-run build
                verification_errors = []
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=180
                )
                if result.returncode == 0:
                    print(f"✅ Build succeeded after installing {missing_pkg}!")
                else:
                    verification_errors.append(
                        f"Build still failing after npm install {missing_pkg}:\n"
                        f"{(result.stderr or result.stdout)[:1000]}"
                    )
            except Exception as e:
                verification_errors.append(f"Failed to auto-install {missing_pkg}: {e}")
    
    # Auto-fix Prettier formatting errors (don't burn LLM attempts on formatting)
    error_text = "\n".join(verification_errors)
    if "prettier/prettier" in error_text and is_node_project:
        # Extract file paths from error (e.g. ./src/lib/db/repositories/tenants.ts)
        prettier_files = list(set(re.findall(r'\./([^\s]+\.(?:ts|tsx|js|jsx|css|json))', error_text)))
        if prettier_files:
            try:
                print("Running Prettier to auto-fix formatting errors...")
                if run_id:
                    add_progress_event(run_id, "verifying", "Running Prettier to fix formatting", {})
                result = subprocess.run(
                    ["npx", "prettier", "--write"] + prettier_files,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    result = subprocess.run(
                        ["npm", "run", "build"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=180
                    )
                    if result.returncode == 0:
                        print("✅ Build succeeded after Prettier fix!")
                        verification_errors = []
                    else:
                        error_output = result.stderr or result.stdout
                        verification_errors = [f"Build still failing after Prettier:\n{error_output[:2000]}"]
                else:
                    print(f"Prettier failed: {result.stderr}")
            except Exception as e:
                print(f"Prettier auto-fix failed: {e}")
    
    while verification_errors and fix_attempt < MAX_FIX_ATTEMPTS:
        fix_attempt += 1
        error_msg = "\n\n".join(verification_errors)
        
        # Determine which model to use
        if fix_attempt <= 2:
            model_name = "Claude"
            model_provider = "anthropic"
        else:
            model_name = f"OpenAI ({settings.OPENAI_MODEL})"
            model_provider = "openai"
            print(f"\n{'='*60}")
            print(f"ESCALATING TO OPENAI: Claude failed {fix_attempt-1} times")
            print(f"Getting second opinion from {settings.OPENAI_MODEL}...")
            print(f"{'='*60}\n")
        
        print(f"\nVERIFICATION FAILED - Attempt {fix_attempt}/{MAX_FIX_ATTEMPTS} using {model_name}")
        print(f"Error summary: {error_msg[:200]}...")
        
        # Classify errors and get targeted hints
        error_category, specific_hint, _ = classify_error(error_msg)
        comprehensive_hint = get_comprehensive_hint(error_msg)
        error_context = extract_error_context(error_msg, max_context_lines=3)
        
        print(f"Error category: {error_category}")
        if error_category != "unknown":
            print(f"Applying targeted fix strategy for {error_category}")
        
        if run_id:
            progress_msg = f"Build failed ({error_category}), asking {model_name} to fix (attempt {fix_attempt}/{MAX_FIX_ATTEMPTS})"
            add_progress_event(run_id, "fixing", progress_msg, {
                "attempt": fix_attempt, 
                "model": model_name,
                "error_category": error_category
            })
        
        # Kill any competing Next.js build processes
        try:
            import subprocess
            print("Checking for competing build processes...")
            # Kill any existing next build processes
            subprocess.run(
                ["pkill", "-f", "next build"],
                cwd=repo_path,
                capture_output=True,
                timeout=5
            )
            # Remove lock files
            lock_file = repo_path / ".next" / "lock"
            if lock_file.exists():
                lock_file.unlink()
                print("Removed .next/lock file")
        except Exception as e:
            print(f"Note: Could not clean up build locks: {e}")
        
        # Extract file paths from error messages and build comprehensive context
        error_files = set()
        import subprocess
        
        # Find file paths in error messages (e.g., ./online-docs/lib/services/brandingService.ts)
        file_pattern = r'\./[^\s:]+\.(ts|tsx|js|jsx|css)'
        for match in re.finditer(file_pattern, error_msg):
            file_path_str = match.group(0).replace('./', '').replace('online-docs/', '')
            error_files.add(file_path_str)
        
        # Also extract imports mentioned in errors (e.g., "import from '../data/storage'")
        import_pattern = r"from ['\"]([^'\"]+)['\"]"
        for match in re.finditer(import_pattern, error_msg):
            import_path = match.group(1)
            # Resolve relative imports to absolute paths
            for error_file in list(error_files):
                if '../' in import_path:
                    # Calculate relative path
                    error_dir = Path(error_file).parent
                    resolved = (error_dir / import_path).resolve()
                    try:
                        rel_to_repo = resolved.relative_to(repo_path)
                        # Try common extensions
                        for ext in ['.ts', '.tsx', '.js', '.jsx']:
                            candidate = str(rel_to_repo) + ext
                            if (repo_path / candidate).exists():
                                error_files.add(candidate)
                                break
                    except Exception:
                        pass
        
        # Build comprehensive error context with actual file contents
        error_file_contents = []
        
        # Add directory structure for relevant directories
        relevant_dirs = set()
        for error_file in error_files:
            relevant_dirs.add(str(Path(error_file).parent))
        
        for dir_path in sorted(relevant_dirs):
            dir_full_path = repo_path / dir_path
            if dir_full_path.exists() and dir_full_path.is_dir():
                try:
                    files_in_dir = [f.name for f in dir_full_path.iterdir() if f.is_file()]
                    error_file_contents.append(f"\n**Files in {dir_path}/:**\n{', '.join(files_in_dir)}")
                except Exception:
                    pass
        
        # Add actual file contents of error files and their dependencies
        for error_file in sorted(error_files):
            file_path = repo_path / error_file
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    error_file_contents.append(f"\n**Current {error_file}:**\n```typescript\n{content[:5000]}\n```")
                    if len(content) > 5000:
                        error_file_contents.append("... (file truncated)")
                except Exception:
                    pass
        
        # Add git diff to show what was just changed (might reveal the issue)
        try:
            git_diff = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if git_diff.returncode == 0 and git_diff.stdout.strip():
                error_file_contents.append(f"\n**Recent Changes (git diff):**\n```diff\n{git_diff.stdout[:2000]}\n```")
        except Exception:
            pass
        
        error_context = "\n".join(error_file_contents) if error_file_contents else ""
        
        # Get comprehensive repository context for fixing (includes ALL code)
        comprehensive_context = _get_repo_context(repo_path, issue, include_all_code=True)
        
        # Prepare fix prompt with targeted hints
        error_analysis_section = ""
        if comprehensive_hint:
            error_analysis_section = f"\n{comprehensive_hint}\n\n"
        elif specific_hint:
            error_analysis_section = f"\n**ERROR TYPE: {error_category.upper()}**\n{specific_hint}\n\n"
        
        fix_prompt = (
            f"The code has build errors. Please fix ALL the errors below.\n\n"
            f"**Attempt:** {fix_attempt}/{MAX_FIX_ATTEMPTS}\n"
            f"**Previous attempts:** {'Claude failed ' + str(fix_attempt-1) + ' time(s)' if fix_attempt > 1 else 'First attempt'}\n\n"
            f"**Original Task:** {issue.key}\n"
            f"**Summary:** {issue.summary}\n\n"
            f"**Build Errors:**\n```\n{error_msg[:1500]}\n```\n\n"  # Limit error size
            f"{error_analysis_section}"  # Targeted hints based on error type
            f"**Key Error Context:**\n{chr(10).join(error_context) if error_context else 'See full errors above'}\n\n"
            f"{error_context}\n\n"  # Show actual file contents with errors
            f"**Full Repository Context (for debugging):**\n{comprehensive_context}\n\n"
            f"**CRITICAL:** Your response MUST be ONLY valid JSON. No markdown, no explanation, JUST JSON.\n\n"
            f"Provide the COMPLETE fixed files as JSON with this EXACT format:\n"
            f"{{\n"
            f'  "implementation_plan": "Brief explanation of fixes",\n'
            f'  "files": [\n'
            f'    {{\n'
            f'      "path": "relative/path/to/file.ext",\n'
            f'      "action": "update",\n'
            f'      "content": "COMPLETE file content"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "summary": "Fixed build errors"\n'
            f"}}\n\n"
            f"**DEBUGGING STRATEGY:**\n"
            f"1. Look at the error messages - they tell you exactly what's missing\n"
            f"2. Look at the ACTUAL file contents provided above\n"
            f"3. Compare what's imported vs what's exported\n"
            f"4. Fix the mismatch by either:\n"
            f"   a) Adding missing exports to the source file, OR\n"
            f"   b) Changing imports to match what exists\n\n"
            f"**COMMON PATTERNS FOR THIS ERROR:**\n"
            f"- Error: 'Export readData doesn't exist'\n"
            f"  → Solution: Check storage.ts - does it export readData? If not, what DOES it export?\n"
            f"  → If it exports 'getData', change import from 'readData' to 'getData'\n"
            f"  → If nothing similar exists, add the function to storage.ts\n\n"
            f"- Error: 'The export X was not found'\n"
            f"  → Look at the actual file contents above\n"
            f"  → Find what IS exported (look for 'export' keyword)\n"
            f"  → Either rename the export to X, or change imports to use actual name\n\n"
            f"**OTHER COMMON FIXES:**\n"
            f"- Cannot find module 'autoprefixer' etc: Add the package to package.json devDependencies "
            f"(e.g. \"autoprefixer\": \"^10.4.0\"), include the updated package.json in your files\n"
            f"- Use valid Tailwind classes: Only bg-blue-600, text-gray-900, etc. (not bg-background)\n"
            f"- Remove @apply directives with invalid classes from CSS files\n"
            f"- Export service instances: `export const serviceName = createService()`\n"
            f"- Check TypeScript types: Ensure all properties exist\n\n"
            f"Focus ONLY on fixing the build errors. Provide ALL files that need changes."
        )
        
        try:
            print(f"Calling {model_name} to fix build errors...")
            
            if model_provider == "anthropic":
                # Use Claude with cached context (skills_content in scope from above)
                fix_raw = client.messages_create({
                    "model": settings.ANTHROPIC_MODEL,
                    "system": _build_system_with_cache(comprehensive_context, skills_content),  # Cached!
                    "messages": [{"role": "user", "content": fix_prompt}],
                    "max_tokens": 16000,
                    "temperature": 1,
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": 8000  # Increased for error fixing
                    }
                })
                
                # Track token usage for fix attempts
                if metrics and fix_raw.get("usage"):
                    usage = fix_raw["usage"]
                    metrics.total_input_tokens += usage.get("input_tokens", 0)
                    metrics.total_output_tokens += usage.get("output_tokens", 0)
                    metrics.cached_tokens += usage.get("cache_read_input_tokens", 0)
                    metrics.self_heal_attempts += 1
                    # Recalculate cost
                    metrics.estimated_cost = calculate_cost(
                        settings.ANTHROPIC_MODEL,
                        metrics.total_input_tokens,
                        metrics.total_output_tokens,
                        metrics.cached_tokens
                    )
                
                fix_text = AnthropicClient.extract_text(fix_raw)
            else:
                # Use OpenAI as fallback (using same client as planner)
                from app.llm_openai import OpenAIClient
                openai_client = OpenAIClient(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL
                )
                fix_text, fix_usage = openai_client.responses_text_with_usage(
                    model=settings.OPENAI_MODEL,
                    system=_system_prompt(),
                    user=fix_prompt,
                    max_tokens=16000,
                    temperature=1.0
                )
                # Track OpenAI token usage and add to total cost
                if metrics and fix_usage:
                    openai_in = fix_usage.get("input_tokens", 0) or fix_usage.get("prompt_tokens", 0)
                    openai_out = fix_usage.get("output_tokens", 0) or fix_usage.get("completion_tokens", 0)
                    metrics.total_input_tokens += openai_in
                    metrics.total_output_tokens += openai_out
                    metrics.self_heal_attempts += 1
                    openai_cost = calculate_cost(settings.OPENAI_MODEL, openai_in, openai_out, 0)
                    metrics.estimated_cost += openai_cost
                    print(f"OpenAI token usage: {openai_in} input, {openai_out} output")
                    print(f"OpenAI cost: ${openai_cost:.4f} (total: ${metrics.estimated_cost:.4f})")
            
            # Parse fix response - be more aggressive about finding JSON
            fix_json_text = fix_text.strip()
            
            # Try to find JSON in the response
            # Method 1: Remove markdown code fences
            if '```' in fix_json_text:
                lines = fix_json_text.split('\n')
                # Find start of JSON block
                start_idx = 0
                for i, line in enumerate(lines):
                    if line.strip().startswith('```'):
                        start_idx = i + 1
                        break
                # Find end of JSON block
                end_idx = len(lines)
                for i in range(start_idx, len(lines)):
                    if lines[i].strip() == '```':
                        end_idx = i
                        break
                fix_json_text = '\n'.join(lines[start_idx:end_idx])
            
            # Method 2: Find first { and last }
            if not fix_json_text.strip().startswith('{'):
                first_brace = fix_json_text.find('{')
                if first_brace >= 0:
                    last_brace = fix_json_text.rfind('}')
                    if last_brace > first_brace:
                        fix_json_text = fix_json_text[first_brace:last_brace+1]
            
            # Try to parse JSON
            try:
                fix_payload = json.loads(fix_json_text)
            except json.JSONDecodeError as e:
                print(f"JSON parsing failed: {e}")
                print(f"Attempted to parse (first 500 chars):\n{fix_json_text[:500]}")
                # Log the full response for debugging
                print(f"Full Claude response (first 1000 chars):\n{fix_text[:1000]}")
                raise RuntimeError(f"Claude's fix response was not valid JSON: {e}")
            
            # Apply the fixes
            fix_files = fix_payload.get("files", [])
            if fix_files:
                print(f"Applying {len(fix_files)} file fixes...")
                fixed_files = []
                for file_op in fix_files:
                    file_path = repo_path / file_op["path"]
                    action = file_op.get("action", "update")
                    
                    if action in ("create", "update"):
                        content = file_op.get("content", "")
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(content, encoding="utf-8")
                        fixed_files.append(file_op['path'])
                
                # Re-run verification after fixes
                print("Re-running build verification after fixes...")
                if run_id:
                    add_progress_event(run_id, "verifying", "Re-running build after fixes", {})
                
                verification_errors = []  # Reset errors
                
                # Detect Next.js (is_nextjs may not have been set if initial verification skipped)
                _is_nextjs = False
                if package_json_path.exists():
                    try:
                        _pkg = package_json_path.read_text(encoding="utf-8")
                        _is_nextjs = '"next"' in _pkg or "'next'" in _pkg
                    except Exception:
                        pass
                
                if _is_nextjs:
                    # Clean locks before retry
                    try:
                        next_dir = repo_path / ".next"
                        if next_dir.exists():
                            lock_file = next_dir / "lock"
                            if lock_file.exists():
                                lock_file.unlink()
                    except Exception:
                        pass
                    
                    result = subprocess.run(
                        ["npm", "run", "build"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=180
                    )
                    
                    if result.returncode != 0:
                        error_output = result.stderr if result.stderr else result.stdout
                        verification_errors.append(f"Build still failing after fix attempt {fix_attempt}:\n{error_output[:1000]}")
                        print(f"Build still failing after {model_name} fix:\n{error_output[:500]}")
                    else:
                        print(f"✅ Build succeeded after {model_name} fixes on attempt {fix_attempt}!")
                        notes += f"\n\n⚠️ *Note: Initial build failed, but {model_name} automatically fixed the errors on attempt {fix_attempt}.*"
                        verification_errors = []  # Clear errors to break the retry loop
                        break  # Exit the retry loop on success
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse {model_name}'s fix response as JSON: {e}")
            verification_errors.append(
                f"Auto-fix attempt {fix_attempt} failed: {model_name}'s response was not valid JSON.\n"
                f"Error: {e}"
            )
            # Continue to next attempt
        except Exception as e:
            print(f"Failed to auto-fix errors with {model_name}: {e}")
            import traceback
            traceback.print_exc()
            verification_errors.append(f"Auto-fix attempt {fix_attempt} with {model_name} failed: {e}")
            # Continue to next attempt
    
    # If still failing after all fix attempts, FAIL THE TASK
    if verification_errors:
        error_msg = "\n\n".join(verification_errors)
        print(f"\n{'='*60}")
        print(f"VERIFICATION STILL FAILING AFTER {fix_attempt} ATTEMPTS")
        print(f"{'='*60}")
        print(error_msg)
        
        # Post detailed error to Jira with attempt history
        jira_client = JiraClient(
            base_url=settings.JIRA_BASE_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN
        )
        
        jira_comment = (
            "❌ **Build Verification Failed After Multiple Attempts**\n\n"
            f"Tried {fix_attempt} times to automatically fix the errors:\n"
            f"- Attempts 1-2: Claude (Anthropic)\n"
            f"- Attempt 3: OpenAI GPT-4 (escalation)\n\n"
            "**All attempts failed. This issue requires human intervention.**\n\n"
            f"**Final Errors:**\n```\n{error_msg[:2000]}\n```\n\n"
            "---\n"
            "*Code was not committed. This appears to be a complex issue that needs manual review.*"
        )
        jira_client.add_comment(issue.key, jira_comment)
        
        # Raise error to fail the task
        raise RuntimeError(f"Build verification failed after {fix_attempt} attempts (Claude + OpenAI):\n{error_msg}")
    
    if run_id:
        add_progress_event(run_id, "committing", f"Committing changes: {len(files_changed)} files", {"file_count": len(files_changed)})
    
    # 6) Commit and push to GitHub with descriptive message
    files_summary = ", ".join(files_changed[:5])  # Limit to first 5 files
    if len(files_changed) > 5:
        files_summary += f" (+{len(files_changed) - 5} more)"
    
    # Create rollback tag before committing (safety net!)
    rollback_tag = create_rollback_tag(repo_settings["repo_workdir"], issue.key)
    if rollback_tag:
        print(f"✓ Rollback tag created: {rollback_tag}")
    
    # Build commit message: title + body with files changed
    commit_title = f"{issue.key}: {issue.summary}"
    commit_body = "Files changed:\n" + "\n".join(f"- {fc}" for fc in files_changed)
    commit_message = f"{commit_title}\n\n{commit_body}"
    result_msg = commit_and_push(repo_settings["repo_workdir"], commit_message)
    if "No changes detected" in result_msg:
        print(f"Note: {result_msg}")
    else:
        print(f"✓ Committed and pushed to GitHub: {branch}")
        if run_id:
            add_progress_event(run_id, "committing", f"Pushed to GitHub on branch {branch}", {"branch": branch})
    
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
                repo_settings["repo_workdir"],
                title=f"{issue.key}: {issue.summary}",
                body=pr_body,
                base=repo_settings["base_branch"],
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
    
    # Update and save metrics
    if metrics:
        end_time = datetime.now()
        metrics.end_time = end_time
        metrics.duration_seconds = (end_time - start_time).total_seconds()
        metrics.success = True
        metrics.status = "completed"
        metrics.files_changed = len(files_changed)
        metrics.model_used = settings.ANTHROPIC_MODEL
        
        # Save metrics
        try:
            save_metrics(metrics)
        except Exception as e:
            print(f"Warning: Could not save metrics: {e}")
    
    return ExecutionResult(branch=branch, pr_url=pr_url, summary=summary, jira_comment=jira_comment)
