#!/bin/bash
#
# Setup Next.js Auto-Deployment System
# Usage: sudo ./setup_nextjs_deployment.sh
#
# This script installs and configures:
# - PM2 for process management
# - Auto-deployment service
# - NGINX configuration
#

set -e

if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "=================================================="
echo "Next.js Auto-Deployment Setup"
echo "=================================================="

# Configuration
APP_DIR="/srv/online-docs"
APP_NAME="online-docs"
APP_USER="moveware-ai"
APP_PORT="3000"
DOMAIN="oa.holdingsite.com.au"

echo ""
echo "Configuration:"
echo "  App Directory: $APP_DIR"
echo "  App Name: $APP_NAME"
echo "  User: $APP_USER"
echo "  Port: $APP_PORT"
echo "  Domain: $DOMAIN"
echo ""

read -p "Continue with this configuration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# 1. Install PM2 globally
echo ""
echo "📦 Installing PM2..."
if ! command -v pm2 &> /dev/null; then
    npm install -g pm2
    echo "✅ PM2 installed"
else
    echo "✅ PM2 already installed"
fi

# 2. Setup PM2 to start on boot for moveware-ai user
echo ""
echo "🔧 Configuring PM2 startup..."
sudo -u $APP_USER pm2 startup systemd -u $APP_USER --hp /home/$APP_USER | grep "sudo" | bash

# 3. Create app directory if it doesn't exist
if [ ! -d "$APP_DIR" ]; then
    echo ""
    echo "📁 Creating app directory..."
    mkdir -p "$APP_DIR"
    chown $APP_USER:$APP_USER "$APP_DIR"
    
    # Clone repository
    echo "📥 Cloning repository..."
    sudo -u $APP_USER git clone git@github.com:leigh-moveware/online-docs.git "$APP_DIR"
fi

# 4. Create logs directory
mkdir -p "$APP_DIR/logs"
chown $APP_USER:$APP_USER "$APP_DIR/logs"

# 5. Copy ecosystem config
echo ""
echo "📝 Creating PM2 ecosystem config..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo -u $APP_USER cp "$SCRIPT_DIR/ecosystem.config.js" "$APP_DIR/"

# Update ecosystem config with actual values
sudo -u $APP_USER sed -i "s|name: 'online-docs'|name: '$APP_NAME'|g" "$APP_DIR/ecosystem.config.js"
sudo -u $APP_USER sed -i "s|cwd: '/srv/online-docs'|cwd: '$APP_DIR'|g" "$APP_DIR/ecosystem.config.js"
sudo -u $APP_USER sed -i "s|PORT: 3000|PORT: $APP_PORT|g" "$APP_DIR/ecosystem.config.js"

# 6. Initial deployment
echo ""
echo "🚀 Running initial deployment..."
sudo -u $APP_USER bash "$SCRIPT_DIR/deploy_nextjs_app.sh" "$APP_DIR" "$APP_NAME" "$APP_PORT"

# 7. Setup auto-deployment service
echo ""
echo "🔧 Setting up auto-deployment service..."
cp "$SCRIPT_DIR/../ops/systemd/online-docs-auto-deploy.service" /etc/systemd/system/

# Update service file with actual values
sed -i "s|/srv/online-docs|$APP_DIR|g" /etc/systemd/system/online-docs-auto-deploy.service
sed -i "s|online-docs|$APP_NAME|g" /etc/systemd/system/online-docs-auto-deploy.service
sed -i "s|User=moveware-ai|User=$APP_USER|g" /etc/systemd/system/online-docs-auto-deploy.service
sed -i "s|3000|$APP_PORT|g" /etc/systemd/system/online-docs-auto-deploy.service

# Make scripts executable
chmod +x "$SCRIPT_DIR/deploy_nextjs_app.sh"
chmod +x "$SCRIPT_DIR/watch_and_deploy.sh"

# Reload systemd and start service
systemctl daemon-reload
systemctl enable online-docs-auto-deploy
systemctl start online-docs-auto-deploy

# 8. Setup NGINX
echo ""
echo "🌐 Setting up NGINX..."
cat > /etc/nginx/sites-available/$APP_NAME << EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://localhost:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable site
ln -sf /etc/nginx/sites-available/$APP_NAME /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo ""
echo "=================================================="
echo "✅ Setup Complete!"
echo "=================================================="
echo ""
echo "Your Next.js app is now:"
echo "  ✅ Running with PM2"
echo "  ✅ Auto-deploying on git push"
echo "  ✅ Served via NGINX at http://$DOMAIN"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status online-docs-auto-deploy  # Check auto-deploy status"
echo "  sudo journalctl -u online-docs-auto-deploy -f   # Watch deployment logs"
echo "  sudo -u $APP_USER pm2 status                     # Check PM2 status"
echo "  sudo -u $APP_USER pm2 logs $APP_NAME             # View app logs"
echo "  sudo -u $APP_USER pm2 restart $APP_NAME          # Manual restart"
echo ""
echo "To setup SSL with Let's Encrypt:"
echo "  sudo certbot --nginx -d $DOMAIN"
echo ""
