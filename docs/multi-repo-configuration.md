# Multi-Repository Configuration

This guide explains how to configure the AI Runner to work with multiple Jira boards and GitHub repositories.

## Overview

The AI Runner can be configured to work with:
- **Single repository** (legacy): Using environment variables
- **Multiple repositories**: Using a JSON configuration file

## Configuration Methods

### Method 1: JSON Configuration File (Recommended for Multiple Repos)

#### 1. Create Configuration File

Create `config/repos.json` based on the example:

```json
{
  "projects": [
    {
      "jira_project_key": "OD",
      "jira_project_name": "Online Docs",
      "repo_ssh": "git@github.com:leigh-moveware/online-docs.git",
      "repo_workdir": "/srv/ai/repos/online-docs",
      "base_branch": "main",
      "repo_owner_slug": "leigh-moveware",
      "repo_name": "online-docs",
      "skills": ["nextjs-fullstack-dev"]
    },
    {
      "jira_project_key": "MW",
      "jira_project_name": "Moveware Core",
      "repo_ssh": "git@github.com:leigh-moveware/moveware-core.git",
      "repo_workdir": "/srv/ai/repos/moveware-core",
      "base_branch": "develop",
      "repo_owner_slug": "leigh-moveware",
      "repo_name": "moveware-core",
      "skills": ["nextjs-fullstack-dev"]
    },
    {
      "jira_project_key": "TB",
      "jira_project_name": "Moveware Go",
      "repo_ssh": "git@github.com:leigh-moveware/moveware-go.git",
      "repo_workdir": "/srv/ai/repos/moveware-go",
      "base_branch": "main",
      "repo_owner_slug": "leigh-moveware",
      "repo_name": "moveware-go",
      "skills": ["flutter-dev"]
    }
  ],
  "default_project_key": "OD"
}
```

#### 2. Set Configuration Path (Optional)

If you want to use a custom location:

```bash
# In .env or environment
REPOS_CONFIG_PATH=/path/to/custom/repos.json
```

Otherwise, it will automatically look for `config/repos.json`.

#### 3. Update Code to Use Multi-Repo Config

The system will automatically detect and use `config/repos.json` if it exists.

**In your worker/executor code:**

```python
from app.repo_config import get_repo_for_issue

# Get repo config for the current issue
repo = get_repo_for_issue(issue.key)

if repo:
    checkout_repo(repo.repo_workdir, repo.repo_ssh, repo.base_branch)
    # ... use repo.repo_owner_slug, repo.repo_name, etc.
else:
    # Handle missing configuration
    raise ValueError(f"No repository configured for project: {issue.key}")
```

### Method 2: Environment Variables (Legacy - Single Repo)

If `config/repos.json` doesn't exist, the system falls back to environment variables:

```bash
# In .env
REPO_SSH=git@github.com:leigh-moveware/online-docs.git
REPO_WORKDIR=/srv/ai/repos/online-docs
BASE_BRANCH=main
REPO_OWNER_SLUG=leigh-moveware
REPO_NAME=online-docs
```

## How It Works

### Issue Key to Repository Mapping

The system extracts the project key from Jira issue keys:

- `OD-123` → Project `OD` → Uses `online-docs` repository
- `MW-456` → Project `MW` → Uses `moveware-core` repository
- `API-789` → Project `API` → Uses `api-services` repository

### Fallback Behavior

1. **Exact match**: If the project key matches a configured project, use that repository
2. **Default fallback**: If no match, use the `default_project_key` from config
3. **Legacy fallback**: If no config file exists, use environment variables

## Setup Steps (Production)

### 1. Create Configuration File

```bash
sudo mkdir -p /srv/ai/app/config
sudo nano /srv/ai/app/config/repos.json
```

Paste your configuration and save.

### 2. Create Repository Directories

```bash
# Create working directories for each repository
sudo mkdir -p /srv/ai/repos/online-docs
sudo mkdir -p /srv/ai/repos/moveware-core
sudo mkdir -p /srv/ai/repos/api-services

# Set ownership
sudo chown -R moveware-ai:moveware-ai /srv/ai/repos
```

### 3. Test Configuration

```bash
# Test that repos.json is valid
python3 -c "
from app.repo_config import get_repo_manager
manager = get_repo_manager()
for key, config in manager.get_all_projects().items():
    print(f'{key}: {config.repo_name}')
"
```

### 4. Restart Services

```bash
sudo systemctl restart moveware-ai-orchestrator
sudo systemctl restart moveware-ai-worker
```

## Add Repository Page (AI Console)

The **Add Repository** page (`/repos`) lets you create a new repo without manually editing `repos.json`:

1. **Access**: From the Status Dashboard, click **Add Repository** (or go to `/repos`)
2. **Fill the form**: Jira project key/name, repo name, owner, description, skills (multi-select), base branch
3. **Optional**: Uncheck "Create on GitHub" if the repo already exists
4. **Submit**: Creates the GitHub repo (if selected), the folder under `/srv/ai/repos`, and appends the project to `config/repos.json`

**Requirements**:
- `gh` CLI installed and authenticated (or valid `GH_TOKEN` / GitHub App)
- Server process has write access to `/srv/ai/repos` and `config/repos.json`

**Admin protection** (optional): Set `ADMIN_SECRET` in your environment. If set, you must enter it in the "Admin Key" field when submitting. This restricts who can add repositories.

```bash
# In .env or /etc/moveware-ai.env
ADMIN_SECRET=your-secret-here
```

## Adding a New Repository (Manual)

To add a new Jira board/repository manually:

### 1. Update `config/repos.json`

Add a new project entry:

```json
{
  "jira_project_key": "NEWPROJ",
  "jira_project_name": "New Project",
  "repo_ssh": "git@github.com:org/new-project.git",
  "repo_workdir": "/srv/ai/repos/new-project",
  "base_branch": "main",
  "repo_owner_slug": "org",
  "repo_name": "new-project"
}
```

### 2. Create Working Directory

```bash
sudo mkdir -p /srv/ai/repos/new-project
sudo chown moveware-ai:moveware-ai /srv/ai/repos/new-project
```

### 3. Initial Clone (Optional)

```bash
sudo -u moveware-ai git clone git@github.com:org/new-project.git /srv/ai/repos/new-project
```

### 4. Reload Configuration

```bash
# Restart worker to pick up new config
sudo systemctl restart moveware-ai-worker
```

No code changes needed! The system will automatically route issues based on their project key.

## Troubleshooting

### Issue: "No repository configured for project"

**Cause**: The project key from the Jira issue doesn't match any configured projects.

**Solution**: 
1. Check the issue key: `OD-123` → Project is `OD`
2. Verify `config/repos.json` has an entry with `"jira_project_key": "OD"`
3. Or set a `default_project_key` in the config

### Issue: Permission denied when cloning

**Cause**: SSH keys not configured for the `moveware-ai` user.

**Solution**:
```bash
# Set up SSH keys for moveware-ai user
sudo -u moveware-ai ssh-keygen -t ed25519 -C "moveware-ai@runner"
sudo cat /home/moveware-ai/.ssh/id_ed25519.pub
# Add this public key to GitHub
```

### Issue: Configuration not loading

**Cause**: JSON syntax error or file not found.

**Solution**:
```bash
# Validate JSON syntax
python3 -m json.tool /srv/ai/app/config/repos.json

# Check file exists and is readable
ls -la /srv/ai/app/config/repos.json
sudo -u moveware-ai cat /srv/ai/app/config/repos.json
```

## Migration from Single to Multi-Repo

### Before (Single Repo - .env)
```bash
REPO_SSH=git@github.com:leigh-moveware/online-docs.git
REPO_WORKDIR=/srv/ai/repos/online-docs
BASE_BRANCH=main
REPO_OWNER_SLUG=leigh-moveware
REPO_NAME=online-docs
```

### After (Multi-Repo - repos.json)
```json
{
  "projects": [
    {
      "jira_project_key": "OD",
      "jira_project_name": "Online Docs",
      "repo_ssh": "git@github.com:leigh-moveware/online-docs.git",
      "repo_workdir": "/srv/ai/repos/online-docs",
      "base_branch": "main",
      "repo_owner_slug": "leigh-moveware",
      "repo_name": "online-docs"
    }
  ],
  "default_project_key": "OD"
}
```

**Note**: You can keep the environment variables in `.env` as a fallback. The system will use `repos.json` if it exists, otherwise fall back to `.env`.

## Best Practices

1. **Use consistent naming**: Match Jira project keys exactly (case-sensitive)
2. **Separate work directories**: Each repo should have its own `repo_workdir`
3. **Set a default**: Always specify a `default_project_key` for unmapped projects
4. **Version control**: Keep `repos.json` in git (but use `.example` for sensitive paths)
5. **Documentation**: Comment your configuration or maintain a separate mapping doc

## Alternative: Database-Backed Configuration

For very large deployments (10+ repos), consider storing configuration in the database:

```sql
CREATE TABLE repo_configs (
    jira_project_key TEXT PRIMARY KEY,
    jira_project_name TEXT,
    repo_ssh TEXT NOT NULL,
    repo_workdir TEXT NOT NULL,
    base_branch TEXT NOT NULL,
    repo_owner_slug TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    is_default BOOLEAN DEFAULT 0
);
```

This allows dynamic configuration via a web UI without restarting services.

## Summary

- **1-2 repos**: Use environment variables (current setup)
- **2-5 repos**: Use `config/repos.json` (recommended)
- **5-10 repos**: Use `config/repos.json` with good organization
- **10+ repos**: Consider database-backed configuration

The system is designed to scale from a single repository to multiple repositories without breaking changes.
