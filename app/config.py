from __future__ import annotations

import os


def env(name: str, default: str | None = None, required: bool = False) -> str:
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return "" if v is None else str(v)


# ---- Service bind ----
LISTEN_HOST = env("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(env("LISTEN_PORT", "8088") or "8088")


# ---- Jira (Cloud) ----
JIRA_BASE_URL = env("JIRA_BASE_URL", required=True).rstrip("/")
JIRA_EMAIL = env("JIRA_EMAIL", required=True)
JIRA_API_TOKEN = env("JIRA_API_TOKEN", required=True)

JIRA_AI_ACCOUNT_ID = env("JIRA_AI_ACCOUNT_ID", required=True)
JIRA_HUMAN_ACCOUNT_ID = env("JIRA_HUMAN_ACCOUNT_ID", required=True)
JIRA_WEBHOOK_SECRET = env("JIRA_WEBHOOK_SECRET", required=True)


# ---- Pilot status names (must match your workflow exactly) ----
STATUS_BACKLOG = env("JIRA_STATUS_BACKLOG", "Backlog")
STATUS_PLAN_REVIEW = env("JIRA_STATUS_PLAN_REVIEW", "Plan Review")
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
