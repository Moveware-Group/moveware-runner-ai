from __future__ import annotations

import json
import os
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


def _get_nextjs_build_env() -> dict:
    """
    Build env for Next.js npm run build - injects placeholder values for common
    required vars (DATABASE_URL, JWT_SECRET, etc.) if not set. Prevents build failures
    when code validates env at import time but .env is gitignored/missing.
    """
    env = dict(os.environ)
    placeholders = {
        "DATABASE_URL": "postgresql://localhost:5432/build_verification",
        "ENCRYPTION_KEY": "build-time-32-char-placeholder!!!!",
        "JWT_SECRET": "build-time-32-char-placeholder!!!!",
        "MOVEWARE_API_URL": "https://example.com",
        "NEXTAUTH_SECRET": "build-time-32-char-placeholder!!!!",
        "NEXTAUTH_URL": "http://localhost:3000",
    }
    for key, val in placeholders.items():
        if key not in env or not str(env.get(key, "")).strip():
            env[key] = val
    return env


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
            "port": getattr(repo, "port", 3000),
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
            "port": 3000,
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
            'repository': ['prisma/schema.prisma', 'lib/db.ts'],
            'prisma': ['prisma/schema.prisma', 'lib/db.ts'],
            'session': ['prisma/schema.prisma', 'lib/auth.ts'],
            'sso': ['prisma/schema.prisma', 'lib/auth.ts'],
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
        "  * Prettier/formatting: use trailing commas in objects/arrays, proper line breaks\n"
        "  * Prisma: only import types that exist in schema; use `import { Prisma }` not `import type { Prisma }` when using Prisma.PrismaClientKnownRequestError at runtime\n"
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
    
    # For Next.js projects: ensure ecosystem.config.js exists with correct port
    skills_list = repo_settings.get("skills", []) or []
    if "nextjs-fullstack-dev" in skills_list:
        port = repo_settings.get("port", 3000)
        prompt += (
            f"**DEPLOYMENT (Next.js):** This app runs on port {port}. "
            f"You MUST include ecosystem.config.js in the project root if it is missing. "
            f"Use name: '{repo_settings.get('repo_name', 'app')}', PORT: {port}, cwd: __dirname. "
            f"Create logs/ directory for PM2 output.\n\n"
        )
    
    prompt += (
        f"**Repository Context:**\n{context_info}\n\n"
        f"**REMINDER - SCOPE CHECK:**\n"
        f"Before implementing, verify that EVERY file you create is explicitly mentioned in the requirements above.\n"
        f"If you're creating a file that isn't directly requested, STOP and ask a question instead.\n\n"
        f"**REMINDER - CODE STYLE:**\n"
        f"Use Prettier-compliant formatting: trailing commas in objects/arrays, proper line breaks for long parameters.\n\n"
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
        from .json_repair import try_parse_json
        payload = try_parse_json(json_text, max_repair_attempts=3)
        
        if payload is None:
            # JSON repair failed - log and raise
            print(f"❌ Could not parse JSON after repair attempts")
            print(f"Extracted text (first 2000 chars): {json_text[:2000]}")
            raise RuntimeError("Failed to parse Claude response as JSON after repairs")
    except RuntimeError:
        raise
    except json.JSONDecodeError as e:
        # JSON parsing failed - try to repair common issues
        print(f"Failed to parse JSON. Error: {e}")
        print(f"Error position: line {e.lineno}, column {e.colno}, char {e.pos}")
        print(f"Extracted text (first 2000 chars): {json_text[:2000]}")
        
        # Attempt 1: Check if JSON is truncated (missing closing braces/brackets)
        # This is common when response is cut off mid-file
        repaired_json = json_text
        
        # Count opening and closing braces
        open_braces = repaired_json.count('{')
        close_braces = repaired_json.count('}')
        open_brackets = repaired_json.count('[')
        close_brackets = repaired_json.count(']')
        
        if open_braces > close_braces or open_brackets > close_brackets:
            print(f"Detected truncated JSON: {open_braces} {{ vs {close_braces} }}, {open_brackets} [ vs {close_brackets} ]")
            print("Attempting to repair by closing open structures...")
            
            # Try to intelligently close the JSON
            # Add missing closing quotes for strings if needed
            if repaired_json.rstrip().endswith('"'):
                pass  # String is closed
            elif '"' in repaired_json[e.pos-50:e.pos] if e.pos else False:
                # We might be in the middle of a string - close it
                repaired_json += '"'
            
            # Close missing arrays
            while open_brackets > close_brackets:
                repaired_json += '\n  ]'
                close_brackets += 1
            
            # Close missing objects
            while open_braces > close_braces:
                repaired_json += '\n}'
                close_braces += 1
            
            try:
                payload = json.loads(repaired_json)
                print("✓ Successfully repaired truncated JSON!")
                # Continue with repaired payload
            except json.JSONDecodeError as e2:
                print(f"Repair attempt 1 failed: {e2}")
                
                # Attempt 2: Try to find the last complete object/array before truncation
                # Find the last valid position where we can close
                print("Attempting repair by truncating to last valid position...")
                try:
                    # Try to parse progressively smaller chunks
                    for cutoff in [e.pos - 100, e.pos - 500, e.pos - 1000, e.pos - 2000]:
                        if cutoff < 0:
                            continue
                        test_json = json_text[:cutoff]
                        # Close any open structures
                        test_open_braces = test_json.count('{')
                        test_close_braces = test_json.count('}')
                        test_open_brackets = test_json.count('[')
                        test_close_brackets = test_json.count(']')
                        
                        while test_open_brackets > test_close_brackets:
                            test_json += '\n  ]'
                            test_close_brackets += 1
                        while test_open_braces > test_close_braces:
                            test_json += '\n}'
                            test_close_braces += 1
                        
                        try:
                            payload = json.loads(test_json)
                            print(f"✓ Successfully parsed by truncating to position {cutoff}")
                            break
                        except:
                            continue
                    else:
                        raise RuntimeError(f"Could not repair JSON after multiple attempts: {e}")
                except Exception as repair_error:
                    print(f"All repair attempts failed: {repair_error}")
                    raise RuntimeError(
                        f"Failed to parse Claude response as JSON: {e}\n\n"
                        f"The JSON response appears to be truncated or malformed at position {e.pos}.\n"
                        f"This often happens when file contents are too large to embed in JSON.\n"
                        f"Error details: {e.msg} at line {e.lineno}, column {e.colno}"
                    )
        else:
            # Not a truncation issue - likely a syntax error
            error_context = json_text[max(0, e.pos-100):e.pos+100] if e.pos else json_text[:200]
            raise RuntimeError(
                f"Failed to parse Claude response as JSON: {e}\n\n"
                f"Error context around position {e.pos}:\n{error_context}\n\n"
                f"This appears to be a JSON syntax error, not truncation."
            )
    except Exception as e:
        # Other non-JSON errors
        print(f"Unexpected error parsing response: {e}")
        print(f"Response (first 2000 chars): {json_text[:2000]}")
        raise RuntimeError(f"Failed to parse Claude response: {e}")

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
    
    # 4b) Proactive formatting: use lint-staged if present, else Prettier + ESLint --fix
    # Uses project tooling when available (Cursor-like)
    code_files = [f["path"] for f in files if f.get("action", "update") != "delete" and f["path"].endswith(('.ts', '.tsx', '.js', '.jsx', '.css'))]
    if code_files and (repo_path / "package.json").exists():
        import subprocess
        if run_id:
            add_progress_event(run_id, "executing", "Auto-formatting changed files", {})
        try:
            pkg = json.loads((repo_path / "package.json").read_text(encoding="utf-8"))
            has_lint_staged = "lint-staged" in (pkg.get("devDependencies") or {}) or "lint-staged" in (pkg.get("dependencies") or {})
            lint_staged_ok = False
            if has_lint_staged:
                print("Running lint-staged (project tooling)...")
                subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True, text=True, timeout=5)
                result = subprocess.run(
                    ["npx", "lint-staged"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env={**os.environ, "ESLINT_USE_FLAT_CONFIG": "false"}
                )
                lint_staged_ok = result.returncode == 0
                if not lint_staged_ok:
                    print(f"lint-staged had issues: {result.stderr[:300]}")
            if not lint_staged_ok:
                print("Running Prettier on changed files...")
                subprocess.run(
                    ["npx", "prettier", "--write"] + code_files,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                eslint_files = [f for f in code_files if f.endswith(('.ts', '.tsx', '.js', '.jsx'))]
                if eslint_files and any((repo_path / c).exists() for c in [".eslintrc", ".eslintrc.js", ".eslintrc.json", "eslint.config.js"]):
                    print("Running ESLint --fix on changed files...")
                    subprocess.run(
                        ["npx", "eslint", "--fix", *eslint_files],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        env={**os.environ, "ESLINT_USE_FLAT_CONFIG": "false"}
                    )
            print("✓ Auto-formatting complete")
        except Exception as e:
            print(f"Warning: Proactive formatting failed: {e}")
    
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

    # 4.5) Proactive checks BEFORE verification (prevent common issues)
    if run_id:
        add_progress_event(run_id, "verifying", "Running proactive dependency checks", {})
    
    from .proactive_checks import run_proactive_checks, format_proactive_check_results
    proactive_fixes, proactive_warnings = run_proactive_checks(repo_path)
    
    if proactive_fixes or proactive_warnings:
        check_results = format_proactive_check_results(proactive_fixes, proactive_warnings)
        print(check_results)
        if proactive_fixes:
            print(f"✓ Applied {len(proactive_fixes)} proactive fixes before build")
    
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
                else:
                    # Address security vulnerabilities after install (non-breaking fixes only)
                    if run_id:
                        add_progress_event(run_id, "verifying", "Checking and fixing security vulnerabilities (npm audit fix)", {})
                    try:
                        print("Running npm audit fix to address security vulnerabilities...")
                        audit_result = subprocess.run(
                            ["npm", "audit", "fix"],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            timeout=60
                        )
                        if audit_result.returncode == 0:
                            if audit_result.stdout and "fixed" in audit_result.stdout.lower():
                                print(f"✓ Security vulnerabilities fixed:\n{audit_result.stdout[:500]}")
                            else:
                                print("✓ No fixable vulnerabilities or already up to date")
                        else:
                            # audit fix exits 1 when vulns remain (e.g. require --force/breaking changes)
                            audit_out = (audit_result.stdout or "") + (audit_result.stderr or "")
                            if audit_out.strip():
                                print(f"npm audit fix: {audit_out[:600]}")
                            # Don't block build - we've applied safe fixes; remaining vulns need manual review
                    except subprocess.TimeoutExpired:
                        print("Warning: npm audit fix timed out")
                    except Exception as e:
                        print(f"Warning: npm audit fix failed: {e}")
            except subprocess.TimeoutExpired:
                verification_errors.append("npm install timed out after 60 seconds")
                print("npm install timed out")
            except Exception as e:
                verification_errors.append(f"Could not run npm install: {e}")
                print(f"npm install exception: {e}")
            
            # Step 2a: Run tsc --noEmit (fast TypeScript gate before heavy build)
            if not verification_errors and (repo_path / "tsconfig.json").exists():
                try:
                    if run_id:
                        add_progress_event(run_id, "verifying", "Running TypeScript check (tsc --noEmit)", {})
                    print("Running tsc --noEmit (TypeScript gate before build)...")
                    tsc_result = subprocess.run(
                        ["npx", "tsc", "--noEmit", "--pretty", "false"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if tsc_result.returncode != 0:
                        tsc_output = tsc_result.stdout or tsc_result.stderr
                        verification_errors.append(f"TypeScript check failed (tsc --noEmit):\n{tsc_output[:3000]}")
                        print(f"tsc failed:\n{tsc_output[:500]}")
                    else:
                        print("✅ TypeScript check passed")
                except subprocess.TimeoutExpired:
                    verification_errors.append("TypeScript check timed out (60s)")
                except Exception as e:
                    verification_errors.append(f"TypeScript check failed: {e}")
            
            # Step 2b: Run build for Next.js/React projects (CRITICAL for catching errors)
            if not verification_errors:  # Only build if tsc and install succeeded
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
                            timeout=180,  # 3 minute timeout for build
                            env=_get_nextjs_build_env(),
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
    MAX_FIX_ATTEMPTS = settings.MAX_FIX_ATTEMPTS
    fix_attempt = 0
    
    # Try all auto-fixes before engaging AI (saves time and cost!)
    if verification_errors:
        from .auto_fixes import try_all_auto_fixes
        from .syntax_fixer import try_syntax_auto_fixes
        error_text_for_autofix = "\n".join(verification_errors)
        
        # First try syntax fixes (handles structural issues)
        if is_node_project:
            # Extract file path from error
            file_match = re.search(r'\./([^\s:]+\.(?:ts|tsx|js|jsx))', error_text_for_autofix)
            if file_match:
                error_file = repo_path / file_match.group(1)
                syntax_fixed, syntax_desc = try_syntax_auto_fixes(error_file, error_text_for_autofix)
                if syntax_fixed:
                    print(f"✅ Syntax auto-fix applied: {syntax_desc}")
                    if run_id:
                        add_progress_event(run_id, "verifying", f"Syntax auto-fix: {syntax_desc}", {})
                    
                    # Re-run build
                    result = subprocess.run(
                        ["npm", "run", "build"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        env=_get_nextjs_build_env(),
                    )
                    if result.returncode == 0:
                        print("✅ Build succeeded after syntax auto-fix!")
                        verification_errors = []
                        error_text_for_autofix = ""
                    else:
                        error_output = result.stderr or result.stdout
                        verification_errors = [f"Build still failing after syntax fix ({syntax_desc}):\n{error_output[:2000]}"]
                        error_text_for_autofix = "\n".join(verification_errors)
        
        # Then try general auto-fixes
        if verification_errors:
            auto_fix_success, auto_fix_desc = try_all_auto_fixes(error_text_for_autofix, repo_path, is_node_project)
        
        if auto_fix_success:
            print(f"✅ Auto-fix applied: {auto_fix_desc}")
            if run_id:
                add_progress_event(run_id, "verifying", f"Auto-fix applied: {auto_fix_desc}", {})
            
            # Re-run build to see if auto-fix worked
            if is_node_project:
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=_get_nextjs_build_env(),
                )
                if result.returncode == 0:
                    print("✅ Build succeeded after auto-fix!")
                    verification_errors = []  # Clear errors - build passed!
                else:
                    # Still failing, update error message
                    error_output = result.stderr or result.stdout
                    verification_errors = [f"Build still failing after auto-fix ({auto_fix_desc}):\n{error_output[:2000]}"]
    
    # Auto-fix missing npm packages (e.g. "Cannot find module 'autoprefixer'") before AI (legacy fallback)
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
                # Determine if it should be a dev dependency
                is_dev_dep = any(pkg in missing_pkg for pkg in ["eslint", "prettier", "typescript", "postcss", "autoprefixer", "tailwind"])
                install_flag = "--save-dev" if is_dev_dep else "--save"
                subprocess.run(
                    ["npm", "install", install_flag, missing_pkg, "--no-audit", "--prefer-offline"],
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
                    timeout=180,
                    env=_get_nextjs_build_env(),
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
    
    # Auto-fix missing ESLint config packages (e.g. "eslint-config-next")
    error_text_initial = "\n".join(verification_errors)
    _eslint_config = re.search(r"Cannot find module ['\"]eslint-config-([^'\"]+)['\"]", error_text_initial)
    if _eslint_config and is_node_project and not _cannot_find:  # Don't duplicate if already handled above
        config_pkg = f"eslint-config-{_eslint_config.group(1).strip()}"
        try:
            print(f"Auto-installing missing ESLint config: {config_pkg}")
            if run_id:
                add_progress_event(run_id, "verifying", f"Installing ESLint config: {config_pkg}", {})
            subprocess.run(
                ["npm", "install", "--save-dev", config_pkg, "--no-audit", "--prefer-offline"],
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
                timeout=180,
                env=_get_nextjs_build_env(),
            )
            if result.returncode == 0:
                print(f"✅ Build succeeded after installing {config_pkg}!")
            else:
                verification_errors.append(
                    f"Build still failing after npm install {config_pkg}:\n"
                    f"{(result.stderr or result.stdout)[:1000]}"
                )
        except Exception as e:
            verification_errors.append(f"Failed to auto-install {config_pkg}: {e}")
    
    # Build error text for downstream checks
    error_text = "\n".join(verification_errors)
    
    # Auto-run prisma generate when @prisma/client has no exported member (schema may have been updated)
    _prisma_member = re.search(r"Module ['\"]@prisma/client['\"] has no exported member ['\"](\w+)['\"]", error_text)
    if _prisma_member and is_node_project and (repo_path / "prisma" / "schema.prisma").exists():
        missing_model = _prisma_member.group(1)
        try:
            print(f"Detected missing Prisma model: {missing_model}")
            print("Running prisma generate (schema may have been updated)...")
            if run_id:
                add_progress_event(run_id, "verifying", "Running prisma generate", {})
            result = subprocess.run(
                ["npx", "prisma", "generate"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=_get_nextjs_build_env(),
                )
                if result.returncode == 0:
                    print("✅ Build succeeded after prisma generate!")
                    verification_errors = []
                    error_text = ""
                else:
                    error_output = result.stderr or result.stdout
                    # Still failing - analyze the schema and provide specific guidance
                    schema_path = repo_path / "prisma" / "schema.prisma"
                    schema_content = schema_path.read_text(encoding="utf-8")
                    
                    # Extract actual model names from schema
                    actual_models = re.findall(r'^model\s+(\w+)\s*\{', schema_content, re.MULTILINE)
                    
                    # Check if the missing model exists (case-insensitive)
                    similar_models = [m for m in actual_models if m.lower() == missing_model.lower()]
                    if similar_models:
                        hint = f"\n\n**CRITICAL SCHEMA ISSUE:**\nModel '{missing_model}' not in schema, but '{similar_models[0]}' exists (case mismatch!).\nUse EXACT model name: '{similar_models[0]}'"
                    else:
                        # Find similar names (simple string matching)
                        similar = [m for m in actual_models if missing_model.lower() in m.lower() or m.lower() in missing_model.lower()]
                        if similar:
                            hint = f"\n\n**CRITICAL SCHEMA ISSUE:**\nModel '{missing_model}' does NOT exist in prisma/schema.prisma.\nSimilar models found: {', '.join(similar)}\nAvailable models: {', '.join(actual_models)}\n\n**FIX OPTIONS:**\n1. Use one of the existing models above\n2. Add 'model {missing_model}' to prisma/schema.prisma and run prisma generate\n3. Define a local TypeScript interface instead"
                        else:
                            hint = f"\n\n**CRITICAL SCHEMA ISSUE:**\nModel '{missing_model}' does NOT exist in prisma/schema.prisma.\nAvailable models in schema: {', '.join(actual_models)}\n\n**FIX OPTIONS:**\n1. Use one of the existing models: {', '.join(actual_models[:5])}\n2. Add 'model {missing_model}' to prisma/schema.prisma and run prisma generate\n3. Define a local TypeScript interface instead of importing from @prisma/client"
                    
                    verification_errors = [f"Build still failing after prisma generate:\n{error_output[:1500]}{hint}"]
            else:
                print(f"prisma generate failed: {result.stderr}")
        except Exception as e:
            print(f"prisma generate failed: {e}")
        error_text = "\n".join(verification_errors)
    
    # Auto-fix Prettier formatting errors (don't burn LLM attempts on formatting)
    if "prettier/prettier" in error_text and is_node_project:
        # Collect files to format: from error output + our known changed files
        prettier_files = set()
        # Match paths in error: ./src/..., /absolute/path/src/..., or src/...
        for m in re.findall(r'src/[^\s:]+\.(?:ts|tsx|js|jsx|css|json)', error_text):
            prettier_files.add(m)
        # Always include our changed code files - we know they're relevant
        for fc in files_changed:
            if "Deleted" not in fc and any(fc.endswith(ext) for ext in ('.ts', '.tsx', '.js', '.jsx', '.css')):
                path = fc.replace("Created ", "").replace("Updated ", "")
                if path:
                    prettier_files.add(path)
        prettier_files = [f for f in prettier_files if (repo_path / f).exists()]
        if not prettier_files:
            # Fallback: format entire src directory
            if (repo_path / "src").exists():
                prettier_files = ["src"]
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
                        timeout=180,
                        env=_get_nextjs_build_env(),
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
    
    # Track previous fix attempts for self-reflection
    previous_fix_attempts = []
    
    # Auto-fix: Prisma imported with "import type" but used as value (e.g. Prisma.PrismaClientKnownRequestError)
    if "cannot be used as a value because it was imported using 'import type'" in error_text and "Prisma" in error_text and is_node_project:
        prisma_import_files = list(set(re.findall(r'src/[^\s:]+\.(?:ts|tsx)', error_text)))
        prisma_fix_applied = False
        for rel_path in prisma_import_files:
            fp = repo_path / rel_path
            if not fp.exists():
                continue
            try:
                content = fp.read_text(encoding="utf-8")
                # Match: import type { X, Prisma, Y } from '@prisma/client'
                def _fix_prisma_import(m):
                    imports = [s.strip() for s in m.group(1).split(",")]
                    if "Prisma" not in imports:
                        return m.group(0)
                    new_imports = [f"type {x}" if x != "Prisma" else "Prisma" for x in imports]
                    return f"import {{ {', '.join(new_imports)} }} from {m.group(2)}"
                new_content, n = re.subn(
                    r"import type\s*\{\s*([^}]+)\}\s*from\s*(['\"]@prisma/client['\"])",
                    _fix_prisma_import,
                    content,
                    count=0
                )
                if n > 0:
                    fp.write_text(new_content, encoding="utf-8")
                    print(f"Fixed Prisma import in {rel_path}")
                    prisma_fix_applied = True
            except Exception as e:
                print(f"Prisma import fix failed for {rel_path}: {e}")
        if prisma_fix_applied:
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=180,
                env=_get_nextjs_build_env(),
            )
            if result.returncode == 0:
                print("✅ Build succeeded after Prisma import fix!")
                verification_errors = []
            else:
                verification_errors = [f"Build still failing after Prisma import fix:\n{(result.stderr or result.stdout)[:2000]}"]
            error_text = "\n".join(verification_errors)
    
    # Auto-fix: Missing env var type definition (e.g. "Property 'JWT_SECRET' does not exist on type")
    _env_type_missing = re.search(r"Property ['\"]([A-Z_]+)['\"] does not exist on type.*?(?:NODE_ENV|DATABASE_URL|env)", error_text)
    if _env_type_missing and is_node_project:
        missing_env_var = _env_type_missing.group(1)
        print(f"Detected missing env type: {missing_env_var}")
        
        # Find env schema file
        env_file_candidates = [
            "src/env.ts",
            "src/env.mjs", 
            "src/lib/env.ts",
            "src/lib/env.mjs",
            "lib/env.ts",
        ]
        
        env_file_path = None
        for candidate in env_file_candidates:
            if (repo_path / candidate).exists():
                env_file_path = repo_path / candidate
                break
        
        if env_file_path:
            try:
                content = env_file_path.read_text(encoding="utf-8")
                
                # Pattern 1: Object literal with properties
                # const env = { NODE_ENV: ..., DATABASE_URL: ... }
                if "const env = {" in content or "const env: " in content:
                    # Find the closing brace of the env object
                    # Add the missing property before the closing brace
                    pattern = r"(const env\s*(?::\s*\{[^}]*\})?\s*=\s*\{[^}]*?)(\n\s*\})"
                    
                    def add_env_property(m):
                        existing = m.group(1)
                        closing = m.group(2)
                        # Add comma if last line doesn't have one
                        if not existing.rstrip().endswith(','):
                            existing += ','
                        new_property = f"\n  {missing_env_var}: process.env.{missing_env_var}!"
                        return existing + new_property + closing
                    
                    new_content, n = re.subn(pattern, add_env_property, content, count=1)
                    
                    if n > 0:
                        env_file_path.write_text(new_content, encoding="utf-8")
                        print(f"✅ Added {missing_env_var} to {env_file_path.relative_to(repo_path)}")
                        
                        # Re-run build
                        result = subprocess.run(
                            ["npm", "run", "build"],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            timeout=180,
                            env=_get_nextjs_build_env(),
                        )
                        if result.returncode == 0:
                            print("✅ Build succeeded after adding env var type!")
                            verification_errors = []
                        else:
                            verification_errors = [f"Build still failing after adding {missing_env_var}:\n{(result.stderr or result.stdout)[:2000]}"]
                        error_text = "\n".join(verification_errors)
            except Exception as e:
                print(f"Failed to auto-fix env type: {e}")
    
    while verification_errors and fix_attempt < MAX_FIX_ATTEMPTS:
        fix_attempt += 1
        error_msg = "\n\n".join(verification_errors)
        
        # Alternate between Claude and OpenAI for diverse perspectives
        # Odd attempts (1, 3, 5, 7): Claude (cheaper, faster)
        # Even attempts (2, 4, 6): OpenAI (fresh perspective, different reasoning)
        if fix_attempt % 2 == 1:
            model_name = "Claude"
            model_provider = "anthropic"
        else:
            model_name = f"OpenAI ({settings.OPENAI_MODEL})"
            model_provider = "openai"
            if fix_attempt == 2:
                print(f"\n{'='*60}")
                print(f"SWITCHING TO OPENAI: Getting second opinion from {settings.OPENAI_MODEL}")
                print(f"Alternating models for diverse fix approaches...")
                print(f"{'='*60}\n")
        
        print(f"\nVERIFICATION FAILED - Attempt {fix_attempt}/{MAX_FIX_ATTEMPTS} using {model_name}")
        print(f"Error summary: {error_msg[:200]}...")
        
        # Classify errors and get targeted hints
        error_category, specific_hint, _ = classify_error(error_msg)
        comprehensive_hint = get_comprehensive_hint(error_msg)
        error_context = extract_error_context(error_msg, max_context_lines=3)
        
        # Get similar successful fixes from pattern learning database
        from .pattern_learner import get_similar_successful_fixes, format_fix_suggestions
        similar_patterns = get_similar_successful_fixes(error_msg, limit=3)
        pattern_guidance = format_fix_suggestions(similar_patterns)
        
        if similar_patterns:
            print(f"Found {len(similar_patterns)} similar past fixes (confidence: {int(similar_patterns[0].confidence*100)}%)")
        
        # Self-reflection: analyze what went wrong in previous attempts
        reflection_guidance = ""
        if fix_attempt > 1 and previous_fix_attempts:
            from .self_reflection import analyze_fix_failure, format_reflection_guidance
            last_attempt = previous_fix_attempts[-1]
            reflection_analysis = analyze_fix_failure(
                attempt_num=fix_attempt,
                previous_error=last_attempt.get("error", ""),
                new_error=error_msg,
                fix_applied=last_attempt,
                previous_attempts=previous_fix_attempts
            )
            reflection_guidance = format_reflection_guidance(reflection_analysis)
            print(f"Self-reflection: {len(reflection_analysis['recommendations'])} recommendations for attempt {fix_attempt}")
        
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
        
        # Also extract TypeScript path alias imports (e.g., "@/lib/db/repositories")
        # These often appear in errors like: Module "@/lib/foo" has no exported member "bar"
        alias_pattern = r'["\']@/([^\s"\']+?)["\']'
        for match in re.finditer(alias_pattern, error_msg):
            alias_path = match.group(1)
            # Try common extensions for TypeScript path aliases
            for ext in ['.ts', '.tsx', '/index.ts', '/index.tsx', '.js', '.jsx']:
                candidate = f"src/{alias_path}{ext}"
                if (repo_path / candidate).exists():
                    error_files.add(candidate)
                    break
            # Also try without src/ prefix in case @ maps to root
            for ext in ['.ts', '.tsx', '/index.ts', '/index.tsx']:
                candidate = f"{alias_path}{ext}"
                if (repo_path / candidate).exists():
                    error_files.add(candidate)
                    break
        
        # For Prisma errors, ALWAYS include schema.prisma so AI can see actual models/fields
        prisma_schema_path = repo_path / "prisma" / "schema.prisma"
        if prisma_schema_path.exists():
            # Include for specific Prisma error types
            if error_category in ("prisma_schema_mismatch", "prisma_model_missing"):
                error_files.add("prisma/schema.prisma")
                print(f"Including prisma/schema.prisma in context for {error_category} error")
            # Also include if error message mentions @prisma/client or PrismaClient
            elif "@prisma/client" in error_msg or "PrismaClient" in error_msg:
                error_files.add("prisma/schema.prisma")
                print("Including prisma/schema.prisma in context (Prisma-related error detected)")
        
        # For env type errors, include env schema files so AI can add missing properties
        if error_category == "env_type_missing":
            # Common env schema file locations
            env_file_candidates = [
                "src/env.ts",
                "src/env.mjs",
                "src/lib/env.ts",
                "src/lib/env.mjs",
                "lib/env.ts",
                "env.ts",
                "src/config/env.ts",
            ]
            for env_file in env_file_candidates:
                if (repo_path / env_file).exists():
                    error_files.add(env_file)
                    print(f"Including {env_file} in context for env_type_missing error")
                    break  # Only include first match
        
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
        
        # Add full file contents of error files (up to 15K chars) for better fix context
        for error_file in sorted(error_files):
            file_path = repo_path / error_file
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    max_chars = 15000  # Full context for typical files
                    error_file_contents.append(f"\n**Current {error_file}:**\n```typescript\n{content[:max_chars]}\n```")
                    if len(content) > max_chars:
                        error_file_contents.append(f"... (file truncated, {len(content) - max_chars} chars omitted)")
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
        elif error_category == "unknown":
            # Fallback for unclassified errors - give generic but useful guidance
            error_analysis_section = (
                "\n**ERROR TYPE: UNKNOWN (no specific pattern matched)**\n"
                "Common causes: Prisma schema mismatches (property doesn't exist in CreateInput/UpdateInput), "
                "type mismatches, missing exports, wrong field names. "
                "Read the error message carefully - it often names the exact property and type. "
                "If it says 'X does not exist in type Y', check the schema/interface for Y and use only valid properties.\n\n"
            )
        
        fix_prompt = (
            f"The code has build errors. You MUST fix ALL errors to make the build pass.\n\n"
            f"**Attempt:** {fix_attempt}/{MAX_FIX_ATTEMPTS}\n"
            f"**Previous attempts:** {'Failed ' + str(fix_attempt-1) + ' time(s) - learn from mistakes!' if fix_attempt > 1 else 'First attempt'}\n\n"
            f"**Original Task:** {issue.key} - {issue.summary}\n\n"
            f"**Build Errors:**\n```\n{error_msg[:1500]}\n```\n\n"
            f"{error_analysis_section}"
            f"{pattern_guidance}"
            f"{reflection_guidance}"
            f"\n**MANDATORY DEBUGGING PROCESS:**\n"
            f"1. **READ THE ERROR MESSAGE COMPLETELY** - Every word matters!\n"
            f"   - What file has the error? (look for file paths)\n"
            f"   - What line number? (helps locate the problem)\n"
            f"   - What exactly is the error? (missing export, type mismatch, syntax, etc.)\n\n"
            f"2. **READ THE ACTUAL FILE CONTENTS** (provided in context below)\n"
            f"   - Don't guess what's in the file - READ IT!\n"
            f"   - Search for 'export' keyword to see what's actually exported\n"
            f"   - Check the exact spelling and casing (JavaScript is case-sensitive!)\n\n"
            f"3. **COMPARE ERROR vs REALITY**\n"
            f"   - Error says: \"Module has no exported member 'userRepository'\"\n"
            f"   - File contains: 'export const UserRepository' ← Different casing!\n"
            f"   - OR File contains: 'const userRepository' ← Missing 'export' keyword!\n"
            f"   - Fix: Either add export OR fix import to match actual name\n\n"
            f"4. **BEFORE CHANGING ANY FILE - VERIFY:**\n"
            f"   - If adding an import → CHECK the source file exports that name\n"
            f"   - If adding a function call → CHECK the function signature (arguments)\n"
            f"   - If adding a constant → CHECK it doesn't already exist (no duplicates!)\n"
            f"   - If changing a file → READ IT FIRST to understand current state\n\n"
            f"5. **APPLY THE FIX**\n"
            f"   - Missing export? Add 'export' keyword to the SOURCE file\n"
            f"   - Wrong name? Fix the import to match actual export name\n"
            f"   - Missing package? Add to package.json dependencies\n"
            f"   - Type error? Check interface and add missing properties\n"
            f"   - Function signature mismatch? Check actual function definition\n\n"
            f"**Key Error Context:**\n{chr(10).join(error_context) if error_context else 'See full errors above'}\n\n"
            f"**Full Repository Context:**\n{comprehensive_context}\n\n"
            f"**RESPONSE FORMAT - CRITICAL:**\n"
            f"Your response MUST be ONLY valid JSON. No markdown code fences, no explanation, JUST JSON.\n\n"
            f"Provide COMPLETE fixed files using this EXACT format:\n"
            f"{{\n"
            f'  "implementation_plan": "Step-by-step: what you read, what you found, what you fixed",\n'
            f'  "files": [\n'
            f'    {{\n'
            f'      "path": "relative/path/to/file.ext",\n'
            f'      "action": "update",\n'
            f'      "content": "COMPLETE file content (not just the changed part)"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "summary": "Fixed [specific errors] by [specific actions]"\n'
            f"}}\n\n"
            f"**COMMON ERROR PATTERNS & FIXES:**\n\n"
            f"❌ Error: \"Module '@/lib/foo' has no exported member 'bar'\"\n"
            f"✅ Fix Process:\n"
            f"   1. Read @/lib/foo file contents (it's in the context!)\n"
            f"   2. Search for 'export' - what DOES it export?\n"
            f"   3. If it exports 'Bar' (capital B) → Change import to 'Bar'\n"
            f"   4. If nothing is exported → Add 'export const bar = ...'\n\n"
            f"❌ Error: \"Cannot find module 'autoprefixer'\"\n"
            f"✅ Fix: Add to package.json devDependencies: \"autoprefixer\": \"^10.4.0\"\n\n"
            f"❌ Error: \"Property 'userId' does not exist on type 'User'\"\n"
            f"✅ Fix Process:\n"
            f"   1. Read the User interface definition\n"
            f"   2. Check what properties it HAS (maybe it's 'id' not 'userId'?)\n"
            f"   3. Either add 'userId' to interface OR change code to use existing property\n\n"
            f"❌ Error: \"Type string is not assignable to type number\"\n"
            f"✅ Fix: Convert the type: parseInt(value) or value.toString() depending on direction\n\n"
            f"❌ Error: \"Unexpected token\"\n"
            f"✅ Fix: Check for missing brackets, quotes, commas, or semicolons\n\n"
            f"**DO NOT MAKE THESE MISTAKES:**\n"
            f"- ❌ Guessing what's in a file without reading it\n"
            f"- ❌ Assuming export names match (check casing!)\n"
            f"- ❌ Adding imports without verifying the export exists\n"
            f"- ❌ Providing partial file content (must be COMPLETE)\n"
            f"- ❌ Wrapping JSON in markdown code fences\n\n"
            f"**REMEMBER:** Read → Verify → Fix → Verify again. Focus ONLY on fixing build errors."
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
            
            # Try to parse JSON with repair
            from .json_repair import try_parse_json
            fix_payload = try_parse_json(fix_json_text, max_repair_attempts=3)
            
            if fix_payload is None:
                print(f"❌ JSON parsing failed after repairs")
                print(f"Attempted to parse (first 500 chars):\n{fix_json_text[:500]}")
                # Log the full response for debugging
                print(f"Full {model_name} response (first 1000 chars):\n{fix_text[:1000]}")
                raise RuntimeError(f"{model_name}'s fix response was not valid JSON after repair attempts")
            
            # Validate the fix BEFORE applying it
            from .fix_validator import validate_fix_before_apply
            is_valid, validation_errors, validation_warnings = validate_fix_before_apply(fix_payload, repo_path)
            
            if not is_valid:
                print(f"❌ Fix validation FAILED:")
                for error in validation_errors:
                    print(f"  - {error}")
                
                # Add validation errors to verification errors and continue to next attempt
                verification_errors.append(
                    f"Fix validation failed before applying:\n" + 
                    "\n".join(f"  - {e}" for e in validation_errors)
                )
                print(f"Skipping this fix due to validation errors, will try again...")
                
                # Record failed attempt
                from .pattern_learner import record_fix_attempt, record_failed_fix
                from .self_reflection import extract_fix_metadata
                fix_strategy = fix_payload.get("summary", "Unknown fix strategy")
                if run_id:
                    record_fix_attempt(
                        run_id=run_id,
                        issue_key=issue.key,
                        attempt_number=fix_attempt,
                        error_msg=error_msg,
                        fix_strategy=fix_strategy,
                        files_changed=[],
                        model_used=model_name,
                        success=False
                    )
                record_failed_fix(error_msg, f"{fix_strategy} (validation failed)")
                
                # Track for self-reflection
                attempt_metadata = extract_fix_metadata(fix_payload, [])
                attempt_metadata["error"] = error_msg
                attempt_metadata["validation_failed"] = True
                attempt_metadata["validation_errors"] = validation_errors
                previous_fix_attempts.append(attempt_metadata)
                
                # If validation keeps failing on same file, add explicit file contents with line numbers
                validation_failures_on_file = sum(
                    1 for attempt in previous_fix_attempts 
                    if attempt.get("validation_failed")
                )
                
                if validation_failures_on_file >= 2:
                    # Add explicit guidance about the validation failure
                    error_file_with_issues = validation_errors[0].split(":")[0] if validation_errors else ""
                    if error_file_with_issues:
                        file_to_show = repo_path / error_file_with_issues
                        if file_to_show.exists():
                            try:
                                actual_content = file_to_show.read_text(encoding="utf-8")
                                lines_with_numbers = []
                                for i, line in enumerate(actual_content.split('\n')[:200], 1):  # First 200 lines
                                    lines_with_numbers.append(f"{i:4d} | {line}")
                                
                                comprehensive_context += (
                                    f"\n\n**⚠️ VALIDATION KEEPS FAILING ON {error_file_with_issues}**\n"
                                    f"**CRITICAL - HERE IS THE CURRENT FILE WITH LINE NUMBERS:**\n\n"
                                    f"```typescript\n"
                                    f"{''.join(lines_with_numbers[:150])}\n"  # First 150 lines
                                    f"```\n\n"
                                    f"**VALIDATION FAILURES:**\n"
                                    + "\n".join(f"  - {e}" for e in validation_errors) + "\n\n"
                                    f"**INSTRUCTIONS:**\n"
                                    f"1. READ the line numbers above to find exact locations\n"
                                    f"2. CHECK for duplicate declarations at the mentioned lines\n"
                                    f"3. DO NOT add new declarations with same name - rename or remove duplicates\n"
                                    f"4. Provide the COMPLETE fixed file\n"
                                )
                            except Exception as e:
                                print(f"Could not add file with line numbers: {e}")
                
                continue  # Skip to next attempt
            
            # Show warnings if any
            if validation_warnings:
                print(f"⚠️  Fix validation warnings:")
                for warning in validation_warnings:
                    print(f"  - {warning}")
            
            # Apply the fixes (validation passed!)
            fix_files = fix_payload.get("files", [])
            if fix_files:
                print(f"✅ Validation passed - applying {len(fix_files)} file fixes...")
                fixed_files = []
                for file_op in fix_files:
                    file_path = repo_path / file_op["path"]
                    action = file_op.get("action", "update")
                    
                    if action in ("create", "update"):
                        content = file_op.get("content", "")
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(content, encoding="utf-8")
                        fixed_files.append(file_op['path'])
                
                # Run Prettier on fixed files - LLM output often introduces formatting errors
                if fixed_files:
                    code_fixed = [p for p in fixed_files if p.endswith(('.ts', '.tsx', '.js', '.jsx', '.css'))]
                    if code_fixed:
                        try:
                            subprocess.run(
                                ["npx", "prettier", "--write"] + code_fixed,
                                cwd=repo_path,
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                        except Exception as e:
                            print(f"Prettier on fixed files: {e}")
                
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
                        timeout=180,
                        env=_get_nextjs_build_env(),
                    )
                    
                    if result.returncode != 0:
                        error_output = result.stderr if result.stderr else result.stdout
                        verification_errors.append(f"Build still failing after fix attempt {fix_attempt}:\n{error_output[:1000]}")
                        print(f"Build still failing after {model_name} fix:\n{error_output[:500]}")
                        
                        # Record failed fix attempt to learn from it
                        from .pattern_learner import record_fix_attempt, record_failed_fix
                        from .self_reflection import extract_fix_metadata
                        fix_strategy = fix_payload.get("summary", "Unknown fix strategy")
                        if run_id:
                            record_fix_attempt(
                                run_id=run_id,
                                issue_key=issue.key,
                                attempt_number=fix_attempt,
                                error_msg=error_msg,
                                fix_strategy=fix_strategy,
                                files_changed=fixed_files,
                                model_used=model_name,
                                success=False
                            )
                        record_failed_fix(error_msg, fix_strategy)
                        
                        # Track for self-reflection
                        attempt_metadata = extract_fix_metadata(fix_payload, fixed_files)
                        attempt_metadata["error"] = error_msg
                        previous_fix_attempts.append(attempt_metadata)
                    else:
                        print(f"✅ Build succeeded after {model_name} fixes on attempt {fix_attempt}!")
                        notes += f"\n\n⚠️ *Note: Initial build failed, but {model_name} automatically fixed the errors on attempt {fix_attempt}.*"
                        
                        # Record successful fix to pattern learning database
                        from .pattern_learner import record_fix_attempt, record_successful_fix
                        fix_strategy = fix_payload.get("summary", "Unknown fix strategy")
                        if run_id:
                            record_fix_attempt(
                                run_id=run_id,
                                issue_key=issue.key,
                                attempt_number=fix_attempt,
                                error_msg=error_msg,
                                fix_strategy=fix_strategy,
                                files_changed=fixed_files,
                                model_used=model_name,
                                success=True
                            )
                        record_successful_fix(error_msg, fix_strategy, fixed_files)
                        print(f"✅ Recorded successful fix pattern for future use (category: {error_category})")
                        
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
        
        # Build attempt summary (alternating models)
        attempt_summary = []
        for i in range(1, fix_attempt + 1):
            model = "Claude (Anthropic)" if i % 2 == 1 else f"OpenAI ({settings.OPENAI_MODEL})"
            attempt_summary.append(f"- Attempt {i}: {model}")
        
        jira_comment = (
            "❌ **Build Verification Failed After Multiple Attempts**\n\n"
            f"Tried {fix_attempt} times with alternating AI models for diverse fix approaches:\n"
            f"{chr(10).join(attempt_summary)}\n\n"
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
