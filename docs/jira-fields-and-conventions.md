# Jira Fields and Conventions

This document defines conventions that keep the AI workflow consistent and predictable.

## Statuses

- Backlog
- Plan Review
- In Progress
- In Testing
- Done
- Blocked

Plan approval is:
- Transition: Plan Review → In Progress

## Ticket structure

### Parent ticket
- Holds the AI Implementation Plan (AIP)
- Single approval gate
- Owns final outcome

### Sub-tasks
- Execution units
- Can loop without invalidating the parent plan
- Each sub-task maps to one PR branch cycle

## Labels (optional but recommended)

Use labels to help routing, reporting, and safety.

### Routing
- `repo:<name>` for selecting target repo
- `area:web`, `area:api`, `area:mobile`
- `ai:ignore` to prevent automation

### Safety
- `ai:no-exec` to allow planning only
- `risk:high` to require manual QA

## Comments

### AI Implementation Plan format
AI should post plans as:
- `AI Implementation Plan v1`
- `AI Implementation Plan v2`

Each plan should include:
- Summary
- Proposed changes (files)
- Assumptions
- Risks
- Sub-task breakdown
- QA requirements and scope

### PR completion comment
When the AI creates a PR, it should comment:
- PR link
- Summary of changes
- Tests run and results
- Any risks or follow-ups