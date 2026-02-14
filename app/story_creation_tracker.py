"""
Story Creation Tracker - Prevents duplicate Story creation.

Uses database to track which Epics have already had Stories created,
providing a reliable check that doesn't depend on Jira API.
"""
import sqlite3
import time
from pathlib import Path
from typing import Optional


DB_PATH = Path("/srv/ai/state/moveware_ai.sqlite3")


def init_story_creation_tracker():
    """Initialize the story_creation_tracker table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS story_creation_tracker (
            epic_key TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            story_count INTEGER NOT NULL,
            created_by_worker TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    print("✅ Story creation tracker schema initialized")


def mark_stories_created(epic_key: str, story_count: int, worker_id: str = "unknown") -> None:
    """
    Mark that Stories have been created for an Epic.
    
    Args:
        epic_key: The Epic key
        story_count: Number of Stories created
        worker_id: Worker that created the Stories
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO story_creation_tracker 
        (epic_key, created_at, story_count, created_by_worker)
        VALUES (?, ?, ?, ?)
    """, (epic_key, int(time.time()), story_count, worker_id))
    
    conn.commit()
    conn.close()
    
    print(f"✅ Marked {story_count} Stories created for Epic {epic_key}")


def were_stories_already_created(epic_key: str) -> tuple[bool, Optional[int]]:
    """
    Check if Stories were already created for an Epic.
    
    Args:
        epic_key: The Epic key
    
    Returns:
        (already_created, story_count_if_created)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT story_count, created_at, created_by_worker
        FROM story_creation_tracker
        WHERE epic_key = ?
    """, (epic_key,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        story_count, created_at, worker_id = row
        age_seconds = int(time.time()) - created_at
        print(f"✅ Stories for Epic {epic_key} were already created {age_seconds}s ago by {worker_id} ({story_count} Stories)")
        return True, story_count
    
    return False, None


def clear_story_creation_flag(epic_key: str) -> None:
    """
    Clear the Story creation flag for an Epic.
    Use this if you want to allow Stories to be regenerated.
    
    Args:
        epic_key: The Epic key
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM story_creation_tracker
        WHERE epic_key = ?
    """, (epic_key,))
    
    conn.commit()
    conn.close()
    
    print(f"✅ Cleared Story creation flag for Epic {epic_key}")
