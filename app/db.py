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
        cx.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_runs_issue ON runs(issue_key);")


@contextmanager
def connect():
    cx = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        yield cx
    finally:
        cx.close()


def now() -> int:
    return int(time.time())


def enqueue_run(issue_key: str, payload: Dict[str, Any]) -> int:
    ts = now()
    with connect() as cx:
        cur = cx.execute(
            "INSERT INTO runs(issue_key,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?)",
            (issue_key, "queued", json.dumps(payload), ts, ts),
        )
        run_id = int(cur.lastrowid)
        cx.execute(
            "INSERT INTO events(run_id,ts,level,message,meta_json) VALUES(?,?,?,?,?)",
            (run_id, ts, "info", "Run enqueued", json.dumps({"issue_key": issue_key})),
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
