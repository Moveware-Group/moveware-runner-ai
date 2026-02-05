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
    return {"status": "ok"}


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
                    completed_at
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
                run_data = {
                    "run_id": run_id,
                    "issue_key": run[1],
                    "status": run[2],
                    "locked_by": run[3],
                    "locked_at": run[4],
                    "created_at": run[5],
                    "completed_at": run[6],
                    "progress_events": []
                }
                
                # Get progress events for this run
                if detail == "detailed":
                    # Get all progress events
                    cursor.execute("""
                        SELECT event_type, message, meta, timestamp
                        FROM events
                        WHERE run_id = ? AND event_type = 'progress'
                        ORDER BY timestamp DESC
                    """, (run_id,))
                else:
                    # Get only the latest progress event
                    cursor.execute("""
                        SELECT event_type, message, meta, timestamp
                        FROM events
                        WHERE run_id = ? AND event_type = 'progress'
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """, (run_id,))
                
                events = cursor.fetchall()
                for event in events:
                    meta_dict = {}
                    if event[2]:  # meta field
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

