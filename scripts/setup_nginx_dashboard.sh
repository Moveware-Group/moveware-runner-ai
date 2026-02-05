#!/bin/bash
# Setup NGINX configuration for AI Runner Dashboard
# Run as: sudo ./scripts/setup_nginx_dashboard.sh

set -e

echo "Setting up NGINX for ai-console.holdingsite.com.au..."

# 1. Copy NGINX config to sites-available
echo "1. Copying NGINX configuration..."
cp /srv/ai/app/ops/nginx/ai-console.conf /etc/nginx/sites-available/ai-console.conf

# 2. Create symlink to sites-enabled
echo "2. Enabling site..."
ln -sf /etc/nginx/sites-available/ai-console.conf /etc/nginx/sites-enabled/ai-console.conf

# 3. Test NGINX configuration
echo "3. Testing NGINX configuration..."
nginx -t

# 4. Reload NGINX
echo "4. Reloading NGINX..."
systemctl reload nginx

echo ""
echo "✅ NGINX configuration deployed successfully!"
echo ""
echo "Next steps:"
echo "1. Ensure DNS for ai-console.holdingsite.com.au points to this server"
echo "2. Test HTTP access: http://ai-console.holdingsite.com.au"
echo "3. Set up SSL with: sudo ./scripts/setup_ssl_dashboard.sh"
echo ""
