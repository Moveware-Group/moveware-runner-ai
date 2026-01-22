# Webhook Payloads (Jira Automation → AI Orchestrator)

This document contains copy-paste request bodies for Jira Automation “Send web request” actions.

All requests must include headers:
- `Content-Type: application/json`
- `X-Moveware-Webhook-Secret: <YOUR_SECRET>`

---

## Base notes

We keep payloads intentionally small and stable.
The Orchestrator will fetch full issue details using Jira REST API.

Variables below use Jira Automation smart values.

---

## Automation payload: Parent assigned

Use in Rule 1.

```json
{
  "event_type": "issue_assigned",
  "issue_key": "{{issue.key}}",
  "issue_id": "{{issue.id}}",
  "issue_type": "{{issue.issueType.name}}",
  "project_key": "{{issue.project.key}}",
  "assignee": "{{issue.assignee.displayName}}",
  "assignee_account_id": "{{issue.assignee.accountId}}",
  "status": "{{issue.status.name}}",
  "summary": "{{issue.summary}}",
  "parent_key": ""
}

## Automation payload: Sub-task assigned

Use in Rule 2.

```json
{
  "event_type": "issue_assigned",
  "issue_key": "{{issue.key}}",
  "issue_id": "{{issue.id}}",
  "issue_type": "{{issue.issueType.name}}",
  "project_key": "{{issue.project.key}}",
  "assignee": "{{issue.assignee.displayName}}",
  "assignee_account_id": "{{issue.assignee.accountId}}",
  "status": "{{issue.status.name}}",
  "summary": "{{issue.summary}}",
  "parent_key": "{{issue.parent.key}}"
}

## Automation payload: Plan approved (Plan Review -> In Progress)

Use in Rule 3.
{
  "event_type": "plan_approved",
  "issue_key": "{{issue.key}}",
  "issue_id": "{{issue.id}}",
  "issue_type": "{{issue.issueType.name}}",
  "project_key": "{{issue.project.key}}",
  "from_status": "{{changelog.status.fromString}}",
  "to_status": "{{changelog.status.toString}}",
  "actor": "{{initiator.displayName}}"
}

## Automation payload: Blocked (optional)

Use in Rule 4.

{
  "event_type": "blocked",
  "issue_key": "{{issue.key}}",
  "issue_id": "{{issue.id}}",
  "issue_type": "{{issue.issueType.name}}",
  "project_key": "{{issue.project.key}}",
  "status": "{{issue.status.name}}",
  "actor": "{{initiator.displayName}}"
}

The Orchestrator can infer everything else via Jira API lookups.