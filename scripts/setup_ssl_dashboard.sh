#!/bin/bash
# Setup SSL for AI Runner Dashboard using Let's Encrypt
# Run as: sudo ./scripts/setup_ssl_dashboard.sh

set -e

DOMAIN="ai-console.holdingsite.com.au"
EMAIL="your-email@example.com"  # Update this!

echo "Setting up SSL for ${DOMAIN}..."
echo ""
echo "⚠️  Before running this script:"
echo "   1. Ensure DNS for ${DOMAIN} points to this server"
echo "   2. Update EMAIL variable in this script with your email"
echo "   3. Ensure port 80 and 443 are open in firewall"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# 1. Install certbot if not present
if ! command -v certbot &> /dev/null; then
    echo "Installing certbot..."
    apt-get update
    apt-get install -y certbot python3-certbot-nginx
fi

# 2. Obtain SSL certificate
echo "Obtaining SSL certificate from Let's Encrypt..."
certbot --nginx \
    -d ${DOMAIN} \
    --email ${EMAIL} \
    --agree-tos \
    --non-interactive \
    --redirect

# 3. Test NGINX configuration
echo "Testing NGINX configuration..."
nginx -t

# 4. Reload NGINX
echo "Reloading NGINX..."
systemctl reload nginx

echo ""
echo "✅ SSL setup complete!"
echo ""
echo "Dashboard URLs:"
echo "  HTTP:  http://${DOMAIN} (redirects to HTTPS)"
echo "  HTTPS: https://${DOMAIN}"
echo ""
echo "Certbot will automatically renew the certificate before expiry."
echo "You can test renewal with: sudo certbot renew --dry-run"
echo ""
