#!/usr/bin/env python3
"""
Check for and optionally reset stuck runs in the database.

This script identifies runs that may be stuck in claimed/running state
due to worker crashes or other issues.

Usage:
    # Check for stuck runs (read-only)
    python scripts/check_stuck_runs.py

    # Reset stuck runs
    python scripts/check_stuck_runs.py --reset

    # Check specific issue
    python scripts/check_stuck_runs.py --issue TB-16

    # Reset specific issue
    python scripts/check_stuck_runs.py --issue TB-16 --reset
"""

import sys
import time
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import connect


def check_stuck_runs(issue_key=None, reset=False):
    """
    Check for stuck runs in the database.
    
    Args:
        issue_key: Optional issue key to check specific run
        reset: If True, reset stuck runs to failed status
    """
    with connect() as conn:
        cursor = conn.cursor()
        
        # Define "stuck" as claimed/running for more than 1 hour
        one_hour_ago = int(time.time()) - 3600
        
        if issue_key:
            # Check specific issue
            cursor.execute("""
                SELECT id, issue_key, status, locked_by, locked_at, created_at, updated_at
                FROM runs
                WHERE issue_key = ?
                ORDER BY id DESC
                LIMIT 10
            """, (issue_key.upper(),))
        else:
            # Check all potentially stuck runs
            cursor.execute("""
                SELECT id, issue_key, status, locked_by, locked_at, created_at, updated_at
                FROM runs
                WHERE status IN ('claimed', 'running')
                  AND (locked_at IS NULL OR locked_at < ?)
                ORDER BY locked_at ASC
            """, (one_hour_ago,))
        
        runs = cursor.fetchall()
        
        if not runs:
            if issue_key:
                print(f"✓ No runs found for {issue_key}")
            else:
                print("✓ No stuck runs found")
            return
        
        print(f"\n{'='*80}")
        print(f"Found {len(runs)} potentially stuck run(s):")
        print(f"{'='*80}\n")
        
        for run in runs:
            run_id, issue, status, locked_by, locked_at, created_at, updated_at = run
            
            print(f"Run ID:      {run_id}")
            print(f"Issue:       {issue}")
            print(f"Status:      {status}")
            print(f"Locked by:   {locked_by or 'None'}")
            
            if locked_at:
                locked_minutes_ago = (int(time.time()) - locked_at) // 60
                print(f"Locked at:   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(locked_at))} ({locked_minutes_ago} minutes ago)")
            else:
                print(f"Locked at:   None")
            
            created_minutes_ago = (int(time.time()) - created_at) // 60
            print(f"Created:     {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))} ({created_minutes_ago} minutes ago)")
            
            # Get last few events
            cursor.execute("""
                SELECT level, message, ts
                FROM events
                WHERE run_id = ?
                ORDER BY ts DESC
                LIMIT 3
            """, (run_id,))
            
            events = cursor.fetchall()
            if events:
                print(f"\nRecent events:")
                for event_level, event_msg, event_ts in events:
                    event_time = time.strftime('%H:%M:%S', time.localtime(event_ts))
                    print(f"  [{event_time}] {event_level.upper()}: {event_msg}")
            
            if reset:
                print(f"\n🔧 Resetting run {run_id} to failed status...")
                
                cursor.execute("""
                    UPDATE runs
                    SET status = 'failed',
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error = 'Run was stuck and automatically reset',
                        updated_at = ?
                    WHERE id = ?
                """, (int(time.time()), run_id))
                
                # Add event
                cursor.execute("""
                    INSERT INTO events (run_id, ts, level, message, meta_json)
                    VALUES (?, ?, 'info', 'Run reset by check_stuck_runs.py', '{}')
                """, (run_id, int(time.time())))
                
                conn.commit()
                print(f"✓ Run {run_id} reset to failed status")
            
            print(f"{'-'*80}\n")
        
        if not reset:
            print("\nTo reset these runs, use: python scripts/check_stuck_runs.py --reset")
            if not issue_key:
                print("To check specific issue: python scripts/check_stuck_runs.py --issue TB-16")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Check for and reset stuck runs in the database'
    )
    parser.add_argument(
        '--issue', 
        help='Check specific issue key (e.g., TB-16)'
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Reset stuck runs to failed status'
    )
    
    args = parser.parse_args()
    
    try:
        check_stuck_runs(issue_key=args.issue, reset=args.reset)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
