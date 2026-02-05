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
    with connect() as conn:
        cursor = conn.cursor()
        
        # Get recent runs with their latest progress events
        if detail == "detailed":
            # Detailed view: include all progress events
            cursor.execute("""
                SELECT 
                    r.id,
                    r.issue_key,
                    r.status,
                    r.locked_by,
                    r.locked_at,
                    r.created_at,
                    r.completed_at,
                    e.event_type,
                    e.message,
                    e.meta,
                    e.timestamp
                FROM runs r
                LEFT JOIN events e ON r.id = e.run_id AND e.event_type = 'progress'
                WHERE r.created_at > ?
                ORDER BY r.id DESC, e.timestamp DESC
                LIMIT 200
            """, (int(__import__('time').time()) - 3600,))  # Last hour
        else:
            # Summary view: just get the latest progress event per run
            cursor.execute("""
                SELECT 
                    r.id,
                    r.issue_key,
                    r.status,
                    r.locked_by,
                    r.locked_at,
                    r.created_at,
                    r.completed_at,
                    e.event_type,
                    e.message,
                    e.meta,
                    e.timestamp
                FROM runs r
                LEFT JOIN (
                    SELECT run_id, event_type, message, meta, timestamp, 
                           ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY timestamp DESC) as rn
                    FROM events
                    WHERE event_type = 'progress'
                ) e ON r.id = e.run_id AND e.rn = 1
                WHERE r.created_at > ?
                ORDER BY r.id DESC
                LIMIT 50
            """, (int(__import__('time').time()) - 3600,))  # Last hour
        
        rows = cursor.fetchall()
    
    # Group results by run_id
    runs_dict: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        run_id = row[0]
        if run_id not in runs_dict:
            runs_dict[run_id] = {
                "run_id": run_id,
                "issue_key": row[1],
                "status": row[2],
                "locked_by": row[3],
                "locked_at": row[4],
                "created_at": row[5],
                "completed_at": row[6],
                "progress_events": []
            }
        
        if row[7]:  # event_type exists
            meta_dict = {}
            if row[9]:  # meta field
                try:
                    meta_dict = json.loads(row[9])
                except:
                    pass
            
            event = {
                "message": row[8],
                "stage": meta_dict.get("stage", "unknown"),
                "timestamp": row[10]
            }
            
            if detail == "detailed":
                event["meta"] = meta_dict
            
            runs_dict[run_id]["progress_events"].append(event)
    
    # Convert to list and sort by run_id descending
    runs_list = sorted(runs_dict.values(), key=lambda x: x["run_id"], reverse=True)
    
    return {
        "detail_level": detail,
        "runs": runs_list,
        "timestamp": int(__import__('time').time())
    }
