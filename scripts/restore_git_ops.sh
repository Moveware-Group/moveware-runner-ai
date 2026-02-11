#!/bin/bash
# Emergency restoration script for corrupted git_ops.py
# 
# This script restores git_ops.py from the git repository
# Usage: bash scripts/restore_git_ops.sh

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="${PROJECT_ROOT}/app"
TARGET_FILE="${APP_DIR}/git_ops.py"

echo "🔧 Restoring git_ops.py from git repository..."

# Check if we're in a git repo
if [ ! -d "${PROJECT_ROOT}/.git" ]; then
    echo "❌ Error: Not in a git repository"
    exit 1
fi

# Backup corrupted file if it exists
if [ -f "$TARGET_FILE" ]; then
    BACKUP_FILE="${TARGET_FILE}.corrupted.$(date +%Y%m%d_%H%M%S)"
    echo "📦 Backing up corrupted file to: $BACKUP_FILE"
    cp "$TARGET_FILE" "$BACKUP_FILE"
fi

# Restore from git
echo "♻️  Restoring from git..."
cd "$PROJECT_ROOT"
git checkout HEAD -- app/git_ops.py

# Verify the file is valid Python
echo "🔍 Verifying restored file..."
if python3 -m py_compile "$TARGET_FILE"; then
    echo "✅ File restored successfully and syntax is valid"
    
    # Show first 3 lines to confirm
    echo ""
    echo "First 3 lines of restored file:"
    head -n 3 "$TARGET_FILE"
    
    # Restart worker service if running on server
    if systemctl is-active --quiet moveware-ai-worker 2>/dev/null; then
        echo ""
        echo "🔄 Restarting moveware-ai-worker service..."
        sudo systemctl restart moveware-ai-worker
        sleep 2
        systemctl status moveware-ai-worker --no-pager -l
    fi
else
    echo "❌ Error: Restored file has syntax errors"
    exit 1
fi

echo ""
echo "✅ Recovery complete!"
echo ""
echo "Next steps:"
echo "1. Check worker status: systemctl status moveware-ai-worker"
echo "2. Check worker logs: journalctl -u moveware-ai-worker -f"
echo "3. Check for stuck TB-16 run: Check database or Jira"
