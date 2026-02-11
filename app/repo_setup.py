"""
Repository setup - creates GitHub repos, folders, and updates config.

Used by the AI Console "Add Repository" feature.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.github_app import get_github_token
from app.repo_config import get_repo_manager
from app.skill_loader import SKILLS_DIR


def list_available_skills() -> List[Dict[str, str]]:
    """
    List available skills from .cursor/skills.
    
    Returns:
        List of {"id": "skill-name", "description": "..."} dicts
    """
    skills = []
    
    if not SKILLS_DIR.exists():
        return skills
    
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        
        desc = ""
        try:
            content = skill_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 2:
                    # Parse YAML frontmatter for description
                    for line in parts[1].strip().split("\n"):
                        if line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip().strip('"')
                            break
            if not desc:
                desc = f"Skill for {skill_dir.name}"
        except Exception:
            desc = skill_dir.name
        
        skills.append({
            "id": skill_dir.name,
            "description": desc
        })
    
    return skills


def get_repos_config_path() -> Path:
    """Get path to repos.json."""
    path = os.getenv("REPOS_CONFIG_PATH")
    if path:
        return Path(path)
    return Path(__file__).parent.parent / "config" / "repos.json"


def get_repos_base_dir() -> Path:
    """Get base directory for repos (e.g. /srv/ai/repos)."""
    # Infer from first project or use env
    manager = get_repo_manager()
    projects = manager.get_all_projects()
    if projects:
        first = next(iter(projects.values()))
        workdir = Path(first.repo_workdir)
        return workdir.parent  # e.g. /srv/ai/repos
    return Path(os.getenv("REPOS_BASE_DIR", "/srv/ai/repos"))


def create_github_repo(
    owner: str,
    repo_name: str,
    description: str,
    private: bool = True
) -> Dict[str, Any]:
    """
    Create a GitHub repository using gh CLI.
    
    Returns:
        {"ok": True, "ssh_url": "...", "clone_url": "..."} or {"ok": False, "error": "..."}
    """
    try:
        token = get_github_token()
        env = os.environ.copy()
        env["GH_TOKEN"] = token
        
        full_name = f"{owner}/{repo_name}"
        args = [
            "gh", "repo", "create", full_name,
            "--description", description[:350],  # GitHub limit
        ]
        if private:
            args.append("--private")
        
        result = subprocess.run(
            args,
            env=env,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            # Repo might already exist
            if "name already exists" in (result.stderr or "").lower():
                return {
                    "ok": True,
                    "ssh_url": f"git@github.com:{full_name}.git",
                    "clone_url": f"https://github.com/{full_name}.git",
                    "message": "Repository already exists, using existing"
                }
            return {
                "ok": False,
                "error": result.stderr or result.stdout or "Unknown error"
            }
        
        # Parse output for URLs if needed
        ssh_url = f"git@github.com:{full_name}.git"
        return {
            "ok": True,
            "ssh_url": ssh_url,
            "clone_url": f"https://github.com/{full_name}.git"
        }
        
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "GitHub CLI timed out"}
    except FileNotFoundError:
        return {"ok": False, "error": "gh CLI not found. Install: apt install gh"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def create_repo_folder(repo_name: str) -> Dict[str, Any]:
    """
    Create the local folder for the repo.
    
    Returns:
        {"ok": True, "path": "..."} or {"ok": False, "error": "..."}
    """
    try:
        base = get_repos_base_dir()
        repo_path = base / repo_name
        
        if repo_path.exists():
            return {"ok": True, "path": str(repo_path), "message": "Folder already exists"}
        
        repo_path.mkdir(parents=True, exist_ok=True)
        
        return {"ok": True, "path": str(repo_path)}
        
    except PermissionError as e:
        return {"ok": False, "error": f"Permission denied: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def add_project_to_config(
    jira_project_key: str,
    jira_project_name: str,
    repo_owner_slug: str,
    repo_name: str,
    description: str,
    skills: List[str],
    base_branch: str = "main"
) -> Dict[str, Any]:
    """
    Add a new project to repos.json.
    
    Returns:
        {"ok": True} or {"ok": False, "error": "..."}
    """
    try:
        config_path = get_repos_config_path()
        
        if not config_path.exists():
            # Create from scratch
            data = {"projects": [], "default_project_key": jira_project_key}
        else:
            with open(config_path) as f:
                data = json.load(f)
        
        base_dir = get_repos_base_dir()
        workdir = str(base_dir / repo_name)
        ssh_url = f"git@github.com:{repo_owner_slug}/{repo_name}.git"
        
        new_project = {
            "jira_project_key": jira_project_key,
            "jira_project_name": jira_project_name,
            "repo_ssh": ssh_url,
            "repo_workdir": workdir,
            "base_branch": base_branch,
            "repo_owner_slug": repo_owner_slug,
            "repo_name": repo_name,
            "skills": skills if skills else ["nextjs-fullstack-dev"]
        }
        
        # Check for duplicate
        projects = data.get("projects", [])
        for p in projects:
            if p.get("jira_project_key") == jira_project_key:
                return {"ok": False, "error": f"Project {jira_project_key} already exists"}
            if p.get("repo_name") == repo_name and p.get("repo_owner_slug") == repo_owner_slug:
                return {"ok": False, "error": f"Repository {repo_owner_slug}/{repo_name} already configured"}
        
        projects.append(new_project)
        data["projects"] = projects
        
        # Set default if this is the first
        if not data.get("default_project_key"):
            data["default_project_key"] = jira_project_key
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)
        
        return {"ok": True, "message": "Configuration updated"}
        
    except Exception as e:
        return {"ok": False, "error": str(e)}


def setup_new_repository(
    jira_project_key: str,
    jira_project_name: str,
    repo_name: str,
    repo_owner: str,
    description: str,
    skills: List[str],
    base_branch: str = "main",
    create_on_github: bool = True,
    private: bool = True
) -> Dict[str, Any]:
    """
    Full setup: create GitHub repo, folder, and update config.
    
    Returns:
        {"ok": True, "steps": {...}} or {"ok": False, "error": "...", "steps": {...}}
    """
    steps = {}
    
    # 1. Create GitHub repo
    if create_on_github:
        steps["github"] = create_github_repo(repo_owner, repo_name, description, private)
        if not steps["github"]["ok"]:
            return {"ok": False, "error": steps["github"].get("error", "GitHub creation failed"), "steps": steps}
    
    # 2. Create folder
    steps["folder"] = create_repo_folder(repo_name)
    if not steps["folder"]["ok"]:
        return {"ok": False, "error": steps["folder"].get("error", "Folder creation failed"), "steps": steps}
    
    # 3. Update config
    steps["config"] = add_project_to_config(
        jira_project_key=jira_project_key,
        jira_project_name=jira_project_name,
        repo_owner_slug=repo_owner,
        repo_name=repo_name,
        description=description,
        skills=skills,
        base_branch=base_branch
    )
    if not steps["config"]["ok"]:
        return {"ok": False, "error": steps["config"].get("error", "Config update failed"), "steps": steps}
    
    return {"ok": True, "steps": steps}
