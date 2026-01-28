# Monitoring and Logging Guide

## Current Logging Architecture

The system uses three logging mechanisms:

1. **systemd journald** - Captures stdout/stderr from both services
2. **SQLite events table** - Structured event log per run with metadata
3. **Print statements** - Simple logging in worker.py

## Quick Monitoring Commands

### Real-time Log Monitoring

```bash
# Watch worker activity
sudo journalctl -u moveware-ai-worker.service -f

# Watch orchestrator (webhook receiver)
sudo journalctl -u moveware-ai-orchestrator.service -f

# Watch both services
sudo journalctl -u moveware-ai-worker.service -u moveware-ai-orchestrator.service -f

# Filter by time
sudo journalctl -u moveware-ai-worker.service --since "10 minutes ago"
sudo journalctl -u moveware-ai-worker.service --since "2024-01-28 15:00:00"
```

### Database Queries

```bash
# Recent runs
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "SELECT id, issue_key, status, datetime(created_at, 'unixepoch', 'localtime') 
   FROM runs ORDER BY id DESC LIMIT 10;"

# Failed runs
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "SELECT id, issue_key, last_error, datetime(updated_at, 'unixepoch', 'localtime') 
   FROM runs WHERE status='failed' ORDER BY id DESC LIMIT 5;"

# Events for a specific run
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "SELECT datetime(ts, 'unixepoch', 'localtime'), level, message 
   FROM events WHERE run_id=1 ORDER BY ts;"

# Queued runs waiting to process
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "SELECT id, issue_key, datetime(created_at, 'unixepoch', 'localtime') 
   FROM runs WHERE status='queued' ORDER BY created_at;"

# Running time for completed runs
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "SELECT issue_key, (updated_at - created_at) as duration_seconds 
   FROM runs WHERE status='completed' ORDER BY id DESC LIMIT 10;"
```

### Helper Scripts

```bash
# Monitor worker with dashboard
./scripts/monitor_worker.sh

# Check specific run details
./scripts/check_run_status.sh <run_id>
```

## Testing the System

### 1. Test with Jira Webhook

1. Create a Jira ticket and assign to AI Runner
2. Watch logs: `sudo journalctl -u moveware-ai-worker.service -f`
3. Check database: `sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "SELECT * FROM runs ORDER BY id DESC LIMIT 1;"`

### 2. Test with curl

```bash
curl -X POST https://ai-runner.moveconnect.com/webhook/jira \
  -H "Content-Type: application/json" \
  -H "X-Moveware-Webhook-Secret: $JIRA_WEBHOOK_SECRET" \
  -d '{
    "event_type": "issue_assigned",
    "issue_key": "TEST-123",
    "issue_type": "Story",
    "status": "Backlog",
    "assignee_account_id": "$JIRA_AI_ACCOUNT_ID"
  }'
```

### 3. Monitor Processing

```bash
# Terminal 1: Worker logs
sudo journalctl -u moveware-ai-worker.service -f

# Terminal 2: Database status
watch -n 2 "sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  'SELECT id, issue_key, status FROM runs ORDER BY id DESC LIMIT 5;'"
```

## Adding Sentry Integration (Production)

### Install Sentry SDK

```bash
source .venv/bin/activate
pip install sentry-sdk
pip freeze > requirements.txt
```

### Configure Sentry

Add to `.env`:
```bash
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
```

### Update config.py

```python
# Add to Settings class
SENTRY_DSN: str = env("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT: str = env("SENTRY_ENVIRONMENT", default="production")
SENTRY_TRACES_SAMPLE_RATE: float = float(env("SENTRY_TRACES_SAMPLE_RATE", default="0.1"))
```

### Initialize Sentry in worker.py

```python
import sentry_sdk
from .config import settings

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        _experiments={
            "profiles_sample_rate": 0.1,
        },
    )
```

### Initialize Sentry in main.py

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )
```

## Structured Logging with Python logging

### Create app/logger.py

```python
import logging
import sys
from typing import Optional

from .config import settings

def setup_logging(service_name: str) -> logging.Logger:
    """Setup structured logging for the service."""
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger
```

### Use in worker.py

```python
from .logger import setup_logging

logger = setup_logging("worker")

def worker_loop(poll_interval_seconds: float = 2.0, worker_id: str = "worker-1") -> None:
    logger.info(f"Worker {worker_id} started, polling every {poll_interval_seconds}s")
    
    while True:
        result = claim_next_run(worker_id)
        if not result:
            time.sleep(poll_interval_seconds)
            continue
            
        run_id, issue_key, payload = result
        logger.info(f"Claimed run {run_id} for issue {issue_key}")
        
        try:
            process_run(ctx, run_id, issue_key, payload)
            logger.info(f"Successfully processed run {run_id}")
        except Exception as e:
            logger.error(f"ERROR processing run {run_id}: {e}", exc_info=True)
```

## Log Aggregation Options

### Option 1: journald → CloudWatch Logs

```bash
# Install AWS CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# Configure to ship journald logs
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard
```

### Option 2: Vector.dev (Lightweight)

```bash
# Install Vector
curl --proto '=https' --tlsv1.2 -sSf https://sh.vector.dev | bash

# Configure vector to read journald and forward to Sentry/Datadog/etc
```

### Option 3: Direct to Azure Monitor

Use Azure Monitor agent to collect systemd logs.

## Alerts and Notifications

### systemd Email Alerts

```bash
# Install mailutils
sudo apt install mailutils

# Edit service to send email on failure
sudo systemctl edit moveware-ai-worker.service
```

Add:
```ini
[Unit]
OnFailure=failure-notification@%n.service
```

### Database-based Alerting

Create a cron job to check for failures:

```bash
#!/bin/bash
# Check for recent failures and alert
FAILURES=$(sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "SELECT COUNT(*) FROM runs WHERE status='failed' AND updated_at > strftime('%s', 'now', '-1 hour');")

if [ "$FAILURES" -gt 0 ]; then
    # Send alert (email, Slack, PagerDuty, etc.)
    echo "ALERT: $FAILURES failed runs in the last hour" | mail -s "AI Runner Alert" ops@moveware.com
fi
```

## Performance Monitoring

### Track Processing Times

```sql
-- Average processing time by status
SELECT 
  status,
  COUNT(*) as count,
  AVG(updated_at - created_at) as avg_duration_seconds,
  MAX(updated_at - created_at) as max_duration_seconds
FROM runs 
WHERE created_at > strftime('%s', 'now', '-7 days')
GROUP BY status;

-- Slowest runs
SELECT 
  issue_key,
  status,
  (updated_at - created_at) as duration_seconds,
  datetime(created_at, 'unixepoch', 'localtime') as started
FROM runs 
ORDER BY duration_seconds DESC 
LIMIT 10;
```

## Healthcheck Endpoints

The orchestrator already has `/health`. Consider adding:

```python
@app.get("/health/detailed")
def health_detailed() -> Dict[str, Any]:
    """Detailed health check including worker status."""
    # Check database connectivity
    try:
        with connect() as cx:
            cx.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {e}"
    
    # Check for stuck runs
    with connect() as cx:
        stuck = cx.execute(
            "SELECT COUNT(*) FROM runs WHERE status='running' AND updated_at < ?",
            (now() - 3600,)
        ).fetchone()[0]
    
    return {
        "status": "healthy" if db_status == "healthy" and stuck == 0 else "degraded",
        "database": db_status,
        "stuck_runs": stuck,
        "timestamp": now()
    }
```

## Troubleshooting Common Issues

### Worker not processing runs

```bash
# Check worker is running
sudo systemctl status moveware-ai-worker.service

# Check for queued runs
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "SELECT * FROM runs WHERE status='queued';"

# Check for stale locks
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "SELECT * FROM runs WHERE locked_by IS NOT NULL;"
```

### High error rates

```bash
# Recent errors
sudo journalctl -u moveware-ai-worker.service -p err --since "1 hour ago"

# Error patterns
sudo journalctl -u moveware-ai-worker.service --since "1 day ago" | grep -i error | sort | uniq -c | sort -rn
```

### Database growing too large

```bash
# Check database size
du -h /srv/ai/state/moveware_ai.sqlite3

# Archive old runs (keep last 30 days)
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "DELETE FROM events WHERE run_id IN (
    SELECT id FROM runs WHERE updated_at < strftime('%s', 'now', '-30 days')
  );"

sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 \
  "DELETE FROM runs WHERE updated_at < strftime('%s', 'now', '-30 days');"

# Vacuum to reclaim space
sudo sqlite3 /srv/ai/state/moveware_ai.sqlite3 "VACUUM;"
```
