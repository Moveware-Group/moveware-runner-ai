# Jira workflow definitions (pilot)

This is a direct translation of the latest flow diagram into Jira statuses, transitions, and recommended automations.

## Statuses
Create these statuses (exact names):

- **Backlog**
- **Plan Review**
- **In Progress**
- **In Testing**
- **Done**
- **Blocked**

## Issue hierarchy
- **Parent issue**: Feature/Epic/Task (represents one feature or one sprint unit)
- **Sub-tasks**: execution units created under the parent by the runner

## Transitions
Suggested transitions to keep the board clean:

### Backlog
- Backlog → Plan Review ("Send to plan")

### Plan Review
- Plan Review → In Progress ("Plan approved")
- Plan Review → Backlog ("Needs more detail")

### In Progress
- In Progress → In Testing ("Ready for testing")
- In Progress → Blocked ("Blocked")

### In Testing
- In Testing → Done ("Done")
- In Testing → In Progress ("Changes required")

### Blocked
- Blocked → In Progress ("Unblocked")
- Blocked → Done ("Cancelled")

## Assignment policy (recommended)
- Parent issue:
  - Backlog: usually assigned to **AI Runner** once ready for planning
  - Plan Review: assigned to **Leigh Morrow** (plan approval)
  - In Progress: assigned to **AI Runner** (or left as Leigh, but automation below expects AI Runner)
  - Done: leave as Leigh
- Sub-tasks:
  - In Progress: assigned to **AI Runner**
  - In Testing: assigned to **Leigh Morrow**
  - Done: leave as Leigh

## Automations (Jira Automation rules)

### Rule 1 , Kick off planning
**When**: Issue created OR status changes to Backlog

**Condition**:
- Issue is NOT a sub-task
- Assignee = AI Runner

**Action**:
- Send web request to runner webhook (or rely on the Jira webhook already configured)

### Rule 2 , Plan Review ownership
**When**: Status changes to Plan Review

**Action**:
- Assign issue to Leigh Morrow

### Rule 3 , After plan approval
**When**: Status changes Plan Review → In Progress

**Action**:
- Assign issue to AI Runner

### Rule 4 , Sub-task testing hand-off
**When**: Status changes to In Testing

**Action**:
- Assign issue to Leigh Morrow

### Rule 5 , Parent completion
**When**: Sub-task transitioned to Done

**Condition**:
- Parent exists
- All sub-tasks are Done

**Action**:
- Transition parent to Done

## Notes
- The runner also performs some of these assignment changes automatically via the Jira REST API. If you implement the automation rules, the system is more resilient (either side can do the right thing).
- If your Jira workflow uses different transition names, that is fine , the runner transitions by **target status name**.