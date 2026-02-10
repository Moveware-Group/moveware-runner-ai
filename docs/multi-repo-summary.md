# Multi-Repository Support - Quick Summary

## Question: Should we keep updating .env or use something else?

**Answer**: For multiple Jira boards and repositories, use a **JSON configuration file** instead of `.env`.

## Why Not .env for Multiple Repos?

❌ **Problems with .env for multiple repos:**
- Would need variables like `REPO1_SSH`, `REPO2_SSH`, etc. (messy)
- Hard to scale beyond 2-3 repositories
- No way to map Jira projects to repos dynamically
- Complex to maintain and error-prone

✅ **Benefits of JSON config file:**
- Clean structure for multiple repos
- Easy to add new projects without code changes
- Automatic routing based on Jira project key
- Still supports `.env` as fallback for single-repo setups

## Solution: Use `config/repos.json`

### File Structure
```json
{
  "projects": [
    {
      "jira_project_key": "OD",
      "repo_ssh": "git@github.com:org/online-docs.git",
      "repo_workdir": "/srv/ai/repos/online-docs",
      "base_branch": "main",
      "repo_owner_slug": "org",
      "repo_name": "online-docs"
    },
    {
      "jira_project_key": "MW",
      "repo_ssh": "git@github.com:org/moveware.git",
      "repo_workdir": "/srv/ai/repos/moveware",
      "base_branch": "develop",
      "repo_owner_slug": "org",
      "repo_name": "moveware"
    }
  ],
  "default_project_key": "OD"
}
```

### How It Works

1. **Issue created**: `OD-123` (Online Docs project)
2. **System extracts**: Project key = `OD`
3. **Looks up config**: Finds `OD` → uses `online-docs` repository
4. **Executes**: Commits/PRs go to correct repo automatically

## Adding a New Board/Repo

### Step 1: Update `config/repos.json`
Add new entry with project key and repo details.

### Step 2: Create Work Directory
```bash
sudo mkdir -p /srv/ai/repos/new-repo
sudo chown moveware-ai:moveware-ai /srv/ai/repos/new-repo
```

### Step 3: Restart Worker
```bash
sudo systemctl restart moveware-ai-worker
```

**That's it!** No code changes needed.

## Files Created

I've created the following files to support multi-repo:

1. **`app/repo_config.py`** - Core multi-repo configuration manager
2. **`config/repos.example.json`** - Example configuration template
3. **`docs/multi-repo-configuration.md`** - Complete setup guide
4. **`docs/multi-repo-implementation-example.md`** - Code examples
5. **`.gitignore`** - Protects sensitive configuration

## Implementation Status

✅ **Ready to use** - Configuration framework is complete
⚠️ **Needs code updates** - Worker and executor need minor modifications to use the new config

## Next Steps

### Option A: Start Fresh with Multi-Repo (Recommended)
1. Copy `config/repos.example.json` to `config/repos.json`
2. Update it with your actual projects
3. Modify `worker.py` and `executor.py` as shown in implementation example
4. Test and deploy

### Option B: Keep Using .env (Simpler for Now)
1. If you only have 1-2 repos, keep using `.env`
2. The new code will fall back to `.env` if `config/repos.json` doesn't exist
3. Migrate to JSON config when you add more repos

## Backward Compatibility

The system is designed to be backward compatible:
- ✅ If `config/repos.json` exists → uses it
- ✅ If not → falls back to `.env` variables
- ✅ No breaking changes to existing deployments

## Recommendation

**For 1-2 repos**: Keep using `.env` (current setup works fine)

**For 3+ repos**: Switch to `config/repos.json` now to avoid refactoring later

**Growing fast?**: Implement multi-repo support now, even with just one repo in the config, so you're ready to scale.

## Example: Current State

Right now you have:
- 1 Jira project: `OD` (Online Docs)
- 1 GitHub repo: `leigh-moveware/online-docs`
- Configuration in: `.env`

This works fine! But if you want to add a second board/repo:

### Without multi-repo:
Would need complex environment variable juggling or code changes

### With multi-repo:
Just add 3 lines to `config/repos.json` and restart the worker

## Questions?

See the detailed guides:
- **[Multi-Repo Configuration Guide](multi-repo-configuration.md)** - Full setup instructions
- **[Implementation Examples](multi-repo-implementation-example.md)** - Code patterns

Or ask me to help implement the changes in your worker/executor code.
