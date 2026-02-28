"""
Vercel integration for the AI orchestrator.

Provides deployment context, build log analysis, and environment variable
awareness for the LLM when working on Next.js/React projects deployed to
Vercel. When a deployment fails, the executor can fetch build logs so Claude
gets precise error context. Also provides project configuration (framework,
env vars, domains) so generated code is deployment-ready.

Requires environment variables:
  VERCEL_TOKEN   - Vercel API token (Bearer token)
  VERCEL_TEAM_ID - (Optional) Vercel team/org ID for team-scoped projects

Generate token at: https://vercel.com/account/tokens
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


VERCEL_API_BASE = "https://api.vercel.com"


@dataclass
class VercelProjectContext:
    """Vercel project configuration relevant to code generation."""
    project_name: str = ""
    framework: str = ""
    node_version: str = ""
    build_command: str = ""
    output_directory: str = ""
    root_directory: str = ""
    domains: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)  # names only, no values
    latest_deployment_status: str = ""
    latest_deployment_url: str = ""

    def to_prompt_context(self) -> str:
        """Format as context for injection into LLM prompts."""
        parts = [f"**Vercel Project: {self.project_name}**"]

        if self.framework:
            parts.append(f"- Framework: {self.framework}")
        if self.node_version:
            parts.append(f"- Node.js: {self.node_version}")
        if self.build_command:
            parts.append(f"- Build: `{self.build_command}`")
        if self.output_directory:
            parts.append(f"- Output dir: `{self.output_directory}`")
        if self.root_directory:
            parts.append(f"- Root dir: `{self.root_directory}`")

        if self.domains:
            parts.append(f"- Domains: {', '.join(self.domains[:5])}")

        if self.env_vars:
            parts.append(f"- Env vars configured: {', '.join(self.env_vars[:20])}")

        if self.latest_deployment_status:
            parts.append(
                f"- Latest deployment: {self.latest_deployment_status}"
                + (f" ({self.latest_deployment_url})" if self.latest_deployment_url else "")
            )

        return "\n".join(parts)


@dataclass
class VercelDeploymentError:
    """Build error details from a failed Vercel deployment."""
    deployment_url: str = ""
    status: str = ""
    error_message: str = ""
    build_logs: str = ""
    created_at: str = ""

    def to_prompt_context(self) -> str:
        """Format as context for injection into LLM prompts."""
        parts = [
            f"**Vercel Deployment Error:**",
            f"- Status: {self.status}",
            f"- URL: {self.deployment_url}" if self.deployment_url else None,
            f"- Created: {self.created_at}" if self.created_at else None,
        ]

        if self.error_message:
            parts.append(f"- Error: {self.error_message}")

        if self.build_logs:
            parts.append(f"\nBuild logs (last 3000 chars):\n```\n{self.build_logs[-3000:]}\n```")

        return "\n".join(p for p in parts if p)


def _get_token() -> Optional[str]:
    return os.getenv("VERCEL_TOKEN")


def _team_id() -> Optional[str]:
    return os.getenv("VERCEL_TEAM_ID")


def _headers() -> dict:
    token = _get_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _params() -> dict:
    """Add team scope if configured."""
    tid = _team_id()
    return {"teamId": tid} if tid else {}


def is_configured() -> bool:
    """Check whether Vercel integration is configured."""
    return bool(_get_token())


def _get(path: str, extra_params: Optional[dict] = None) -> Optional[dict]:
    """Make a GET request to the Vercel API."""
    token = _get_token()
    if not token:
        return None

    params = _params()
    if extra_params:
        params.update(extra_params)

    try:
        resp = requests.get(
            f"{VERCEL_API_BASE}{path}",
            headers=_headers(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Vercel API error ({path}): {e}")
        return None


def list_projects() -> List[Dict[str, str]]:
    """List Vercel projects accessible with the current token."""
    if not is_configured():
        return []

    data = _get("/v9/projects", {"limit": "20"})
    if not data:
        return []

    projects = []
    for p in data.get("projects", []):
        projects.append({
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "framework": p.get("framework") or "unknown",
        })
    return projects


def find_project_by_repo(repo_name: str) -> Optional[str]:
    """Find a Vercel project ID by matching its linked Git repository name."""
    if not is_configured():
        return None

    projects = list_projects()
    repo_lower = repo_name.lower()
    for p in projects:
        if p["name"].lower() == repo_lower:
            return p["id"]
    return None


def fetch_project_context(project_id_or_name: str) -> Optional[VercelProjectContext]:
    """
    Fetch Vercel project configuration including framework, build settings,
    domains, and environment variable names.
    """
    if not is_configured():
        print("Vercel integration skipped: VERCEL_TOKEN not set")
        return None

    data = _get(f"/v9/projects/{project_id_or_name}")
    if not data:
        return None

    ctx = VercelProjectContext()
    ctx.project_name = data.get("name", "")
    ctx.framework = data.get("framework") or ""
    ctx.node_version = data.get("nodeVersion") or ""
    ctx.build_command = data.get("buildCommand") or ""
    ctx.output_directory = data.get("outputDirectory") or ""
    ctx.root_directory = data.get("rootDirectory") or ""

    # Domains
    for alias in data.get("alias", []):
        if isinstance(alias, dict):
            ctx.domains.append(alias.get("domain", ""))
        elif isinstance(alias, str):
            ctx.domains.append(alias)

    # Also check targets for production domain
    targets = data.get("targets", {})
    if isinstance(targets, dict):
        prod = targets.get("production", {})
        if isinstance(prod, dict) and prod.get("alias"):
            for a in prod["alias"]:
                if a not in ctx.domains:
                    ctx.domains.append(a)

    # Environment variables (names only - never expose values)
    env_data = _get(f"/v9/projects/{project_id_or_name}/env")
    if env_data:
        for ev in env_data.get("envs", []):
            key = ev.get("key", "")
            target = ev.get("target", [])
            if key:
                targets_str = ",".join(target) if isinstance(target, list) else str(target)
                ctx.env_vars.append(f"{key} [{targets_str}]")

    # Latest deployment status
    deployments = _get(f"/v6/deployments", {"projectId": data.get("id", ""), "limit": "1"})
    if deployments and deployments.get("deployments"):
        latest = deployments["deployments"][0]
        ctx.latest_deployment_status = latest.get("readyState", latest.get("state", ""))
        ctx.latest_deployment_url = f"https://{latest.get('url', '')}" if latest.get("url") else ""

    return ctx


def fetch_failed_deployment_logs(project_id_or_name: str) -> Optional[VercelDeploymentError]:
    """
    Fetch build logs from the most recent failed deployment.
    Useful for debugging build errors in the executor's self-healing loop.
    """
    if not is_configured():
        return None

    # Get recent deployments
    project_data = _get(f"/v9/projects/{project_id_or_name}")
    if not project_data:
        return None

    project_id = project_data.get("id", "")
    deployments = _get(f"/v6/deployments", {
        "projectId": project_id,
        "limit": "5",
        "state": "ERROR",
    })

    if not deployments or not deployments.get("deployments"):
        return None

    latest_failed = deployments["deployments"][0]
    deployment_uid = latest_failed.get("uid", "")

    error = VercelDeploymentError()
    error.deployment_url = f"https://{latest_failed.get('url', '')}" if latest_failed.get("url") else ""
    error.status = latest_failed.get("readyState", latest_failed.get("state", "ERROR"))
    error.created_at = str(latest_failed.get("createdAt", ""))

    # Fetch build logs
    if deployment_uid:
        # Build logs via events endpoint
        events = _get(f"/v2/deployments/{deployment_uid}/events")
        if events:
            log_lines = []
            for event in events if isinstance(events, list) else []:
                payload = event.get("payload", {})
                text = payload.get("text", "")
                if text:
                    log_lines.append(text)
            error.build_logs = "\n".join(log_lines)

    # Also check deployment detail for error message
    detail = _get(f"/v13/deployments/{deployment_uid}")
    if detail:
        error.error_message = detail.get("errorMessage") or ""

    return error


# Patterns to detect Vercel-related tasks
VERCEL_KEYWORDS = [
    "vercel", "deploy", "deployment", "build error", "build fail",
    "serverless function", "edge function", "next.js deploy",
]

VERCEL_URL_PATTERN = re.compile(
    r"https?://(?:[\w-]+\.)?vercel\.app"
    r"|https?://vercel\.com/[\w-]+/[\w-]+/deployments"
)


def _is_vercel_task(text: str) -> bool:
    """Detect if a task involves Vercel deployment or build issues."""
    text_lower = (text or "").lower()
    if VERCEL_URL_PATTERN.search(text or ""):
        return True
    return any(kw in text_lower for kw in VERCEL_KEYWORDS)


def get_vercel_context_for_issue(
    description: str,
    summary: str = "",
    repo_name: str = "",
) -> str:
    """
    Fetch Vercel project context if the issue involves deployment or build topics.

    Auto-detects Vercel-related tasks by scanning for keywords like
    "deploy", "build error", "vercel", etc. Also tries to match the
    repo name to a Vercel project.

    Returns formatted context string for LLM prompt injection,
    or empty string if not relevant or API unavailable.
    """
    if not is_configured():
        return ""

    combined = f"{summary} {description}"

    # Only fetch context if task is Vercel-related or we can match the repo
    is_vercel = _is_vercel_task(combined)
    project_id = None

    if repo_name:
        project_id = find_project_by_repo(repo_name)

    if not is_vercel and not project_id:
        return ""

    contexts = []

    # Fetch project config if we can identify the project
    if project_id:
        project_ctx = fetch_project_context(project_id)
        if project_ctx:
            contexts.append(project_ctx.to_prompt_context())

            # If the issue mentions build errors, also fetch failed deployment logs
            if any(kw in combined.lower() for kw in ["build error", "build fail", "deployment fail"]):
                error_ctx = fetch_failed_deployment_logs(project_id)
                if error_ctx:
                    contexts.append(error_ctx.to_prompt_context())
    elif repo_name:
        # Try by name directly
        project_ctx = fetch_project_context(repo_name)
        if project_ctx:
            contexts.append(project_ctx.to_prompt_context())

    if not contexts:
        return ""

    return (
        "\n\n---\n\n"
        "**Vercel Deployment Context:**\n\n"
        + "\n\n".join(contexts)
        + "\n\n**IMPORTANT:** Ensure your implementation is compatible with Vercel's "
        "deployment model (serverless functions, edge runtime, static assets). "
        "Reference the environment variables listed above using `process.env.VAR_NAME`.\n"
    )
