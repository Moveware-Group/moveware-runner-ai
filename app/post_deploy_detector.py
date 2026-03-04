"""
Post-Deployment Step Detection

Detects when code changes require manual post-deployment steps
(migrations, env vars, seed data, etc.) and generates instructions.
Can optionally create a Jira subtask assigned to the user with these steps.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Set, Dict, Any


class PostDeployStep:
    """Represents a required post-deployment step."""
    
    def __init__(self, category: str, command: str, description: str, priority: str = "required"):
        self.category = category
        self.command = command
        self.description = description
        self.priority = priority  # "required", "recommended", "optional"


def detect_post_deploy_steps(repo_path: Path, changed_files: List[str]) -> List[PostDeployStep]:
    """
    Analyze changed files and detect required post-deployment steps.
    
    Args:
        repo_path: Path to the repository
        changed_files: List of file paths that were changed
        
    Returns:
        List of PostDeployStep objects
    """
    steps = []
    
    for file_path in changed_files:
        full_path = repo_path / file_path
        
        # Skip if file doesn't exist (deleted files)
        if not full_path.exists():
            continue
        
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception:
            continue
        
        # Detect Prisma schema changes
        if file_path.endswith("schema.prisma") or "prisma/schema.prisma" in file_path:
            steps.extend(_detect_prisma_changes(content, file_path))
        
        # Detect new environment variables
        if file_path.endswith(".env.example") or file_path.endswith(".env.template"):
            steps.extend(_detect_env_changes(content, file_path))
        
        # Detect package.json changes
        if file_path.endswith("package.json"):
            steps.extend(_detect_package_changes(content, file_path))
        
        # Detect requirements.txt changes
        if file_path.endswith("requirements.txt"):
            steps.extend(_detect_python_deps(content, file_path))
        
        # Detect database seeding scripts
        if "seed" in file_path.lower() and (file_path.endswith(".ts") or file_path.endswith(".js") or file_path.endswith(".py")):
            steps.extend(_detect_seed_script(content, file_path))
        
        # Detect migration files
        if "migration" in file_path.lower() or "migrations/" in file_path:
            steps.extend(_detect_migration_file(file_path))
    
    steps = _deduplicate_steps(steps)

    # When Prisma/DB work is involved, prepend explicit "Create database" step
    if _has_database_steps(steps):
        steps = _prepend_database_creation_step(steps)

    return steps


def _has_database_steps(steps: List[PostDeployStep]) -> bool:
    """True if any step is database-related (migration, Prisma, seed)."""
    db_categories = ("Database Migration", "Database Seeding", "Prisma Client")
    return any(s.category in db_categories for s in steps)


def _prepend_database_creation_step(steps: List[PostDeployStep]) -> List[PostDeployStep]:
    """Add an explicit 'Create database' step at the start of required steps."""
    create_db = PostDeployStep(
        category="Create Database",
        command=(
            "# PostgreSQL example:\n"
            "createdb myapp_dev\n"
            "# Or via psql: CREATE DATABASE myapp_dev;\n"
            "# Then set DATABASE_URL in .env (see step below)"
        ),
        description="Create a PostgreSQL database for this app if it does not exist yet.",
        priority="required",
    )
    # Insert before other required steps
    required = [s for s in steps if s.priority == "required"]
    if required:
        idx = steps.index(required[0])
        return steps[:idx] + [create_db] + steps[idx:]
    return [create_db] + steps


def _detect_prisma_changes(content: str, file_path: str) -> List[PostDeployStep]:
    """Detect Prisma schema changes that require migration."""
    steps = []
    
    # Check if new models were added
    model_count = len(re.findall(r'^\s*model\s+\w+', content, re.MULTILINE))
    
    # Check for enum changes
    enum_count = len(re.findall(r'^\s*enum\s+\w+', content, re.MULTILINE))
    
    if model_count > 0 or enum_count > 0:
        steps.append(PostDeployStep(
            category="Database Migration",
            command="npx prisma migrate dev --name <migration_name>",
            description=f"Prisma schema modified ({file_path}). Create and apply database migration.",
            priority="required"
        ))
        
        steps.append(PostDeployStep(
            category="Prisma Client",
            command="npx prisma generate",
            description="Regenerate Prisma client to reflect schema changes.",
            priority="required"
        ))
    
    return steps


def _detect_env_changes(content: str, file_path: str) -> List[PostDeployStep]:
    """Detect new environment variables and produce explicit .env lines."""
    steps = []
    env_vars = re.findall(r'^([A-Z_][A-Z0-9_]*)\s*=', content, re.MULTILINE)
    env_vars = sorted(set(env_vars))

    if env_vars:
        # Build explicit lines for .env (one per variable with placeholder)
        placeholders = {
            "DATABASE_URL": "postgresql://user:password@localhost:5432/myapp_dev",
            "DIRECT_URL": "postgresql://user:password@localhost:5432/myapp_dev",
            "NEXTAUTH_SECRET": "generate-with-openssl-rand-hex-32",
            "NEXTAUTH_URL": "http://localhost:3000",
            "JWT_SECRET": "your-jwt-secret",
            "ENCRYPTION_KEY": "32-character-encryption-key!!",
        }
        lines = []
        for var in env_vars:
            placeholder = placeholders.get(var, "<set-me>")
            lines.append(f"{var}={placeholder}")
        command = "# Add to .env (create file if missing):\n" + "\n".join(lines)
        steps.append(PostDeployStep(
            category="Environment Variables",
            command=command,
            description=f"Set these in .env (from {file_path}): " + ", ".join(env_vars),
            priority="required",
        ))
    return steps


def _detect_package_changes(content: str, file_path: str) -> List[PostDeployStep]:
    """Detect package.json changes requiring npm install."""
    steps = []
    
    # This is a heuristic - we can't know if deps changed without git diff
    # But if package.json was modified, it's safer to recommend npm install
    steps.append(PostDeployStep(
        category="Dependencies",
        command="npm install",
        description=f"package.json was modified. Install/update dependencies.",
        priority="recommended"
    ))
    
    return steps


def _detect_python_deps(content: str, file_path: str) -> List[PostDeployStep]:
    """Detect Python dependency changes."""
    steps = []
    
    steps.append(PostDeployStep(
        category="Dependencies",
        command="pip install -r requirements.txt",
        description=f"Python dependencies updated in {file_path}.",
        priority="recommended"
    ))
    
    return steps


def _detect_seed_script(content: str, file_path: str) -> List[PostDeployStep]:
    """Detect database seeding scripts."""
    steps = []
    
    # Check if it's a Prisma seed script
    if "prisma" in content.lower() and "seed" in file_path.lower():
        steps.append(PostDeployStep(
            category="Database Seeding",
            command="npx prisma db seed",
            description=f"Seed script detected ({file_path}). Run to populate database with initial data.",
            priority="optional"
        ))
    
    return steps


def _detect_migration_file(file_path: str) -> List[PostDeployStep]:
    """Detect migration files."""
    steps = []
    
    if "prisma/migrations/" in file_path:
        steps.append(PostDeployStep(
            category="Database Migration",
            command="npx prisma migrate deploy",
            description=f"New migration file detected ({file_path}). Apply migration to database.",
            priority="required"
        ))
    
    return steps


def _deduplicate_steps(steps: List[PostDeployStep]) -> List[PostDeployStep]:
    """Remove duplicate steps based on command."""
    seen = set()
    unique_steps = []
    
    for step in steps:
        key = (step.category, step.command)
        if key not in seen:
            seen.add(key)
            unique_steps.append(step)
    
    return unique_steps


def format_post_deploy_comment(steps: List[PostDeployStep]) -> str:
    """
    Format post-deployment steps as a Jira comment with explicit numbered steps and code blocks.
    """
    if not steps:
        return ""
    required = [s for s in steps if s.priority == "required"]
    recommended = [s for s in steps if s.priority == "recommended"]
    optional = [s for s in steps if s.priority == "optional"]
    parts = ["## ⚠️ Post-Deployment Steps Required\n\n", "After pulling this code, perform these steps in order:\n"]
    if required:
        parts.append("\n### 🔴 Required\n")
        for i, step in enumerate(required, 1):
            parts.append(f"\n**{i}. {step.category}**\n")
            parts.append(f"{step.description}\n")
            parts.append(f"```bash\n{step.command}\n```\n")
    if recommended:
        parts.append("\n### 🟡 Recommended\n")
        for i, step in enumerate(recommended, 1):
            parts.append(f"\n**{len(required) + i}. {step.category}**\n")
            parts.append(f"{step.description}\n")
            parts.append(f"```bash\n{step.command}\n```\n")
    if optional:
        parts.append("\n### 🟢 Optional\n")
        for i, step in enumerate(optional, 1):
            parts.append(f"\n**{len(required) + len(recommended) + i}. {step.category}**\n")
            parts.append(f"{step.description}\n")
            parts.append(f"```bash\n{step.command}\n```\n")
    parts.append("\n---\n_Generated by AI Runner._")
    return "".join(parts)


def format_post_deploy_steps_as_plain_text(steps: List[PostDeployStep]) -> str:
    """
    Format steps as a single explicit numbered list (for Jira ticket description).
    Copy-paste friendly.
    """
    if not steps:
        return ""
    return _format_steps_document(steps, title="Post-deployment steps", intro="Complete these steps to set up database, .env, and run migrations:\n")


def _format_steps_document(
    steps: List[PostDeployStep],
    title: str,
    intro: str,
) -> str:
    """Shared formatter: group by priority, then output explicit numbered steps."""
    required = [s for s in steps if s.priority == "required"]
    recommended = [s for s in steps if s.priority == "recommended"]
    optional = [s for s in steps if s.priority == "optional"]

    parts = [f"{title}\n\n", intro]

    if required:
        parts.append("\n--- Required ---\n")
        for i, step in enumerate(required, 1):
            parts.append(f"\n{i}. {step.category}\n")
            parts.append(f"   {step.description}\n")
            parts.append(f"   Commands:\n")
            for line in step.command.strip().split("\n"):
                parts.append(f"   {line}\n")
    if recommended:
        parts.append("\n--- Recommended ---\n")
        for i, step in enumerate(recommended, 1):
            parts.append(f"\n{len(required) + i}. {step.category}\n")
            parts.append(f"   {step.description}\n")
            for line in step.command.strip().split("\n"):
                parts.append(f"   {line}\n")
    if optional:
        parts.append("\n--- Optional ---\n")
        for i, step in enumerate(optional, 1):
            parts.append(f"\n{len(required) + len(recommended) + i}. {step.category}\n")
            parts.append(f"   {step.description}\n")
            for line in step.command.strip().split("\n"):
                parts.append(f"   {line}\n")

    parts.append("\n---\nGenerated by AI Runner.")
    return "".join(parts)


def check_and_notify_post_deploy_steps(
    repo_path: Path,
    changed_files: List[str],
    issue_key: str,
    jira_client,
    create_ticket_assigned_to_account_id: Optional[str] = None,
) -> bool:
    """
    Detect post-deployment steps and add comment to Jira. Optionally create a
    subtask assigned to the user with the full steps (for database, .env, migrations).

    Args:
        repo_path: Path to the repository
        changed_files: List of changed file paths
        issue_key: Jira issue key (Story)
        jira_client: JiraClient instance
        create_ticket_assigned_to_account_id: If set, create a subtask under this issue
            with the steps as description and assign to this account (e.g. human reviewer).

    Returns:
        True if post-deploy steps were detected and comment added, False otherwise
    """
    steps = detect_post_deploy_steps(repo_path, changed_files)
    if not steps:
        return False

    comment = format_post_deploy_comment(steps)
    try:
        jira_client.add_comment(issue_key, comment)
        print(f"✅ Added post-deployment steps comment to {issue_key}")
    except Exception as e:
        print(f"⚠️  Failed to add post-deployment comment to {issue_key}: {e}")
        return False

    if create_ticket_assigned_to_account_id:
        try:
            description = format_post_deploy_steps_as_plain_text(steps)
            subtask_key = jira_client.create_subtask(
                parent_key=issue_key,
                summary="[Post-deploy] Database, .env & migrations setup",
                description=description.strip(),
            )
            if subtask_key:
                jira_client.assign(subtask_key, create_ticket_assigned_to_account_id)
                print(f"✅ Created post-deploy subtask {subtask_key} assigned to you")
        except Exception as e:
            print(f"⚠️  Failed to create post-deploy subtask: {e}")

    return True
