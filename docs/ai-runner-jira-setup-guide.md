# AI Runner – Jira Setup and Workflow Guide

*This guide walks through setting up a Jira board for use with the AI Runner and the step-by-step workflow from creating an Epic to having the AI implement sub-tasks.*

---

## 1. Create the Jira Project / Board

1. In Jira, create a new project or use an existing one.
2. Ensure the project uses a board (Kanban or Scrum) that supports your workflow.

---

## 2. Add Required Statuses

Create these statuses in your Jira workflow. **Names must match exactly** (or update `.env` / config to match your names):

| Status Name | Purpose |
|-------------|---------|
| **Backlog** | Epics awaiting planning; Stories/sub-tasks awaiting work |
| **Plan Review** | Epic plan ready for human review |
| **Selected for Development** | Epic/Story approved; AI creates Stories or sub-tasks |
| **In Progress** | Work in progress |
| **In Testing** | Ready for QA / human review |
| **Blocked** | Waiting on clarification or external dependency |
| **Done** | Completed |

### Required Transitions

Ensure these transitions exist in your workflow:

- **Backlog** → Plan Review
- **Plan Review** → Selected for Development (for approval)
- **Plan Review** → Backlog (if plan needs changes)
- **Selected for Development** → In Progress
- **In Progress** → In Testing
- **In Progress** → Blocked
- **In Testing** → Done
- **In Testing** → In Progress (if changes required)
- **Blocked** → In Progress

---

## 3. Configure Issue Types

- **Epic**: Parent issue that the AI plans and breaks down into Stories.
- **Story**: Child of Epic; owns one PR and contains sub-tasks.
- **Sub-task**: Implementation units under a Story.

---

## 4. Create the AI Runner User

1. Create a Jira user for the AI Runner (e.g. "AI Runner" or "AR").
2. Obtain the **Account ID** (Settings → Users → select user → copy Account ID).
3. Add to your `.env`:

```
JIRA_AI_ACCOUNT_ID=<account-id-of-ai-runner-user>
JIRA_HUMAN_ACCOUNT_ID=<account-id-of-human-reviewer>
```

---

## 5. Configure Jira Automation (Webhooks)

The AI Runner is triggered by Jira webhooks. Configure Jira Automation rules to call your webhook when work is assigned to the AI Runner.

### Webhook Details

- **URL**: `https://your-ai-runner-domain/webhook/jira`
- **Method**: POST
- **Headers**:
  - `X-Moveware-Webhook-Secret`: `<JIRA_WEBHOOK_SECRET from your .env>`
  - `Content-Type`: application/json

### Recommended Rules

| Rule | Trigger | Action |
|------|---------|--------|
| **Planning** | Issue assigned to AI Runner, Issue type ≠ Sub-task | Send webhook |
| **Story creation** | Epic transitioned to "Selected for Development" or "In Progress" | Send webhook |
| **Sub-task execution** | Sub-task assigned to AI Runner, status "In Progress" | Send webhook |
| **Blocked retry** | Sub-task in Blocked assigned to AI Runner (after human answers questions) | Send webhook (see Rule 2c) |

See `docs/jira-automation-rules.md` for detailed rule definitions and payloads.

---

## 6. End-to-End Workflow

### Step 1: Create an Epic

1. Create a new Epic in your project.
2. Set **Summary** and **Description** with clear requirements.
3. Leave status as **Backlog**.

### Step 2: Assign Epic to AI Runner (Planning)

1. Assign the Epic to **AI Runner**.
2. The webhook fires; the AI Runner generates an implementation plan.
3. AI adds the plan as a Jira comment and moves the Epic to **Plan Review**.
4. Epic is assigned to the human reviewer.

### Step 3: Review and Revise the Plan (Optional)

1. Review the plan in the Epic comments.
2. To request changes:
   - Add a comment with your feedback.
   - Assign the Epic back to **AI Runner**.
   - AI revises the plan based on your feedback.

### Step 4: Approve the Plan → Create Stories

1. Move the Epic to **Selected for Development**.
2. Assign the Epic to **AI Runner**.
3. The webhook fires; the AI Runner creates **Stories** from the plan.
4. Epic is moved to **In Progress** and linked to the new Stories.

> **Note:** If you move the Epic directly to **In Progress** instead of **Selected for Development**, the AI Runner will also create Stories (fallback behavior).

### Step 5: Kick Off Each Story

For each Story:

1. Move the Story to **Selected for Development**.
2. Assign the Story to **AI Runner**.
3. AI creates sub-tasks, a Story branch, and a draft PR.
4. Story moves to **In Progress** and sub-tasks are created.

### Step 6: Execute Sub-tasks

1. Move a sub-task to **In Progress**.
2. Assign the sub-task to **AI Runner**.
3. AI implements the work, commits to the Story branch, and pushes.
4. Sub-task moves to **In Testing**; next sub-task may start.

#### When the AI Needs Clarification

If the requirements or schema are unclear, the AI may post questions instead of implementing. When that happens:

1. The AI adds a comment to the sub-task with the blocking questions.
2. The sub-task is assigned to you and moved to **Blocked**.
3. Add a comment to the sub-task with your answers.
4. Assign the sub-task to **AI Runner** again.

The existing Jira rule (sub-task assigned to AI Runner) will fire. The AI Runner will process the sub-task even while it's in Blocked, move it to In Progress, and use your answers in the context.

### Step 7: Review and Complete

1. Review the PR on GitHub.
2. If changes are needed: add a comment on the sub-task, assign to AI Runner, and AI iterates.
3. When done, move the sub-task to **Done**.
4. When all sub-tasks are Done, the Story moves to **In Testing**.
5. When all Stories are Done, the Epic moves to **Done**.

---

## 7. Quick Reference: Status → AI Action

| Issue Type | Status | Assignee | AI Action |
|------------|--------|----------|-----------|
| Epic | Backlog | AI Runner | Generate plan → move to Plan Review |
| Epic | Plan Review | AI Runner | Revise plan based on comments |
| Epic | Selected for Development | AI Runner | Create Stories from plan |
| Epic | In Progress | AI Runner | Create Stories (fallback if not yet created) |
| Story | Selected for Development | AI Runner | Create sub-tasks, branch, draft PR |
| Sub-task | In Progress | AI Runner | Implement, commit, push to Story branch |
| Sub-task | Blocked | AI Runner | Retry with human answers (move to In Progress, execute) |

---

## 8. Troubleshooting

| Problem | Solution |
|---------|----------|
| No plan generated | Ensure Epic is in **Backlog**, assigned to AI Runner, and webhook fired. Check worker logs. |
| Stories not created | Move Epic to **Selected for Development** (or **In Progress**), assign to AI Runner. Trigger webhook (e.g. reassign or edit Epic). |
| Sub-tasks not created | Move Story to **Selected for Development**, assign to AI Runner. |
| AI doesn't execute sub-task | Move sub-task to **In Progress**, assign to AI Runner. |
| Story in Selected for Dev but nothing happens | **1. Assign before transitioning:** The Story must be assigned to AI Runner *when* it enters Selected for Development. Assign it to AI Runner first, then move to Selected for Dev. **2. Status/assignee must match config:** Worker checks `JIRA_STATUS_SELECTED_FOR_DEV` (exact match) and `JIRA_AI_ACCOUNT_ID`. Check worker logs for `[NOOP]` – they now show why no action was taken. **3. Manual trigger:** `curl -X POST https://your-runner/webhook/jira -H "Content-Type: application/json" -H "X-Moveware-Webhook-Secret: YOUR_SECRET" -d '{"issue_key":"TB-2"}'` |
| **Worker not picking up runs** | Webhooks return 200 OK but worker never claims runs. **1. Check queue:** `GET /api/queue/stats` shows `total_queued`, `stale_runs`. **2. Stale runs:** Runs stuck in `claimed`/`running` (from crashes) can block the repo. Reset them: `POST /api/queue/reset-stale` with header `X-Admin-Secret: <ADMIN_SECRET>`. **3. DB path:** Ensure orchestrator and worker use the same `DB_PATH` (same `EnvironmentFile` in systemd). |
| **AI Console shows completed but Jira still In Progress** | Edge case – transitions usually work. **1. Manually move** the issue to In Testing (code is committed). **2. Check worker logs** for `Warning: No transition to '...'` if it recurs. **3. Reset stale** if another run is blocked. |
| **Run does not fire** | **1. Did webhook create a run?** `curl .../api/debug/recent-runs?issue_key=TB-2` – check if a run was created when you moved the issue. No new run = Jira rule didn't fire or request didn't reach the server. **2. Orchestrator logs:** `journalctl -u moveware-ai-orchestrator -f` – look for `POST /webhook/jira` and `[webhook] TB-2 -> run_id=X` when you transition. **3. Stuck queue:** Run `POST /api/queue/reset-stale` – an orphaned run (e.g. after worker restart) can block. **4. Jira rule:** The rule must **assign to AI Runner first**, then send webhook. See `docs/jira-automation-rules.md` Rule 2b. **5. Manual trigger:** `POST /api/trigger` with `{"issue_key":"TB-2"}` to force a run. |
| **Implementation blocked by questions** | The AI Runner posts questions when it cannot implement (e.g. schema mismatch). **1. Check the sub-task comment** – the AI adds a comment listing the questions. **2. Add your answers** as a reply comment. **3. Assign the sub-task to AI Runner** (it stays in Blocked). **4. Jira rule:** If your sub-task rule uses "transitioned To" (not "Issue assigned"), you need Rule 2c – "Blocked sub-task assigned to AI Runner" – or the webhook won't fire. See `docs/jira-automation-rules.md`. |

---

## 9. Related Documentation

- `docs/jira-automation-rules.md` – Webhook and automation setup
- `docs/jira-workflow-definitions.md` – Status and transition reference
- `docs/story-workflow.md` – Story-based workflow details
- `docs/webhook-payloads.md` – Jira Automation payload examples
