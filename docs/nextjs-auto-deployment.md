# Next.js Auto-Deployment System

Automated deployment system for Next.js applications created by the AI Runner. When the AI Runner pushes code, the app automatically builds and restarts.

## Overview

The system consists of:

1. **PM2** - Process manager that keeps Next.js running
2. **Auto-Deploy Service** - Watches git repository for changes
3. **Deploy Script** - Builds and restarts the application
4. **NGINX** - Reverse proxy serving the app

```
AI Runner pushes code → Git repo updated → Watcher detects change → 
Deploy script runs → npm install → npm build → PM2 restart → App live
```

## Quick Setup

```bash
# SSH to your server
ssh moveware-ai-runner-01

# Navigate to the runner repo
cd /srv/moveware-runner-ai

# Pull latest scripts
git pull

# Run setup (will prompt for confirmation)
sudo ./scripts/setup_nextjs_deployment.sh
```

This installs everything and starts auto-deployment.

## Manual Deployment

If you need to manually deploy:

```bash
sudo -u moveware-ai /srv/moveware-runner-ai/scripts/deploy_nextjs_app.sh \
  /srv/online-docs \
  online-docs \
  3000
```

## Architecture

### 1. PM2 Process Manager

PM2 keeps the Next.js app running in production mode.

**Configuration:** `/srv/online-docs/ecosystem.config.js`

```javascript
module.exports = {
  apps: [{
    name: 'online-docs',
    script: 'npm',
    args: 'start',
    cwd: '/srv/online-docs',
    instances: 1,
    autorestart: true,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production',
      PORT: 3000
    }
  }]
}
```

**Commands:**

```bash
# View all PM2 processes
sudo -u moveware-ai pm2 status

# View logs
sudo -u moveware-ai pm2 logs online-docs

# Restart app
sudo -u moveware-ai pm2 restart online-docs

# Stop app
sudo -u moveware-ai pm2 stop online-docs

# Monitor resources
sudo -u moveware-ai pm2 monit
```

### 2. Auto-Deploy Watcher

A systemd service continuously monitors the git repository for changes.

**Service:** `/etc/systemd/system/online-docs-auto-deploy.service`

**How it works:**

1. Every 30 seconds, checks if remote has new commits
2. If new commits detected, runs deployment script
3. Logs all activity to systemd journal

**Commands:**

```bash
# Check status
sudo systemctl status online-docs-auto-deploy

# View logs
sudo journalctl -u online-docs-auto-deploy -f

# Restart watcher
sudo systemctl restart online-docs-auto-deploy

# Stop auto-deployment
sudo systemctl stop online-docs-auto-deploy
```

### 3. Deploy Script

**Location:** `/srv/moveware-runner-ai/scripts/deploy_nextjs_app.sh`

**What it does:**

1. `git pull` - Pulls latest code
2. `npm install` - Installs dependencies
3. `npm run build` - Builds Next.js for production
4. `pm2 restart` - Restarts the application

**Usage:**

```bash
./deploy_nextjs_app.sh [app_directory] [app_name] [port]

# Example
./deploy_nextjs_app.sh /srv/online-docs online-docs 3000
```

### 4. NGINX Reverse Proxy

**Configuration:** `/etc/nginx/sites-available/online-docs`

```nginx
server {
    listen 80;
    server_name oa.holdingsite.com.au;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

## Directory Structure

```
/srv/
├── moveware-runner-ai/       # AI Runner repository
│   └── scripts/
│       ├── deploy_nextjs_app.sh
│       ├── watch_and_deploy.sh
│       ├── setup_nextjs_deployment.sh
│       └── ecosystem.config.js
│
└── online-docs/               # Next.js app
    ├── .git/
    ├── .next/                 # Build output
    ├── node_modules/
    ├── logs/
    │   ├── pm2-error.log
    │   └── pm2-out.log
    ├── ecosystem.config.js    # PM2 config
    └── package.json
```

## Workflow Example

1. **AI Runner creates code:**
   ```
   AI Runner (OD-20) → Creates component.tsx → Commits → Pushes to GitHub
   ```

2. **Auto-deployment triggers:**
   ```
   Watcher detects change → Runs deploy script → Pulls code
   ```

3. **App rebuilds:**
   ```
   npm install → npm run build → Creates .next/ folder
   ```

4. **App restarts:**
   ```
   PM2 restarts → Next.js serves on port 3000 → NGINX proxies to domain
   ```

5. **App is live:**
   ```
   http://oa.holdingsite.com.au shows new component
   ```

## Troubleshooting

### App not starting

```bash
# Check PM2 status
sudo -u moveware-ai pm2 status

# View PM2 logs
sudo -u moveware-ai pm2 logs online-docs --lines 50

# Try manual restart
sudo -u moveware-ai pm2 restart online-docs
```

### Auto-deploy not working

```bash
# Check watcher service
sudo systemctl status online-docs-auto-deploy

# View deployment logs
sudo journalctl -u online-docs-auto-deploy -f

# Check if git can pull
cd /srv/online-docs
sudo -u moveware-ai git pull origin main
```

### Build failures

```bash
# Check npm install errors
cd /srv/online-docs
sudo -u moveware-ai npm install

# Check build errors
sudo -u moveware-ai npm run build

# View full deployment logs
sudo journalctl -u online-docs-auto-deploy -n 100
```

### NGINX errors

```bash
# Test NGINX config
sudo nginx -t

# Check NGINX logs
sudo tail -f /var/log/nginx/error.log

# Restart NGINX
sudo systemctl restart nginx
```

### Port already in use

```bash
# Check what's using port 3000
sudo lsof -i :3000

# Kill process if needed
sudo kill -9 <PID>

# Restart PM2
sudo -u moveware-ai pm2 restart online-docs
```

## SSL/HTTPS Setup

After basic setup, add SSL with Let's Encrypt:

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d oa.holdingsite.com.au

# Test auto-renewal
sudo certbot renew --dry-run
```

## Multiple Apps

To deploy additional Next.js apps:

```bash
# Deploy second app
sudo ./scripts/setup_nextjs_deployment.sh

# When prompted, provide different values:
#   App Directory: /srv/another-app
#   App Name: another-app
#   Port: 3001
#   Domain: another.holdingsite.com.au
```

## Performance Tuning

### PM2 Cluster Mode

For better performance, run multiple instances:

```javascript
// ecosystem.config.js
module.exports = {
  apps: [{
    name: 'online-docs',
    script: 'npm',
    args: 'start',
    instances: 'max',  // Use all CPU cores
    exec_mode: 'cluster',
    autorestart: true,
    max_memory_restart: '1G'
  }]
}
```

### NGINX Caching

Add caching to NGINX config:

```nginx
# Add to server block
location /_next/static {
    proxy_pass http://localhost:3000;
    proxy_cache_valid 60m;
    add_header Cache-Control "public, immutable";
}
```

## Monitoring

### View all logs together

```bash
# PM2 logs + Deploy logs + NGINX logs
sudo pm2 logs online-docs & 
sudo journalctl -u online-docs-auto-deploy -f &
sudo tail -f /var/log/nginx/access.log
```

### Resource monitoring

```bash
# PM2 built-in monitor
sudo -u moveware-ai pm2 monit

# System resources
htop

# Disk usage
df -h /srv/online-docs
```

## Best Practices

1. **Always test locally first** - Test Next.js builds locally before pushing
2. **Check logs after deployment** - Verify deployment succeeded
3. **Use semantic versioning** - Tag releases in git
4. **Monitor memory usage** - Watch PM2 memory limits
5. **Keep dependencies updated** - Regular npm updates
6. **Backup before major changes** - Snapshot VM before big updates

## Integration with AI Runner

The AI Runner workflow:

```
Epic (OD-12) → Stories → Sub-tasks → Code commits → Auto-deploy → Live app
```

No manual deployment needed! The AI Runner pushes code, and it's automatically:
- Built
- Tested (via npm install verification)
- Deployed
- Restarted

## Related Documentation

- [Story Workflow](./story-workflow.md) - How AI Runner processes Epics/Stories
- [Dashboard Setup](./dashboard-nginx-setup.md) - Monitoring the AI Runner
- [Monitoring and Logging](./monitoring-and-logging.md) - System monitoring
