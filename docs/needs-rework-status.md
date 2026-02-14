# "Needs Rework" Status Implementation

## Overview

The AI Runner now uses a dedicated **"Needs Rework"** Jira status to handle tasks that require fixes, making the workflow clearer and more explicit.

## Status Flow

### For Sub-tasks

```
In Testing → (tester finds issues) → Needs Rework → (AI fixes) → In Progress → In Testing
```

### For Stories

```
In Testing → (tester finds issues) → Needs Rework → (AI marks all subtasks for rework) → In Progress
```

## How to Set Up in Jira

### 1. Create the Status

1. Go to **Jira Settings** (gear icon) → **Issues** → **Statuses**
2. Click **Add status**
3. Name: `Needs Rework`
4. Category: **In Progress** (or **To Do** if you prefer)

### 2. Add Workflow Transitions

Edit your project's workflow:

**From "In Testing":**
- Add transition → "Needs Rework"
- Transition name: "Request Changes"

**From "Needs Rework":**
- Add transition → "In Progress"
- Transition name: "Start Rework"

**Optional (but helpful):**
- From "Needs Rework" → "Done" (if issue was actually fine)

### 3. Publish Workflow

If you edited a draft, remember to **Publish** it!

## Configuration

The new status is configured in `app/config.py`:

```python
JIRA_STATUS_NEEDS_REWORK: str = env("JIRA_STATUS_NEEDS_REWORK", default="Needs Rework")
```

**No `.env` change needed** - it defaults to `"Needs Rework"` automatically.

## How It Works

### Rework Detection

The AI Runner detects rework scenarios in two ways:

1. **Preferred**: Task is in **"Needs Rework"** status + assigned to AI
2. **Legacy fallback**: Task moved from "In Testing" back to "Selected for Development" + assigned to AI

### Priority Boost

Rework tasks automatically get **HIGH priority** in the queue, so they're processed before new work.

### Feedback Integration

When a tester moves a task to "Needs Rework" and adds a comment:

1. AI Runner extracts the human comment
2. Adds it to the subtask description temporarily
3. Re-executes with explicit instructions to fix the issues
4. Posts a "Rework Complete" comment when done

## Benefits

✅ **Clear Intent**: "Needs Rework" explicitly signals that something needs fixing  
✅ **Better Tracking**: Easy to see which tasks are blocked on AI fixes  
✅ **Higher Priority**: Rework tasks jump the queue  
✅ **Better Audit Trail**: Separate status makes it easy to report on rework rates  
✅ **Less Confusion**: No ambiguity between "first-time approval" and "rework"

## Backward Compatibility

The AI Runner still supports the old workflow (moving tasks to "Selected for Development" for rework), so you can migrate gradually.

## Testing the Flow

### For Sub-tasks

1. Move a completed subtask from **"In Testing"** to **"Needs Rework"**
2. Assign it back to the **AI Runner account**
3. Add a comment explaining what's wrong
4. AI Runner should pick it up within ~30 seconds
5. Watch logs: `journalctl -u moveware-ai-worker -f`

### For Stories

1. Move a Story from **"In Testing"** to **"Needs Rework"**
2. Assign it back to the **AI Runner account**
3. Add a comment with overall feedback
4. AI Runner marks all non-blocked subtasks for rework
5. Each subtask is re-queued with HIGH priority

## Troubleshooting

**Issue**: Transitions missing  
**Fix**: Ensure you added the transitions in the Jira workflow editor and published

**Issue**: AI Runner doesn't pick up rework  
**Fix**: Verify task is assigned to AI Runner account (`JIRA_AI_ACCOUNT_ID`)

**Issue**: Rework tasks not prioritized  
**Fix**: Check `journalctl` logs - HIGH priority should be logged during enqueue

## Related Files

- `app/config.py` - Status configuration
- `app/router.py` - Routing logic for "Needs Rework"
- `app/worker.py` - Handlers: `_handle_rework_subtask`, `_handle_rework_story`
- `app/queue_manager.py` - Priority handling
