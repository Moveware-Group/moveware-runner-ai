from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    success: bool = True


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


def _resolve_file_questions(
    questions: list, repo_path: Path
) -> tuple:
    """
    Detect file-path references in Claude's questions and auto-read them.

    Returns:
        (file_contents: dict[str, str], remaining_questions: list[str])
        file_contents maps relative paths to their content.
        remaining_questions are questions that could NOT be resolved by reading files.
    """
    # Regex patterns that match common file-path references in questions
    path_pattern = re.compile(
        r"""(?:content of|provide|see|read|need|source|check|look at|view|inspect)[:\s]*"""
        r"""[`'"]*"""
        r"""((?:src|app|lib|components|pages|public|utils|hooks|services|types|config|prisma)"""
        r"""[/\\][\w./\\[\]-]+\.(?:ts|tsx|js|jsx|css|json|prisma|md))""",
        re.IGNORECASE,
    )
    # Also catch bare file paths like src/foo/bar.ts mentioned anywhere
    bare_path_pattern = re.compile(
        r"""((?:src|app|lib|components|pages|public|utils|hooks|services|types|config|prisma)"""
        r"""[/\\][\w./\\[\]-]+\.(?:ts|tsx|js|jsx|css|json|prisma))"""
    )

    file_contents: dict = {}
    remaining_questions: list = []
    max_file_size = 30_000

    for q in questions:
        found_paths = set(path_pattern.findall(q))
        found_paths.update(bare_path_pattern.findall(q))

        # Normalise separators
        normalised = {p.replace("\\", "/") for p in found_paths}

        resolved_any = False
        for rel_path in normalised:
            if rel_path in file_contents:
                resolved_any = True
                continue
            full_path = repo_path / rel_path
            if full_path.exists() and full_path.is_file():
                try:
                    content = full_path.read_text(encoding="utf-8")
                    if len(content) > max_file_size:
                        content = content[:max_file_size] + f"\n... (truncated, {len(content)} total chars)"
                    file_contents[rel_path] = content
                    resolved_any = True
                    print(f"  ✅ Auto-read: {rel_path} ({len(content):,} chars)")
                except Exception as e:
                    print(f"  ⚠️ Could not read {rel_path}: {e}")
            else:
                print(f"  ❌ File not found: {rel_path}")

        if not resolved_any:
            remaining_questions.append(q)

    return file_contents, remaining_questions


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
    
    # 4b. ALWAYS include prisma/schema.prisma if it exists — prevents
    # the AI from guessing model names, relations, and field types.
    prisma_schema = repo_path / "prisma" / "schema.prisma"
    if prisma_schema.exists() and "prisma/schema.prisma" not in files_to_read:
        try:
            schema_content = prisma_schema.read_text(encoding="utf-8")
            context.append("**Prisma Schema (prisma/schema.prisma) — AUTHORITATIVE source of database models:**")
            context.append("```prisma")
            context.append(schema_content[:8000])
            if len(schema_content) > 8000:
                context.append("... (truncated)")
            context.append("```")
            context.append(
                "**CRITICAL:** Use ONLY the models, fields, and relations defined above. "
                "Do NOT invent relations (e.g. `include: { tenant: ... }`) unless the "
                "relation exists in schema.prisma. Prisma-generated types are strict."
            )
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
    
    # 6a. Always include AI_RULES.md if it exists (project-specific rules)
    for rules_name in ["AI_RULES.md", "RULES.md", ".ai-rules"]:
        rules_path = repo_path / rules_name
        if rules_path.exists():
            try:
                content = rules_path.read_text(encoding="utf-8")
                context.append(f"**PROJECT RULES ({rules_name}) — YOU MUST FOLLOW THESE:**")
                context.append("```markdown")
                context.append(content[:8000])
                if len(content) > 8000:
                    context.append("... (truncated)")
                context.append("```")
                context.append("")
                context.append("**CRITICAL:** The rules above are MANDATORY for this project. Violating them will cause build failures or rejected PRs.")
                context.append("")
                print(f"📋 Loaded project rules from {rules_name}")
                break
            except Exception:
                pass

    # 6b. Always include DESIGN.md if it exists (design system)
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


def _build_system_with_cache(
    repo_context: str,
    skills_content: str = "",
    knowledge_base_context: str = "",
    type_definitions_context: str = "",
) -> list:
    """
    Build system prompt with prompt caching for repository context.
    
    Includes optional project-specific skills (e.g., Next.js vs Flutter conventions),
    preventive knowledge base lessons, and auto-detected type definitions.
    
    Returns array of system message blocks with cache_control markers.
    This reduces costs by 90% and speeds up responses 5x for repeated context.
    """
    cached_parts = []
    if skills_content:
        cached_parts.append(skills_content)
    cached_parts.append(f"\n\n**Repository Context (cached for performance):**\n\n{repo_context}")
    if type_definitions_context:
        cached_parts.append(f"\n\n{type_definitions_context}")

    blocks = [
        {
            "type": "text",
            "text": _system_prompt()
        },
        {
            "type": "text",
            "text": "\n\n".join(cached_parts),
            "cache_control": {"type": "ephemeral"}
        },
    ]

    # Knowledge base lessons are NOT cached — they change per-run as the
    # system learns, and they must always be fresh.
    if knowledge_base_context:
        blocks.append({
            "type": "text",
            "text": knowledge_base_context,
        })

    return blocks


def _system_prompt() -> str:
    return (
        "You are an expert software engineer implementing a Jira sub-task. "
        "You will be given the task requirements and must implement the actual code changes.\n\n"
        "Working directory: The repository is already checked out and you're on the correct branch.\n\n"
        "**RESPONSE FORMAT:** Your response MUST be ONLY valid JSON. "
        "Do NOT write any text, explanation, or preamble before the JSON. "
        "Start your response with the opening brace '{'. Use this structure:\n"
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
        "**🚨 IMPORT COMPLETENESS — THE #1 BUILD FAILURE:**\n"
        "- EVERY file you import from MUST either already exist in the repo OR be in your 'files' array\n"
        "- If file A imports from file B, you MUST include file B in your response\n"
        "- Do NOT reference modules that don't exist — check the repo file listing carefully\n"
        "- If you need a sub-component you can't fully implement, create it as a minimal stub in the same response\n"
        "- BEFORE responding: verify every import in every file resolves to something real\n\n"
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
        "- When in doubt, implement LESS rather than MORE\n\n"
        "**🚫 BANNED PATTERNS — NEVER USE:**\n"
        "- NEVER create or use `MovewareClient` — it is deprecated. Use Rest API v2 (fetch/axios) instead.\n"
        "- NEVER import from '@/lib/api/moveware-client' or similar moveware-client paths.\n"
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
        "  * Prisma: ONLY use fields that exist in prisma/schema.prisma in select/include/where clauses. "
        "Do NOT invent encrypted fields (e.g. 'refreshTokenEncrypted', 'metadataEncrypted') — check the schema!\n"
        "  * Prisma: for null checks in where clauses, use `{ isSet: false }` not `null` or `{ equals: null }`\n"
        "  * Importing from modules that DO NOT EXIST in the repository\n"
        "- **IMPORT VALIDATION — #1 CAUSE OF BUILD FAILURES (WILL BE REJECTED):**\n"
        "  * EVERY file you import from MUST either (a) already exist in the repo, or (b) be included in YOUR response\n"
        "  * If you create file A that imports from file B, you MUST also create file B in the SAME response\n"
        "  * Do NOT split implementation across files unless you provide ALL of them\n"
        "  * Do NOT invent module paths — only import from paths you can see in the repo context\n"
        "  * BEFORE finishing: mentally verify EVERY import in EVERY file you're creating resolves to something real\n"
        "  * Common mistake: creating a Shell component that imports NotesPanel, ClickToCallButton, etc. without creating those files\n"
        "  * If a component needs sub-components you can't provide, inline them or use a placeholder div\n\n"
        "**CRITICAL: DO NOT REGRESS EXISTING FUNCTIONALITY:**\n"
        "- When adding new features, you MUST preserve ALL existing functionality\n"
        "- DO NOT remove existing exports, functions, or components unless explicitly instructed\n"
        "- DO NOT replace existing UI elements - ADD new ones alongside them\n"
        "- If a page has multiple sections/tabs, preserve ALL of them\n"
        "- Example: If adding a chatbot to a settings page, keep all existing settings sections\n"
        "- If you think something should be removed, add a question instead - DO NOT remove it\n"
        "- Regression detection will flag removed exports and significant code deletion\n"
        "- When in doubt, ADD code rather than REPLACE code\n\n"
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


def _build_completion_summary(
    issue: JiraIssue,
    branch: str,
    pr_url: Optional[str],
    files_changed: List[str],
    implementation_notes: str,
    verification_errors: List[str],
    repo_path: Path
) -> str:
    """
    Build a comprehensive summary comment for Jira when task moves to In Testing.
    
    Includes:
    - What was requested (task summary)
    - What was implemented (AI's implementation notes)
    - Files changed (grouped by type)
    - Branch and PR links
    - Testing notes
    - Post-deployment steps (if any)
    """
    lines = []
    
    # Header
    lines.append("## ✅ Implementation Complete")
    lines.append("")
    
    # What was requested
    lines.append("### 📋 Task")
    lines.append(f"**{issue.summary}**")
    lines.append("")
    
    # What was implemented
    if implementation_notes:
        lines.append("### 🛠️ What Was Implemented")
        lines.append(implementation_notes)
        lines.append("")
    
    # Files changed (grouped by type)
    lines.append("### 📁 Files Changed")
    if files_changed:
        # Group files by action type
        created = [f.replace("Created ", "") for f in files_changed if f.startswith("Created")]
        updated = [f.replace("Updated ", "") for f in files_changed if f.startswith("Updated")]
        deleted = [f.replace("Deleted ", "") for f in files_changed if f.startswith("Deleted")]
        
        if created:
            lines.append(f"**Created** ({len(created)} files):")
            for file_path in created[:10]:  # Limit to 10
                lines.append(f"- `{file_path}`")
            if len(created) > 10:
                lines.append(f"- ... and {len(created) - 10} more")
            lines.append("")
        
        if updated:
            lines.append(f"**Updated** ({len(updated)} files):")
            for file_path in updated[:10]:  # Limit to 10
                lines.append(f"- `{file_path}`")
            if len(updated) > 10:
                lines.append(f"- ... and {len(updated) - 10} more")
            lines.append("")
        
        if deleted:
            lines.append(f"**Deleted** ({len(deleted)} files):")
            for file_path in deleted[:10]:  # Limit to 10
                lines.append(f"- `{file_path}`")
            if len(deleted) > 10:
                lines.append(f"- ... and {len(deleted) - 10} more")
            lines.append("")
    else:
        lines.append("No files changed.")
        lines.append("")
    
    # Branch and PR info
    lines.append("### 🔗 Code Review")
    lines.append(f"**Branch:** `{branch}`")
    if pr_url:
        lines.append(f"**Pull Request:** {pr_url}")
    lines.append("")
    
    # Check for post-deployment steps
    try:
        from .post_deploy_detector import detect_post_deploy_steps, format_post_deploy_comment
        
        # Extract clean file paths
        changed_file_paths = []
        for fc in files_changed:
            parts = fc.split(" ", 1)
            if len(parts) == 2:
                changed_file_paths.append(parts[1])
        
        if changed_file_paths:
            post_deploy_steps = detect_post_deploy_steps(repo_path, changed_file_paths)
            
            if post_deploy_steps:
                # Add just a summary, full details will be in separate comment
                required = [s for s in post_deploy_steps if s.priority == "required"]
                recommended = [s for s in post_deploy_steps if s.priority == "recommended"]
                
                lines.append("### ⚠️ Post-Deployment Steps")
                if required:
                    lines.append(f"**{len(required)} required step(s)** detected (migrations, env vars, etc.)")
                if recommended:
                    lines.append(f"**{len(recommended)} recommended step(s)** detected (dependencies, etc.)")
                lines.append("")
                lines.append("_See separate comment for detailed instructions._")
                lines.append("")
    except Exception as e:
        # Don't fail if post-deploy detection errors
        print(f"Warning: Post-deploy detection in summary failed: {e}")
    
    # Testing notes
    lines.append("### 🧪 Testing Notes")
    lines.append("Please test the following:")
    lines.append(f"1. Pull branch `{branch}`")
    lines.append(f"2. Run any required post-deployment steps (see above)")
    lines.append(f"3. Verify the implementation matches the acceptance criteria")
    lines.append(f"4. Test edge cases and error handling")
    lines.append("")
    
    # Build verification status
    if verification_errors:
        lines.append("### ⚠️ Build Verification Warnings")
        for error in verification_errors[:3]:  # Limit to 3
            error_preview = error[:200] + "..." if len(error) > 200 else error
            lines.append(f"- {error_preview}")
        if len(verification_errors) > 3:
            lines.append(f"- ... and {len(verification_errors) - 3} more warnings")
        lines.append("")
        lines.append("_Note: These warnings were present but did not block the build._")
        lines.append("")
    else:
        lines.append("### ✅ Build Verification")
        lines.append("All checks passed successfully.")
        lines.append("")
    
    # Footer
    lines.append("---")
    lines.append("_Ready for testing! If you find issues, move back to 'In Progress' and assign to AI Runner._")
    
    return "\n".join(lines)


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
        add_progress_event(run_id, "executing", f"Preparing repository for {issue.key}", {"issue_type": issue.issue_type})

    # Get repository configuration for this issue (supports multi-repo)
    repo_settings = _get_repo_settings(issue.key)

    # Check if this subtask should have its own PR
    is_independent = "independent-pr" in (issue.labels or [])

    # 1) Checkout/update repo
    if run_id:
        add_progress_event(run_id, "executing", f"Cloning/updating repo ({repo_settings.get('repo_name', 'unknown')})", {"repo": repo_settings.get("repo_name")})
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
        add_progress_event(run_id, "executing", f"Checked out branch: {branch}", {"branch": branch})

    # 3) Ask Claude to implement the code changes
    client = AnthropicClient(api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL, timeout=settings.ANTHROPIC_TIMEOUT_SECONDS)
    
    # Get repository context (includes file contents)
    repo_path = Path(repo_settings["repo_workdir"])
    context_info = _get_repo_context(repo_path, issue)
    
    # PREVENTIVE: Inject lessons learned from past build failures
    kb_context = ""
    try:
        from .error_knowledge_base import get_preventive_lessons, format_preventive_prompt, init_knowledge_base_schema
        init_knowledge_base_schema()
        repo_name = repo_settings.get("repo_name", "unknown")
        task_text = f"{issue.summary} {issue.description or ''}"
        lessons = get_preventive_lessons(repo_name, task_text)
        kb_context = format_preventive_prompt(lessons)
        if kb_context:
            print(f"📚 Knowledge base: {lessons.total_lessons} lessons loaded ({lessons.total_prevented} errors prevented so far)")
            if run_id:
                add_progress_event(run_id, "executing", f"Knowledge base: {lessons.total_lessons} lessons, {len(lessons.type_corrections)} type corrections", {"lessons": lessons.total_lessons, "prevented": lessons.total_prevented})
    except Exception as e:
        print(f"Note: Knowledge base unavailable: {e}")

    # PREVENTIVE: Read type definitions mentioned in task description
    type_context = ""
    try:
        from .type_context_extractor import extract_type_context
        type_context = extract_type_context(
            repo_path,
            f"{issue.summary} {issue.description or ''}",
            max_files=10,
        )
        if type_context:
            print(f"📖 Auto-detected type definitions for task context")
    except Exception as e:
        print(f"Note: Type context extraction unavailable: {e}")

    from app.skill_loader import load_skills
    skills_list = repo_settings.get("skills", ["nextjs-fullstack-dev"])
    if run_id:
        add_progress_event(run_id, "executing", f"Loading project skills: {', '.join(skills_list)}", {"skills": skills_list})
    skills_content = load_skills(skills_list)
    
    # Get human comments for additional context/clarifications
    human_comments = _get_human_comments(issue.key)
    
    # Fetch external integration context
    integrations_loaded = []

    figma_context = ""
    try:
        from app.integrations.figma import get_design_context_for_issue
        figma_context = get_design_context_for_issue(issue.description or "")
        if figma_context:
            integrations_loaded.append("Figma")
            print(f"🎨 Figma design context loaded for {issue.key}")
    except Exception as e:
        print(f"Note: Figma integration unavailable: {e}")

    sentry_context = ""
    try:
        from app.integrations.sentry_client import get_error_context_for_issue
        sentry_context = get_error_context_for_issue(issue.description or "")
        if sentry_context:
            integrations_loaded.append("Sentry")
            print(f"🐛 Sentry error context loaded for {issue.key}")
    except Exception as e:
        print(f"Note: Sentry integration unavailable: {e}")

    stripe_context = ""
    try:
        from app.integrations.stripe_client import get_stripe_context_for_issue
        stripe_context = get_stripe_context_for_issue(issue.description or "", issue.summary)
        if stripe_context:
            integrations_loaded.append("Stripe")
            print(f"💳 Stripe account context loaded for {issue.key}")
    except Exception as e:
        print(f"Note: Stripe integration unavailable: {e}")

    vercel_context = ""
    try:
        from app.integrations.vercel_client import get_vercel_context_for_issue
        vercel_context = get_vercel_context_for_issue(
            issue.description or "",
            issue.summary,
            repo_path=repo_settings.get("repo_workdir", ""),
            skills=repo_settings.get("skills", []),
        )
        if vercel_context:
            integrations_loaded.append("Vercel")
            print(f"▲ Vercel best practices injected for {issue.key}")
    except Exception as e:
        print(f"Note: Vercel best practices unavailable: {e}")

    if run_id and integrations_loaded:
        add_progress_event(run_id, "executing", f"Context loaded: {', '.join(integrations_loaded)}", {"integrations": integrations_loaded})

    # Detect if this is a REWORK scenario (fixing issues found in testing)
    is_rework = "REWORK REQUESTED" in (issue.description or "").upper()
    
    # Detect if this is a restoration task
    from .restoration_detector import (
        detect_restoration_task,
        analyze_git_history,
        format_restoration_context_for_prompt
    )
    
    restoration_context = detect_restoration_task(issue.summary, issue.description or "")
    
    if restoration_context.is_restoration:
        print(f"🔄 RESTORATION SUB-TASK DETECTED")
        # Try to get git history context
        try:
            search_terms = [word for word in issue.summary.lower().split() if len(word) > 4]
            restoration_context = analyze_git_history(repo_path, restoration_context, search_terms)
        except Exception as e:
            print(f"⚠️  Could not analyze git history for sub-task: {e}")
    
    # Build prompt with special handling for rework scenarios
    if is_rework:
        print(f"🔧 REWORK DETECTED for {issue.key} - emphasizing fixes over re-implementation")
        prompt = (
            f"⚠️  **THIS IS A REWORK TASK** - Fix specific issues, do NOT re-implement from scratch!\n\n"
            f"**Task:** {issue.key}\n"
            f"**Summary:** {issue.summary}\n\n"
            f"**Original Requirements:**\n{issue.description}\n\n"
            f"**CRITICAL INSTRUCTIONS FOR REWORK:**\n"
            f"1. This code was already implemented but had issues\n"
            f"2. READ the feedback carefully in the description above\n"
            f"3. Identify what's WRONG or MISSING in the current implementation\n"
            f"4. Make TARGETED fixes - do NOT delete and rewrite everything\n"
            f"5. Preserve existing working functionality\n"
            f"6. ONLY fix the specific issues mentioned in the feedback\n\n"
        )
    else:
        prompt = (
            f"Implement this Jira sub-task:\n\n"
            f"**Task:** {issue.key}\n"
            f"**Summary:** {issue.summary}\n\n"
            f"**Requirements:**\n{issue.description}\n\n"
        )
    
    # Inject restoration context if detected
    if restoration_context.is_restoration:
        restoration_prompt = format_restoration_context_for_prompt(restoration_context)
        prompt += "\n" + restoration_prompt + "\n"
    
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
    
    # Inject external service context (Figma, Sentry, Stripe, Vercel)
    if figma_context:
        prompt += figma_context + "\n"
    if sentry_context:
        prompt += sentry_context + "\n"
    if stripe_context:
        prompt += stripe_context + "\n"
    if vercel_context:
        prompt += vercel_context + "\n"

    # Inject security requirements reminder
    prompt += (
        "**SECURITY REQUIREMENTS:**\n"
        "- Never hardcode secrets, API keys, or tokens — use environment variables\n"
        "- Use parameterized queries for all database operations (no string interpolation)\n"
        "- Sanitize user input before rendering (avoid dangerouslySetInnerHTML unless sanitized)\n"
        "- Set httpOnly and secure flags on cookies\n"
        "- Use crypto.randomBytes() for tokens, never Math.random()\n\n"
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
        "system": _build_system_with_cache(context_info, skills_content, kb_context, type_context),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 64000,
        "temperature": 1,
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
        if run_id:
            add_progress_event(run_id, "executing", f"Claude responded — {metrics.total_input_tokens:,} in / {metrics.total_output_tokens:,} out, cost: ${metrics.estimated_cost:.4f}", {
                "input_tokens": metrics.total_input_tokens,
                "output_tokens": metrics.total_output_tokens,
                "cached_tokens": metrics.cached_tokens,
                "cost": round(metrics.estimated_cost, 4),
            })

    # Extract assistant text and parse JSON
    text = AnthropicClient.extract_text(raw)
    
    # Extract JSON from Claude's response (may include explanatory text)
    from .json_repair import try_parse_json, extract_json_from_llm_response
    json_text = text.strip()

    # Strategy 1: Strip markdown code fences
    lines = json_text.split('\n')
    if lines[0].strip().startswith('```'):
        lines = lines[1:]
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == '```':
                lines = lines[:i]
                break
        json_text = '\n'.join(lines)

    # Strategy 2: If first non-whitespace char is NOT '{', Claude wrote
    # explanatory text before JSON — extract from first '{' to last '}'
    stripped = json_text.lstrip()
    if stripped and stripped[0] != '{':
        extracted = extract_json_from_llm_response(json_text)
        if extracted:
            print(f"ℹ️  Stripped {len(json_text) - len(extracted)} chars of preamble text before JSON")
            json_text = extracted

    try:
        payload = try_parse_json(json_text, max_repair_attempts=3)
        
        if payload is None:
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

    # Check if there are questions instead of implementation.
    # Many "questions" are actually requests for file contents — auto-resolve those.
    if "questions" in payload and payload["questions"]:
        questions = payload["questions"]
        questions_text = "\n".join([f"- {q}" for q in questions])
        print(f"Claude asked {len(questions)} question(s) instead of implementing:")
        print(questions_text)

        # --- Auto-resolve: extract file paths from questions and read them ---
        file_contents, remaining_questions = _resolve_file_questions(questions, repo_path)

        if file_contents:
            print(f"📂 Auto-resolved {len(file_contents)} file(s) from questions — re-prompting Claude")
            if run_id:
                add_progress_event(run_id, "executing",
                    f"Claude asked for {len(file_contents)} file(s) — auto-reading and re-prompting",
                    {"files_resolved": list(file_contents.keys())})

            # Build follow-up content with the requested files
            file_context_parts = [
                "Here are the source files you requested. Now implement the task with NO further questions.\n"
            ]
            for fpath, fcontent in file_contents.items():
                ext = fpath.rsplit(".", 1)[-1] if "." in fpath else ""
                file_context_parts.append(f"**{fpath}:**\n```{ext}\n{fcontent}\n```\n")

            if remaining_questions:
                file_context_parts.append(
                    "For your other questions — use your best judgement based on the code provided. "
                    "Do NOT ask further questions. Implement the solution now.\n"
                )

            followup_content = "\n".join(file_context_parts)

            # Re-call Claude with the file contents as a follow-up message
            raw2 = client.messages_create({
                "model": settings.ANTHROPIC_MODEL,
                "system": _build_system_with_cache(context_info, skills_content, kb_context, type_context),
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": followup_content},
                ],
                "max_tokens": 64000,
                "temperature": 1,
                "thinking": {"type": "enabled", "budget_tokens": 8000},
            })

            # Track cost of follow-up call
            if metrics and raw2.get("usage"):
                usage2 = raw2["usage"]
                metrics.total_input_tokens += usage2.get("input_tokens", 0)
                metrics.total_output_tokens += usage2.get("output_tokens", 0)
                metrics.cached_tokens += usage2.get("cache_read_input_tokens", 0)
                metrics.estimated_cost = calculate_cost(
                    settings.ANTHROPIC_MODEL,
                    metrics.total_input_tokens,
                    metrics.total_output_tokens,
                    metrics.cached_tokens,
                )
                if run_id:
                    add_progress_event(run_id, "executing",
                        f"Follow-up response — cumulative cost: ${metrics.estimated_cost:.4f}",
                        {"cost": round(metrics.estimated_cost, 4)})

            text2 = AnthropicClient.extract_text(raw2)
            json_text2 = text2.strip()

            # Parse the follow-up response
            lines2 = json_text2.split('\n')
            if lines2[0].strip().startswith('```'):
                lines2 = lines2[1:]
                for i in range(len(lines2) - 1, -1, -1):
                    if lines2[i].strip() == '```':
                        lines2 = lines2[:i]
                        break
                json_text2 = '\n'.join(lines2)

            stripped2 = json_text2.lstrip()
            if stripped2 and stripped2[0] != '{':
                extracted2 = extract_json_from_llm_response(json_text2)
                if extracted2:
                    json_text2 = extracted2

            try:
                payload2 = try_parse_json(json_text2, max_repair_attempts=3)
                if payload2 is not None:
                    payload = payload2
                    print("✅ Follow-up response parsed successfully — proceeding with implementation")
                    # If the follow-up STILL has questions and no files, fall through to human escalation
                    if "questions" in payload and payload["questions"] and not payload.get("files"):
                        remaining_questions = payload["questions"]
                    else:
                        remaining_questions = []
                else:
                    print("⚠️ Could not parse follow-up response, falling through to human escalation")
            except Exception as e2:
                print(f"⚠️ Failed to parse follow-up: {e2}")

        # If there are still unresolved questions (not file requests), escalate to human
        if remaining_questions and not payload.get("files"):
            final_questions_text = "\n".join([f"- {q}" for q in remaining_questions])
            summary = payload.get("summary", "") or payload.get("implementation_plan", "")
            jira_comment = (
                "❓ *Implementation blocked – clarification needed*\n\n"
                "The AI Runner needs answers before it can implement:\n\n"
                f"{final_questions_text}\n\n"
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
            raise RuntimeError(f"Implementation blocked by questions:\n{final_questions_text}")

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
            msg = f"Applied {len(proactive_fixes)} proactive fixes before build"
            print(f"✓ {msg}")
            if run_id:
                add_progress_event(run_id, "verifying", msg, {"fixes": len(proactive_fixes), "warnings": len(proactive_warnings)})
    
    # 4.6) Pre-build import resolution — create stubs for any @/ imports that don't resolve
    try:
        from .import_resolver import resolve_all_missing_imports
        _changed = [f["path"] for f in files if f.get("action", "update") != "delete"]
        _stubs_created = resolve_all_missing_imports(repo_path, changed_files=_changed)
        if _stubs_created:
            msg = f"Pre-build: created {len(_stubs_created)} stub module(s) for missing imports"
            print(f"📦 {msg}")
            if run_id:
                add_progress_event(run_id, "verifying", msg, {"stubs": _stubs_created})
    except Exception as _ir_err:
        print(f"Warning: pre-build import resolution failed: {_ir_err}")

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
                    # Run npm audit: fix safe vulnerabilities and report remaining
                    if run_id:
                        add_progress_event(run_id, "verifying", "Running npm audit (security vulnerability scan)", {})
                    try:
                        from app.integrations.npm_audit import run_audit, run_audit_fix
                        fix_msg = run_audit_fix(repo_path)
                        print(f"npm audit fix: {fix_msg}")
                        audit_report = run_audit(repo_path)
                        if audit_report.has_actionable_issues:
                            audit_msg = f"npm audit: {audit_report.critical} critical, {audit_report.high} high vulnerabilities"
                            print(f"⚠ {audit_msg}")
                            if run_id:
                                add_progress_event(run_id, "verifying", f"⚠ {audit_msg}", {"critical": audit_report.critical, "high": audit_report.high, "total": audit_report.total})
                        elif audit_report.total > 0:
                            print(f"npm audit: {audit_report.total} low/moderate vulnerabilities (non-blocking)")
                            if run_id:
                                add_progress_event(run_id, "verifying", f"npm audit: {audit_report.total} low/moderate vulnerabilities (non-blocking)", {"total": audit_report.total})
                        else:
                            print("✓ npm audit: no vulnerabilities")
                            if run_id:
                                add_progress_event(run_id, "verifying", "npm audit: clean — no vulnerabilities", {})
                    except Exception as e:
                        print(f"Warning: npm audit failed: {e}")
            except subprocess.TimeoutExpired:
                verification_errors.append("npm install timed out after 60 seconds")
                print("npm install timed out")
            except Exception as e:
                verification_errors.append(f"Could not run npm install: {e}")
                print(f"npm install exception: {e}")
            
            # Step 2a: Run tsc --noEmit (fast TypeScript gate before heavy build)
            if not verification_errors and (repo_path / "tsconfig.json").exists():
                try:
                    next_types_dir = repo_path / ".next" / "types"
                    if next_types_dir.exists():
                        import shutil
                        shutil.rmtree(next_types_dir, ignore_errors=True)
                        print("🗑️  Cleaned .next/types/ to prevent stale type errors")

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

                        # Filter out .next/ build artifact errors (auto-generated, not fixable)
                        filtered_lines = [
                            line for line in tsc_output.splitlines()
                            if not line.startswith(".next/")
                        ]
                        tsc_output = "\n".join(filtered_lines)

                        from .error_summarizer import format_concise_error_summary, should_show_full_errors

                        error_count = tsc_output.count("error TS")

                        if error_count == 0:
                            print("✅ TypeScript check passed (only .next/ build artifact errors filtered)")
                            if run_id:
                                add_progress_event(run_id, "verifying", "✓ TypeScript check passed (build artifacts filtered)", {})
                        else:
                            if should_show_full_errors(error_count):
                                error_message = f"TypeScript check failed (tsc --noEmit):\n{tsc_output[:3000]}"
                            else:
                                summary = format_concise_error_summary(tsc_output)
                                error_message = f"TypeScript check failed (tsc --noEmit):\n\n{summary}\n\n--- Full Output (first 1000 chars) ---\n{tsc_output[:1000]}"

                            verification_errors.append(error_message)
                            print(f"tsc failed ({error_count} errors):\n{tsc_output[:500]}")
                            if run_id:
                                add_progress_event(run_id, "verifying", f"✗ TypeScript check failed — {error_count} errors", {"error_count": error_count})
                    else:
                        print("✅ TypeScript check passed")
                        if run_id:
                            add_progress_event(run_id, "verifying", "✓ TypeScript check passed", {})
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
                            
                            # Use intelligent error summarization
                            from .error_summarizer import format_concise_error_summary, should_show_full_errors
                            
                            # Count errors in build output
                            error_count = error_output.count("error TS") + error_output.count("Error:")
                            
                            if should_show_full_errors(error_count):
                                # Few errors - show them all
                                build_message = (
                                    f"❌ CRITICAL: Production build failed\n\n"
                                    f"Build output:\n{error_output[:2000]}\n\n"
                                    f"Common fixes:\n"
                                    f"- Check for missing exports\n"
                                    f"- Verify all imports exist\n"
                                    f"- Fix TypeScript type errors"
                                )
                            else:
                                # Many errors - show concise summary
                                summary = format_concise_error_summary(error_output)
                                build_message = (
                                    f"❌ CRITICAL: Production build failed\n\n"
                                    f"{summary}\n\n"
                                    f"--- First 800 chars of build output ---\n{error_output[:800]}"
                                )
                            
                            verification_errors.append(build_message)
                            print(f"Build failed ({error_count} errors):\n{error_output[:500]}")
                            if run_id:
                                add_progress_event(run_id, "verifying", f"✗ Build failed — {error_count} errors", {"error_count": error_count})
                        else:
                            print("✅ Build succeeded!")
                            if run_id:
                                add_progress_event(run_id, "verifying", "✓ Build succeeded", {})
                            
                except subprocess.TimeoutExpired:
                    verification_errors.append("Build timed out after 3 minutes")
                    print("Build timed out")
                except Exception as e:
                    verification_errors.append(f"Could not run build: {e}")
                    print(f"Build exception: {e}")
    
    # If verification failed, try to fix the errors (self-healing) with multi-attempt strategy
    MAX_FIX_ATTEMPTS = settings.MAX_FIX_ATTEMPTS
    fix_attempt = 0
    
    # LEARNING: Record lessons from initial build failure (before self-healing)
    if verification_errors:
        try:
            from .error_knowledge_base import extract_lessons_from_error
            _repo_name = repo_settings.get("repo_name", "unknown")
            _n = extract_lessons_from_error(_repo_name, "\n".join(verification_errors))
            if _n:
                print(f"📚 Recorded {_n} lesson(s) from initial build failure")
        except Exception:
            pass

    # Resolve missing imports FIRST (this is the #1 cause of cascading failures)
    if verification_errors and is_node_project:
        _has_missing_modules = any(
            "Module not found" in e or "Cannot find module" in e
            for e in verification_errors
        )
        if _has_missing_modules:
            try:
                from .import_resolver import resolve_all_missing_imports
                _stubs = resolve_all_missing_imports(repo_path)
                if _stubs:
                    print(f"📦 Pre-fix: resolved {len(_stubs)} missing import(s) with stubs")
                    if run_id:
                        add_progress_event(run_id, "verifying", f"Created {len(_stubs)} stubs for missing imports", {"stubs": _stubs})
                    # Re-run tsc to see if stubs resolved the issues
                    _tsc_retry = subprocess.run(
                        ["npx", "tsc", "--noEmit", "--pretty", "false"],
                        cwd=repo_path, capture_output=True, text=True, timeout=60,
                    )
                    if _tsc_retry.returncode == 0:
                        print("✅ TypeScript check passed after stub creation!")
                        verification_errors = []
                    else:
                        _tsc_out = _tsc_retry.stdout or _tsc_retry.stderr
                        _filtered = [l for l in _tsc_out.splitlines() if not l.startswith(".next/")]
                        _remaining = len([l for l in _filtered if ": error " in l])
                        if _remaining > 0:
                            verification_errors = [f"TypeScript check still failing ({_remaining} errors) after stub creation:\n{chr(10).join(_filtered[:500])}"]
                        else:
                            print("✅ TypeScript check passed after stub creation (only .next/ errors filtered)")
                            verification_errors = []
            except Exception as _ir_err:
                print(f"Warning: pre-fix import resolution failed: {_ir_err}")

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

    # Auto-fix common AI-generated issues (Zod query param types, duplicate declarations in validate.ts)
    if verification_errors and is_node_project:
        try:
            from .auto_fixes import try_all_auto_fixes
            applied, desc = try_all_auto_fixes(error_text, repo_path, is_node_project)
            if applied:
                if run_id:
                    add_progress_event(run_id, "verifying", f"Re-running checks after auto-fix: {desc}", {})
                if (repo_path / "tsconfig.json").exists():
                    next_types_dir = repo_path / ".next" / "types"
                    if next_types_dir.exists():
                        import shutil
                        shutil.rmtree(next_types_dir, ignore_errors=True)
                    tsc_result = subprocess.run(
                        ["npx", "tsc", "--noEmit", "--pretty", "false"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if tsc_result.returncode == 0:
                        # Re-run build if Next.js
                        package_json_path = repo_path / "package.json"
                        if package_json_path.exists():
                            pj = package_json_path.read_text(encoding="utf-8")
                            if '"next"' in pj or "'next'" in pj:
                                build_result = subprocess.run(
                                    ["npm", "run", "build"],
                                    cwd=repo_path,
                                    capture_output=True,
                                    text=True,
                                    timeout=180,
                                    env=_get_nextjs_build_env(),
                                )
                                if build_result.returncode == 0:
                                    print("✅ Build succeeded after auto-fix!")
                                    verification_errors = []
                                    error_text = ""
                                else:
                                    verification_errors = [
                                        f"Build still failing after auto-fix:\n{(build_result.stderr or build_result.stdout)[:2000]}"
                                    ]
                                    error_text = "\n".join(verification_errors)
                            else:
                                verification_errors = []
                                error_text = ""
                        else:
                            verification_errors = []
                            error_text = ""
                    else:
                        tsc_out = tsc_result.stdout or tsc_result.stderr
                        verification_errors = [f"TypeScript check failed after auto-fix:\n{tsc_out[:2000]}"]
                        error_text = "\n".join(verification_errors)
        except Exception as e:
            print(f"Auto-fix step failed (non-fatal): {e}")

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
    
    # Save git checkpoint before fix loop — allows rollback on cascading errors
    _checkpoint_hash = None
    try:
        _cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if _cp.returncode == 0:
            _checkpoint_hash = _cp.stdout.strip()
    except Exception:
        pass
    
    # Track the original error signature to detect cascading (new) errors
    # Use a regex that handles Next.js dynamic route segments like [id], [slug], etc.
    def _extract_error_basenames(text: str) -> set:
        """Extract unique file basenames from error text (handles [id] in paths)."""
        # Match filenames like page.tsx, route.ts, CustomerDetailShell.tsx etc.
        basenames = set()
        for m in re.finditer(r'([\w.-]+\.(?:ts|tsx|js|jsx))\b', text):
            basenames.add(m.group(1))
        return basenames
    
    _original_error_basenames = _extract_error_basenames("\n".join(verification_errors))
    
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
        
        # SHORT-CIRCUIT: "Module not found" → create stubs directly (LLM is terrible at this)
        _module_not_found_resolved = False
        try:
            _mnf_matches = re.findall(
                r"(?:Module not found: Can't resolve|Cannot find module)\s+'(@/[^']+)'",
                error_msg,
            )
            if _mnf_matches:
                from .import_resolver import resolve_all_missing_imports
                print(f"📦 Detected {len(set(_mnf_matches))} missing module(s) — resolving with stubs...")
                _stubs = resolve_all_missing_imports(repo_path)
                if _stubs:
                    print(f"📦 Created {len(_stubs)} stub(s): {', '.join(_stubs)}")
                    _af_result = subprocess.run(
                        ["npm", "run", "build"],
                        cwd=repo_path, capture_output=True, text=True,
                        timeout=180, env=_get_nextjs_build_env(),
                    )
                    if _af_result.returncode == 0:
                        print(f"✅ Build passed after import resolution!")
                        verification_errors = []
                        _module_not_found_resolved = True
                    else:
                        _af_err = _af_result.stderr if _af_result.stderr else _af_result.stdout
                        verification_errors = [f"Build still failing after stub creation:\n{_af_err[:2000]}"]
                        error_msg = "\n\n".join(verification_errors)
                        print(f"⚠️  Stubs created but build still failing — continuing with auto-fixes")
        except Exception as _mnf_err:
            print(f"Warning: module-not-found short-circuit failed: {_mnf_err}")

        if _module_not_found_resolved:
            break

        # Try auto-fixes FIRST before calling the LLM (cheaper, faster, more reliable)
        # Run in a loop — one auto-fix may expose another (e.g. phantom import -> jsx-no-undef)
        _autofix_rounds = 0
        _max_autofix_rounds = 5
        try:
            from .auto_fixes import try_all_auto_fixes
            while _autofix_rounds < _max_autofix_rounds:
                _autofix_rounds += 1
                auto_success, auto_desc = try_all_auto_fixes(error_msg, repo_path, is_node_project)
                if not auto_success:
                    break
                print(f"✅ Auto-fix round {_autofix_rounds}: {auto_desc}")
                _af_result = subprocess.run(
                    ["npm", "run", "build"],
                    cwd=repo_path, capture_output=True, text=True,
                    timeout=180, env=_get_nextjs_build_env(),
                )
                if _af_result.returncode == 0:
                    print(f"✅ Build passed after auto-fix round {_autofix_rounds}!")
                    verification_errors = []
                    break
                else:
                    _af_err = _af_result.stderr if _af_result.stderr else _af_result.stdout
                    print(f"Auto-fix round {_autofix_rounds} applied but build still failing, trying more auto-fixes...")
                    verification_errors = [f"Build still failing after auto-fix ({auto_desc}):\n{_af_err[:1000]}"]
                    error_msg = "\n\n".join(verification_errors)
            if not verification_errors:
                break
        except Exception as e:
            print(f"Auto-fix in loop failed: {e}")
        
        # Classify errors and get targeted hints
        error_category, specific_hint, _ = classify_error(error_msg)
        comprehensive_hint = get_comprehensive_hint(error_msg)
        error_context = extract_error_context(error_msg, max_context_lines=3)
        
        # Get similar successful fixes from pattern learning database
        from .pattern_learner import get_similar_successful_fixes, format_fix_suggestions
        similar_patterns = get_similar_successful_fixes(error_msg, limit=5)
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
            meta = {
                "attempt": fix_attempt, 
                "model": model_name,
                "error_category": error_category,
            }
            if similar_patterns:
                meta["past_fixes_found"] = len(similar_patterns)
                meta["past_fix_confidence"] = round(similar_patterns[0].confidence * 100)
            if reflection_guidance:
                meta["has_self_reflection"] = True
            add_progress_event(run_id, "fixing", progress_msg, meta)
        
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
            include_prisma = False
            reason = ""

            if error_category in ("prisma_schema_mismatch", "prisma_model_missing", "prisma_model_not_exported", "property_type_mismatch"):
                include_prisma = True
                reason = f"{error_category} error"
            elif "@prisma/client" in error_msg or "PrismaClient" in error_msg:
                include_prisma = True
                reason = "Prisma-related error detected"
            elif re.search(r"does not exist in type ['\"].*?(?:Select|Include|Where|Create|Update|OrderBy)", error_msg):
                include_prisma = True
                reason = "Prisma-generated type in error"
            elif re.search(r"not assignable to type ['\"].*?(?:Select|Include|Where|Create|Update|OrderBy)", error_msg):
                include_prisma = True
                reason = "Prisma type assignment error"

            if include_prisma:
                error_files.add("prisma/schema.prisma")
                print(f"Including prisma/schema.prisma in context ({reason})")
        
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
        
        # For type errors referencing a component Props type, find and include the component file
        # e.g. "does not exist on type 'IntrinsicAttributes & CustomerDetailShellProps'"
        props_type_match = re.search(
            r"(?:does not exist on type|is not assignable to type)\s+['\"](?:IntrinsicAttributes & )?(\w+Props)['\"]",
            error_msg,
        )
        if props_type_match:
            props_type = props_type_match.group(1)  # e.g. CustomerDetailShellProps
            # Derive likely component name from props type (remove "Props" suffix)
            component_name = props_type.replace("Props", "")
            print(f"🔍 Searching for component '{component_name}' (type: {props_type})")
            # Search for files that define or export this type/component
            try:
                for root, dirs, files in os.walk(repo_path):
                    # Skip node_modules, .next, .git
                    dirs[:] = [d for d in dirs if d not in ("node_modules", ".next", ".git", "dist", "build")]
                    for f in files:
                        if f.endswith((".ts", ".tsx")):
                            full = Path(root) / f
                            try:
                                content = full.read_text(encoding="utf-8", errors="ignore")
                                if props_type in content or f"interface {props_type}" in content or f"type {props_type}" in content:
                                    rel = str(full.relative_to(repo_path)).replace("\\", "/")
                                    if rel not in error_files:
                                        error_files.add(rel)
                                        print(f"  ✅ Found {props_type} in {rel}")
                            except Exception:
                                pass
            except Exception as e:
                print(f"  ⚠ Props type search failed: {e}")

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
        
        error_file_context = "\n".join(error_file_contents) if error_file_contents else ""
        
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
            f"\n**FIX RULES:**\n"
            f"- Read the error message carefully — it names the file, line, and exact issue\n"
            f"- Read the actual file contents from context — don't guess\n"
            f"- If a property 'does not exist in type', check prisma/schema.prisma or the type definition for valid fields\n"
            f"- Don't add fields that aren't in the schema — remove references to them instead\n"
            f"- Verify imports match actual exports before changing them\n"
            f"- Never duplicate existing declarations\n\n"
            f"**Key Error Context (files with errors):**\n{error_file_context if error_file_context else chr(10).join(error_context) if error_context else 'See full errors above'}\n\n"
            f"**NOTE:** Full repository context is provided in the system prompt — do NOT ask for files.\n\n"
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
            f"❌ Error: \"Property 'X' does not exist on type 'IntrinsicAttributes & SomeProps'\"\n"
            f"✅ MINIMAL FIX — DO NOT REWRITE THE WHOLE FILE:\n"
            f"   1. Find the SomeProps interface/type definition in the component file\n"
            f"   2. Add the missing property as OPTIONAL (e.g. X?: Type)\n"
            f"   3. ONLY change the interface — do NOT rewrite the rest of the component\n"
            f"   4. NEVER add new imports — the fix is ONLY adding a property to an interface\n"
            f"   5. Alternatively, remove the prop from the caller (page.tsx) if it shouldn't be passed\n\n"
            f"❌ Error: \"Type string is not assignable to type number\"\n"
            f"✅ Fix: Convert the type: parseInt(value) or value.toString() depending on direction\n\n"
            f"❌ Error: \"Unexpected token\"\n"
            f"✅ Fix: Check for missing brackets, quotes, commas, or semicolons\n\n"
            f"**🎯 MINIMAL FIX PRINCIPLE — MOST IMPORTANT RULE:**\n"
            f"Make the SMALLEST possible change to fix the error. Do NOT:\n"
            f"- Rewrite entire files when only one line needs to change\n"
            f"- Add new imports unless absolutely necessary for the specific fix\n"
            f"- Refactor or restructure code that isn't related to the error\n"
            f"- Create new components or modules — fix what exists\n"
            f"- Replace the existing file with a newly written version — preserve existing code\n\n"
            f"**DO NOT MAKE THESE MISTAKES:**\n"
            f"- ❌ Guessing what's in a file without reading it\n"
            f"- ❌ Assuming export names match (check casing!)\n"
            f"- ❌ Adding imports without verifying the export exists\n"
            f"- ❌ Providing partial file content (must be COMPLETE)\n"
            f"- ❌ Wrapping JSON in markdown code fences\n"
            f"- ❌ NEVER create or use MovewareClient — use Rest API v2 (fetch/axios) instead\n"
            f"- ❌ NEVER import from modules that don't exist in the repository\n"
            f"- ❌ NEVER create new files that import from other files you're also creating — "
            f"this causes cascading 'Module not found' errors\n\n"
            f"**IMPORT RULES (CRITICAL — violations will be rejected):**\n"
            f"- Every import MUST resolve to a file that ALREADY EXISTS on disk or is included "
            f"in your fix response\n"
            f"- Do NOT invent new module paths — check the repository context to see what files exist\n"
            f"- If you need functionality from a module that doesn't exist, implement it inline "
            f"or import from an existing module that provides similar functionality\n"
            f"- If fixing a component, update the EXISTING component file — don't create new sub-components "
            f"that would need their own new files\n\n"
            f"**CRITICAL:** Your response MUST be valid JSON only. Start with {{ and end with }}. "
            f"No markdown, no explanation before or after. Raw JSON only.\n\n"
            f"**REMEMBER:** Read → Verify → Fix → Verify again. Focus ONLY on fixing build errors."
        )
        
        try:
            print(f"Calling {model_name} to fix build errors...")

            _fell_through_to_openai = False

            if model_provider == "anthropic":
                try:
                    fix_text = ""
                    for claude_attempt in range(2):
                        fix_raw = client.messages_create({
                            "model": settings.ANTHROPIC_MODEL,
                            "system": _build_system_with_cache(comprehensive_context, skills_content),
                            "messages": [{"role": "user", "content": fix_prompt}],
                            "max_tokens": 16000,
                            "temperature": 1,
                            "thinking": {
                                "type": "enabled",
                                "budget_tokens": 4000
                            }
                        })
                        fix_text = AnthropicClient.extract_text(fix_raw)
                        if fix_text and "{" in fix_text:
                            break
                        if claude_attempt == 0:
                            print(f"⚠ Claude returned empty/invalid response, retrying once...")
                        else:
                            print(f"⚠ Claude returned empty response again after retry")
                    if metrics and fix_raw.get("usage"):
                        usage = fix_raw["usage"]
                        metrics.total_input_tokens += usage.get("input_tokens", 0)
                        metrics.total_output_tokens += usage.get("output_tokens", 0)
                        metrics.cached_tokens += usage.get("cache_read_input_tokens", 0)
                        metrics.self_heal_attempts += 1
                        metrics.estimated_cost = calculate_cost(
                            settings.ANTHROPIC_MODEL,
                            metrics.total_input_tokens,
                            metrics.total_output_tokens,
                            metrics.cached_tokens
                        )
                except Exception as claude_err:
                    err_str = str(claude_err)
                    if "400" in err_str or "invalid_request" in err_str:
                        print(f"⚠️ Claude 400 error (likely prompt too large), falling through to OpenAI for this attempt")
                        model_provider = "openai"
                        model_name = f"OpenAI ({settings.OPENAI_MODEL})"
                        _fell_through_to_openai = True
                    else:
                        raise

            if model_provider == "openai" or _fell_through_to_openai:
                # Use OpenAI as fallback (using same client as planner)
                from app.llm_openai import OpenAIClient
                openai_client = OpenAIClient(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                    timeout=settings.OPENAI_TIMEOUT_SECONDS
                )
                openai_system = (
                    _system_prompt() + "\n\n"
                    f"**Repository Context:**\n{comprehensive_context}\n"
                )
                fix_text, fix_usage = openai_client.responses_text_with_usage(
                    model=settings.OPENAI_MODEL,
                    system=openai_system,
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
            
            # Fail fast if empty or no JSON structure (saves expensive repair attempts)
            if not fix_json_text.strip() or '{' not in fix_json_text:
                print(f"❌ {model_name} returned empty or non-JSON response (len={len(fix_text)})")
                print(f"Raw response preview: {repr(fix_text[:200])}")
                raise RuntimeError(f"{model_name}'s fix response was empty or not valid JSON")
            
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
                
                # Resolve any missing imports the LLM fix may have introduced
                try:
                    from .import_resolver import resolve_all_missing_imports
                    _fix_stubs = resolve_all_missing_imports(repo_path, changed_files=fixed_files)
                    if _fix_stubs:
                        print(f"📦 Post-fix: created {len(_fix_stubs)} stub(s) for new missing imports")
                except Exception as _ir_err:
                    print(f"Warning: post-fix import resolution failed: {_ir_err}")

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
                        
                        # CASCADING ERROR DETECTION + ROLLBACK
                        # If the new error is in a DIFFERENT file than the original,
                        # the fix made things worse. Rollback to checkpoint.
                        new_error_basenames = _extract_error_basenames(error_output[:2000])
                        new_files_introduced = new_error_basenames - _original_error_basenames
                        if new_files_introduced and _checkpoint_hash:
                            print(f"⚠️  CASCADING ERROR DETECTED: fix introduced errors in new files: {new_files_introduced}")
                            print(f"🔄 Rolling back to checkpoint {_checkpoint_hash[:8]} to prevent snowball...")
                            try:
                                subprocess.run(
                                    ["git", "checkout", "."],
                                    cwd=repo_path,
                                    capture_output=True, text=True, timeout=10,
                                )
                                # Also clean any newly created files
                                subprocess.run(
                                    ["git", "clean", "-fd"],
                                    cwd=repo_path,
                                    capture_output=True, text=True, timeout=10,
                                )
                                print(f"✅ Rolled back successfully. Next attempt starts from clean state.")
                                # Re-create stubs that were wiped by the rollback
                                try:
                                    from .import_resolver import resolve_all_missing_imports
                                    _post_rollback_stubs = resolve_all_missing_imports(repo_path)
                                    if _post_rollback_stubs:
                                        print(f"📦 Re-created {len(_post_rollback_stubs)} stub(s) after rollback")
                                except Exception as _ir_err:
                                    print(f"Warning: post-rollback stub creation failed: {_ir_err}")
                                # Reset verification errors to the original error
                                # so the next attempt focuses on the ORIGINAL problem
                                verification_errors = list(verification_errors[:1]) if verification_errors else verification_errors
                                # Update baseline to include current error files —
                                # prevents false cascade detection on subsequent attempts
                                _original_error_basenames = _original_error_basenames | new_error_basenames
                            except Exception as e:
                                print(f"⚠️  Rollback failed: {e}")
                    else:
                        print(f"✅ Build succeeded after {model_name} fixes on attempt {fix_attempt}!")
                        if run_id:
                            add_progress_event(run_id, "fixing", f"✓ Build passed after {model_name} fix (attempt {fix_attempt})", {"attempt": fix_attempt, "model": model_name, "success": True})
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
                        
                        # LEARNING: Extract preventive lessons from the error+fix
                        try:
                            from .error_knowledge_base import extract_lessons_from_error
                            repo_name = repo_settings.get("repo_name", "unknown")
                            n_lessons = extract_lessons_from_error(repo_name, error_msg, fix_strategy, fixed_files)
                            if n_lessons:
                                print(f"📚 Learned {n_lessons} preventive lesson(s) from this fix")
                        except Exception as kb_err:
                            print(f"Note: Could not record KB lessons: {kb_err}")
                        
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
    
    # If still failing after all fix attempts, run post-mortem then fail the task
    if verification_errors:
        error_msg = "\n\n".join(verification_errors)
        print(f"\n{'='*60}")
        print(f"VERIFICATION STILL FAILING AFTER {fix_attempt} ATTEMPTS")
        print(f"{'='*60}")
        print(error_msg)
        if run_id:
            add_progress_event(run_id, "failed", f"Build failed after {fix_attempt} self-healing attempts", {"attempts": fix_attempt})

        # POST-MORTEM: Deep analysis, KB learning, GitHub Issue, and optional re-queue
        pm_result = None
        try:
            from .post_mortem import run_post_mortem
            repo_name = repo_settings.get("repo_name", "unknown")
            pm_result = run_post_mortem(
                run_id=run_id,
                repo_name=repo_name,
                final_errors=error_msg,
                fix_attempt_count=fix_attempt,
            )
            if pm_result.get("lessons_added"):
                print(f"📚 Post-mortem learned {pm_result['lessons_added']} preventive lesson(s)")
            if pm_result.get("github_issue_url"):
                print(f"📋 GitHub Issue: {pm_result['github_issue_url']}")
        except Exception as pm_err:
            print(f"[post_mortem] Error: {pm_err}")
            import traceback
            traceback.print_exc()

        # Post detailed error to Jira with attempt history
        jira_client = JiraClient(
            base_url=settings.JIRA_BASE_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN
        )

        attempt_summary = []
        for i in range(1, fix_attempt + 1):
            model = "Claude (Anthropic)" if i % 2 == 1 else f"OpenAI ({settings.OPENAI_MODEL})"
            attempt_summary.append(f"- Attempt {i}: {model}")

        pm_note = ""
        if pm_result:
            pm_note = "\n\n🔬 *Post-mortem analysis completed:*\n"
            pm_note += f"- Pattern: {pm_result.get('analysis', {}).get('pattern', 'unknown')}\n"
            pm_note += f"- New KB rules added: {pm_result.get('lessons_added', 0)}\n"
            if pm_result.get("github_issue_url"):
                pm_note += f"- GitHub Issue: {pm_result['github_issue_url']}\n"
            if pm_result.get("requeued"):
                pm_note += "- *Run has been re-queued with new knowledge — retrying automatically.*\n"
            else:
                pm_note += "- *Max post-mortem retries reached. Requires human intervention.*\n"

        jira_comment = (
            "❌ **Build Verification Failed After Multiple Attempts**\n\n"
            f"Tried {fix_attempt} times with alternating AI models for diverse fix approaches:\n"
            f"{chr(10).join(attempt_summary)}\n\n"
            f"**Final Errors:**\n```\n{error_msg[:2000]}\n```"
            f"{pm_note}\n"
            "---\n"
            "*Code was not committed.*"
        )
        jira_client.add_comment(issue.key, jira_comment)

        if pm_result and pm_result.get("requeued"):
            print(f"[post_mortem] Run re-queued — returning without raising error")
            return ExecutionResult(
                branch="",
                pr_url=None,
                summary="Re-queued by post-mortem analysis with new KB rules",
                jira_comment="",
                success=False,
            )

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
    
    # 5b) Detect and notify about post-deployment steps
    post_deploy_comment = None
    try:
        from .post_deploy_detector import check_and_notify_post_deploy_steps
        
        # Extract file paths from files_changed (remove "Created "/"Updated "/"Deleted " prefix)
        changed_file_paths = []
        for fc in files_changed:
            # Parse "Created path/to/file", "Updated path/to/file", etc.
            parts = fc.split(" ", 1)
            if len(parts) == 2:
                changed_file_paths.append(parts[1])
        
        if changed_file_paths:
            # Create Jira client for posting post-deployment steps
            jira_client = JiraClient(
                base_url=settings.JIRA_BASE_URL,
                email=settings.JIRA_EMAIL,
                api_token=settings.JIRA_API_TOKEN,
                timeout_s=120
            )
            check_and_notify_post_deploy_steps(
                repo_path=repo_path,
                changed_files=changed_file_paths,
                issue_key=issue.key,
                jira_client=jira_client,
                create_ticket_assigned_to_account_id=settings.JIRA_HUMAN_ACCOUNT_ID if settings.CREATE_POST_DEPLOY_TICKET else None,
            )
    except Exception as e:
        print(f"⚠️  Post-deployment detection failed (non-critical): {e}")
    
    # 5c) Check GitHub Actions CI status (non-blocking)
    ci_comment = ""
    try:
        from app.integrations.github_ci import check_ci_after_push
        ci_status = check_ci_after_push(
            owner=repo_settings["repo_owner_slug"],
            repo=repo_settings["repo_name"],
            branch=branch,
            wait=False,
        )
        if ci_status.overall == "failure":
            ci_comment = f"\n\n⚠️ CI checks failed on `{branch}`:\n{ci_status.to_jira_comment()}"
            print(f"⚠️  CI checks failed on {branch}")
            if run_id:
                add_progress_event(run_id, "verifying", f"⚠ GitHub CI checks failed on {branch}", {"ci_status": "failure"})
        elif ci_status.overall == "success":
            print(f"✓ CI checks passed on {branch}")
            if run_id:
                add_progress_event(run_id, "verifying", f"✓ GitHub CI checks passed", {"ci_status": "success"})
        elif ci_status.overall == "pending":
            print(f"⏳ CI checks still running on {branch}")
            if run_id:
                add_progress_event(run_id, "verifying", f"CI checks pending on {branch}", {"ci_status": "pending"})
    except Exception as e:
        print(f"Note: GitHub CI check skipped: {e}")

    # 5d) npm audit report (attach to Jira for visibility)
    try:
        from app.integrations.npm_audit import run_audit as run_npm_audit
        if (repo_path / "node_modules").exists():
            audit_result = run_npm_audit(repo_path)
            if audit_result.has_actionable_issues:
                jira_audit_comment = audit_result.to_jira_comment()
                notes += f"\n\n{jira_audit_comment}"
                print(f"⚠️  npm audit: {audit_result.critical} critical, {audit_result.high} high vulnerabilities")
    except Exception as e:
        print(f"Note: npm audit report skipped: {e}")

    # 5e) Playwright E2E regression tests (non-blocking, reported in Jira)
    try:
        from app.integrations.playwright_runner import detect_playwright as _detect_pw, run_tests as _run_pw
        if _detect_pw(repo_path):
            print("Running Playwright E2E regression tests...")
            if run_id:
                add_progress_event(run_id, "verifying", "Running Playwright E2E tests", {})
            pw_result = _run_pw(
                repo_path,
                project="chromium",
                timeout_seconds=180,
                max_retries=1,
                changed_files=[f["path"] for f in files if f.get("action") != "delete"],
            )
            if pw_result.error:
                notes += f"\n\n⚠️ E2E tests: {pw_result.error}"
                print(f"⚠️  Playwright: {pw_result.error}")
                if run_id:
                    add_progress_event(run_id, "verifying", f"⚠ Playwright E2E: {pw_result.error}", {})
            elif not pw_result.all_passed:
                notes += f"\n\n{pw_result.to_jira_comment()}"
                print(f"⚠️  Playwright: {pw_result.failed}/{pw_result.total} tests failed")
                if run_id:
                    add_progress_event(run_id, "verifying", f"⚠ Playwright E2E: {pw_result.failed}/{pw_result.total} tests failed", {"passed": pw_result.passed, "failed": pw_result.failed, "total": pw_result.total})
            elif pw_result.total > 0:
                notes += f"\n\n✅ E2E tests: {pw_result.passed}/{pw_result.total} passed"
                print(f"✓ Playwright: all {pw_result.total} tests passed")
                if run_id:
                    add_progress_event(run_id, "verifying", f"✓ Playwright E2E: {pw_result.total}/{pw_result.total} tests passed", {"total": pw_result.total})
    except Exception as e:
        print(f"Note: Playwright tests skipped: {e}")

    # 5f) Semgrep SAST scan report (non-blocking, informational for Jira)
    try:
        from app.integrations.semgrep_scanner import is_installed as _semgrep_ok, scan as _semgrep_scan
        if _semgrep_ok():
            print("Running Semgrep SAST scan for security report...")
            if run_id:
                add_progress_event(run_id, "verifying", "Running Semgrep SAST scan", {})
            sg_result = _semgrep_scan(
                repo_path,
                changed_files=[f["path"] for f in files if f.get("action") != "delete"],
            )
            if sg_result.error:
                print(f"⚠️  Semgrep: {sg_result.error}")
            elif sg_result.total > 0:
                notes += f"\n\n{sg_result.to_jira_comment()}"
                print(f"⚠️  Semgrep: {sg_result.errors_count} errors, {sg_result.warnings_count} warnings")
                if run_id:
                    add_progress_event(run_id, "verifying", f"⚠ Semgrep SAST: {sg_result.errors_count} errors, {sg_result.warnings_count} warnings", {"total": sg_result.total, "files_scanned": sg_result.files_scanned})
            else:
                notes += f"\n\n✅ Semgrep SAST: no issues ({sg_result.files_scanned} files scanned)"
                print(f"✓ Semgrep: clean ({sg_result.files_scanned} files)")
                if run_id:
                    add_progress_event(run_id, "verifying", f"✓ Semgrep SAST: clean ({sg_result.files_scanned} files)", {"files_scanned": sg_result.files_scanned})
    except Exception as e:
        print(f"Note: Semgrep scan skipped: {e}")

    # 5g) OWASP ZAP DAST scan (non-blocking, only if deployed URL available)
    try:
        from app.integrations.owasp_zap import is_configured as _zap_ok, run_baseline_scan
        deployed_url = repo_settings.get("deployed_url", "")
        if deployed_url and _zap_ok():
            print(f"Running OWASP ZAP baseline scan on {deployed_url}...")
            if run_id:
                add_progress_event(run_id, "verifying", "Running OWASP ZAP security scan", {})
            zap_result = run_baseline_scan(deployed_url)
            if zap_result.error:
                print(f"⚠️  ZAP: {zap_result.error}")
            elif zap_result.total > 0:
                notes += f"\n\n{zap_result.to_jira_comment()}"
                print(f"⚠️  ZAP: {zap_result.high_count} high, {zap_result.medium_count} medium")
                if run_id:
                    add_progress_event(run_id, "verifying", f"⚠ OWASP ZAP: {zap_result.high_count} high, {zap_result.medium_count} medium alerts", {"high": zap_result.high_count, "medium": zap_result.medium_count})
            else:
                notes += f"\n\n✅ OWASP ZAP: no vulnerabilities found"
                print(f"✓ ZAP: no vulnerabilities")
                if run_id:
                    add_progress_event(run_id, "verifying", "✓ OWASP ZAP: no vulnerabilities found", {})
    except Exception as e:
        print(f"Note: OWASP ZAP scan skipped: {e}")

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
            if run_id and pr_url:
                add_progress_event(run_id, "committing", f"PR created: {pr_url}", {"pr_url": pr_url})
        except Exception as e:
            pr_url = None
            notes += f"\n\nPR creation failed: {e}"
        summary = "Created branch, committed changes, and opened PR." if pr_url else "Created branch and committed changes."
    else:
        # Not independent: committed to Story branch, PR already exists or will be created by Story
        summary = f"Committed to Story branch ({branch}). Story PR will be updated automatically."
        pr_url = None  # Story owns the PR
    
    # Build comprehensive Jira comment with summary
    jira_comment = _build_completion_summary(
        issue=issue,
        branch=branch,
        pr_url=pr_url,
        files_changed=files_changed,
        implementation_notes=notes,
        verification_errors=verification_errors,
        repo_path=repo_path
    )
    
    # Update and save metrics
    if metrics:
        end_time = datetime.now()
        metrics.end_time = end_time
        metrics.duration_seconds = (end_time - start_time).total_seconds()
        metrics.success = True
        metrics.status = "completed"
        metrics.files_changed = len(files_changed)
        metrics.model_used = settings.ANTHROPIC_MODEL
        
        if run_id:
            duration_min = metrics.duration_seconds / 60
            cost_str = f"${metrics.estimated_cost:.4f}" if metrics.estimated_cost else "N/A"
            add_progress_event(run_id, "completed", f"Done in {duration_min:.1f}m — {len(files_changed)} files, cost {cost_str}", {
                "duration_seconds": round(metrics.duration_seconds, 1),
                "files_changed": len(files_changed),
                "cost": round(metrics.estimated_cost, 4) if metrics.estimated_cost else 0,
                "tokens_in": metrics.total_input_tokens,
                "tokens_out": metrics.total_output_tokens,
            })
        
        try:
            save_metrics(metrics)
        except Exception as e:
            print(f"Warning: Could not save metrics: {e}")
    
    return ExecutionResult(branch=branch, pr_url=pr_url, summary=summary, jira_comment=jira_comment)
