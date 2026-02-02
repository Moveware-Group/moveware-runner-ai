# Story-Based Workflow

## Overview

The AI Runner now follows a **Story owns the PR** model where:

- **Epics** create Stories (no PRs for Epics)
- **Stories** own exactly one PR
- **Sub-tasks** commit to the Story branch (no individual PRs unless marked as independent)

## Issue Hierarchy

```
Epic (OD-1: "Create Online Documents platform")
  └─ Story (OD-4: "Quote submission flow")  
      ├─ Sub-task (OD-5: "Add form validation")
      ├─ Sub-task (OD-6: "Create API endpoint")  
      └─ Sub-task (OD-7: "Add database schema")
      
      → 1 Branch: story/od-4-quote-submission-flow
      → 1 PR (contains all 3 sub-task commits)
```

## Workflow Steps

### 1. Epic Planning

**Trigger:** Epic assigned to AI Runner in Backlog

**AI Actions:**
- Generates implementation plan with Stories (not sub-tasks)
- Each Story includes its own sub-task breakdown
- Posts plan as comment
- Moves Epic to "Plan Review"
- Assigns to human reviewer

**Plan Format (v2):**
```json
{
  "plan_version": "v2",
  "overview": "Build Online Documents platform",
  "stories": [
    {
      "summary": "Quote submission flow",
      "description": "User-facing feature for submitting quotes",
      "subtasks": [
        {
          "summary": "Add form validation",
          "description": "Client-side validation for quote form",
          "independent": false
        },
        {
          "summary": "Create API endpoint",
          "description": "POST /api/quotes endpoint",
          "independent": false
        }
      ]
    }
  ]
}
```

### 2. Epic Approval

**Trigger:** Epic moved from "Plan Review" → "Selected for Development"

**AI Actions:**
- Creates Stories from approved plan
- Links Stories to Epic
- Assigns Stories to AI Runner in Backlog
- Adds sub-task breakdown as comment on each Story
- Moves Epic to "In Progress"

### 3. Story Kickoff

**Trigger:** Story moved to "Selected for Development" and assigned to AI Runner

**AI Actions:**
- Creates Story branch: `story/OD-4-quote-submission-flow`
- Creates **draft PR** for the Story with sub-task checklist
- Creates sub-tasks under the Story
- Assigns sub-tasks to AI Runner in Backlog
- Moves Story to "In Progress"
- Starts first sub-task

**Story PR Example:**
```markdown
## Story: OD-4

Build quote submission flow with validation and API integration.

### Sub-tasks:
- [ ] OD-5: Add form validation
- [ ] OD-6: Create API endpoint
- [ ] OD-7: Add database schema

---
*This PR will be updated as sub-tasks are completed.*
```

### 4. Sub-task Execution

**Trigger:** Sub-task moved to "In Progress" and assigned to AI Runner

**AI Behavior:**

#### Regular Sub-task (Default):
- Uses **Story branch** (story/OD-4)
- Commits with message: `OD-5: add form validation`
- Pushes to Story branch (updates Story PR)
- Moves sub-task to "In Testing"
- Starts next sub-task

#### Independent Sub-task (Exception):
If sub-task has label `independent-pr`:
- Creates own branch: `ai/OD-5`
- Commits and pushes
- Creates **separate PR**
- Use cases: infrastructure, build config, hotfixes

### 5. Story Completion

**Trigger:** All sub-tasks under Story are "Done"

**AI Actions:**
- Comments on Story: "✅ All sub-tasks completed! Story PR is ready for review."
- Marks Story PR as "Ready for Review" (TODO: GitHub API integration)
- Moves Story to "In Testing"
- Assigns to human reviewer

### 6. Epic Completion

**Trigger:** All Stories under Epic are "Done"

**AI Actions:**
- Moves Epic to "Done"
- Comments: "All Stories complete."

## Commit Message Format

Sub-tasks use this format:
```
OD-5: add form validation
OD-6: create API endpoint  
OD-7: add database schema
```

Each commit references the sub-task key for traceability.

## Branch Naming

- **Epic:** No branch (Epics don't have code)
- **Story:** `story/od-4-quote-submission-flow`
- **Independent sub-task:** `ai/od-5-infrastructure-update`

## When to Use Independent PRs

Mark a sub-task with label `independent-pr` if it's:

✅ **Good candidates:**
- Infrastructure changes (CI/CD, Docker, etc.)
- Build configuration
- Package updates
- Database migrations (if risky)
- Hotfixes
- Changes that affect multiple Stories

❌ **Not recommended:**
- Feature code that's part of the Story
- UI components
- API endpoints
- Tests for Story features

## Jira Configuration

### Issue Types Required:
- **Epic** - High-level features
- **Story** - User-facing feature slices  
- **Sub-task** - Technical implementation tasks

### Status Flow:
```
Backlog → Plan Review → Selected for Development → In Progress → In Testing → Done
                                    ↓
                                Blocked (if issues)
```

### Labels:
- `independent-pr` - Sub-task should have its own PR

## GitHub PR Strategy

| Issue Type | Branch | PR | When |
|------------|--------|-----|------|
| Epic | None | None | N/A |
| Story | `story/KEY` | 1 PR | Story kickoff |
| Sub-task | Story branch | Reuses Story PR | Default |
| Sub-task (independent) | `ai/KEY` | Own PR | Exception |

## Benefits

✅ **Smaller, focused reviews** - Each Story PR is a cohesive feature
✅ **Clear traceability** - Commit messages link to sub-tasks
✅ **Incremental progress** - Stories can be merged independently  
✅ **Better testing** - Each Story is independently testable
✅ **Easier rollback** - Revert entire Story or individual independent changes
✅ **Reduced PR noise** - No PR per sub-task unless truly independent

## Migration from Old Workflow

Old workflow (v1 plan): Epic creates sub-tasks directly, 1 PR per sub-task

New workflow (v2 plan): Epic → Stories → Sub-tasks, 1 PR per Story

Both are supported! The system detects plan version:
- **v1 plans** (subtasks array) → Create sub-tasks directly (old behavior)
- **v2 plans** (stories array) → Create Stories first (new behavior)

To migrate existing Epics:
1. Update plan comment to v2 format with Stories
2. Move Epic back to "Selected for Development"
3. AI will create Stories from new plan
