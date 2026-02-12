import hmac
import json
import os
import time
from hashlib import sha256
from typing import Any, Dict, Optional, List
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import init_db, enqueue_run, add_event, connect
from app.metrics import get_summary_stats
from app.queue_manager import get_queue_stats, reset_stale_runs

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


@app.post("/webhook/github-deploy")
async def webhook_github_deploy(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """
    GitHub webhook for auto-deployment.
    
    Triggers git pull and service restart when code is pushed to main branch.
    
    Setup in GitHub:
    1. Go to repo Settings > Webhooks > Add webhook
    2. Payload URL: https://ai-console.moveconnect.com/webhook/github-deploy
    3. Content type: application/json
    4. Secret: Set GITHUB_DEPLOY_WEBHOOK_SECRET in .env
    5. Events: Just the push event
    """
    import subprocess
    import os
    
    body_bytes = await request.body()
    
    # Verify webhook signature
    deploy_secret = os.getenv("GITHUB_DEPLOY_WEBHOOK_SECRET", "")
    if deploy_secret and x_hub_signature_256:
        expected = "sha256=" + hmac.new(
            deploy_secret.encode("utf-8"),
            body_bytes,
            sha256
        ).hexdigest()
        
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=403, detail="Invalid signature")
    
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Check if it's a push to main/master branch
    ref = payload.get("ref", "")
    repository = payload.get("repository", {})
    repo_name = repository.get("full_name", "")
    
    # Only deploy on push to main/master
    if ref not in ["refs/heads/main", "refs/heads/master"]:
        return {
            "status": "ignored",
            "message": f"Not a push to main/master (ref: {ref})"
        }
    
    # Log the deployment trigger
    pusher = payload.get("pusher", {}).get("name", "unknown")
    commits = payload.get("commits", [])
    commit_count = len(commits)
    
    print(f"🚀 Auto-deploy triggered: {repo_name} by {pusher} ({commit_count} commit(s))")
    
    # Execute deployment script
    deploy_script = "/srv/ai/scripts/deploy.sh"
    
    if os.path.exists(deploy_script):
        try:
            # Run deployment script in background
            subprocess.Popen(
                [deploy_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            
            return {
                "status": "deploying",
                "message": f"Deployment started for {repo_name}",
                "ref": ref,
                "commits": commit_count,
                "pusher": pusher
            }
        except Exception as e:
            print(f"❌ Deployment failed: {e}")
            return {
                "status": "error",
                "message": f"Deployment script failed: {str(e)}"
            }
    else:
        return {
            "status": "error",
            "message": f"Deployment script not found: {deploy_script}"
        }


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
    print(f"[webhook] {issue_key} -> run_id={run_id}")
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


@app.get("/api/debug/recent-runs")
async def debug_recent_runs(issue_key: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """
    Diagnostic: recent runs, optionally filtered by issue_key.
    Use to verify if webhooks are creating runs when you move issues in Jira.
    """
    try:
        with connect() as conn:
            cursor = conn.cursor()
            if issue_key:
                cursor.execute("""
                    SELECT id, issue_key, status, created_at, updated_at, locked_by
                    FROM runs WHERE issue_key = ?
                    ORDER BY id DESC LIMIT ?
                """, (issue_key.upper(), limit))
            else:
                cursor.execute("""
                    SELECT id, issue_key, status, created_at, updated_at, locked_by
                    FROM runs ORDER BY id DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            runs = [
                {"id": r[0], "issue_key": r[1], "status": r[2], "created_at": r[3], "updated_at": r[4], "locked_by": r[5]}
                for r in rows
            ]
            return {"runs": runs, "queue": get_queue_stats()}
    except Exception as e:
        return {"error": str(e), "runs": []}


@app.get("/api/queue/stats")
async def queue_stats_api() -> Dict[str, Any]:
    """Get current queue statistics with priorities and repo breakdown."""
    try:
        stats = get_queue_stats()
        return stats
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/queue/reset-stale")
async def reset_stale_runs_api(
    x_admin_secret: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """
    Reset runs stuck in claimed/running (stale locks).
    Use when worker crashed and runs are blocking the queue.
    """
    _require_admin(x_admin_secret)
    try:
        n = reset_stale_runs()
        return {"ok": True, "reset_count": n}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _require_admin(x_admin_secret: Optional[str] = Header(default=None)) -> None:
    """Optional: require ADMIN_SECRET header for admin endpoints."""
    admin_secret = os.getenv("ADMIN_SECRET")
    if admin_secret and (not x_admin_secret or not hmac.compare_digest(x_admin_secret, admin_secret)):
        raise HTTPException(403, "Admin authentication required")


@app.post("/api/trigger")
async def trigger_run_api(
    request: Request,
    x_admin_secret: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """
    Manually enqueue a run for an issue (bypasses Jira webhook).
    Use when Story is already in Selected for Development but webhook didn't fire.

    Body: {"issue_key": "TB-2"}
    """
    _require_admin(x_admin_secret)
    try:
        body = await request.json()
        issue_key = (body.get("issue_key") or "").strip().upper()
        if not issue_key:
            return {"ok": False, "error": "issue_key required"}
        run_id = enqueue_run(issue_key=issue_key, payload={"issue_key": issue_key, "trigger": "manual"}, force_new=True)
        add_event(run_id, "info", "Manually triggered", {"source": "api_trigger"})
        return {"ok": True, "run_id": run_id, "issue_key": issue_key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/repos", response_class=HTMLResponse)
async def repos_page(request: Request):
    """Add Repository - setup new repos with GitHub, folder, and config."""
    return templates.TemplateResponse("repos.html", {"request": request})


@app.get("/api/repos/skills")
async def list_skills_api() -> Dict[str, Any]:
    """List available skills for repository setup."""
    try:
        from app.repo_setup import list_available_skills
        skills = list_available_skills()
        return {"skills": skills}
    except Exception as e:
        return {"error": str(e), "skills": []}


@app.get("/api/repos/config")
async def get_repos_config_api(x_admin_secret: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Get current repos.json configuration (read-only)."""
    _require_admin(x_admin_secret)
    try:
        from app.repo_setup import get_repos_config_path
        config_path = get_repos_config_path()
        if not config_path.exists():
            return {"projects": [], "default_project_key": None, "config_path": str(config_path)}
        with open(config_path) as f:
            data = json.load(f)
        data["config_path"] = str(config_path)
        return data
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/repos/add")
async def add_repo_api(
    request: Request,
    x_admin_secret: Optional[str] = Header(default=None)
) -> Dict[str, Any]:
    """
    Add a new repository: create on GitHub, create folder, update repos.json.
    
    Body: {
      "jira_project_key": "TB",
      "jira_project_name": "Moveware Go",
      "repo_name": "moveware-go",
      "repo_owner": "org",
      "description": "Flutter mobile app",
      "skills": ["flutter-dev"],
      "base_branch": "main",
      "create_on_github": true,
      "private": true
    }
    """
    _require_admin(x_admin_secret)
    try:
        body = await request.json()
        jira_project_key = (body.get("jira_project_key") or "").strip().upper()
        jira_project_name = (body.get("jira_project_name") or "").strip()
        repo_name = (body.get("repo_name") or "").strip().lower().replace(" ", "-")
        repo_owner = (body.get("repo_owner") or os.getenv("REPO_OWNER_SLUG") or "").strip()
        description = (body.get("description") or "").strip()
        skills = body.get("skills") or ["nextjs-fullstack-dev"]
        base_branch = (body.get("base_branch") or "main").strip()
        create_on_github = body.get("create_on_github", True)
        private = body.get("private", True)
        port = int(body.get("port", 3000))

        if not jira_project_key:
            raise HTTPException(400, "jira_project_key is required")
        if not jira_project_name:
            raise HTTPException(400, "jira_project_name is required")
        if not repo_name:
            raise HTTPException(400, "repo_name is required")
        if not repo_owner and create_on_github:
            raise HTTPException(400, "repo_owner is required (or set REPO_OWNER_SLUG)")

        from app.repo_setup import setup_new_repository
        result = setup_new_repository(
            jira_project_key=jira_project_key,
            jira_project_name=jira_project_name,
            repo_name=repo_name,
            repo_owner=repo_owner,
            description=description,
            skills=skills,
            base_branch=base_branch,
            create_on_github=create_on_github,
            private=private,
            port=port,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
async def status_api(detail: str = "summary", hours: str = "24") -> Dict[str, Any]:
    """
    Get current AI Runner status with progress information.
    
    Args:
        detail: 'summary' for high-level view, 'detailed' for all progress events
        hours: Number of hours to look back, or 'all' for all runs
    """
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Calculate time cutoff
            if hours == "all":
                # Get all runs, but limit to reasonable number
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
                    ORDER BY id DESC
                    LIMIT 200
                """)
            else:
                hours_int = int(hours)
                cutoff_time = int(__import__('time').time()) - (hours_int * 3600)
                
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
                    LIMIT 200
                """, (cutoff_time,))
            
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

