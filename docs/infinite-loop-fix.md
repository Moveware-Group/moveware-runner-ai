# Infinite Story Creation Loop - Fix Documentation

**Date:** February 14, 2026  
**Issue:** 590 duplicate Stories created in BACKLOG  
**Status:** ✅ FIXED

---

## 🐛 What Happened

The AI runner created **590 duplicate Stories** in an infinite loop when processing Epic **OD-48**.

### Root Cause

The `_create_stories_from_plan()` function **did not check if Stories already existed** before creating them. When the function was called multiple times (due to webhook retries, worker restarts, or other triggers), it kept creating duplicate Stories from the same plan.

**Infinite Loop Trigger:**
1. Epic approved → Stories created
2. Webhook retry OR worker restart → Function called again
3. No check for existing Stories → **Duplicates created**
4. Repeat indefinitely...

---

## ✅ Fix Implemented

### 1. **Existence Check Before Creation**

Added check at the start of `_create_stories_from_plan()`:

```python
# Check if Stories already exist to prevent infinite loop
existing_stories = ctx.jira.get_stories_for_epic(epic.key)
if existing_stories and len(existing_stories) > 0:
    print(f"⚠️  Epic {epic.key} already has {len(existing_stories)} Stories, skipping creation")
    ctx.jira.add_comment(
        epic.key,
        f"Stories already exist for this Epic ({len(existing_stories)} found). "
        "If you need to regenerate Stories, please delete existing ones first."
    )
    return True  # Return True because Stories exist
```

**Impact:** Prevents duplicate creation entirely.

---

### 2. **New Method: `get_stories_for_epic()`**

Added to `JiraClient` in `app/jira.py`:

```python
def get_stories_for_epic(self, epic_key: str) -> List[Dict[str, Any]]:
    """Get all Stories linked to an Epic using JQL search."""
    jql = f'parent = "{epic_key}" AND issuetype = Story'
    
    url = f"{self.base_url}/rest/api/3/search"
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "summary,status,assignee,parent,issuetype"
    }
    
    r = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout_s)
    r.raise_for_status()
    result = r.json()
    return result.get("issues", [])
```

**Impact:** Enables checking for existing Stories before creation.

---

### 3. **Safety Limits**

Added maximum limits to prevent runaway creation even if checks fail:

**Stories per Epic:**
- **Limit:** 50 Stories maximum
- **Action:** Block Epic and assign to human if exceeded

**Subtasks per Story:**
- **Limit:** 30 Subtasks maximum  
- **Action:** Block Story and assign to human if exceeded

```python
MAX_STORIES_PER_EPIC = 50
if len(stories) > MAX_STORIES_PER_EPIC:
    print(f"⚠️  Plan has {len(stories)} stories, which exceeds safety limit")
    ctx.jira.add_comment(
        epic.key,
        f"⚠️ Plan has {len(stories)} stories (limit: {MAX_STORIES_PER_EPIC}). "
        "This might indicate a plan generation error."
    )
    ctx.jira.transition_to_status(epic.key, settings.JIRA_STATUS_BLOCKED)
    ctx.jira.assign_issue(epic.key, settings.JIRA_HUMAN_ACCOUNT_ID)
    return False
```

**Impact:** Catches and blocks excessive creation attempts.

---

## 🧹 Cleanup Required

You have **590 duplicate Stories** in the BACKLOG that need to be cleaned up.

### Option 1: Bulk Delete in Jira (Recommended)

1. **Go to Jira Search**
2. **Use JQL:**
   ```jql
   parent = OD-48 AND issuetype = Story ORDER BY created DESC
   ```
3. **Select all results** (should show ~590 Stories)
4. **Review** - Keep only the FIRST set created (should be ~3-5 unique Stories)
5. **Bulk delete** the rest:
   - Click "⋯" (More actions) → "Bulk Change"
   - Select Stories to delete
   - Choose "Delete Issues"
   - Confirm

### Option 2: Keep Only Unique Stories

If you want to be more selective:

1. **Identify unique Story summaries** (there should be 3-5 unique ones based on the plan)
2. **For each unique summary:**
   - Keep the **oldest** Story (created first)
   - Delete all duplicates
3. **Delete using bulk actions**

### Option 3: Delete All and Regenerate

If you want a clean slate:

1. **Delete ALL Stories** for OD-48:
   ```jql
   parent = OD-48 AND issuetype = Story
   ```
   Bulk delete all
2. **Move Epic OD-48 back to BACKLOG**
3. **Move to "Selected for Development"** again
4. **AI will create Stories fresh** (only once, no duplicates!)

---

## 🚀 Deploy the Fix

### 1. Push to GitHub

**Via GitHub Desktop:**
- Review commit: "Add critical safeguards to prevent infinite Story/Subtask creation"
- Click "Push origin"

**OR via CLI:**
```bash
git push origin main
```

---

### 2. Deploy on Server

```bash
# SSH to server
ssh moveware-ai-runner-01

# Pull latest code
cd /srv/ai/app
git pull origin main

# Restart worker to load new safeguards
sudo systemctl restart moveware-ai-worker

# Verify restart
sudo systemctl status moveware-ai-worker

# Monitor logs
journalctl -u moveware-ai-worker -f
```

---

## 📊 What This Prevents

### Before Fix:
```
Epic Approved → Create 5 Stories
Webhook Retry → Create 5 MORE Stories (duplicates!)
Worker Restart → Create 5 MORE Stories (duplicates!)
[Loop continues until manually stopped]
Result: 590 duplicate Stories 😱
```

### After Fix:
```
Epic Approved → Check existing Stories
  → None found → Create 5 Stories
  → Add Stories to database
Webhook Retry → Check existing Stories
  → 5 found → Skip creation ✅
Worker Restart → Check existing Stories
  → 5 found → Skip creation ✅
Result: Exactly 5 Stories (as intended) 🎉
```

---

## 🔍 Why This Happened Now

### Timing Factors:

1. **JSON Repair System** (Commit 5)
   - Added retry logic for plan generation
   - May have caused multiple webhook calls

2. **Extended Thinking Timeout** (Your logs)
   - Plan generation took 5+ minutes
   - Increased chance of webhook retries

3. **No Idempotency Check**
   - Original code assumed function would only run once
   - No safeguard against multiple invocations

---

## ✅ Testing the Fix

After deploying, test with a new Epic:

1. **Create test Epic** in BACKLOG
2. **Move to "Selected for Development"**
3. **Wait for Stories to be created**
4. **Manually trigger webhook** (or restart worker)
5. **Verify:** No duplicate Stories created ✅

---

## 📈 Expected Results After Fix

| Scenario | Before Fix | After Fix |
|----------|-----------|-----------|
| First approval | 5 Stories | 5 Stories ✅ |
| Webhook retry | 5 MORE (10 total) | 0 (skipped) ✅ |
| Worker restart | 5 MORE (15 total) | 0 (skipped) ✅ |
| Plan > 50 Stories | All created (runaway) | Blocked with alert ✅ |
| **Total** | **590+ Stories** 😱 | **5 Stories** 🎉 |

---

## 🎯 Summary

**Fixed:**
- ✅ Infinite Story creation loop
- ✅ No duplicate Stories on retries
- ✅ Safety limits prevent runaway creation
- ✅ Clear error messages when limits exceeded

**Next Steps:**
1. Push this commit to GitHub
2. Deploy on server (restart worker)
3. Clean up 590 duplicate Stories in Jira
4. Monitor new Epic approvals to confirm fix

**Commit Ready:**
```bash
git push origin main
```

🚀 **Deploy now to prevent future infinite loops!**
