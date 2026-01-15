import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()  # loads from .env if present


def _req(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


@dataclass(frozen=True)
class Settings:
    # Network
    listen_host: str = os.getenv("LISTEN_HOST", "127.0.0.1")
    listen_port: int = int(os.getenv("LISTEN_PORT", "8088"))
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")

    # Jira
    jira_base_url: str = _req("JIRA_BASE_URL")
    jira_email: str = _req("JIRA_EMAIL")
    jira_api_token: str = _req("JIRA_API_TOKEN")
    jira_webhook_secret: str = _req("JIRA_WEBHOOK_SECRET")

    jira_ai_account_id: str = _req("JIRA_ASSIGNEE_AI_ACCOUNT_ID")
    jira_leigh_account_id: str = _req("JIRA_ASSIGNEE_LEIGH_ACCOUNT_ID")

    # Jira workflow transition IDs (recommended: set explicit IDs)
    jira_transition_in_testing: str = os.getenv("JIRA_TRANSITION_IN_TESTING", "")
    jira_transition_done: str = os.getenv("JIRA_TRANSITION_DONE", "")

    # GitHub
    github_repo: str = _req("GITHUB_REPO")  # e.g. leigh-moveware/online-docs
    github_default_branch: str = os.getenv("GITHUB_DEFAULT_BRANCH", "main")
    github_token: str = _req("GITHUB_TOKEN")  # PAT with repo scope (pilot)

    # Paths
    work_root: str = os.getenv("WORK_ROOT", "/srv/ai/work")
    repo_cache_dir: str = os.getenv("REPO_CACHE_DIR", "/srv/ai/repos")

    # Behaviour
    max_attempts: int = int(os.getenv("MAX_ATTEMPTS", "3"))
    worker_poll_seconds: int = int(os.getenv("WORKER_POLL_SECONDS", "3"))
    worker_id: str = os.getenv("WORKER_ID", "worker-1")

    # LLM routing (optional)
    llm_provider: str = os.getenv("LLM_PROVIDER", "none")  # none|openai|anthropic
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.2-codex")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4.5")


settings = Settings()
