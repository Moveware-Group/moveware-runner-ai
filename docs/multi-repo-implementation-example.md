# Multi-Repo Implementation Example

This document shows how to modify the worker and executor code to support multiple repositories.

## Changes Required

### 1. Update `app/worker.py` - Story Branch Creation

**Before (single repo):**
```python
from app.config import settings

def _handle_story_approved(ctx: Context, story: JiraIssue) -> None:
    # ... existing code ...
    
    story_branch = f"story/{story.key.lower()}"
    
    try:
        # Checkout repo and create Story branch
        checkout_repo(settings.REPO_WORKDIR, settings.REPO_SSH, settings.BASE_BRANCH)
        create_branch(settings.REPO_WORKDIR, story_branch)
        ctx.jira.add_comment(story.key, f"Created Story branch: {story_branch}")
    except Exception as e:
        error_msg = f"Warning: Could not create Story branch: {e}"
        print(f"ERROR in _handle_story_approved: {error_msg}")
        ctx.jira.add_comment(story.key, error_msg)
```

**After (multi-repo):**
```python
from app.config import settings
from app.repo_config import get_repo_for_issue

def _handle_story_approved(ctx: Context, story: JiraIssue) -> None:
    # ... existing code ...
    
    # Get repository configuration for this issue
    repo = get_repo_for_issue(story.key)
    if not repo:
        ctx.jira.add_comment(
            story.key, 
            f"ERROR: No repository configured for project {story.key.split('-')[0]}"
        )
        ctx.jira.transition_to_status(story.key, settings.JIRA_STATUS_BLOCKED)
        return
    
    story_branch = f"story/{story.key.lower()}"
    
    try:
        # Checkout repo and create Story branch (using repo config)
        checkout_repo(repo.repo_workdir, repo.repo_ssh, repo.base_branch)
        create_branch(repo.repo_workdir, story_branch)
        ctx.jira.add_comment(
            story.key, 
            f"Created Story branch: {story_branch} in {repo.repo_name}"
        )
    except Exception as e:
        error_msg = f"Warning: Could not create Story branch: {e}"
        print(f"ERROR in _handle_story_approved: {error_msg}")
        ctx.jira.add_comment(story.key, error_msg)
```

### 2. Update `app/executor.py` - Execute Subtask

**Before (single repo):**
```python
from app.config import settings

def execute_subtask(issue: JiraIssue, run_id: Optional[int] = None) -> ExecutionResult:
    # 1) Checkout/update repo
    checkout_repo(settings.REPO_WORKDIR, settings.REPO_SSH, settings.BASE_BRANCH)
    
    # 2) Determine branch
    if "independent-pr" in issue.labels:
        branch = f"ai/{issue.key.lower()}"
        create_branch(settings.REPO_WORKDIR, branch)
    else:
        # Use Story branch
        story_branch = f"story/{issue.parent_key.lower()}" if issue.parent_key else None
        checkout_or_create_story_branch(settings.REPO_WORKDIR, story_branch, settings.BASE_BRANCH)
        branch = story_branch
    
    # ... rest of execution ...
    
    commit_and_push(settings.REPO_WORKDIR, commit_message)
    
    # Create PR if independent
    if "independent-pr" in issue.labels:
        pr_url = create_pr(
            settings.REPO_WORKDIR,
            title=f"{issue.key}: {issue.summary}",
            body=pr_body,
            base=settings.BASE_BRANCH,
        )
```

**After (multi-repo):**
```python
from app.config import settings
from app.repo_config import get_repo_for_issue

def execute_subtask(issue: JiraIssue, run_id: Optional[int] = None) -> ExecutionResult:
    # Get repository configuration for this issue
    repo = get_repo_for_issue(issue.key)
    if not repo:
        raise ValueError(f"No repository configured for project {issue.key.split('-')[0]}")
    
    # 1) Checkout/update repo (using repo config)
    checkout_repo(repo.repo_workdir, repo.repo_ssh, repo.base_branch)
    
    # 2) Determine branch
    if "independent-pr" in issue.labels:
        branch = f"ai/{issue.key.lower()}"
        create_branch(repo.repo_workdir, branch)
    else:
        # Use Story branch
        story_branch = f"story/{issue.parent_key.lower()}" if issue.parent_key else None
        checkout_or_create_story_branch(repo.repo_workdir, story_branch, repo.base_branch)
        branch = story_branch
    
    # ... rest of execution (update all settings.REPO_* references to use repo.*) ...
    
    commit_and_push(repo.repo_workdir, commit_message)
    
    # Create PR if independent
    if "independent-pr" in issue.labels:
        pr_url = create_pr(
            repo.repo_workdir,
            title=f"{issue.key}: {issue.summary}",
            body=pr_body,
            base=repo.base_branch,
        )
```

### 3. Update PR Creation in Worker

**Before:**
```python
pr_url = create_pr(
    settings.REPO_WORKDIR,
    title=f"{parent.key}: {parent.summary}",
    body=pr_body,
    base=settings.BASE_BRANCH,
)
```

**After:**
```python
repo = get_repo_for_issue(parent.key)
if repo:
    pr_url = create_pr(
        repo.repo_workdir,
        title=f"{parent.key}: {parent.summary}",
        body=pr_body,
        base=repo.base_branch,
    )
```

## Helper Function Pattern

Create a helper function to reduce repetition:

```python
# In app/worker.py or app/executor.py

from app.repo_config import get_repo_for_issue, RepoConfig

def get_repo_or_fail(ctx: Context, issue: JiraIssue) -> RepoConfig:
    """
    Get repository configuration or transition issue to BLOCKED.
    
    Raises ValueError if no repo configured.
    """
    repo = get_repo_for_issue(issue.key)
    if not repo:
        project_key = issue.key.split('-')[0]
        error_msg = f"ERROR: No repository configured for project '{project_key}'"
        
        ctx.jira.add_comment(issue.key, error_msg)
        ctx.jira.transition_to_status(issue.key, settings.JIRA_STATUS_BLOCKED)
        ctx.jira.assign_issue(issue.key, settings.JIRA_HUMAN_ACCOUNT_ID)
        
        raise ValueError(error_msg)
    
    return repo


# Usage:
def _handle_story_approved(ctx: Context, story: JiraIssue) -> None:
    try:
        repo = get_repo_or_fail(ctx, story)
        
        # Now use repo.* for all operations
        checkout_repo(repo.repo_workdir, repo.repo_ssh, repo.base_branch)
        # ...
    except ValueError:
        # Already handled by get_repo_or_fail
        return
```

## Testing Multi-Repo Setup

### Test Configuration Loading

```python
# test_repo_config.py
from app.repo_config import get_repo_manager, get_repo_for_issue

def test_multi_repo_config():
    manager = get_repo_manager()
    
    # List all configured projects
    print("\nConfigured projects:")
    for key, config in manager.get_all_projects().items():
        print(f"  {key}: {config.repo_name} -> {config.repo_workdir}")
    
    # Test issue key resolution
    test_keys = ["OD-123", "MW-456", "API-789", "UNKNOWN-999"]
    
    print("\nIssue key resolution:")
    for issue_key in test_keys:
        repo = get_repo_for_issue(issue_key)
        if repo:
            print(f"  {issue_key} -> {repo.repo_name}")
        else:
            print(f"  {issue_key} -> NO CONFIG FOUND")

if __name__ == "__main__":
    test_multi_repo_config()
```

### Run Test

```bash
# From project root
python test_repo_config.py
```

Expected output:
```
Configured projects:
  OD: online-docs -> /srv/ai/repos/online-docs
  MW: moveware-core -> /srv/ai/repos/moveware-core
  API: api-services -> /srv/ai/repos/api-services

Issue key resolution:
  OD-123 -> online-docs
  MW-456 -> moveware-core
  API-789 -> api-services
  UNKNOWN-999 -> online-docs (default)
```

## Migration Strategy

### Phase 1: Add Configuration (Backward Compatible)

1. Create `app/repo_config.py` (already done)
2. Create `config/repos.json` with current repo
3. Keep environment variables as fallback
4. Test that system still works

### Phase 2: Update Code to Use Multi-Repo

1. Update `worker.py` to use `get_repo_for_issue()`
2. Update `executor.py` to use `get_repo_for_issue()`
3. Update any other files that reference `settings.REPO_*`
4. Test with single repo configuration

### Phase 3: Add Additional Repositories

1. Update `config/repos.json` with new projects
2. Create work directories for new repos
3. Test with different project keys
4. Deploy to production

## Complete Example: Minimal Changes to Worker

Here's a minimal change pattern that adds multi-repo support with fallback:

```python
from app.config import settings
from app.repo_config import get_repo_for_issue

def _get_repo_settings(issue_key: str) -> dict:
    """
    Get repository settings for an issue.
    Falls back to environment variables if multi-repo config not found.
    
    Returns dict with: repo_ssh, repo_workdir, base_branch, repo_owner_slug, repo_name
    """
    repo = get_repo_for_issue(issue_key)
    
    if repo:
        return {
            "repo_ssh": repo.repo_ssh,
            "repo_workdir": repo.repo_workdir,
            "base_branch": repo.base_branch,
            "repo_owner_slug": repo.repo_owner_slug,
            "repo_name": repo.repo_name,
        }
    else:
        # Fallback to environment variables (legacy single-repo mode)
        return {
            "repo_ssh": settings.REPO_SSH,
            "repo_workdir": settings.REPO_WORKDIR,
            "base_branch": settings.BASE_BRANCH,
            "repo_owner_slug": settings.REPO_OWNER_SLUG,
            "repo_name": settings.REPO_NAME,
        }


# Then in your functions:
def _handle_story_approved(ctx: Context, story: JiraIssue) -> None:
    # Get repo settings for this story
    repo_settings = _get_repo_settings(story.key)
    
    checkout_repo(
        repo_settings["repo_workdir"], 
        repo_settings["repo_ssh"], 
        repo_settings["base_branch"]
    )
    # ... rest of code ...
```

This pattern provides:
- ✅ Multi-repo support when `config/repos.json` exists
- ✅ Backward compatibility with environment variables
- ✅ Minimal code changes
- ✅ Easy to test incrementally

## Summary

To add multi-repo support:

1. **Add** `app/repo_config.py` (already created)
2. **Create** `config/repos.json` with your project mappings
3. **Update** `worker.py` and `executor.py` to use `get_repo_for_issue()`
4. **Test** with existing single repo first
5. **Add** new projects to `config/repos.json` as needed

No changes to `.env` required - it serves as a fallback for single-repo deployments.
