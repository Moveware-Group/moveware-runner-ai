#!/bin/bash
#
# Auto-deployment script for Moveware AI Runner
# Triggered by GitHub webhook when code is pushed to main
#

set -e  # Exit on error

# Configuration
APP_DIR="/srv/ai/app"
LOG_FILE="/srv/ai/logs/deploy.log"
USER="moveware-ai"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $1${NC}" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] ℹ $1${NC}" | tee -a "$LOG_FILE"
}

# Start deployment
log_info "🚀 Starting auto-deployment..."

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

# Change to app directory
cd "$APP_DIR" || {
    log_error "Failed to change to $APP_DIR"
    exit 1
}

# Check if we're the right user
CURRENT_USER=$(whoami)
if [ "$CURRENT_USER" != "root" ]; then
    log_error "This script must be run as root (to restart services)"
    exit 1
fi

# Stash any local changes (shouldn't be any)
log "Stashing local changes (if any)..."
sudo -u "$USER" git stash

# Pull latest code
log "Pulling latest code from origin..."
sudo -u "$USER" git pull origin main || {
    log_error "Git pull failed"
    exit 1
}

# Get the latest commit info
LATEST_COMMIT=$(sudo -u "$USER" git log -1 --pretty=format:"%h - %s (%an)")
log_success "Updated to: $LATEST_COMMIT"

# Install/update dependencies
log "Updating Python dependencies..."
sudo -u "$USER" .venv/bin/pip install -r requirements.txt --quiet || {
    log_error "Failed to install dependencies"
    exit 1
}

# Run database migrations (if any)
log "Running database initialization..."
sudo -u "$USER" .venv/bin/python -c "from app.db import init_db; init_db()"

# Validate configuration
log "Validating configuration..."
if ! sudo -u "$USER" .venv/bin/python validate_config.py > /dev/null 2>&1; then
    log_error "Configuration validation failed"
    # Don't exit - continue with restart anyway
fi

# Restart services
log "Restarting services..."

# Restart orchestrator (webhook receiver)
systemctl restart moveware-ai-orchestrator
if [ $? -eq 0 ]; then
    log_success "Orchestrator restarted"
else
    log_error "Failed to restart orchestrator"
fi

# Restart worker
systemctl restart moveware-ai-worker
if [ $? -eq 0 ]; then
    log_success "Worker restarted"
else
    log_error "Failed to restart worker"
fi

# Wait a moment for services to start
sleep 2

# Check service status
if systemctl is-active --quiet moveware-ai-orchestrator && \
   systemctl is-active --quiet moveware-ai-worker; then
    log_success "✅ Deployment completed successfully!"
    log_success "Commit: $LATEST_COMMIT"
else
    log_error "❌ Services may not be running correctly. Check status manually."
    exit 1
fi

# Clean up old logs (keep last 30 days)
find /srv/ai/logs -name "deploy.log.*" -mtime +30 -delete 2>/dev/null || true

exit 0
