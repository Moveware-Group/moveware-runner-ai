# Security, Tokens, and Accounts

This workflow uses standard service-account patterns for Jira and GitHub.

## Jira (Cloud)

### Authentication
- Use a dedicated Jira service user (AI Runner)
- Create a Jira personal API token for that user
- Store token only on the server (env file)

Required permissions:
- Browse projects
- Create sub-tasks
- Transition issues
- Assign issues
- Comment on issues

### Webhook secret
- We use a shared secret in a custom header:
  - `X-Moveware-Webhook-Secret: <secret>`
- The Orchestrator validates it against `JIRA_WEBHOOK_SECRET`

## GitHub

### Pilot approach
- Use `gh auth login` under the `moveware-ai` Linux user
- Export `GH_TOKEN` in `/etc/moveware-ai.env`

Minimum permissions:
- Repo read/write
- PR create
- (Optional) workflow if triggering Actions

### Production approach (recommended)
- Replace PAT with a GitHub App
- Repo-scoped permissions
- Short-lived tokens
- Better audit and rotation

## Where secrets live

- `/etc/moveware-ai.env`
  - owned by `moveware-ai`
  - permissions: `600`

Never store secrets in:
- repo files
- Jira comments
- Jira automation bodies
- shell history
