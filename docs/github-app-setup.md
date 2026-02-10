# GitHub App Setup Guide

Complete guide to setting up GitHub App authentication for the AI Runner.

## Why GitHub App?

### GitHub App ✅ **Recommended**
- ✅ Single app can access multiple repos
- ✅ Fine-grained permissions (only what you need)
- ✅ Better audit trail (shows "AI Runner" in GitHub)
- ✅ Token auto-rotation (1 hour expiry, auto-refresh)
- ✅ Can be scoped to organization
- ✅ Easier to revoke/manage centrally
- ✅ GitHub's recommended approach for automation

### Personal Access Token (PAT) ❌
- ❌ No audit trail of which service did what
- ❌ If compromised, need to rotate everywhere
- ❌ No fine-grained permissions
- ❌ Not recommended for organization automation

---

## Setup Instructions

### Step 1: Create GitHub App

1. **Go to organization settings:**
   ```
   https://github.com/organizations/YOUR-ORG/settings/apps/new
   ```

2. **Fill in basic information:**
   - **Name:** `Moveware AI Runner`
   - **Description:** `Automated AI coding assistant for Jira issues`
   - **Homepage URL:** `https://ai-console.moveconnect.com`
   - **Webhook URL:** Leave blank (or use Jira webhook if you want GitHub events)
   - **Webhook Secret:** Leave blank for now

3. **Set permissions (Repository permissions):**
   - **Contents:** Read & Write _(for cloning, committing, pushing)_
   - **Pull requests:** Read & Write _(for creating PRs)_
   - **Metadata:** Read-only _(automatic, needed for basic operations)_

4. **Where can this GitHub App be installed:**
   - ✅ **Only on this account** (your organization)

5. **Click "Create GitHub App"**

---

### Step 2: Generate Private Key

After creating the app:

1. Scroll down to **"Private keys"** section
2. Click **"Generate a private key"**
3. Save the downloaded `.pem` file securely (e.g., `moveware-ai-runner.2026-02-11.private-key.pem`)

**⚠️ Security Note:** This private key is sensitive! Store it securely.

---

### Step 3: Install the App

1. In the GitHub App settings, click **"Install App"** in the left sidebar
2. Select your organization
3. Choose:
   - **All repositories** (if you want it to access all), OR
   - **Only select repositories** (choose: moveware-runner-ai, online-docs, vs-project, etc.)
4. Click **"Install"**

---

### Step 4: Get App Credentials

You'll need three pieces of information:

#### 1. App ID
- Found on the app settings page (top left, under app name)
- Example: `123456`

#### 2. Installation ID (Optional - will auto-detect)
- **Method A:** Check the URL after installing
  ```
  https://github.com/organizations/YOUR-ORG/settings/installations/12345678
                                                                     ^^^^^^^^ 
                                                              This is the installation ID
  ```

- **Method B:** Via API (if you need it programmatically)
  ```bash
  curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
       -H "Accept: application/vnd.github.v3+json" \
       https://api.github.com/app/installations
  ```

**Note:** The AI Runner will auto-detect this if you leave it blank!

#### 3. Private Key Path
- The `.pem` file you downloaded in Step 2

---

### Step 5: Install on Your Server

```bash
# 1. Copy private key to server
# On your local machine:
scp moveware-ai-runner.*.private-key.pem lm_admin@your-server:~/

# On server:
sudo mkdir -p /srv/ai/.ssh
sudo mv ~/moveware-ai-runner.*.private-key.pem /srv/ai/.ssh/github-app-private-key.pem
sudo chown moveware-ai:moveware-ai /srv/ai/.ssh/github-app-private-key.pem
sudo chmod 600 /srv/ai/.ssh/github-app-private-key.pem
```

```bash
# 2. Update environment variables
sudo nano /etc/moveware-ai.env

# Add these lines (replace with your actual values):
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=12345678  # Optional, will auto-detect
GITHUB_APP_PRIVATE_KEY_PATH=/srv/ai/.ssh/github-app-private-key.pem
```

```bash
# 3. Pull latest code
cd /srv/ai/app
sudo -u moveware-ai git pull

# 4. Install new dependencies
sudo -u moveware-ai .venv/bin/pip install -r requirements.txt

# 5. Restart services
sudo systemctl restart moveware-ai-worker
sudo systemctl restart moveware-ai-orchestrator
```

---

### Step 6: Verify It's Working

```bash
# Check worker logs for GitHub App initialization message
sudo journalctl -u moveware-ai-worker -n 50 | grep -i github

# Should see:
# ✓ GitHub App authentication initialized (App ID: 123456)
```

**Test with a Jira issue:**
1. Create a new issue in Jira
2. Assign it to the AI Runner
3. Watch the logs - it should use GitHub App tokens for all operations
4. Check the created PR - it will show "moveware-ai-runner" as the author

---

## How It Works

### Token Flow

```
1. AI Runner starts
   ↓
2. Loads private key from file
   ↓
3. Generates JWT (valid 10 min)
   ↓
4. Uses JWT to request installation token (valid 1 hour)
   ↓
5. Uses installation token for all GitHub API calls
   ↓
6. Auto-refreshes when token expires (< 5 min remaining)
```

### Security Features

- ✅ **JWT tokens** expire after 10 minutes
- ✅ **Installation tokens** expire after 1 hour (auto-refresh)
- ✅ **Private key** never sent over network
- ✅ **Tokens** cached in memory only (not on disk)
- ✅ **Auto-refresh** before expiration (5 min buffer)

---

## Troubleshooting

### Error: "Private key not found"

**Problem:** Can't find the `.pem` file

**Solution:**
```bash
# Check file exists
ls -la /srv/ai/.ssh/github-app-private-key.pem

# Check permissions
# Should be: -rw------- moveware-ai moveware-ai

# Fix permissions if needed
sudo chown moveware-ai:moveware-ai /srv/ai/.ssh/github-app-private-key.pem
sudo chmod 600 /srv/ai/.ssh/github-app-private-key.pem
```

### Error: "No installations found for this GitHub App"

**Problem:** App not installed in your organization

**Solution:**
1. Go to GitHub App settings
2. Click "Install App"
3. Select your organization
4. Choose repositories

### Error: "403 Forbidden" when creating PRs

**Problem:** App doesn't have correct permissions

**Solution:**
1. Go to GitHub App settings
2. Check **Permissions > Repository permissions**
3. Ensure these are set:
   - Contents: Read & Write
   - Pull requests: Read & Write
4. Save changes
5. You'll need to accept the new permissions in your organization

### Falls Back to PAT

**Symptom:** Logs show "Falling back to PAT authentication"

**Causes:**
- `GITHUB_APP_ID` not set
- `GITHUB_APP_PRIVATE_KEY_PATH` not set
- Private key file doesn't exist
- Error loading private key

**Solution:** Check all three environment variables are set correctly

---

## Migration from PAT

If you're currently using `GH_TOKEN` (PAT), here's how to migrate:

### 1. Keep PAT as Backup

```bash
# Keep existing PAT in environment
GH_TOKEN=ghp_xxxxx...

# Add GitHub App settings (higher priority)
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_APP_PRIVATE_KEY_PATH=/srv/ai/.ssh/github-app-private-key.pem
```

The AI Runner will:
1. Try GitHub App first
2. Fall back to PAT if GitHub App fails
3. Log which method it's using

### 2. Test GitHub App

```bash
# Restart services
sudo systemctl restart moveware-ai-worker

# Watch logs
sudo journalctl -u moveware-ai-worker -f

# Should see:
# ✓ GitHub App authentication initialized (App ID: 123456)
```

### 3. Process a Test Issue

Create a test Jira issue and verify:
- PR is created successfully
- PR shows GitHub App as author
- No errors in logs

### 4. Remove PAT (Optional)

Once confirmed working:

```bash
sudo nano /etc/moveware-ai.env
# Comment out or remove: GH_TOKEN=...
```

---

## Monitoring

### Check Token Status

The AI Runner automatically:
- ✅ Generates JWT tokens (10 min validity)
- ✅ Requests installation tokens (1 hour validity)
- ✅ Refreshes tokens before expiry (5 min buffer)
- ✅ Logs token refresh events

### View Logs

```bash
# Watch for GitHub App events
sudo journalctl -u moveware-ai-worker -f | grep -i "github\|token"

# Look for:
# - "GitHub App authentication initialized"
# - "Refreshing GitHub App installation token"
```

### GitHub Audit Log

View all GitHub App activity:
```
https://github.com/organizations/YOUR-ORG/settings/audit-log
```

Filter by:
- **Action:** `integration.*`
- Shows all actions performed by your GitHub App

---

## Advanced Configuration

### Multiple GitHub Apps

If you need different apps for different repos:

```python
# In app/github_app.py, modify to support per-repo apps
# (Future enhancement - not currently implemented)
```

### Custom Token Refresh Interval

Default: Refresh when < 5 minutes remaining

To customize, modify `app/github_app.py`:

```python
def is_expired(self) -> bool:
    """Check if token is expired (with buffer)."""
    buffer_minutes = 5  # Change this
    return datetime.now() >= self.expires_at - timedelta(minutes=buffer_minutes)
```

### Revoke Access

To revoke GitHub App access:

1. **Temporarily:** Suspend the app installation
   ```
   https://github.com/organizations/YOUR-ORG/settings/installations
   → Configure → Suspend
   ```

2. **Permanently:** Delete the app
   ```
   https://github.com/organizations/YOUR-ORG/settings/apps/YOUR-APP
   → Advanced → Delete GitHub App
   ```

---

## Security Best Practices

1. ✅ **Store private key securely**
   - Restrict to `moveware-ai` user only (chmod 600)
   - Never commit to git
   - Backup in secure password manager

2. ✅ **Use minimal permissions**
   - Only grant what's needed (Contents + PRs)
   - Don't grant admin or org permissions

3. ✅ **Monitor usage**
   - Check GitHub audit logs regularly
   - Watch for unexpected activity

4. ✅ **Rotate keys periodically**
   - Generate new private key every 6-12 months
   - Update on server and test before deleting old key

5. ✅ **Limit installation scope**
   - Only install on needed repos
   - Don't use "All repositories" unless necessary

---

## Comparison: PAT vs GitHub App

| Feature | Personal Access Token | GitHub App |
|---------|----------------------|------------|
| **Multi-repo access** | ✅ Yes | ✅ Yes |
| **Audit trail** | ❌ Shows as you | ✅ Shows as App |
| **Token rotation** | ❌ Manual | ✅ Automatic (1h) |
| **Fine-grained permissions** | ❌ No | ✅ Yes |
| **Revocation** | ❌ Affects all uses | ✅ App-specific |
| **Organization-wide** | ❌ Per-user | ✅ Per-org |
| **Setup complexity** | ✅ Simple | ⚠️ More steps |
| **GitHub recommendation** | ❌ Not for automation | ✅ Yes |

---

## Summary

### To enable GitHub App:

1. ✅ Create GitHub App in your organization
2. ✅ Set permissions (Contents + PRs: Read & Write)
3. ✅ Generate and download private key
4. ✅ Install app in your organization
5. ✅ Note App ID and Installation ID
6. ✅ Copy private key to server (`/srv/ai/.ssh/`)
7. ✅ Update environment variables
8. ✅ Install new dependencies
9. ✅ Restart services
10. ✅ Verify in logs

### Result:
- ✅ More secure authentication
- ✅ Better audit trail
- ✅ Auto-rotating tokens
- ✅ Fine-grained permissions
- ✅ Organization-wide management

Your AI Runner is now using enterprise-grade GitHub authentication! 🔐
