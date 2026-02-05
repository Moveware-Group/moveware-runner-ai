#!/bin/bash
#
# Deploy Next.js app - Build and restart with PM2
# Usage: ./deploy_nextjs_app.sh [app_directory]
#
# This script:
# 1. Pulls latest code from git
# 2. Runs npm install
# 3. Runs npm run build
# 4. Restarts the app with PM2
#

set -e  # Exit on error

APP_DIR="${1:-/srv/online-docs}"
APP_NAME="${2:-online-docs}"
PORT="${3:-3000}"

echo "=================================================="
echo "Deploying Next.js App: $APP_NAME"
echo "Directory: $APP_DIR"
echo "Port: $PORT"
echo "=================================================="

# Check if directory exists
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: Directory $APP_DIR does not exist"
    exit 1
fi

cd "$APP_DIR"

# Check if it's a git repository
if [ ! -d ".git" ]; then
    echo "ERROR: $APP_DIR is not a git repository"
    exit 1
fi

# Pull latest code
echo ""
echo "📥 Pulling latest code from git..."
git fetch --all
git pull origin main

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
npm install --production=false

# Build the application
echo ""
echo "🔨 Building Next.js application..."
npm run build

# Check if PM2 is installed
if ! command -v pm2 &> /dev/null; then
    echo "ERROR: PM2 is not installed. Install with: npm install -g pm2"
    exit 1
fi

# Check if ecosystem file exists
ECOSYSTEM_FILE="$APP_DIR/ecosystem.config.js"
if [ ! -f "$ECOSYSTEM_FILE" ]; then
    echo ""
    echo "⚠️  No ecosystem.config.js found. Creating default configuration..."
    cat > "$ECOSYSTEM_FILE" << EOF
module.exports = {
  apps: [{
    name: '$APP_NAME',
    script: 'npm',
    args: 'start',
    cwd: '$APP_DIR',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production',
      PORT: $PORT
    },
    error_file: '$APP_DIR/logs/pm2-error.log',
    out_file: '$APP_DIR/logs/pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
  }]
}
EOF
    mkdir -p "$APP_DIR/logs"
fi

# Start or restart with PM2
echo ""
echo "🚀 Managing application with PM2..."

# Check if app is already running
if pm2 describe "$APP_NAME" > /dev/null 2>&1; then
    echo "   Restarting existing PM2 process..."
    pm2 restart "$APP_NAME"
else
    echo "   Starting new PM2 process..."
    pm2 start "$ECOSYSTEM_FILE"
fi

# Save PM2 process list
pm2 save

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Useful PM2 commands:"
echo "  pm2 status              - Show all processes"
echo "  pm2 logs $APP_NAME      - View logs"
echo "  pm2 restart $APP_NAME   - Restart app"
echo "  pm2 stop $APP_NAME      - Stop app"
echo "  pm2 delete $APP_NAME    - Remove app from PM2"
echo ""
