# Simple script to push with GitHub authentication
# Usage: .\scripts\push-with-auth.ps1

Write-Host "GitHub Authentication and Push" -ForegroundColor Cyan
Write-Host "==============================`n" -ForegroundColor Cyan

# Check for pending commits
$pendingCommits = git log --oneline origin/main..HEAD 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Warning: Could not compare with origin/main" -ForegroundColor Yellow
    $pendingCommits = git log --oneline HEAD -n 5
}

Write-Host "Pending commits to push:" -ForegroundColor Yellow
Write-Host $pendingCommits
Write-Host ""

# Prompt for token
Write-Host "You need a GitHub Personal Access Token to push." -ForegroundColor Cyan
Write-Host "Create one at: https://github.com/settings/tokens" -ForegroundColor Cyan
Write-Host "Required scope: repo (Full control of private repositories)`n" -ForegroundColor Gray

$tokenSecure = Read-Host "Enter your GitHub token" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenSecure)
$token = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)

if (-not $token) {
    Write-Host "No token provided. Exiting." -ForegroundColor Red
    exit 1
}

# Configure remote
Write-Host "`nConfiguring git remote..." -ForegroundColor Cyan
$remoteUrl = "https://x-access-token:$token@github.com/Moveware-Group/moveware-runner-ai.git"
git remote set-url origin $remoteUrl

# Test authentication
Write-Host "Testing authentication..." -ForegroundColor Cyan
git ls-remote origin HEAD 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Authentication failed. Check your token." -ForegroundColor Red
    exit 1
}

Write-Host "Authentication successful!" -ForegroundColor Green

# Push
Write-Host "`nPushing to GitHub..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nSuccessfully pushed!" -ForegroundColor Green
    Write-Host "`nNext: Deploy to production server" -ForegroundColor Yellow
} else {
    Write-Host "`nPush failed" -ForegroundColor Red
    exit 1
}
