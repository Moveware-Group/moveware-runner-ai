import hmac
import json
from hashlib import sha256
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db, enqueue_run, append_event

app = FastAPI(title="Moveware AI Orchestrator")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _verify_secret(given: str | None) -> None:
    if not settings.jira_webhook_secret:
        raise HTTPException(500, "Server misconfigured")
    if not given or not hmac.compare_digest(given, settings.jira_webhook_secret):
        raise HTTPException(401, "Invalid webhook secret")


@app.post("/webhook/jira")
async def jira_webhook(
    request: Request,
    x_moveware_secret: Optional[str] = Header(default=None),
):
    _verify_secret(x_moveware_secret)
    payload: Dict[str, Any] = await request.json()

    issue_key = (
        payload.get("issue", {}).get("key")
        or payload.get("issue", {}).get("id")
        or payload.get("issueKey")
    )
    if not issue_key:
        raise HTTPException(400, "Missing issue key")

    run_id = enqueue_run(issue_key=issue_key, payload=payload)
    append_event(run_id, "enqueued", {"source": "jira_webhook"})
    return JSONResponse({"ok": True, "run_id": run_id})
