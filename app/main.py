import hmac
import json
from hashlib import sha256
from typing import Any, Dict, Optional, List
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import init_db, enqueue_run, add_event, connect
from app.metrics import get_summary_stats
from app.queue_manager import get_queue_stats

app = FastAPI(title="Moveware AI Orchestrator")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def root():
    """Redirect root to the dashboard."""
    return RedirectResponse(url="/status")


@app.get("/health")
def health() -> Dict[str, str]:
    """Basic health check."""
    return {"status": "ok"}


@app.get("/api/health/detailed")
async def health_detailed() -> Dict[str, Any]:
    """Detailed health check with system status."""
    try:
        import psutil
        import sys
        
        health_data = {
            "status": "ok",
            "timestamp": int(time.time()),
            "uptime_seconds": int(time.time() - psutil.Process().create_time()),
            "python_version": sys.version,
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
            }
        }
        
        # Check database connectivity
        try:
            with connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM runs")
                total_runs = cursor.fetchone()[0]
                health_data["database"] = {
                    "status": "ok",
                    "total_runs": total_runs
                }
        except Exception as e:
            health_data["database"] = {
                "status": "error",
                "error": str(e)
            }
            health_data["status"] = "degraded"
        
        # Check queue status
        try:
            queue_stats = get_queue_stats()
            health_data["queue"] = queue_stats
        except Exception as e:
            health_data["queue"] = {"error": str(e)}
        
        return health_data
        
    except ImportError:
        # psutil not installed, return basic health
        return {
            "status": "ok",
            "timestamp": int(time.time()),
            "note": "Install psutil for detailed system metrics"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": int(time.time())
        }


def _verify_secret(given: str | None) -> None:
    if not settings.JIRA_WEBHOOK_SECRET:
        raise HTTPException(500, "Server misconfigured")
    if not given or not hmac.compare_digest(given, settings.JIRA_WEBHOOK_SECRET):
        raise HTTPException(401, "Invalid webhook secret")


@app.post("/webhook/jira")
async def jira_webhook(
    request: Request,
    x_moveware_webhook_secret: Optional[str] = Header(default=None),
):
    _verify_secret(x_moveware_webhook_secret)
    payload: Dict[str, Any] = await request.json()

    issue_key = (
        payload.get("issue_key")
        or payload.get("issueKey")
        or payload.get("issue", {}).get("key")
        or payload.get("issue", {}).get("id")
    )
    if not issue_key:
        raise HTTPException(400, "Missing issue key")

    run_id = enqueue_run(issue_key=issue_key, payload=payload)
    add_event(run_id, "info", "Webhook received", {"source": "jira_webhook"})
    return JSONResponse({"ok": True, "run_id": run_id})


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    """Render the status dashboard HTML page."""
    return templates.TemplateResponse("status.html", {"request": request})


@app.get("/api/metrics/summary")
async def metrics_summary_api(hours: int = 24) -> Dict[str, Any]:
    """
    Get summary metrics for the specified time period.
    
    Args:
        hours: Number of hours to look back (default: 24)
    """
    try:
        stats = get_summary_stats(hours)
        return stats
    except Exception as e:
        return {
            "error": str(e),
            "total_runs": 0,
            "completed": 0,
            "failed": 0,
            "success_rate": 0,
            "total_cost_usd": 0,
            "avg_duration_seconds": 0,
            "total_tokens": 0,
            "error_categories": {}
        }


@app.get("/api/queue/stats")
async def queue_stats_api() -> Dict[str, Any]:
    """Get current queue statistics with priorities and repo breakdown."""
    try:
        stats = get_queue_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: int) -> Dict[str, Any]:
    """Get detailed information about a specific run."""
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Get run details
            cursor.execute("""
                SELECT id, issue_key, status, branch, pr_url, last_error,
                       created_at, updated_at, locked_by, locked_at, priority, repo_key, metrics_json
                FROM runs
                WHERE id = ?
            """, (run_id,))
            
            row = cursor.fetchone()
            if not row:
                return {"error": "Run not found"}
            
            # Get all events for this run
            cursor.execute("""
                SELECT level, message, meta_json, ts
                FROM events
                WHERE run_id = ?
                ORDER BY ts ASC
            """, (run_id,))
            
            events = []
            for event_row in cursor.fetchall():
                meta = {}
                if event_row[2]:
                    try:
                        meta = json.loads(event_row[2])
                    except:
                        pass
                
                events.append({
                    "level": event_row[0],
                    "message": event_row[1],
                    "meta": meta,
                    "timestamp": event_row[3]
                })
            
            # Parse metrics if present
            metrics_data = None
            if row[12]:
                try:
                    metrics_data = json.loads(row[12])
                except:
                    pass
            
            return {
                "run_id": row[0],
                "issue_key": row[1],
                "status": row[2],
                "branch": row[3],
                "pr_url": row[4],
                "last_error": row[5],
                "created_at": row[6],
                "updated_at": row[7],
                "locked_by": row[8],
                "locked_at": row[9],
                "priority": row[10],
                "repo_key": row[11],
                "metrics": metrics_data,
                "events": events
            }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/runs/{run_id}/retry")
async def retry_run(run_id: int) -> Dict[str, Any]:
    """Retry a failed run."""
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Check if run exists and is failed
            cursor.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            
            if not row:
                return {"error": "Run not found"}
            
            if row[0] not in ("failed", "completed"):
                return {"error": f"Cannot retry run with status: {row[0]}"}
            
            # Reset run to queued
            ts = int(time.time())
            cursor.execute("""
                UPDATE runs 
                SET status = 'queued', 
                    locked_by = NULL, 
                    locked_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
            """, (ts, run_id))
            
            # Add event
            cursor.execute(
                "INSERT INTO events(run_id,ts,level,message,meta_json) VALUES(?,?,?,?,?)",
                (run_id, ts, "info", "Run manually retried", "{}"),
            )
            
            conn.commit()
            
            return {"ok": True, "message": f"Run {run_id} queued for retry"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/status")
async def status_api(detail: str = "summary") -> Dict[str, Any]:
    """
    Get current AI Runner status with progress information.
    
    Args:
        detail: 'summary' for high-level view, 'detailed' for all progress events
    """
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Get recent runs (last hour)
            one_hour_ago = int(__import__('time').time()) - 3600
            
            cursor.execute("""
                SELECT 
                    id,
                    issue_key,
                    status,
                    locked_by,
                    locked_at,
                    created_at,
                    updated_at
                FROM runs
                WHERE created_at > ?
                ORDER BY id DESC
                LIMIT 50
            """, (one_hour_ago,))
            
            runs = cursor.fetchall()
            
            # Build result
            runs_list = []
            for run in runs:
                run_id = run[0]
                run_status = run[2]
                run_data = {
                    "run_id": run_id,
                    "issue_key": run[1],
                    "status": run_status,
                    "locked_by": run[3],
                    "locked_at": run[4],
                    "created_at": run[5],
                    "completed_at": run[6] if run_status in ('completed', 'failed') else None,
                    "progress_events": []
                }
                
                # Get progress events for this run
                if detail == "detailed":
                    # Get all progress events
                    cursor.execute("""
                        SELECT level, message, meta_json, ts
                        FROM events
                        WHERE run_id = ? AND level = 'progress'
                        ORDER BY ts DESC
                    """, (run_id,))
                else:
                    # Get only the latest progress event
                    cursor.execute("""
                        SELECT level, message, meta_json, ts
                        FROM events
                        WHERE run_id = ? AND level = 'progress'
                        ORDER BY ts DESC
                        LIMIT 1
                    """, (run_id,))
                
                events = cursor.fetchall()
                for event in events:
                    meta_dict = {}
                    if event[2]:  # meta_json field
                        try:
                            meta_dict = json.loads(event[2])
                        except:
                            pass
                    
                    event_data = {
                        "message": event[1],
                        "stage": meta_dict.get("stage", "unknown"),
                        "timestamp": event[3]
                    }
                    
                    if detail == "detailed":
                        event_data["meta"] = meta_dict
                    
                    run_data["progress_events"].append(event_data)
                
                runs_list.append(run_data)
        
        return {
            "detail_level": detail,
            "runs": runs_list,
            "timestamp": int(__import__('time').time())
        }
    
    except Exception as e:
        # Return error response that won't crash the dashboard
        return {
            "detail_level": detail,
            "runs": [],
            "timestamp": int(__import__('time').time()),
            "error": str(e)
        }

