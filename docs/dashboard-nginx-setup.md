# AI Runner Dashboard - NGINX Setup Guide

This guide explains how to set up NGINX to proxy the AI Runner dashboard at `ai-console.moveconnect.com`.

## Prerequisites

1. DNS record for `ai-console.moveconnect.com` pointing to your server's IP
2. NGINX installed on the server
3. Ports 80 and 443 open in firewall
4. The AI Runner orchestrator running on port 8088

## Quick Setup

### Option 1: Using the Setup Script (Recommended)

```bash
# 1. Pull the latest code
cd /srv/ai/app
sudo -u moveware-ai git pull

# 2. Make scripts executable
sudo chmod +x scripts/setup_nginx_dashboard.sh scripts/setup_ssl_dashboard.sh

# 3. Deploy NGINX configuration
sudo ./scripts/setup_nginx_dashboard.sh

# 4. Test HTTP access
curl -I http://ai-console.moveconnect.com

# 5. Set up SSL (update EMAIL in script first!)
sudo nano scripts/setup_ssl_dashboard.sh  # Update EMAIL variable
sudo ./scripts/setup_ssl_dashboard.sh
```

### Option 2: Manual Setup

```bash
# 1. Copy NGINX configuration
sudo cp /srv/ai/app/ops/nginx/ai-console.conf /etc/nginx/sites-available/

# 2. Enable the site
sudo ln -sf /etc/nginx/sites-available/ai-console.conf /etc/nginx/sites-enabled/

# 3. Test NGINX configuration
sudo nginx -t

# 4. Reload NGINX
sudo systemctl reload nginx

# 5. Test HTTP access
curl http://ai-console.moveconnect.com/health

# 6. Set up SSL with Certbot
sudo certbot --nginx -d ai-console.moveconnect.com
```

## What's Configured

The NGINX configuration (`ops/nginx/ai-console.conf`) sets up:

- **Root Path (`/`)**: Proxies to the dashboard at `http://127.0.0.1:8088`
- **Health Check (`/health`)**: Proxies to the health endpoint
- **API Endpoints (`/api/`)**: Proxies to the JSON API
- **WebSocket Support**: Ready for future real-time features
- **Timeouts**: 60-second timeouts for long-running requests

## Dashboard URLs

After setup:

- **HTTP**: http://ai-console.moveconnect.com
- **HTTPS**: https://ai-console.moveconnect.com (after SSL setup)
- **Health Check**: http://ai-console.moveconnect.com/health
- **API**: http://ai-console.moveconnect.com/api/status

## Dashboard Features

The dashboard provides real-time visibility into AI Runner operations:

- **Auto-refresh**: Updates every 5 seconds
- **Detail Toggle**: Switch between summary and detailed views
- **Progress Tracking**: See stages like claimed, analyzing, planning, executing, committing, verifying
- **Status Badges**: Visual indicators for queued, running, completed, failed runs
- **Timing Information**: Relative timestamps (e.g., "2m ago")

## Troubleshooting

### NGINX won't start
```bash
# Check NGINX error log
sudo tail -f /var/log/nginx/error.log

# Test configuration
sudo nginx -t
```

### Dashboard not accessible
```bash
# Check if orchestrator is running
sudo systemctl status moveware-ai-orchestrator

# Check if port 8088 is listening
sudo netstat -tlnp | grep 8088

# Test direct connection
curl http://127.0.0.1:8088/health
```

### SSL certificate issues
```bash
# Check certbot logs
sudo journalctl -u certbot

# Test renewal (dry run)
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal
```

### DNS not resolving
```bash
# Check DNS
nslookup ai-console.moveconnect.com

# Test with IP directly
curl -H "Host: ai-console.moveconnect.com" http://your-server-ip/health
```

## Security Considerations

1. **SSL/HTTPS**: Always use HTTPS in production
2. **Firewall**: Ensure only ports 80 and 443 are exposed publicly
3. **Authentication**: Consider adding basic auth if needed:
   ```nginx
   location / {
       auth_basic "AI Runner Dashboard";
       auth_basic_user_file /etc/nginx/.htpasswd;
       # ... rest of proxy config
   }
   ```

## Certificate Renewal

Certbot automatically renews certificates. To check:

```bash
# Check certbot timer
sudo systemctl status certbot.timer

# Manual renewal test
sudo certbot renew --dry-run
```

## Updating Configuration

If you need to update the NGINX config:

```bash
# 1. Edit the config
sudo nano /etc/nginx/sites-available/ai-console.conf

# 2. Test configuration
sudo nginx -t

# 3. Reload NGINX
sudo systemctl reload nginx
```
