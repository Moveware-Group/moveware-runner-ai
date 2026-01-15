# Moveware AI Runner, Jira-driven delivery model (Pilot)

## Purpose
This pilot introduces a controlled, auditable workflow where Jira remains the **system of record** and an AI Runner performs development tasks in a repeatable way, producing GitHub branches and pull requests for human review.

Key outcomes:
- Faster delivery while maintaining governance.
- Clear human accountability (who approved, who reviewed, who merged).
- Reduced manual admin work (status moves, assignment, summaries).

---

## End-to-end workflow (as implemented)

### 1) Ticket creation and assignment
1. Ticket is created in Jira.
2. When the ticket is **ready for AI work**, it is assigned to the **AI Runner user**.
3. A Jira Automation rule sends a webhook event to the AI Runner Orchestrator.

### 2) Orchestrator receives the webhook
- Orchestrator validates the webhook secret header.
- Orchestrator stores a **Run** record (immutable audit) and immediately returns `200 OK`.

This ensures Jira Automation is never blocked by long-running builds.

### 3) Worker claims the Run and performs work
The Worker:
1. Fetches Jira issue details (summary, description, current status, comments).
2. Loads the configured target repo (pilot: `online-docs`).
3. Creates or updates a deterministic branch (e.g. `ai/MWC-123`).
4. Generates a change plan and patch using the configured LLM provider.
5. Applies the patch, runs validation, and commits.
6. Pushes to GitHub and creates/updates a Pull Request.
7. Updates Jira:
   - Adds a comment summarising the work and linking to the branch/PR
   - Transitions status to **In Testing**
   - Assigns the ticket to **Leigh Morrow**

### 4) Human review loop
- Leigh reviews the PR.
- If changes are required:
  - Leigh adds a Jira comment describing required adjustments.
  - Leigh reassigns the ticket back to the AI Runner user.
  - Jira Automation triggers a new webhook, and the Worker iterates on the existing branch/PR.

### 5) Completion
Two supported patterns:

**Option A (recommended): Auto-Done on merge**
- When the PR is merged, a GitHub webhook calls the Orchestrator.
- Orchestrator transitions the Jira ticket to **Done**.

**Option B: Manual Done**
- Leigh transitions to Done after PR merge.

---

## Suggested improvements (before scale-out)

1. **Auto-Done on merge (GitHub webhook)**
   - Reduces human admin and ensures Jira reflects code reality.

2. **Branch protection + required checks**
   - Require CI to pass, and require at least one human approval.

3. **Idempotency and "single active run" per issue**
   - Prevents duplicate webhooks from creating parallel runs.

4. **Security hardening**
   - Rate limit webhook endpoints (Nginx `limit_req`).
   - Restrict inbound network access (only Jira IP ranges where practical).
   - Store secrets in Key Vault (post-pilot), not `.env`.

5. **Multi-repo routing (later)**
   - Use Jira labels/components/custom field to pick repo + base branch.

---

## External accounts and API keys required

### Jira Cloud
- `JIRA_BASE_URL` (e.g. `https://moveware.atlassian.net`)
- `JIRA_EMAIL` (account used to create API token)
- `JIRA_API_TOKEN`
- `JIRA_WEBHOOK_SECRET` (shared secret set in Jira Automation + validated in runner)
- Account IDs:
  - `JIRA_ASSIGNEE_AI_ACCOUNT_ID` (AI Runner user)
  - `JIRA_ASSIGNEE_LEIGH_ACCOUNT_ID` (Leigh)
- Jira transition IDs or names for:
  - **In Testing**
  - **Done**

> Note: The implementation supports transition by name and will discover the transition ID at runtime.

### GitHub
Pilot:
- A GitHub PAT for the bot identity (recommended: separate bot user)
- `gh` CLI installed
- `gh auth login` completed for the service user

Production:
- Prefer a **GitHub App** (fine-grained, revocable, per-repo).

### LLM
Choose one:
- Anthropic (Claude): `ANTHROPIC_API_KEY`
- OpenAI (GPT): `OPENAI_API_KEY`

---

## Deployment topology (pilot)

- **Nginx (TLS termination + rate limiting)**
  - Public internet
  - Forwards to `127.0.0.1:8088`

- **Orchestrator (FastAPI)**
  - Webhook endpoints

- **Worker (Python process)**
  - Polls DB for queued Runs
  - Executes git operations + LLM calls

- **SQLite**
  - Stores Runs + events

---

## Jira Automation rules to configure

### Rule 1: Assigned to AI Runner → webhook
Trigger: Issue updated (Assignee changed)
Condition: Assignee == AI Runner user
Action: Send web request
- URL: `https://<runner-domain>/jira/webhook`
- Method: `POST`
- Headers:
  - `X-Jira-Webhook-Secret: <your secret>`
- Body: include `issue.key` and minimal metadata

### Rule 2 (optional): PR merged → Done
Trigger: Incoming webhook from GitHub (PR merged)
Action: Transition issue to Done

In the pilot, we implement this as a GitHub webhook into the runner, not a Jira rule.

---

## GitHub configuration

- Branch naming: `ai/<JIRA_KEY>`
- Commit messages: `<JIRA_KEY>: <short summary>`
- Branch protection (recommended):
  - Require PR review
  - Require status checks
  - Disallow direct pushes to main

---

## Operational notes

- Worker is safe to restart, it uses DB locking + run states.
- Every run writes an event log for auditability.
- The system is designed to be extended to multiple specialist agents later.

