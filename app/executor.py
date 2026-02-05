from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import settings
from .git_ops import checkout_repo, create_branch, commit_and_push, create_pr, checkout_or_create_story_branch
from .jira import JiraClient
from .jira_adf import adf_to_plain_text
from .llm_anthropic import AnthropicClient
from .models import JiraIssue
from .db import add_progress_event


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
    
    if run_id:
        add_progress_event(run_id, "executing", f"Preparing repository for {issue.key}", {})

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
    
    if run_id:
        add_progress_event(run_id, "executing", f"Analyzing task and planning implementation", {"branch": branch})

    # 3) Ask Claude to implement the code changes
    client = AnthropicClient(api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    
    # Get repository context (includes file contents)
    repo_path = Path(settings.REPO_WORKDIR)
    context_info = _get_repo_context(repo_path, issue)
    
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
        f"Provide your implementation as JSON following the specified format."
    )
    
    if run_id:
        add_progress_event(run_id, "executing", f"Calling Claude to generate implementation", {})
    
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

    # 5) Verify the changes (run npm install and build for Node projects)
    verification_errors = []
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
    
    # If verification failed, try to fix the errors (self-healing)
    if verification_errors:
        error_msg = "\n\n".join(verification_errors)
        print(f"VERIFICATION FAILED - Attempting to fix errors...\n{error_msg}")
        
        if run_id:
            add_progress_event(run_id, "fixing", "Build failed, asking Claude to fix errors", {})
        
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
        import re
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
        
        # Ask Claude to fix the build errors
        fix_prompt = (
            f"The code you generated has build errors. Please fix ALL the errors below.\n\n"
            f"**Original Task:** {issue.key}\n"
            f"**Summary:** {issue.summary}\n\n"
            f"**Build Errors:**\n```\n{error_msg[:1500]}\n```\n\n"  # Limit error size
            f"{error_context}\n\n"  # Show actual file contents with errors
            f"**Repository Context:**\n{context_info}\n\n"
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
            f"- Use valid Tailwind classes: Only bg-blue-600, text-gray-900, etc. (not bg-background)\n"
            f"- Remove @apply directives with invalid classes from CSS files\n"
            f"- Export service instances: `export const serviceName = createService()`\n"
            f"- Check TypeScript types: Ensure all properties exist\n\n"
            f"Focus ONLY on fixing the build errors. Provide ALL files that need changes."
        )
        
        try:
            print("Calling Claude to fix build errors...")
            fix_raw = client.messages_create({
                "model": settings.ANTHROPIC_MODEL,
                "system": _system_prompt(),
                "messages": [{"role": "user", "content": fix_prompt}],
                "max_tokens": 16000,
                "temperature": 1,
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 5000
                }
            })
            
            fix_text = AnthropicClient.extract_text(fix_raw)
            
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
                
                if is_nextjs:
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
                        verification_errors.append(f"Build still failing after fix attempt:\n{error_output[:1000]}")
                        print(f"Build still failing:\n{error_output[:500]}")
                    else:
                        print("✅ Build succeeded after fixes!")
                        notes += "\n\n⚠️ *Note: Initial build failed, but Claude automatically fixed the errors and build now succeeds.*"
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse Claude's fix response as JSON: {e}")
            verification_errors.append(
                f"Auto-fix failed: Claude's response was not valid JSON.\n"
                f"This usually means the errors are too complex for automatic fixing.\n"
                f"Error: {e}"
            )
        except Exception as e:
            print(f"Failed to auto-fix errors: {e}")
            import traceback
            traceback.print_exc()
            verification_errors.append(f"Auto-fix attempt failed: {e}")
        
        # If still failing after fix attempt, FAIL THE TASK
        if verification_errors:
            error_msg = "\n\n".join(verification_errors)
            print(f"VERIFICATION STILL FAILING:\n{error_msg}")
            
            # Post detailed error to Jira
            jira_client = JiraClient(
                base_url=settings.JIRA_BASE_URL,
                email=settings.JIRA_EMAIL,
                api_token=settings.JIRA_API_TOKEN
            )
            
            jira_comment = (
                "❌ **Build Verification Failed**\n\n"
                "The code changes did not pass verification even after attempting auto-fix.\n\n"
                f"**Errors:**\n{error_msg}\n\n"
                "---\n"
                "*Code was not committed. Please review the errors and reassign the task.*"
            )
            jira_client.add_comment(issue.key, jira_comment)
            
            # Raise error to fail the task
            raise RuntimeError(f"Build verification failed after fix attempt:\n{error_msg}")
    
    if run_id:
        add_progress_event(run_id, "committing", f"Committing changes: {len(files_changed)} files", {"file_count": len(files_changed)})
    
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
