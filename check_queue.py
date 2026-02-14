#!/usr/bin/env python3
"""Quick diagnostic to check queue status for a specific issue."""
import sqlite3
import json
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent / "app" / "app.db"

print(f"Checking database: {DB_PATH}")
print(f"Database exists: {DB_PATH.exists()}\n")

if not DB_PATH.exists():
    print("❌ Database not found!")
    exit(1)

conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

# Check for OD-764 specifically
print("=" * 80)
print("Recent runs for OD-764:")
print("=" * 80)
cursor.execute("""
    SELECT id, issue_key, status, created_at, updated_at, locked_by, locked_at, priority, repo_key
    FROM runs 
    WHERE issue_key LIKE 'OD-764%'
    ORDER BY id DESC 
    LIMIT 10
""")

rows = cursor.fetchall()
if not rows:
    print("❌ No runs found for OD-764")
else:
    for row in rows:
        print(f"\nRun ID: {row[0]}")
        print(f"  Issue: {row[1]}")
        print(f"  Status: {row[2]}")
        print(f"  Created: {row[3]}")
        print(f"  Updated: {row[4]}")
        print(f"  Locked by: {row[5]}")
        print(f"  Locked at: {row[6]}")
        print(f"  Priority: {row[7]}")
        print(f"  Repo key: {row[8]}")

# Check all queued runs
print("\n" + "=" * 80)
print("All queued runs:")
print("=" * 80)
cursor.execute("""
    SELECT id, issue_key, status, repo_key, priority, locked_by, locked_at
    FROM runs 
    WHERE status = 'queued'
    ORDER BY priority ASC, id ASC
    LIMIT 20
""")

rows = cursor.fetchall()
if not rows:
    print("✅ No runs in queued status")
else:
    for row in rows:
        print(f"\n{row[0]}: {row[1]} - {row[2]} (repo: {row[3]}, priority: {row[4]}, locked_by: {row[5]}, locked_at: {row[6]})")

# Check claimed/running
print("\n" + "=" * 80)
print("Claimed/Running runs:")
print("=" * 80)
cursor.execute("""
    SELECT id, issue_key, status, repo_key, locked_by, locked_at
    FROM runs 
    WHERE status IN ('claimed', 'running')
    ORDER BY id DESC
    LIMIT 10
""")

rows = cursor.fetchall()
if not rows:
    print("✅ No runs in claimed/running status")
else:
    import time
    current_time = int(time.time())
    for row in rows:
        locked_at = row[5] if row[5] else 0
        age = current_time - locked_at if locked_at else 999999
        stale = " ⚠️ STALE" if age > 180 else ""
        print(f"{row[0]}: {row[1]} - {row[2]} (repo: {row[3]}, locked_by: {row[4]}, age: {age}s{stale})")

# Check recent failed runs
print("\n" + "=" * 80)
print("Recent failed runs:")
print("=" * 80)
cursor.execute("""
    SELECT id, issue_key, last_error, updated_at
    FROM runs 
    WHERE status = 'failed'
    ORDER BY id DESC
    LIMIT 5
""")

rows = cursor.fetchall()
if not rows:
    print("✅ No recent failed runs")
else:
    for row in rows:
        print(f"\n{row[0]}: {row[1]}")
        print(f"  Error: {row[2][:200] if row[2] else 'N/A'}")
        print(f"  Time: {row[3]}")

conn.close()
print("\n" + "=" * 80)
