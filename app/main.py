import hmac
import json
from hashlib import sha256
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import init_db, enqueue_run, add_event

app = FastAPI(title="Moveware AI Orchestrator")


@app.on_event("startup")
def _startup() -> None:
    init_db()


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
        payload.get("issue", {}).get("key")
        or payload.get("issue", {}).get("id")
        or payload.get("issueKey")
    )
    if not issue_key:
        raise HTTPException(400, "Missing issue key")

    run_id = enqueue_run(issue_key=issue_key, payload=payload)
    add_event(run_id, "info", "Webhook received", {"source": "jira_webhook"})
    return JSONResponse({"ok": True, "run_id": run_id})
