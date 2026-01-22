# Implementation Notes (Pilot)

## Repo targeting

For pilot we may start with one repo, but the workflow supports multiple repos.

Recommended approach:
- Use a repo mapping file (or env variables) that maps:
  - repo key to clone URL
  - default base branch
  - working directory path
  - optional QA command

Jira routing options:
- Component
- Label prefix `repo:<name>`
- Custom field (later)

## Monorepo vs multi-repo

Pilot recommendation:
- Keep repos separate
- Add routing conventions (label/component)
- Revisit monorepo only if there is strong shared-code coupling

## Rate limiting and safety (future)

Jira webhook endpoint should be protected by:
- secret header check
- IP allowlist if possible
- Nginx rate limit (recommended)

GitHub operations should be safe by default:
- no auto-merge
- no force push
- PR required

## Observability

Minimum:
- systemd logs for orchestrator and worker
- structured logging in app

Optional:
- Better Uptime / Azure monitoring
- Nginx access logs
