import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple

DB_PATH = os.getenv("DB_PATH", "/srv/ai/state/moveware_ai.sqlite3")


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with connect() as cx:
        cx.execute("PRAGMA journal_mode=WAL;")
        cx.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT,
            branch TEXT,
            pr_url TEXT,
            last_error TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            locked_by TEXT,
            locked_at INTEGER
        );
        """)
        cx.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            ts INTEGER NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            meta_json TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(id)
        );
        """)
        cx.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_key TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(issue_key)
        );
        """)
        cx.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_runs_issue ON runs(issue_key);")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_plans_issue ON plans(issue_key);")
    
    # Initialize queue management schema
    from .queue_manager import init_queue_schema
    init_queue_schema()
    
    # Initialize pattern learning schema
    from .pattern_learner import init_pattern_learning_schema
    init_pattern_learning_schema()


@contextmanager
def connect():
    cx = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        yield cx
    finally:
        cx.close()


def now() -> int:
    return int(time.time())


# Dedup 2 disabled: blocking new runs after "recent" completion was too aggressive - prevented
# processing when issue moved to Selected for Development right after a NOOP. Rely on Dedup 1 only.
DEDUP_RECENT_COMPLETED_SECONDS = 0  # 0 = disabled


def enqueue_run(issue_key: str, payload: Dict[str, Any], priority: Optional[int] = None, force_new: bool = False) -> int:
    """
    Enqueue a run with optional priority.
    
    Deduplication (unless force_new): avoids duplicate runs for the same issue
    when webhooks fire repeatedly (e.g. multiple Jira automation rules).
    """
    from .queue_manager import Priority, extract_repo_key
    
    ts = now()
    
    # Extract repo key from issue_key
    repo_key = extract_repo_key(issue_key)
    
    # Determine priority from labels if not explicitly provided
    if priority is None:
        labels = []
        if isinstance(payload, dict):
            issue_data = payload.get("issue", {})
            fields = issue_data.get("fields", {})
            labels = fields.get("labels", [])
        
        priority_enum = Priority.from_labels(labels)
        priority = priority_enum.value
    
    with connect() as cx:
        if not force_new:
            # Dedup 1: Already have queued/claimed/running run for this issue - update payload, return existing
            row = cx.execute(
                "SELECT id FROM runs WHERE issue_key = ? AND status IN ('queued', 'claimed', 'running') LIMIT 1",
                (issue_key,),
            ).fetchone()
            if row:
                existing_id = row[0]
                cx.execute(
                    "UPDATE runs SET payload_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(payload), ts, existing_id),
                )
                return existing_id
            
            # Dedup 2: Recently completed (disabled when DEDUP_RECENT_COMPLETED_SECONDS=0)
            if DEDUP_RECENT_COMPLETED_SECONDS > 0:
                cutoff = ts - DEDUP_RECENT_COMPLETED_SECONDS
                row = cx.execute(
                    "SELECT id FROM runs WHERE issue_key = ? AND status IN ('completed', 'failed') AND updated_at > ? ORDER BY id DESC LIMIT 1",
                    (issue_key, cutoff),
                ).fetchone()
                if row:
                    return row[0]  # Skip creating duplicate; return existing run id
        
        cur = cx.execute(
            "INSERT INTO runs(issue_key,status,payload_json,created_at,updated_at,priority,repo_key) VALUES(?,?,?,?,?,?,?)",
            (issue_key, "queued", json.dumps(payload), ts, ts, priority, repo_key),
        )
        run_id = int(cur.lastrowid)
        cx.execute(
            "INSERT INTO events(run_id,ts,level,message,meta_json) VALUES(?,?,?,?,?)",
            (run_id, ts, "info", "Run enqueued", json.dumps({"issue_key": issue_key, "priority": priority, "repo_key": repo_key})),
        )
        return run_id


def claim_next_run(worker_id: str, stale_lock_seconds: int = 600) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    ts = now()
    with connect() as cx:
        cx.execute("BEGIN IMMEDIATE")
        # Release stale locks
        cx.execute(
            "UPDATE runs SET locked_by=NULL, locked_at=NULL WHERE locked_at IS NOT NULL AND locked_at < ? AND status IN ('queued','running')",
            (ts - stale_lock_seconds,),
        )
        row = cx.execute(
            "SELECT id, issue_key, payload_json FROM runs WHERE status='queued' AND locked_by IS NULL ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            cx.execute("COMMIT")
            return None
        run_id, issue_key, payload_json = row
        cx.execute(
            "UPDATE runs SET status='running', locked_by=?, locked_at=?, updated_at=? WHERE id=?",
            (worker_id, ts, ts, run_id),
        )
        cx.execute(
            "INSERT INTO events(run_id,ts,level,message,meta_json) VALUES(?,?,?,?,?)",
            (run_id, ts, "info", "Run claimed", json.dumps({"worker_id": worker_id})),
        )
        cx.execute("COMMIT")
        return int(run_id), str(issue_key), json.loads(payload_json or "{}")


def update_run(run_id: int, **fields: Any) -> None:
    allowed = {
        "status",
        "attempts",
        "branch",
        "pr_url",
        "last_error",
        "locked_by",
        "locked_at",
    }
    parts = []
    values = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        parts.append(f"{k}=?")
        values.append(v)
    if not parts:
        return
    parts.append("updated_at=?")
    values.append(now())
    values.append(run_id)
    with connect() as cx:
        cx.execute(f"UPDATE runs SET {', '.join(parts)} WHERE id=?", values)


def add_event(run_id: int, level: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
    with connect() as cx:
        cx.execute(
            "INSERT INTO events(run_id,ts,level,message,meta_json) VALUES(?,?,?,?,?)",
            (run_id, now(), level, message, json.dumps(meta or {})),
        )


def add_progress_event(run_id: int, stage: str, detail: str, meta: Optional[Dict[str, Any]] = None) -> None:
    """Add a standardized progress event for dashboard tracking.
    
    Args:
        run_id: The run ID
        stage: High-level stage (claimed, analyzing, planning, executing, committing, verifying, completed, failed)
        detail: Detailed description of current action
        meta: Optional metadata (file counts, timing, etc.)
    """
    full_meta = meta or {}
    full_meta["stage"] = stage
    add_event(run_id, "progress", detail, full_meta)


def get_run(run_id: int) -> Dict[str, Any]:
    with connect() as cx:
        row = cx.execute(
            "SELECT id, issue_key, status, attempts, payload_json, branch, pr_url, last_error, created_at, updated_at FROM runs WHERE id=?",
            (run_id,),
        ).fetchone()
    if not row:
        raise KeyError(run_id)
    return {
        "id": row[0],
        "issue_key": row[1],
        "status": row[2],
        "attempts": row[3],
        "payload": json.loads(row[4] or "{}"),
        "branch": row[5],
        "pr_url": row[6],
        "last_error": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def save_plan(issue_key: str, plan_data: Dict[str, Any]) -> None:
    """Save or update a plan for an issue."""
    ts = now()
    with connect() as cx:
        cx.execute(
            "INSERT OR REPLACE INTO plans(issue_key, plan_json, created_at) VALUES(?,?,?)",
            (issue_key, json.dumps(plan_data), ts),
        )


def get_plan(issue_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve the plan for an issue."""
    with connect() as cx:
        row = cx.execute(
            "SELECT plan_json FROM plans WHERE issue_key=?",
            (issue_key,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0])
