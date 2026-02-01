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
    JIRA_STATUS_SELECTED_FOR_DEV: str = env("JIRA_STATUS_SELECTED_FOR_DEV", required=True)
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

# This is what main.py expects
settings = Settings()
