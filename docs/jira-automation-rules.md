# Jira Automation Rules (Moveware AI Runner)

This document defines the Jira Automation rules required to run the AI-assisted development workflow, using Jira as the only UI.

## Overview

We use Jira Automation to:
- Trigger the AI Orchestrator when work is assigned to AI Runner
- Pass Jira issue context to the Orchestrator via webhook
- Keep the process auditable and consistent

The AI Orchestrator performs:
- Planning for parent tickets
- Execution for sub-tasks
- Jira transitions, assignment changes, and comments
- Git branch, commit, push, PR creation (via `gh` CLI)

---

## Shared Configuration

### Webhook URL
Set this to your Orchestrator endpoint:

`https://moveware-ai-runner.holdingsite.com.au/webhook/jira`

(Adjust path if your app uses a different endpoint.)

### Required Header (Webhook Secret)
In every "Send web request" action, set this header:

- Header: `X-Moveware-Webhook-Secret`
- Value: `<YOUR_SECRET>`

This must match the server env var `JIRA_WEBHOOK_SECRET`.

### Content type
- `Content-Type: application/json`

### Actor / Permissions
Your Jira API user (AI Runner service account) must be able to:
- Read issues
- Create sub-tasks
- Add comments
- Transition issues
- Assign issues

---

## Rule 1: Parent ticket assigned to AI Runner (Planning trigger)

### Purpose
When a parent ticket is assigned to AI Runner, trigger the Planning workflow.

### Rule type
- **Rule trigger:** Issue assigned

### Trigger conditions
- Assignee changes to: `AI Runner`
- Issue type is NOT: `Sub-task`

### Optional conditions (recommended)
- Status is: `Backlog` or `In Progress`
- Label does not contain: `ai:ignore`

### Actions
1) **Send web request**
- URL: `https://moveware-ai-runner.holdingsite.com.au/webhook/jira`
- Method: `POST`
- Headers:
  - `X-Moveware-Webhook-Secret: <YOUR_SECRET>`
  - `Content-Type: application/json`
- Body: use the payload in `/docs/webhook-payloads.md#automation-payload-parent-assigned`

2) (Optional) Add comment to issue:
- “AI Runner has been triggered for planning.”

---

## Rule 2: Sub-task assigned to AI Runner (Execution trigger)

### Purpose
When a sub-task is assigned to AI Runner, trigger execution.

### Rule type
- **Rule trigger:** Issue assigned

### Trigger conditions
- Assignee changes to: `AI Runner`
- Issue type IS: `Sub-task`

### Recommended condition
- Parent status is: `In Progress`
(Prevents execution before plan approval.)

### Actions
1) **Send web request**
- URL: `https://moveware-ai-runner.holdingsite.com.au/webhook/jira`
- Method: `POST`
- Headers:
  - `X-Moveware-Webhook-Secret: <YOUR_SECRET>`
  - `Content-Type: application/json`
- Body: use the payload in `/docs/webhook-payloads.md#automation-payload-subtask-assigned`

---

## Rule 3: Plan approval transition (Plan Review → In Progress)

### Purpose
Plan approval is a Jira transition. We notify the Orchestrator so it can create sub-tasks if needed, and resume execution.

### Rule type
- **Rule trigger:** Issue transitioned

### Trigger conditions
- From: `Plan Review`
- To: `In Progress`
- Issue type is NOT: `Sub-task`

### Actions
1) **Send web request**
- URL: `https://moveware-ai-runner.holdingsite.com.au/webhook/jira`
- Method: `POST`
- Headers:
  - `X-Moveware-Webhook-Secret: <YOUR_SECRET>`
  - `Content-Type: application/json`
- Body: use the payload in `/docs/webhook-payloads.md#automation-payload-plan-approved`

---

## Rule 4: Human requests clarification (optional)

### Purpose
If a human changes status to Blocked, we can notify the Orchestrator that the ticket is waiting for clarification, so it pauses cleanly.

### Rule type
- **Rule trigger:** Issue transitioned

### Trigger conditions
- To: `Blocked`

### Actions
1) Send web request (optional)
- Body: use `/docs/webhook-payloads.md#automation-payload-blocked`

---

## Rule 5: PR feedback loop (recommended)

### Purpose
If PR feedback is given, we want a consistent way to loop the sub-task back to AI Runner.

Because PR comments live in GitHub, the simplest pilot approach is:
- Human adds feedback comment on the Jira sub-task
- Human assigns sub-task to AI Runner
- Rule 2 triggers execution again

If you want automated GitHub-to-Jira mirroring later, we can add a GitHub webhook receiver.

### Rule type
No separate rule required, the standard flow is:
- Comment on sub-task
- Assign to AI Runner
- Rule 2 fires

---

## Rule 6: Auto-complete parent when all sub-tasks are Done (optional)

### Purpose
Let the Orchestrator manage this. No Jira Automation required.

If you want Jira Automation instead:
- Trigger: Sub-task transitioned to Done
- Branch rule: Check parent has no remaining open sub-tasks
- Action: Transition parent to Done

This is optional, the Orchestrator can do it more reliably.

---

## Quick Test Checklist (Jira Automation)

1) Assign a parent ticket to AI Runner
- Expected: webhook fires, plan posted, parent moved to Plan Review, assigned to Leigh

2) Transition parent Plan Review → In Progress
- Expected: webhook fires, sub-tasks created (if not already), first sub-task assigned to AI Runner

3) Assign a sub-task to AI Runner
- Expected: webhook fires, branch/commit/PR created, sub-task moved to In Testing, assigned back to Leigh

4) Reject PR
- Add feedback comment to sub-task and assign to AI Runner
- Expected: agent iterates and updates PR

5) Approve PR
- Expected: sub-task moved to Done, parent moved to Done once all sub-tasks complete
