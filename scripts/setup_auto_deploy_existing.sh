#!/bin/bash
#
# Setup Auto-Deploy for Existing Next.js App
# Usage: sudo ./setup_auto_deploy_existing.sh
#
# This script assumes:
# - Repository already cloned
# - NGINX already configured
# - Just needs PM2 and auto-deploy watcher
#

set -e

if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "=================================================="
echo "Next.js Auto-Deploy Setup (Existing App)"
echo "=================================================="

# Configuration
APP_DIR="/srv/ai/repos/online-docs"
APP_NAME="online-docs"
APP_USER="moveware-ai"
APP_PORT="3000"

echo ""
echo "Configuration:"
echo "  App Directory: $APP_DIR"
echo "  App Name: $APP_NAME"
echo "  User: $APP_USER"
echo "  Port: $APP_PORT"
echo ""

read -p "Continue with this configuration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# 1. Check if directory exists
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: Directory $APP_DIR does not exist"
    echo "Please verify the path or run: git clone git@github.com:leigh-moveware/online-docs.git $APP_DIR"
    exit 1
fi

echo "✅ App directory exists"

# 2. Install PM2 globally if not installed
echo ""
echo "📦 Checking PM2..."
if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    npm install -g pm2
    echo "✅ PM2 installed"
else
    echo "✅ PM2 already installed"
fi

# 3. Setup PM2 to start on boot
echo ""
echo "🔧 Configuring PM2 startup..."
sudo -u $APP_USER pm2 startup systemd -u $APP_USER --hp /home/$APP_USER | grep "sudo" | bash || true

# 4. Create logs directory
mkdir -p "$APP_DIR/logs"
chown $APP_USER:$APP_USER "$APP_DIR/logs"

# 5. Create PM2 ecosystem config
echo ""
echo "📝 Creating PM2 ecosystem config..."
cat > "$APP_DIR/ecosystem.config.js" << EOF
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
      PORT: $APP_PORT
    },
    error_file: '$APP_DIR/logs/pm2-error.log',
    out_file: '$APP_DIR/logs/pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    merge_logs: true,
    time: true
  }]
}
EOF
chown $APP_USER:$APP_USER "$APP_DIR/ecosystem.config.js"

# 6. Initial deployment
echo ""
echo "🚀 Running initial deployment..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo -u $APP_USER bash "$SCRIPT_DIR/deploy_nextjs_app.sh" "$APP_DIR" "$APP_NAME" "$APP_PORT"

# 7. Setup auto-deployment service
echo ""
echo "🔧 Setting up auto-deployment service..."

cat > /etc/systemd/system/online-docs-auto-deploy.service << EOF
[Unit]
Description=Online Docs Auto-Deploy Service
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$SCRIPT_DIR/watch_and_deploy.sh $APP_DIR $APP_NAME $APP_PORT
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=online-docs-deploy

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Make scripts executable
chmod +x "$SCRIPT_DIR/deploy_nextjs_app.sh"
chmod +x "$SCRIPT_DIR/watch_and_deploy.sh"

# Reload systemd and start service
systemctl daemon-reload
systemctl enable online-docs-auto-deploy
systemctl start online-docs-auto-deploy

echo ""
echo "=================================================="
echo "✅ Setup Complete!"
echo "=================================================="
echo ""
echo "Your Next.js app is now:"
echo "  ✅ Running with PM2 at http://localhost:$APP_PORT"
echo "  ✅ Auto-deploying on git push"
echo "  ✅ NGINX already configured (no changes made)"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status online-docs-auto-deploy  # Check auto-deploy status"
echo "  sudo journalctl -u online-docs-auto-deploy -f   # Watch deployment logs"
echo "  sudo -u $APP_USER pm2 status                     # Check PM2 status"
echo "  sudo -u $APP_USER pm2 logs $APP_NAME             # View app logs"
echo "  sudo -u $APP_USER pm2 restart $APP_NAME          # Manual restart"
echo ""
echo "Manual deployment:"
echo "  sudo -u $APP_USER $SCRIPT_DIR/deploy_nextjs_app.sh $APP_DIR $APP_NAME $APP_PORT"
echo ""
