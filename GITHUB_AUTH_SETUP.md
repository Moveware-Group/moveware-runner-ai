# GitHub Authentication Setup Guide

## Current Issue

Git is using cached credentials from "netninjasdev" user which doesn't have write access to Moveware-Group/moveware-runner-ai.

Error:
```
remote: Permission to Moveware-Group/moveware-runner-ai.git denied to netninjasdev.
fatal: unable to access 'https://github.com/Moveware-Group/moveware-runner-ai.git/': The requested URL returned error: 403
```

## Quick Fix: Clear Cached Credentials and Use PAT

### Step 1: Clear Cached Credentials

```powershell
# Remove GitHub credentials from Windows Credential Manager
cmdkey /list | Select-String "github" | ForEach-Object {
    if ($_ -match "Target: (.+)") {
        cmdkey /delete:$($matches[1])
    }
}

# Or manually:
# 1. Press Win + R
# 2. Type: control /name Microsoft.CredentialManager
# 3. Find and remove any github.com credentials
```

### Step 2: Create GitHub Personal Access Token (PAT)

1. Go to GitHub: https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Name: `moveware-runner-ai-local`
4. Select scopes:
   - [x] **repo** (Full control of private repositories)
   - [x] **workflow** (Update GitHub Action workflows)
5. Click "Generate token"
6. **Copy the token immediately** (you won't see it again)

### Step 3: Configure Git to Use Token

```powershell
# Set the token as environment variable (this session only)
$env:GITHUB_TOKEN = "your_token_here"

# Or add to your PowerShell profile for persistence
Add-Content $PROFILE "`n`$env:GITHUB_TOKEN = 'your_token_here'"

# Update git remote to use token
git remote set-url origin "https://$env:GITHUB_TOKEN@github.com/Moveware-Group/moveware-runner-ai.git"

# Or if you prefer to keep the remote as-is, Git will prompt for credentials and use the token
```

### Step 4: Test and Push

```powershell
# Test authentication
git ls-remote origin

# Push your changes
git push origin main
```

## Recommended: GitHub App (Better for Organizations)

For production use with the Moveware-Group organization, a GitHub App is more secure and provides better audit trails.

### Benefits of GitHub App vs PAT:

- ✅ Fine-grained permissions per repository
- ✅ Tokens expire and auto-rotate
- ✅ Better audit trail in GitHub
- ✅ Can't be used to access other repos
- ✅ Organization admins have more control

### Setup GitHub App for Moveware-Group

#### 1. Create GitHub App

1. Go to: https://github.com/organizations/Moveware-Group/settings/apps
2. Click "New GitHub App"
3. Fill in:
   - **Name**: `moveware-runner-ai-bot`
   - **Homepage URL**: `https://ai-console.moveconnect.com`
   - **Webhook**: Uncheck "Active" (not needed for this use case)
   - **Repository permissions**:
     - Contents: **Read and write**
     - Pull requests: **Read and write**
     - Metadata: **Read-only** (automatically selected)
   - **Where can this GitHub App be installed?**: Only on this account
4. Click "Create GitHub App"
5. Note the **App ID** (you'll need this)

#### 2. Generate Private Key

1. On the app settings page, scroll to "Private keys"
2. Click "Generate a private key"
3. Save the downloaded `.pem` file securely
4. Move it to: `~/.ssh/github-app-moveware.pem`

#### 3. Install the App

1. On the app settings page, click "Install App" in left sidebar
2. Select "Moveware-Group" organization
3. Choose:
   - **All repositories**, OR
   - **Only select repositories** → Select `moveware-runner-ai`
4. Click "Install"
5. Note the **Installation ID** from the URL:
   ```
   https://github.com/organizations/Moveware-Group/settings/installations/12345678
                                                                          ^^^^^^^^
   ```

#### 4. Configure Locally

Create `.env` file in project root:

```bash
# GitHub App Configuration
GITHUB_APP_ID=123456
GITHUB_APP_INSTALLATION_ID=12345678
GITHUB_APP_PRIVATE_KEY_PATH=C:\Users\Leigh.Morrow\.ssh\github-app-moveware.pem

# Or use the private key content directly (base64 encoded):
# GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
```

#### 5. Test GitHub App Authentication

```powershell
# Test that the app can authenticate
cd C:\Users\Leigh.Morrow\Documents\GitHub\moveware-runner-ai

# Run Python to test
python -c "from app.github_app import get_github_token; print('Token:', get_github_token()[:20] + '...')"
```

#### 6. Update Git Remote for GitHub App

```powershell
# Get token from GitHub App
$token = python -c "from app.github_app import get_github_token; print(get_github_token())"

# Update remote to use token
git remote set-url origin "https://x-access-token:$token@github.com/Moveware-Group/moveware-runner-ai.git"

# Push
git push origin main
```

## Automated Push Script (For Future Use)

Create `scripts/push.ps1`:

```powershell
# Automated push with GitHub App authentication

# Get token from GitHub App
$token = python -c "from app.github_app import get_github_token; print(get_github_token())"

if ($LASTEXITCODE -ne 0 -or -not $token) {
    Write-Error "Failed to get GitHub token. Check GitHub App configuration."
    exit 1
}

# Update remote URL with token
git remote set-url origin "https://x-access-token:$token@github.com/Moveware-Group/moveware-runner-ai.git"

# Push to main
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Output "✅ Successfully pushed to GitHub"
} else {
    Write-Error "❌ Push failed"
    exit 1
}
```

Then use:
```powershell
.\scripts\push.ps1
```

## Production Server Setup

On the production server (moveware-ai-runner-01), the GitHub App is already configured because it needs to create PRs and push code.

Check server configuration:
```bash
# Check if GitHub App is configured
ssh moveware-ai-runner-01
cat /srv/ai/app/.env | grep GITHUB_APP

# Should show:
# GITHUB_APP_ID=...
# GITHUB_APP_INSTALLATION_ID=...
# GITHUB_APP_PRIVATE_KEY_PATH=/srv/ai/.ssh/github-app-private-key.pem
```

## Troubleshooting

### "Permission denied" errors

1. **Check which user is cached**:
   ```powershell
   git credential-manager get <<EOF
   protocol=https
   host=github.com
   EOF
   ```

2. **Clear and retry**:
   ```powershell
   git credential-manager erase <<EOF
   protocol=https
   host=github.com
   EOF
   ```

3. **Verify token permissions**:
   - Go to: https://github.com/settings/tokens
   - Check token has `repo` scope
   - For organization repos, check organization settings allow the token

### GitHub App issues

1. **Token generation fails**:
   - Check App ID is correct
   - Check Installation ID is correct
   - Verify private key file exists and is readable
   - Check private key format (should start with `-----BEGIN RSA PRIVATE KEY-----`)

2. **Permission errors with GitHub App**:
   - Check app is installed on the repository
   - Verify app has "Contents: Read and write" permission
   - Check organization settings allow the app

### Git credential helper issues

```powershell
# Check current helper
git config --global credential.helper

# If using 'manager', credentials are cached in Windows Credential Manager
# To disable caching temporarily:
git config --global --unset credential.helper

# To use token from environment:
git config --global credential.helper store
```

## Security Best Practices

1. **Never commit tokens or private keys to git**
   - Add `.env` to `.gitignore` ✅ (already done)
   - Keep private keys in `~/.ssh/` with proper permissions

2. **Use GitHub App instead of PAT for production**
   - Better security
   - Fine-grained permissions
   - Auto-rotating tokens

3. **Limit token scope**
   - Only grant necessary permissions
   - Use separate tokens for different purposes
   - Regularly rotate tokens

4. **Store secrets securely**
   - Use environment variables
   - Use secret management tools (Azure Key Vault, AWS Secrets Manager)
   - Never hardcode in scripts

## Next Steps

After setting up authentication:

1. ✅ Clear cached credentials
2. ✅ Set up PAT or GitHub App
3. ✅ Test authentication: `git ls-remote origin`
4. ✅ Push changes: `git push origin main`
5. ✅ Verify on GitHub: https://github.com/Moveware-Group/moveware-runner-ai/commits/main
6. ✅ Deploy to server: `ssh moveware-ai-runner-01` → `cd /srv/ai/app` → `git pull`
