# Multi-Repo Integration - Deployment Checklist

Use this checklist when deploying the multi-repository changes to production.

## Pre-Deployment (Local)

- [ ] Review changes in Git
  ```bash
  git status
  git log --oneline -10
  ```

- [ ] Run local test (optional)
  ```bash
  python test_repo_config.py
  ```

- [ ] Commit and push changes
  ```bash
  git add .
  git commit -m "Add multi-repository support with backward compatibility"
  git push origin main
  ```

## Deployment to Server

### 1. Pull Changes

- [ ] SSH to server
  ```bash
  ssh user@moveware-ai-runner-01
  ```

- [ ] Navigate to app directory
  ```bash
  cd /srv/ai/app
  ```

- [ ] Backup current version (safety)
  ```bash
  git log --oneline -1 > /tmp/pre-multi-repo-version.txt
  ```

- [ ] Pull changes
  ```bash
  sudo -u moveware-ai git pull
  ```

- [ ] Verify files were pulled
  ```bash
  ls -la app/repo_config.py
  ls -la config/repos.example.json
  ```

### 2. Test Configuration (Keep .env for now)

- [ ] Test that the system can load config
  ```bash
  cd /srv/ai/app
  sudo -u moveware-ai python3 test_repo_config.py
  ```

  Expected output:
  ```
  ✅ Single-repository mode (using .env)
     To enable multi-repo: Create config/repos.json
  ```

### 3. Restart Services

- [ ] Restart worker
  ```bash
  sudo systemctl restart moveware-ai-worker
  ```

- [ ] Check worker status
  ```bash
  sudo systemctl status moveware-ai-worker
  ```

- [ ] Check worker logs
  ```bash
  sudo journalctl -u moveware-ai-worker -n 20 --no-pager
  ```

  Look for:
  - ✅ "Worker worker-1 started"
  - ✅ "Using legacy environment variables for single repository"
  - ❌ NO Python import errors
  - ❌ NO "No module named repo_config" errors

- [ ] Restart orchestrator
  ```bash
  sudo systemctl restart moveware-ai-orchestrator
  ```

- [ ] Check orchestrator status
  ```bash
  sudo systemctl status moveware-ai-orchestrator
  ```

### 4. Functional Testing

- [ ] Test health endpoint
  ```bash
  curl http://127.0.0.1:8088/health
  ```

  Expected: `{"status":"ok"}`

- [ ] Test dashboard
  ```bash
  curl -k https://ai-console.moveconnect.com/health
  ```

  Expected: `{"status":"ok"}`

- [ ] Create a test Jira issue and assign to AI
  - [ ] Verify issue is picked up
  - [ ] Verify commits go to correct repository
  - [ ] Verify PR is created successfully

### 5. Monitor

- [ ] Watch worker logs for 5 minutes
  ```bash
  sudo journalctl -u moveware-ai-worker -f
  ```

- [ ] Check for any errors or warnings

## Post-Deployment

- [ ] Mark deployment as successful
- [ ] Update any runbooks/documentation
- [ ] Note current Git commit for rollback reference
  ```bash
  git log --oneline -1
  ```

## Optional: Enable Multi-Repo (When Ready)

Only do this when you actually have multiple repos to add:

### 1. Create Configuration

- [ ] Create config file
  ```bash
  sudo mkdir -p /srv/ai/app/config
  sudo nano /srv/ai/app/config/repos.json
  ```

- [ ] Paste configuration based on `repos.example.json`

- [ ] Validate JSON
  ```bash
  cat /srv/ai/app/config/repos.json | python3 -m json.tool
  ```

### 2. Create Directories

- [ ] Create work directories for each repo
  ```bash
  sudo mkdir -p /srv/ai/repos/repo1
  sudo mkdir -p /srv/ai/repos/repo2
  ```

- [ ] Set permissions
  ```bash
  sudo chown -R moveware-ai:moveware-ai /srv/ai/repos
  ```

### 3. Test and Deploy

- [ ] Test configuration
  ```bash
  cd /srv/ai/app
  sudo -u moveware-ai python3 test_repo_config.py
  ```

- [ ] Restart services
  ```bash
  sudo systemctl restart moveware-ai-worker
  sudo systemctl restart moveware-ai-orchestrator
  ```

- [ ] Verify logs show multi-repo mode
  ```bash
  sudo journalctl -u moveware-ai-worker -n 20 | grep -i "repository"
  ```

## Rollback Plan

If something goes wrong:

- [ ] Revert Git changes
  ```bash
  cd /srv/ai/app
  sudo -u moveware-ai git revert HEAD
  ```

- [ ] Restart services
  ```bash
  sudo systemctl restart moveware-ai-worker
  sudo systemctl restart moveware-ai-orchestrator
  ```

- [ ] Verify services are working
  ```bash
  curl http://127.0.0.1:8088/health
  ```

## Success Criteria

✅ All services running without errors
✅ Health endpoints responding
✅ Worker processing issues normally
✅ Commits/PRs going to correct repository
✅ No errors in logs for 15+ minutes

## Notes

- Changes are 100% backward compatible
- `.env` continues to work as before
- `repos.json` is optional - only needed for multiple repos
- No database migrations required
- No config changes to systemd services

---

**Deployment Date:** _____________

**Deployed By:** _____________

**Git Commit:** _____________

**Status:** [ ] Success  [ ] Failed  [ ] Rolled Back

**Notes:**
