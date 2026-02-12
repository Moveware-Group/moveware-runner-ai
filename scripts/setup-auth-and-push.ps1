# Setup GitHub authentication and push pending changes
#
# This script will:
# 1. Prompt for GitHub token (or use existing)
# 2. Configure git to use the token
# 3. Push changes to remote
# 4. Save token for future use

param(
    [string]$Token,
    [switch]$UseGitHubApp
)

Write-Host "🔐 GitHub Authentication Setup" -ForegroundColor Cyan
Write-Host "================================`n" -ForegroundColor Cyan

# Check if there are commits to push
$ahead = git rev-list --count origin/main..HEAD 2>$null
if ($LASTEXITCODE -ne 0) {
    $ahead = git rev-list --count HEAD 2>$null
}

if ($ahead -eq 0) {
    Write-Host "✓ No commits to push" -ForegroundColor Green
    exit 0
}

Write-Host "📊 You have $ahead commit(s) waiting to be pushed`n" -ForegroundColor Yellow

# Option 1: GitHub App (if configured)
if ($UseGitHubApp) {
    Write-Host "🤖 Using GitHub App authentication..." -ForegroundColor Cyan
    
    # Check if GitHub App is configured
    if (-not (Test-Path ".env")) {
        Write-Host "❌ No .env file found. GitHub App requires configuration." -ForegroundColor Red
        Write-Host "`nCreate .env file with:" -ForegroundColor Yellow
        Write-Host "GITHUB_APP_ID=your_app_id" -ForegroundColor Gray
        Write-Host "GITHUB_APP_INSTALLATION_ID=your_installation_id" -ForegroundColor Gray
        Write-Host "GITHUB_APP_PRIVATE_KEY_PATH=path/to/private-key.pem" -ForegroundColor Gray
        exit 1
    }
    
    # Try to get token from GitHub App
    Write-Host "Getting token from GitHub App..." -ForegroundColor Gray
    $Token = python -c "from app.github_app import get_github_token; print(get_github_token())" 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to get GitHub App token" -ForegroundColor Red
        Write-Host "Error: $Token" -ForegroundColor Red
        Write-Host "`nTry using a Personal Access Token instead:" -ForegroundColor Yellow
        Write-Host "  .\scripts\setup-auth-and-push.ps1" -ForegroundColor Gray
        exit 1
    }
    
    Write-Host "✓ Got token from GitHub App" -ForegroundColor Green
}

# Option 2: Personal Access Token
if (-not $Token) {
    Write-Host "📝 Personal Access Token Required" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To push changes, you need a GitHub Personal Access Token with 'repo' scope." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Create one at: https://github.com/settings/tokens" -ForegroundColor Cyan
    Write-Host "  1. Click 'Generate new token' → 'Generate new token (classic)'" -ForegroundColor Gray
    Write-Host "  2. Name: moveware-runner-ai-local" -ForegroundColor Gray
    Write-Host "  3. Select scope: [x] repo (Full control of private repositories)" -ForegroundColor Gray
    Write-Host "  4. Click 'Generate token' and copy it" -ForegroundColor Gray
    Write-Host ""
    
    # Prompt for token
    $TokenInput = Read-Host "Paste your GitHub token here (input hidden)" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($TokenInput)
    $Token = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    
    if (-not $Token -or $Token.Length -lt 10) {
        Write-Host "❌ Invalid token provided" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "✓ Token received" -ForegroundColor Green
}

# Configure git remote with token
Write-Host "`n🔧 Configuring git remote..." -ForegroundColor Cyan

$remoteUrl = "https://x-access-token:$Token@github.com/Moveware-Group/moveware-runner-ai.git"
git remote set-url origin $remoteUrl

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to update git remote" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Git remote configured" -ForegroundColor Green

# Test authentication
Write-Host "`n🔍 Testing authentication..." -ForegroundColor Cyan
$testResult = git ls-remote origin HEAD 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Authentication test failed" -ForegroundColor Red
    Write-Host "Error: $testResult" -ForegroundColor Red
    Write-Host "`nPlease check:" -ForegroundColor Yellow
    Write-Host "  - Token is valid and not expired" -ForegroundColor Gray
    Write-Host "  - Token has 'repo' scope" -ForegroundColor Gray
    Write-Host "  - You have write access to Moveware-Group/moveware-runner-ai" -ForegroundColor Gray
    exit 1
}

Write-Host "✓ Authentication successful" -ForegroundColor Green

# Show what will be pushed
Write-Host "`n📤 Commits to be pushed:" -ForegroundColor Cyan
git log --oneline origin/main..HEAD

# Push to remote
Write-Host "`n🚀 Pushing to GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Push failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ Successfully pushed to GitHub!" -ForegroundColor Green

# Save token to environment for future use (this session only)
$env:GITHUB_TOKEN = $Token

Write-Host "`n💡 Token saved to `$env:GITHUB_TOKEN for this session" -ForegroundColor Cyan
Write-Host ""
Write-Host "To save permanently, add to your PowerShell profile:" -ForegroundColor Yellow
Write-Host "  `$env:GITHUB_TOKEN = 'your_token_here'" -ForegroundColor Gray
Write-Host ""
Write-Host "Or for better security, set up a GitHub App:" -ForegroundColor Yellow
Write-Host "  See: GITHUB_AUTH_SETUP.md" -ForegroundColor Gray
Write-Host ""

# Show next steps
Write-Host "🎯 Next steps:" -ForegroundColor Cyan
Write-Host "  1. Deploy to production:" -ForegroundColor Yellow
Write-Host "     ssh moveware-ai-runner-01" -ForegroundColor Gray
Write-Host "     cd /srv/ai/app" -ForegroundColor Gray
Write-Host "     sudo -u moveware-ai git pull origin main" -ForegroundColor Gray
Write-Host "     sudo -u moveware-ai bash scripts/restore_git_ops.sh" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Check worker status:" -ForegroundColor Yellow
Write-Host "     sudo systemctl status moveware-ai-worker" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Reset stuck TB-16 run:" -ForegroundColor Yellow
Write-Host "     sudo -u moveware-ai python3 scripts/check_stuck_runs.py --issue TB-16 --reset" -ForegroundColor Gray
Write-Host ""
