# Moveware AI Runner (Jira-driven)

Production-oriented reference implementation of a **Jira → Orchestrator → Worker → GitHub Branch/PR → Jira status/comment** workflow.

This repo is designed so the pilot can be run "like production": least-privilege system user, systemd services, idempotent run processing, auditable events, and clear separation between orchestration and execution.

## High-level flow (pilot: parent + sub-tasks)

1. **Parent ticket assigned to AI Runner** (Status: Backlog)
2. Worker generates an **Implementation Plan** (ChatGPT API / Codex), posts it as a comment, then moves the parent to **Plan Review** and assigns to Leigh.
3. Leigh approves by transitioning **Plan Review → In Progress**.
4. Worker creates **sub-tasks** from the plan, then processes them sequentially:
   - Moves a sub-task to **In Progress** (assigned to AI Runner)
   - Implements the change (Claude API), commits with the Jira key, pushes a branch, creates a PR
   - Transitions the sub-task to **In Testing**, assigns to Leigh, and comments with what was done + PR link
5. Leigh reviews the PR:
   - If changes needed: comment on the Jira sub-task and assign back to AI Runner
   - If approved: transition sub-task to Done
6. When all sub-tasks are Done, worker transitions the parent to Done.

## Accounts + keys required

- **Jira Cloud**
  - Jira base URL: `https://<your-domain>.atlassian.net`
  - Jira email (for the API token)
  - Jira API token
  - Jira Automation webhook secret (custom header value)
  - Jira accountId values for assignees (AI Runner, Leigh)

- **GitHub**
  - GitHub Personal Access Token (classic or fine-grained) for `gh` CLI authentication (pilot)
  - `gh` CLI installed on the runner and authenticated as the bot user

- **LLM provider** (choose one)
  - Anthropic API key (Claude Sonnet)
  - or OpenAI API key (GPT)

## Repo scope

For the pilot, configuration assumes a single repo:
- `https://github.com/leigh-moveware/online-docs.git`

You can expand to multiple repos later via config.

## Project layout

- `app/main.py` – FastAPI orchestrator (webhook receiver)
- `app/worker.py` – background worker loop (claims runs, performs work)
- `app/jira.py` – Jira REST client (issue fetch, comments, transitions, assignment)
- `app/git_ops.py` – git + `gh` helpers (clone, branch, commit, push, PR)
- `app/llm/*` – LLM adapters (Anthropic/OpenAI) and patch protocol
- `app/db.py` – SQLite storage + run/event tables
- `docs/confluence.md` – Confluence-ready documentation

## Quick start (local)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env

uvicorn app.main:app --reload --host 127.0.0.1 --port 8088
python -m app.worker
```

## Production notes

- Run behind Nginx with TLS (LetsEncrypt) and rate limiting.
- Validate Jira webhooks via a shared secret header.
- Use a dedicated Jira user for the AI Runner to keep auditability.
- Prefer a GitHub App in production; PAT is acceptable for pilot.

