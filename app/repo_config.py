"""
Repository configuration for multi-project support.

Allows mapping Jira projects to different GitHub repositories.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class RepoConfig:
    """Repository configuration for a Jira project."""
    jira_project_key: str
    jira_project_name: str
    repo_ssh: str
    repo_workdir: str
    base_branch: str
    repo_owner_slug: str
    repo_name: str
    skills: List[str]  # Optional list of skill names (e.g. ["nextjs-fullstack-dev", "flutter-dev"])
    port: int = 3000  # Port for Next.js apps (PM2/NGINX). Use 3001, 3002, etc. for additional apps.


class RepoConfigManager:
    """Manages repository configurations for multiple Jira projects."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the repository configuration manager.
        
        Args:
            config_path: Path to repos.json file. If None, uses:
                        1. REPOS_CONFIG_PATH env var
                        2. ./config/repos.json
                        3. Falls back to legacy env vars
        """
        self.configs: Dict[str, RepoConfig] = {}
        self.default_project_key: Optional[str] = None
        
        if config_path is None:
            config_path = os.getenv("REPOS_CONFIG_PATH")
            if not config_path:
                # Try standard location
                config_path = str(Path(__file__).parent.parent / "config" / "repos.json")
        
        # Load configuration if file exists
        if config_path and Path(config_path).exists():
            self._load_from_file(config_path)
        else:
            # Fall back to legacy environment variables
            self._load_from_env()
    
    def _load_from_file(self, config_path: str) -> None:
        """Load repository configurations from JSON file."""
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Invalid JSON in {config_path} at line {e.lineno}, column {e.colno}: {e.msg}. "
                f"Run: python3 -m json.tool {config_path}  # to validate and see the error."
            ) from e
        
        for project in data.get("projects", []):
            config = RepoConfig(
                jira_project_key=project["jira_project_key"],
                jira_project_name=project.get("jira_project_name", ""),
                repo_ssh=project["repo_ssh"],
                repo_workdir=project["repo_workdir"],
                base_branch=project["base_branch"],
                repo_owner_slug=project["repo_owner_slug"],
                repo_name=project["repo_name"],
                skills=project.get("skills") or ["nextjs-fullstack-dev"],
                port=int(project.get("port", 3000)),
            )
            self.configs[config.jira_project_key] = config
        
        self.default_project_key = data.get("default_project_key")
        
        print(f"Loaded {len(self.configs)} repository configurations from {config_path}")
    
    def _load_from_env(self) -> None:
        """Fall back to legacy environment variables (single repo)."""
        from app.config import settings
        
        # Extract project key from repo name or use "DEFAULT"
        project_key = os.getenv("JIRA_PROJECT_KEY", "DEFAULT")
        
        config = RepoConfig(
            jira_project_key=project_key,
            jira_project_name="",
            repo_ssh=settings.REPO_SSH,
            repo_workdir=settings.REPO_WORKDIR,
            base_branch=settings.BASE_BRANCH,
            repo_owner_slug=settings.REPO_OWNER_SLUG,
            repo_name=settings.REPO_NAME,
            skills=["nextjs-fullstack-dev"],
            port=3000,
        )
        
        self.configs[project_key] = config
        self.default_project_key = project_key
        
        print(f"Using legacy environment variables for single repository: {project_key}")
    
    def get_repo_for_issue(self, issue_key: str) -> Optional[RepoConfig]:
        """
        Get repository configuration for a Jira issue key.
        
        Args:
            issue_key: Jira issue key (e.g., "OD-123", "MW-456")
        
        Returns:
            RepoConfig for the project, or None if not found
        """
        # Extract project key from issue key (e.g., "OD-123" -> "OD")
        project_key = issue_key.split("-")[0] if "-" in issue_key else issue_key
        
        # Look up configuration
        config = self.configs.get(project_key)
        
        # Fall back to default if not found
        if not config and self.default_project_key:
            config = self.configs.get(self.default_project_key)
        
        return config
    
    def get_all_projects(self) -> Dict[str, RepoConfig]:
        """Get all configured projects."""
        return self.configs.copy()


# Global instance (initialized once)
_repo_manager: Optional[RepoConfigManager] = None


def get_repo_manager() -> RepoConfigManager:
    """Get or create the global repository configuration manager."""
    global _repo_manager
    if _repo_manager is None:
        _repo_manager = RepoConfigManager()
    return _repo_manager


def get_repo_for_issue(issue_key: str) -> Optional[RepoConfig]:
    """
    Convenience function to get repository configuration for an issue.
    
    Args:
        issue_key: Jira issue key (e.g., "OD-123")
    
    Returns:
        RepoConfig or None
    """
    return get_repo_manager().get_repo_for_issue(issue_key)
