"""
Queue management system with priorities and conflict avoidance.

Manages run queue with:
- Priority-based selection
- Repo conflict avoidance
- Load balancing across repositories
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import time


class Priority(Enum):
    """Run priority levels."""
    URGENT = 1    # Critical bugs, production issues
    HIGH = 2      # Important features, high-value work
    NORMAL = 3    # Standard work
    LOW = 4       # Nice-to-have, cleanup, refactoring
    
    @classmethod
    def from_labels(cls, labels: list[str]) -> "Priority":
        """Determine priority from Jira labels."""
        label_set = {label.lower() for label in labels or []}
        
        if "urgent" in label_set or "p0" in label_set or "critical" in label_set:
            return cls.URGENT
        elif "high" in label_set or "p1" in label_set or "important" in label_set:
            return cls.HIGH
        elif "low" in label_set or "p3" in label_set or "cleanup" in label_set:
            return cls.LOW
        else:
            return cls.NORMAL


def init_queue_schema() -> None:
    """
    Initialize queue-related database schema.
    
    Adds priority and repo_key columns to runs table if they don't exist.
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Check existing columns
            cursor.execute("PRAGMA table_info(runs)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Add priority column if it doesn't exist
            if "priority" not in columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN priority INTEGER DEFAULT 3")
                print("✓ Added priority column to runs table")
            
            # Add repo_key column if it doesn't exist
            if "repo_key" not in columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN repo_key TEXT")
                print("✓ Added repo_key column to runs table")
            
            # Add queue_position column for manual overrides
            if "queue_position" not in columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN queue_position INTEGER DEFAULT 0")
                print("✓ Added queue_position column to runs table")
            
            conn.commit()
            
    except Exception as e:
        print(f"Warning: Could not initialize queue schema: {e}")


def extract_repo_key(issue_key: str) -> str:
    """
    Extract repository key from issue key.
    
    Args:
        issue_key: Jira issue key (e.g., "OD-123")
    
    Returns:
        Repository key (e.g., "OD")
    """
    return issue_key.split("-")[0] if "-" in issue_key else issue_key


def set_run_priority(run_id: int, priority: Priority, repo_key: Optional[str] = None) -> None:
    """
    Set priority for a run.
    
    Args:
        run_id: Run ID
        priority: Priority level
        repo_key: Optional repository key (will be extracted from issue_key if not provided)
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Get issue_key if repo_key not provided
            if not repo_key:
                cursor.execute("SELECT issue_key FROM runs WHERE id = ?", (run_id,))
                row = cursor.fetchone()
                if row:
                    repo_key = extract_repo_key(row[0])
            
            # Update priority and repo_key
            cursor.execute(
                "UPDATE runs SET priority = ?, repo_key = ? WHERE id = ?",
                (priority.value, repo_key, run_id)
            )
            conn.commit()
            
    except Exception as e:
        print(f"Warning: Could not set run priority: {e}")


def get_active_repos(worker_id: Optional[str] = None) -> set[str]:
    """
    Get list of repositories currently being processed.
    
    Args:
        worker_id: Optional filter by worker ID
    
    Returns:
        Set of active repository keys
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Get repos with running/claimed runs
            if worker_id:
                cursor.execute("""
                    SELECT DISTINCT repo_key 
                    FROM runs 
                    WHERE status IN ('claimed', 'running') 
                    AND locked_by = ?
                    AND repo_key IS NOT NULL
                """, (worker_id,))
            else:
                cursor.execute("""
                    SELECT DISTINCT repo_key 
                    FROM runs 
                    WHERE status IN ('claimed', 'running')
                    AND repo_key IS NOT NULL
                """)
            
            return {row[0] for row in cursor.fetchall()}
            
    except Exception as e:
        print(f"Warning: Could not get active repos: {e}")
        return set()


def claim_next_run_smart(
    worker_id: str,
    max_concurrent_per_repo: int = 1,
    respect_priorities: bool = True
) -> Optional[Tuple[int, str, Dict[str, Any]]]:
    """
    Claim next run with smart queue management.
    
    Features:
    - Respects priority queue (URGENT > HIGH > NORMAL > LOW)
    - Avoids concurrent runs on same repo (configurable)
    - Load balances across repositories
    - Considers manual queue_position overrides
    
    Args:
        worker_id: Worker ID claiming the run
        max_concurrent_per_repo: Max concurrent runs per repository (0 = unlimited)
        respect_priorities: If True, strictly follow priorities; if False, simple FIFO
    
    Returns:
        Tuple of (run_id, issue_key, payload) if found, None otherwise
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            current_ts = int(time.time())
            
            # Get currently active repos
            active_repos = get_active_repos()
            
            # Build query based on settings
            if respect_priorities:
                # Priority-based selection with repo conflict avoidance
                order_clause = "priority ASC, queue_position ASC, id ASC"
            else:
                # Simple FIFO
                order_clause = "id ASC"
            
            # Build WHERE clause for repo conflicts
            repo_conflict_clause = ""
            params = []
            
            if max_concurrent_per_repo > 0 and active_repos:
                # Exclude repos that are already at max capacity
                repo_counts = {}
                for repo in active_repos:
                    cursor.execute("""
                        SELECT COUNT(*) FROM runs 
                        WHERE repo_key = ? 
                        AND status IN ('claimed', 'running')
                    """, (repo,))
                    count = cursor.fetchone()[0]
                    if count >= max_concurrent_per_repo:
                        repo_counts[repo] = count
                
                if repo_counts:
                    # Exclude overloaded repos
                    excluded_repos = list(repo_counts.keys())
                    placeholders = ",".join(["?" for _ in excluded_repos])
                    repo_conflict_clause = f"AND (repo_key IS NULL OR repo_key NOT IN ({placeholders}))"
                    params.extend(excluded_repos)
            
            # Find next run
            query = f"""
                SELECT id, issue_key, payload_json 
                FROM runs 
                WHERE status = 'queued' 
                AND (locked_by IS NULL OR locked_at < ?)
                {repo_conflict_clause}
                ORDER BY {order_clause}
                LIMIT 1
            """
            
            params.insert(0, current_ts - 300)  # Consider stale locks (5 min)
            
            cursor.execute(query, params)
            row = cursor.fetchone()
            
            if not row:
                return None
            
            run_id, issue_key, payload_json = row
            
            # Claim the run
            cursor.execute(
                """
                UPDATE runs 
                SET status = 'claimed', locked_by = ?, locked_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (worker_id, current_ts, run_id)
            )
            
            if cursor.rowcount == 0:
                # Someone else claimed it
                return None
            
            conn.commit()
            
            # Parse payload
            import json
            payload = json.loads(payload_json) if payload_json else {}
            
            return (run_id, issue_key, payload)
            
    except Exception as e:
        print(f"Error in claim_next_run_smart: {e}")
        return None


def get_queue_stats() -> Dict[str, Any]:
    """
    Get queue statistics.
    
    Returns:
        Dictionary with queue stats by priority, repo, etc.
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Total queued
            cursor.execute("SELECT COUNT(*) FROM runs WHERE status = 'queued'")
            total_queued = cursor.fetchone()[0]
            
            # By priority
            cursor.execute("""
                SELECT priority, COUNT(*) 
                FROM runs 
                WHERE status = 'queued' 
                GROUP BY priority
                ORDER BY priority
            """)
            by_priority = {Priority(row[0]).name: row[1] for row in cursor.fetchall()}
            
            # By repo
            cursor.execute("""
                SELECT repo_key, COUNT(*) 
                FROM runs 
                WHERE status = 'queued' 
                AND repo_key IS NOT NULL
                GROUP BY repo_key
            """)
            by_repo = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Currently running
            cursor.execute("SELECT COUNT(*) FROM runs WHERE status IN ('claimed', 'running')")
            currently_running = cursor.fetchone()[0]
            
            # Currently running by repo
            cursor.execute("""
                SELECT repo_key, COUNT(*) 
                FROM runs 
                WHERE status IN ('claimed', 'running')
                AND repo_key IS NOT NULL
                GROUP BY repo_key
            """)
            running_by_repo = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                "total_queued": total_queued,
                "by_priority": by_priority,
                "by_repo": by_repo,
                "currently_running": currently_running,
                "running_by_repo": running_by_repo
            }
            
    except Exception as e:
        print(f"Error getting queue stats: {e}")
        return {"error": str(e)}
