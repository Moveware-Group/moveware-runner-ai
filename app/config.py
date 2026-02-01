import os
from dataclasses import dataclass


def env(name: str, required: bool = False, default: str | None = None) -> str:
    val = os.getenv(name)
    if val is None or val == "":
        if required:
            raise RuntimeError(f"Missing required env var: {name}")
        return default if default is not None else ""
    return val


@dataclass(frozen=True)
class Settings:
    # ---- Listener ----
    LISTEN_HOST: str = env("LISTEN_HOST", required=True)
    LISTEN_PORT: int = int(env("LISTEN_PORT", required=True))

    # ---- Jira (Cloud) ----
    JIRA_BASE_URL: str = env("JIRA_BASE_URL", required=True)
    JIRA_EMAIL: str = env("JIRA_EMAIL", required=True)
    JIRA_API_TOKEN: str = env("JIRA_API_TOKEN", required=True)

    JIRA_AI_ACCOUNT_ID: str = env("JIRA_AI_ACCOUNT_ID", required=True)
    JIRA_HUMAN_ACCOUNT_ID: str = env("JIRA_HUMAN_ACCOUNT_ID", required=True)

    JIRA_WEBHOOK_SECRET: str = env("JIRA_WEBHOOK_SECRET", required=True)

    # Workflow statuses
    JIRA_STATUS_BACKLOG: str = env("JIRA_STATUS_BACKLOG", required=True)
    JIRA_STATUS_PLAN_REVIEW: str = env("JIRA_STATUS_PLAN_REVIEW", required=True)
    JIRA_STATUS_IN_PROGRESS: str = env("JIRA_STATUS_IN_PROGRESS", required=True)
    JIRA_STATUS_IN_TESTING: str = env("JIRA_STATUS_IN_TESTING", required=True)
    JIRA_STATUS_DONE: str = env("JIRA_STATUS_DONE", required=True)
    JIRA_STATUS_BLOCKED: str = env("JIRA_STATUS_BLOCKED", required=True)

    # ---- Repo settings (GitHub) ----
    REPO_SSH: str = env("REPO_SSH", required=True)
    REPO_WORKDIR: str = env("REPO_WORKDIR", required=True)
    BASE_BRANCH: str = env("BASE_BRANCH", required=True)
    REPO_OWNER_SLUG: str = env("REPO_OWNER_SLUG", required=True)
    REPO_NAME: str = env("REPO_NAME", required=True)

    GH_TOKEN: str = env("GH_TOKEN", required=True)

    # ---- LLM providers ----
    OPENAI_API_KEY: str = env("OPENAI_API_KEY", required=True)
    OPENAI_MODEL: str = env("OPENAI_MODEL", required=True)
    OPENAI_BASE_URL: str = env("OPENAI_BASE_URL", required=True)

    ANTHROPIC_API_KEY: str = env("ANTHROPIC_API_KEY", required=True)
    ANTHROPIC_MODEL: str = env("ANTHROPIC_MODEL", required=True)
    ANTHROPIC_BASE_URL: str = env("ANTHROPIC_BASE_URL", required=True)

    DEBUG: bool = env("DEBUG", default="false").lower() in ("1", "true", "yes", "y")


# Plan comment marker constant
PARENT_PLAN_COMMENT_PREFIX = "[AI PLAN v1]"

<<<<<<< Updated upstream
# This is what main.py expects
settings = Settings()
=======
JIRA_AI_ACCOUNT_ID = env("JIRA_AI_ACCOUNT_ID", required=True)
JIRA_HUMAN_ACCOUNT_ID = env("JIRA_HUMAN_ACCOUNT_ID", required=True)
JIRA_WEBHOOK_SECRET = env("JIRA_WEBHOOK_SECRET", required=True)


# ---- Pilot status names (must match your workflow exactly) ----
STATUS_BACKLOG = env("JIRA_STATUS_BACKLOG", "Backlog")
STATUS_PLAN_REVIEW = env("JIRA_STATUS_PLAN_REVIEW", "Plan Review")
STATUS_SELECTED_FOR_DEV = env("JIRA_STATUS_SELECTED_FOR_DEV", "Selected for Development")
STATUS_IN_PROGRESS = env("JIRA_STATUS_IN_PROGRESS", "In Progress")
STATUS_IN_TESTING = env("JIRA_STATUS_IN_TESTING", "In Testing")
STATUS_DONE = env("JIRA_STATUS_DONE", "Done")
STATUS_BLOCKED = env("JIRA_STATUS_BLOCKED", "Blocked")


# ---- Git / GitHub ----
REPO_SSH = env("REPO_SSH", required=True)
REPO_WORKDIR = env("REPO_WORKDIR", "/srv/ai/workdir/repo")
BASE_BRANCH = env("BASE_BRANCH", "main")

# For GH CLI PR creation (optional but recommended)
GH_TOKEN = env("GH_TOKEN", "")
REPO_OWNER_SLUG = env("REPO_OWNER_SLUG", "")
REPO_NAME = env("REPO_NAME", "")


# ---- LLMs ----
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-5.2-codex")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1")

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-sonnet-4.5")
ANTHROPIC_BASE_URL = env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")


# ---- Behaviour toggles ----
MAX_PLAN_REFINEMENTS = int(env("MAX_PLAN_REFINEMENTS", "2") or "2")
PARENT_PLAN_COMMENT_PREFIX = env("PARENT_PLAN_COMMENT_PREFIX", "AI Plan v")
>>>>>>> Stashed changes
