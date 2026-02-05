#!/bin/bash
#
# Watch for git changes and auto-deploy Next.js app
# Usage: ./watch_and_deploy.sh [app_directory] [app_name] [port]
#
# This script continuously monitors the git repository for changes
# and automatically triggers deployment when new commits are detected.
#

set -e

APP_DIR="${1:-/srv/online-docs}"
APP_NAME="${2:-online-docs}"
PORT="${3:-3000}"
CHECK_INTERVAL=30  # Check every 30 seconds

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy_nextjs_app.sh"

echo "=================================================="
echo "Auto-Deploy Watcher for: $APP_NAME"
echo "Directory: $APP_DIR"
echo "Check interval: ${CHECK_INTERVAL}s"
echo "=================================================="

# Verify directory exists
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: Directory $APP_DIR does not exist"
    exit 1
fi

cd "$APP_DIR"

# Verify deploy script exists
if [ ! -f "$DEPLOY_SCRIPT" ]; then
    echo "ERROR: Deploy script not found at $DEPLOY_SCRIPT"
    exit 1
fi

# Get initial commit hash
LAST_COMMIT=$(git rev-parse HEAD)
echo "Initial commit: $LAST_COMMIT"
echo ""

while true; do
    # Fetch latest from remote (silent)
    git fetch --quiet origin main 2>/dev/null || true
    
    # Get latest commit on remote
    REMOTE_COMMIT=$(git rev-parse origin/main)
    
    # Check if remote has new commits
    if [ "$LAST_COMMIT" != "$REMOTE_COMMIT" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔔 New commits detected!"
        echo "  Old: $LAST_COMMIT"
        echo "  New: $REMOTE_COMMIT"
        echo ""
        
        # Trigger deployment
        echo "⚡ Triggering deployment..."
        if bash "$DEPLOY_SCRIPT" "$APP_DIR" "$APP_NAME" "$PORT"; then
            echo ""
            echo "✅ Deployment successful!"
            LAST_COMMIT=$REMOTE_COMMIT
        else
            echo ""
            echo "❌ Deployment failed! Will retry on next check."
        fi
        echo ""
    fi
    
    # Wait before next check
    sleep $CHECK_INTERVAL
done
