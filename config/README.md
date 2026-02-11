# Repository Configuration

This directory contains multi-repository configuration for the AI Runner.

## Quick Start

### Single Repository (Default)

If you have only one repository, you don't need to create `repos.json`. The system will fall back to environment variables in `.env`:

```bash
# In .env
REPO_SSH=git@github.com:org/repo.git
REPO_WORKDIR=/srv/ai/repos/repo
BASE_BRANCH=main
REPO_OWNER_SLUG=org
REPO_NAME=repo
```

### Multiple Repositories

For multiple Jira projects/repositories:

1. **Copy the example file:**
   ```bash
   cp repos.example.json repos.json
   ```

2. **Edit `repos.json` with your projects:**
   ```json
   {
     "projects": [
       {
         "jira_project_key": "OD",
         "jira_project_name": "Online Docs",
         "repo_ssh": "git@github.com:org/online-docs.git",
         "repo_workdir": "/srv/ai/repos/online-docs",
         "base_branch": "main",
         "repo_owner_slug": "org",
         "repo_name": "online-docs"
       }
     ],
     "default_project_key": "OD"
   }
   ```

3. **Create work directories:**
   ```bash
   sudo mkdir -p /srv/ai/repos/online-docs
   sudo chown moveware-ai:moveware-ai /srv/ai/repos/online-docs
   ```

4. **Restart services:**
   ```bash
   sudo systemctl restart moveware-ai-worker
   sudo systemctl restart moveware-ai-orchestrator
   ```

## How It Works

- Issue `OD-123` → Project key `OD` → Uses `online-docs` repository
- Issue `MW-456` → Project key `MW` → Uses `moveware-core` repository

## Adding a New Project

Just add a new entry to `repos.json`:

```json
{
  "jira_project_key": "NEWPROJ",
  "repo_ssh": "git@github.com:org/new-project.git",
  "repo_workdir": "/srv/ai/repos/new-project",
  "base_branch": "main",
  "repo_owner_slug": "org",
  "repo_name": "new-project"
}
```

Create the directory and restart the worker:

```bash
sudo mkdir -p /srv/ai/repos/new-project
sudo chown moveware-ai:moveware-ai /srv/ai/repos/new-project
sudo systemctl restart moveware-ai-worker
```

No code changes needed!

## Project Knowledge (Planning Context)

The file `project-knowledge.md` in this directory is used by the AI Runner when creating Epic plans. It contains facts about your infrastructure, cloud provider, deployment setup, and conventions. By providing this context, the AI will not ask basic questions it should already know (e.g. "Which cloud provider?").

Edit `project-knowledge.md` with your environment details.

## Documentation

See [docs/multi-repo-configuration.md](../docs/multi-repo-configuration.md) for complete setup guide.
