#!/bin/bash
# Safe deployment script with validation
#
# This script safely deploys changes to the production server by:
# 1. Pulling latest changes
# 2. Validating all Python files compile correctly
# 3. Rolling back if validation fails
# 4. Restarting services only if validation passes
#
# Usage: bash scripts/safe_deploy.sh

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 Starting safe deployment..."
echo "Project root: $PROJECT_ROOT"
echo ""

# Change to project directory
cd "$PROJECT_ROOT"

# Save current commit hash for rollback
CURRENT_COMMIT=$(git rev-parse HEAD)
echo "📍 Current commit: $CURRENT_COMMIT"

# Pull latest changes
echo ""
echo "📥 Pulling latest changes..."
git pull origin main

NEW_COMMIT=$(git rev-parse HEAD)
echo "📍 New commit: $NEW_COMMIT"

if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
    echo "ℹ️  No new changes to deploy"
    exit 0
fi

# Show what changed
echo ""
echo "📝 Changes:"
git log --oneline "$CURRENT_COMMIT..$NEW_COMMIT"
echo ""

# Validate all Python files
echo "🔍 Validating Python files..."
VALIDATION_FAILED=0

while IFS= read -r file; do
    if [ -f "$file" ]; then
        if ! python3 -m py_compile "$file" 2>/dev/null; then
            echo "❌ Syntax error in: $file"
            VALIDATION_FAILED=1
        else
            echo "✓ Valid: $file"
        fi
    fi
done < <(find app -name "*.py" -type f)

# If validation failed, rollback
if [ $VALIDATION_FAILED -eq 1 ]; then
    echo ""
    echo "❌ Validation failed! Rolling back to previous commit..."
    git reset --hard "$CURRENT_COMMIT"
    echo "✓ Rolled back to $CURRENT_COMMIT"
    echo ""
    echo "Please fix the syntax errors and try again."
    exit 1
fi

echo ""
echo "✅ All Python files validated successfully"

# Check if running as moveware-ai user or with sudo
if [ "$(whoami)" = "moveware-ai" ] || [ -n "$SUDO_USER" ]; then
    # Restart services
    echo ""
    echo "🔄 Restarting services..."
    
    if [ "$(whoami)" = "moveware-ai" ]; then
        # Running as moveware-ai, need sudo for systemctl
        echo "Restarting moveware-ai-worker..."
        sudo systemctl restart moveware-ai-worker
        
        echo "Restarting moveware-ai-orchestrator..."
        sudo systemctl restart moveware-ai-orchestrator
    else
        # Running with sudo or as root
        systemctl restart moveware-ai-worker
        systemctl restart moveware-ai-orchestrator
    fi
    
    # Wait for services to start
    sleep 3
    
    # Check service status
    echo ""
    echo "📊 Service status:"
    systemctl status moveware-ai-worker --no-pager -l | head -n 15
    echo ""
    systemctl status moveware-ai-orchestrator --no-pager -l | head -n 15
    
    # Check for errors in recent logs
    echo ""
    echo "📋 Recent worker logs (last 20 lines):"
    journalctl -u moveware-ai-worker --no-pager -n 20
    
else
    echo ""
    echo "⚠️  Not running as moveware-ai or with sudo"
    echo "To restart services, run:"
    echo "  sudo systemctl restart moveware-ai-worker"
    echo "  sudo systemctl restart moveware-ai-orchestrator"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "To monitor the worker:"
echo "  sudo journalctl -u moveware-ai-worker -f"
echo ""
echo "To check dashboard:"
echo "  https://ai-console.moveconnect.com/status"
