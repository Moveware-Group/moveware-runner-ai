# Moveware AI Runner (Jira-driven)

Production-oriented reference implementation of a **Jira → Orchestrator → Worker → GitHub Branch/PR → Jira status/comment** workflow.

This repo is designed so the pilot can be run "like production": least-privilege system user, systemd services, idempotent run processing, auditable events, and clear separation between orchestration and execution.

## High-level flow (Story-based workflow)

1. **Epic assigned to AI Runner** (Status: Backlog)
2. Worker generates an **Implementation Plan with Stories** (LLM), posts it as a comment, then moves the Epic to **Plan Review** and assigns to Leigh.
3. Leigh approves by transitioning **Plan Review → Selected for Development**.
4. Worker creates **Stories** from the plan, each Story has its own sub-task breakdown.
5. When a Story is moved to **Selected for Development**:
   - Worker creates Story branch (e.g., `story/OD-4-quote-submission`)
   - Creates **one PR** for the entire Story (draft)
   - Creates sub-tasks under the Story
   - Starts processing sub-tasks sequentially
6. For each sub-task (default behavior):
   - Commits to the **Story branch** with message: `OD-5: add form validation`
   - Pushes to Story branch (updates Story PR automatically)
   - Transitions sub-task to **In Testing**
   - Starts next sub-task
7. When all sub-tasks are Done:
   - Story PR marked as ready for review
   - Story transitioned to **In Testing** and assigned to Leigh
8. Leigh reviews the Story PR (contains all sub-task commits):
   - If changes needed: comment on specific sub-task and assign back to AI Runner
   - If approved: merge Story PR and mark Story as Done

**See [docs/story-workflow.md](docs/story-workflow.md) for detailed workflow documentation.**

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

