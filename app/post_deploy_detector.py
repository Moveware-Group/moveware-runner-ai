"""
Post-Deployment Step Detection

Detects when code changes require manual post-deployment steps
(migrations, env vars, seed data, etc.) and generates instructions.
"""

import re
from pathlib import Path
from typing import List, Set, Dict, Any


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
    
    # Deduplicate steps
    return _deduplicate_steps(steps)


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
    """Detect new environment variables."""
    steps = []
    
    # Extract all env var names
    env_vars = re.findall(r'^([A-Z_][A-Z0-9_]*)\s*=', content, re.MULTILINE)
    
    if env_vars:
        var_list = ", ".join(sorted(set(env_vars)))
        steps.append(PostDeployStep(
            category="Environment Variables",
            command=f"# Add to .env file:\n# {chr(10).join(env_vars[:5])}{'...' if len(env_vars) > 5 else ''}",
            description=f"New environment variables detected in {file_path}: {var_list}",
            priority="required"
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
    Format post-deployment steps as a Jira comment.
    
    Args:
        steps: List of PostDeployStep objects
        
    Returns:
        Formatted comment string
    """
    if not steps:
        return ""
    
    # Group by priority
    required = [s for s in steps if s.priority == "required"]
    recommended = [s for s in steps if s.priority == "recommended"]
    optional = [s for s in steps if s.priority == "optional"]
    
    comment_parts = ["## ⚠️ Post-Deployment Steps Required\n"]
    comment_parts.append("After pulling this code, you must perform the following steps:\n")
    
    if required:
        comment_parts.append("\n### 🔴 Required Steps\n")
        for i, step in enumerate(required, 1):
            comment_parts.append(f"\n**{i}. {step.category}**\n")
            comment_parts.append(f"{step.description}\n")
            comment_parts.append(f"```bash\n{step.command}\n```\n")
    
    if recommended:
        comment_parts.append("\n### 🟡 Recommended Steps\n")
        for i, step in enumerate(recommended, 1):
            comment_parts.append(f"\n**{i}. {step.category}**\n")
            comment_parts.append(f"{step.description}\n")
            comment_parts.append(f"```bash\n{step.command}\n```\n")
    
    if optional:
        comment_parts.append("\n### 🟢 Optional Steps\n")
        for i, step in enumerate(optional, 1):
            comment_parts.append(f"\n**{i}. {step.category}**\n")
            comment_parts.append(f"{step.description}\n")
            comment_parts.append(f"```bash\n{step.command}\n```\n")
    
    comment_parts.append("\n---\n")
    comment_parts.append("_This comment was automatically generated by the AI Runner._")
    
    return "".join(comment_parts)


def check_and_notify_post_deploy_steps(repo_path: Path, changed_files: List[str], issue_key: str, jira_client) -> bool:
    """
    Detect post-deployment steps and add comment to Jira if any found.
    
    Args:
        repo_path: Path to the repository
        changed_files: List of changed file paths
        issue_key: Jira issue key
        jira_client: JiraClient instance
        
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
        return True
    except Exception as e:
        print(f"⚠️  Failed to add post-deployment comment to {issue_key}: {e}")
        return False
