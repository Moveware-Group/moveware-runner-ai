# GitHub Webhook Auto-Deployment

Automatically deploy the AI Runner when code is pushed to the `main` branch.

## Overview

When you push code to GitHub, a webhook triggers the server to:
1. Pull latest code
2. Install dependencies
3. Restart services
4. Log the deployment

## Setup Instructions

### 1. Install Deployment Script on Server

```bash
# Create scripts directory
sudo mkdir -p /srv/ai/scripts
sudo mkdir -p /srv/ai/logs

# Copy the deployment script (after pulling the code)
cd /srv/ai/app
git pull
sudo cp scripts/deploy.sh /srv/ai/scripts/
sudo chmod +x /srv/ai/scripts/deploy.sh
sudo chown root:root /srv/ai/scripts/deploy.sh

# Test the script
sudo /srv/ai/scripts/deploy.sh
```

### 2. Add Webhook Secret to Environment

```bash
# Generate a random secret
SECRET=$(openssl rand -hex 32)
echo "Generated secret: $SECRET"

# Add to environment file
sudo nano /etc/moveware-ai.env

# Add this line:
GITHUB_DEPLOY_WEBHOOK_SECRET=your-secret-here
```

### 3. Restart Services (to load new webhook endpoint)

```bash
sudo systemctl restart moveware-ai-orchestrator
```

### 4. Configure GitHub Webhook

Go to your repository settings:
```
https://github.com/YOUR-ORG/moveware-runner-ai/settings/hooks/new
```

**Webhook Configuration:**
- **Payload URL:** `https://ai-console.moveconnect.com/webhook/github-deploy`
- **Content type:** `application/json`
- **Secret:** (paste the secret from step 2)
- **SSL verification:** Enable SSL verification
- **Which events:** Just the `push` event
- **Active:** ✅ Checked

Click **Add webhook**

### 5. Test the Webhook

Make a test commit and push to main:

```bash
# On your local machine
cd /path/to/moveware-runner-ai
echo "# Test" >> README.md
git add README.md
git commit -m "Test auto-deploy webhook"
git push origin main
```

Check GitHub webhook delivery:
- Go to Settings > Webhooks
- Click on your webhook
- Check "Recent Deliveries" tab
- Should see a 200 OK response

Check server logs:
```bash
# On server
tail -f /srv/ai/logs/deploy.log

# Or check orchestrator logs
sudo journalctl -u moveware-ai-orchestrator -f
```

---

## How It Works

### Webhook Flow

```
GitHub Push → Webhook → AI Runner → Deploy Script → Services Restart
```

1. **Developer pushes to main branch**
2. **GitHub sends webhook** to `https://ai-console.moveconnect.com/webhook/github-deploy`
3. **Webhook endpoint verifies signature** (security check)
4. **Checks if push is to main/master** (ignores other branches)
5. **Runs deployment script** `/srv/ai/scripts/deploy.sh`
6. **Script:**
   - Pulls latest code
   - Installs dependencies
   - Restarts services
   - Logs everything

### Security

- ✅ Webhook signature verification (HMAC SHA-256)
- ✅ Only deploys from main/master branches
- ✅ Script runs as root (needed to restart services)
- ✅ All actions logged with timestamps

---

## Monitoring

### View Deployment Logs

```bash
# Latest deployment
tail -n 50 /srv/ai/logs/deploy.log

# Watch in real-time
tail -f /srv/ai/logs/deploy.log

# View all deployments today
grep "$(date '+%Y-%m-%d')" /srv/ai/logs/deploy.log
```

### Check Webhook Deliveries

In GitHub:
1. Go to Settings > Webhooks
2. Click your webhook
3. View "Recent Deliveries"
4. See request/response for each push

### Service Status After Deploy

```bash
# Check both services
sudo systemctl status moveware-ai-orchestrator
sudo systemctl status moveware-ai-worker

# View recent logs
sudo journalctl -u moveware-ai-orchestrator -n 20
sudo journalctl -u moveware-ai-worker -n 20
```

---

## Troubleshooting

### Webhook Shows "Failed" in GitHub

**Check orchestrator logs:**
```bash
sudo journalctl -u moveware-ai-orchestrator -n 50 | grep webhook
```

**Common issues:**
- Secret mismatch → Update `GITHUB_DEPLOY_WEBHOOK_SECRET`
- Endpoint not responding → Check orchestrator is running
- SSL issues → Verify nginx SSL configuration

### Deployment Script Fails

**View deploy logs:**
```bash
sudo tail -100 /srv/ai/logs/deploy.log
```

**Common issues:**
- Git pull fails → Check SSH keys for moveware-ai user
- Permission errors → Script must run as root
- Dependencies fail → Check Python virtual environment
- Services won't restart → Check systemd unit files

### Services Don't Start After Deploy

**Check status:**
```bash
sudo systemctl status moveware-ai-orchestrator
sudo systemctl status moveware-ai-worker
```

**Rollback if needed:**
```bash
cd /srv/ai/app
sudo -u moveware-ai git log --oneline -5
sudo -u moveware-ai git reset --hard <previous-commit>
sudo systemctl restart moveware-ai-orchestrator
sudo systemctl restart moveware-ai-worker
```

---

## Per-Repository Setup

### Option 1: Webhook in AI Runner Repo Only (Recommended)

Setup webhook in **moveware-runner-ai** repository only.
- Pro: Simple, focused
- Con: Each repo needs its own webhook

### Option 2: Organization-Level Webhook

Setup one webhook at organization level:
```
https://github.com/organizations/YOUR-ORG/settings/hooks
```

Update the endpoint to handle multiple repos:
```python
# In app/main.py
if repo_name == "YOUR-ORG/moveware-runner-ai":
    # Deploy AI Runner
    deploy_script = "/srv/ai/scripts/deploy-runner.sh"
elif repo_name == "YOUR-ORG/online-docs":
    # Deploy docs site
    deploy_script = "/srv/ai/scripts/deploy-docs.sh"
```

---

## Advanced Configuration

### Custom Deploy Script Per Environment

Create environment-specific scripts:

```bash
/srv/ai/scripts/
├── deploy.sh              # Main script (production)
├── deploy-staging.sh      # Staging environment
└── deploy-rollback.sh     # Rollback helper
```

### Slack/Email Notifications

Add to deploy script:

```bash
# At the end of deploy.sh
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"✅ AI Runner deployed: '"$LATEST_COMMIT"'"}' \
  https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Health Check After Deploy

Add to deploy script:

```bash
# Wait for services to be fully ready
sleep 5

# Test health endpoint
if curl -s http://127.0.0.1:8088/health | grep -q "ok"; then
    log_success "Health check passed"
else
    log_error "Health check failed - rolling back"
    git reset --hard HEAD~1
    systemctl restart moveware-ai-orchestrator
    systemctl restart moveware-ai-worker
    exit 1
fi
```

---

## Security Best Practices

1. ✅ **Use webhook secrets** - Always verify signatures
2. ✅ **Restrict to main branch** - Don't auto-deploy feature branches
3. ✅ **Run as root only when needed** - Script needs root for systemctl
4. ✅ **Log everything** - Track who deployed what and when
5. ✅ **Test in staging first** - Use separate webhook for staging
6. ✅ **Set up rollback** - Keep deploy.log for audit trail
7. ✅ **Monitor deploys** - Check logs after each deployment

---

## Summary

**To enable auto-deploy:**
1. ✅ Add deployment script to server
2. ✅ Set webhook secret in environment
3. ✅ Restart orchestrator
4. ✅ Add webhook in GitHub
5. ✅ Test with a push to main

**Result:**
- Push to main → Automatic deployment
- No manual server access needed
- All deployments logged
- Services automatically restarted
