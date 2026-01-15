# Moveware AI Runner (Jira-driven)

Production-oriented reference implementation of a **Jira → Orchestrator → Worker → GitHub Branch/PR → Jira status/comment** workflow.

This repo is designed so the pilot can be run "like production": least-privilege system user, systemd services, idempotent run processing, auditable events, and clear separation between orchestration and execution.

## High-level flow

1. **Jira ticket is assigned to the AI Runner** (a dedicated Jira user).
2. **Jira Automation sends a webhook** to the Orchestrator.
3. Orchestrator persists a **Run** in SQLite and returns `200 OK`.
4. Worker claims the Run, loads the Jira issue (summary, description, comments, status), then:
   - Checks governance (approval gate, required fields)
   - Creates/updates a **branch per issue**
   - Applies LLM-generated patch(es)
   - Runs lightweight validation/tests
   - **Commits with the Jira key** and pushes
   - Creates/updates a PR
   - Transitions Jira to **In Testing**, assigns to **Leigh Morrow**, and adds a summary comment
5. Leigh reviews the PR:
   - If changes needed, Leigh comments on the Jira ticket and assigns back to the AI Runner, which triggers a new Run.
   - If approved/merged, a GitHub webhook (optional) can transition Jira to **Done**.

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

