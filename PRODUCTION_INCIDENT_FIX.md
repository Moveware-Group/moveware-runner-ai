# Production Incident: git_ops.py Corruption - Emergency Fix

## Incident Summary

**Date**: Jan 15, 2026 21:49 UTC  
**Issue**: moveware-ai-worker service failing to start  
**Root Cause**: `/srv/ai/app/app/git_ops.py` corrupted with shell command instead of Python code  
**Impact**: TB-16 task failed, worker unable to process any runs

## Error Details

```
File "/srv/ai/app/app/git_ops.py", line 1
    sudo -u moveware-ai tee /srv/ai/app/app/git_ops.py >/dev/null <<'PY'
            ^^^^^^^^
SyntaxError: invalid syntax
```

The file was accidentally overwritten with a shell heredoc command instead of Python code.

## Immediate Fix (Run on Server)

### Option 1: Automated Script (Recommended)

```bash
# SSH to the server
ssh moveware-ai-runner-01

# Navigate to the project
cd /srv/ai/app

# Pull latest changes (includes the fix)
sudo -u moveware-ai git pull origin main

# Run the restoration script
sudo -u moveware-ai bash scripts/restore_git_ops.sh
```

### Option 2: Manual Fix (If script unavailable)

```bash
# SSH to the server
ssh moveware-ai-runner-01

# Switch to the AI user
sudo -u moveware-ai bash

# Navigate to the project
cd /srv/ai/app

# Backup the corrupted file
cp app/git_ops.py app/git_ops.py.corrupted.$(date +%Y%m%d_%H%M%S)

# Restore from git
git checkout HEAD -- app/git_ops.py

# Verify the file is valid Python
python3 -m py_compile app/git_ops.py

# Check first few lines to confirm
head -n 5 app/git_ops.py

# Should show:
# import os
# import subprocess
# from pathlib import Path
# from typing import Optional, Tuple

# Restart the worker service
exit  # Exit from moveware-ai user
sudo systemctl restart moveware-ai-worker

# Check status
sudo systemctl status moveware-ai-worker

# Watch logs
sudo journalctl -u moveware-ai-worker -f
```

### Option 3: Direct File Restoration (Emergency)

If git is also corrupted, restore directly from this repository:

```bash
# SSH to server
ssh moveware-ai-runner-01

# Backup corrupted file
sudo cp /srv/ai/app/app/git_ops.py /srv/ai/app/app/git_ops.py.corrupted

# Download fresh copy from GitHub
sudo -u moveware-ai curl -o /srv/ai/app/app/git_ops.py \
  https://raw.githubusercontent.com/leigh-moveware/moveware-runner-ai/main/app/git_ops.py

# Verify
python3 -m py_compile /srv/ai/app/app/git_ops.py

# Restart worker
sudo systemctl restart moveware-ai-worker
```

## Verification Steps

1. **Check worker is running:**
   ```bash
   sudo systemctl status moveware-ai-worker
   ```
   Should show: `Active: active (running)`

2. **Check for errors in logs:**
   ```bash
   sudo journalctl -u moveware-ai-worker --since "5 minutes ago" --no-pager
   ```
   Should NOT show syntax errors

3. **Verify worker can claim runs:**
   ```bash
   # Watch worker logs
   sudo journalctl -u moveware-ai-worker -f
   ```
   Should show: `Worker worker-1 started with SMART QUEUE...`

## Handle Stuck Run (TB-16)

The TB-16 run may be stuck in the database. Check and reset if needed:

```bash
# Connect to database
sudo -u moveware-ai python3 -c "
from app.db import connect
with connect() as conn:
    cursor = conn.cursor()
    
    # Find TB-16 run
    cursor.execute('SELECT id, status, locked_by FROM runs WHERE issue_key = ?', ('TB-16',))
    run = cursor.fetchone()
    
    if run:
        print(f'Run ID: {run[0]}, Status: {run[1]}, Locked by: {run[2]}')
        
        # Reset if stuck
        if run[1] in ('claimed', 'running'):
            cursor.execute('''
                UPDATE runs 
                SET status = 'failed',
                    locked_by = NULL,
                    locked_at = NULL,
                    last_error = 'Worker crashed due to git_ops.py corruption'
                WHERE id = ?
            ''', (run[0],))
            conn.commit()
            print(f'Reset run {run[0]} to failed status')
"
```

## Root Cause Analysis

The corruption happened because a shell command was executed that wrote to the file incorrectly:

```bash
# This command pattern was likely executed:
sudo -u moveware-ai tee /srv/ai/app/app/git_ops.py >/dev/null <<'PY'
# ... (Python code should have been here)
PY
```

**Problem**: The heredoc delimiter or the command itself was written into the file instead of the content.

**Possible causes:**
1. Script error during deployment
2. Manual file edit that went wrong
3. Automated process that had incorrect syntax
4. Copy-paste error in terminal

## Prevention Measures

### 1. Add File Integrity Check to Worker Startup

Add to worker startup:

```python
# app/worker.py - add at startup
def verify_code_integrity():
    """Verify critical files are valid Python before starting."""
    critical_files = [
        'app/git_ops.py',
        'app/executor.py',
        'app/worker.py',
        'app/main.py'
    ]
    
    for file_path in critical_files:
        try:
            with open(file_path) as f:
                compile(f.read(), file_path, 'exec')
        except SyntaxError as e:
            raise RuntimeError(f"Code integrity check failed: {file_path} has syntax error: {e}")

# Call before starting worker loop
verify_code_integrity()
```

### 2. Use Git-based Deployments Only

**Never** manually edit files on the server. Always:
1. Make changes in git repository
2. Commit and push
3. Pull on server: `sudo -u moveware-ai git pull`
4. Restart services: `sudo systemctl restart moveware-ai-worker`

### 3. Add Deployment Script with Validation

```bash
#!/bin/bash
# scripts/deploy.sh

set -e

echo "Pulling latest changes..."
sudo -u moveware-ai git pull origin main

echo "Validating Python files..."
find app -name "*.py" -type f | while read file; do
    python3 -m py_compile "$file" || {
        echo "Syntax error in $file - rolling back"
        sudo -u moveware-ai git reset --hard HEAD~1
        exit 1
    }
done

echo "Restarting services..."
sudo systemctl restart moveware-ai-worker
sudo systemctl restart moveware-ai-orchestrator

echo "Deployment complete"
```

### 4. Add Systemd Service Restart Limits

Modify `/etc/systemd/system/moveware-ai-worker.service`:

```ini
[Unit]
# ... existing config ...

[Service]
# ... existing config ...

# Restart limits to prevent infinite restart loops
StartLimitIntervalSec=300
StartLimitBurst=5

# If fails 5 times in 5 minutes, stop trying
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

Then reload:
```bash
sudo systemctl daemon-reload
```

### 5. Add Monitoring Alert

Add to monitoring (if available):

```bash
# Alert if worker has restarted more than 3 times in 5 minutes
if systemctl show moveware-ai-worker -p NRestarts | grep -q "NRestarts=[3-9]\|NRestarts=[0-9][0-9]"; then
    alert "moveware-ai-worker has restarted multiple times - check logs"
fi
```

## Testing After Fix

1. **Trigger a simple test run:**
   ```bash
   # Use the API trigger endpoint
   curl -X POST http://localhost:8088/api/trigger \
     -H "Content-Type: application/json" \
     -H "x-admin-secret: $ADMIN_SECRET" \
     -d '{"issue_key": "TB-17"}'
   ```

2. **Watch the logs:**
   ```bash
   sudo journalctl -u moveware-ai-worker -f
   ```

3. **Check dashboard:**
   Visit: https://ai-console.moveconnect.com/status

## Post-Incident Actions

- [ ] Fix applied and worker restarted
- [ ] TB-16 run status checked and reset if needed
- [ ] File integrity check added to worker startup
- [ ] Deployment script created with validation
- [ ] Documentation updated
- [ ] Team notified of incident and prevention measures

## Contact

If issues persist:
1. Check logs: `sudo journalctl -u moveware-ai-worker -f`
2. Check database for stuck runs
3. Contact: leigh.morrow@moveconnect.com
