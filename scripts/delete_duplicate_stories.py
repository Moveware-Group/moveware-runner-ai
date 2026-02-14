#!/usr/bin/env python3
"""
Delete duplicate Stories for Epic OD-48

Usage:
    python3 scripts/delete_duplicate_stories.py OD-48

Requirements:
    - Environment variables loaded (from .env or systemd environment file)
"""
import os
import sys
import time
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file if it exists
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    print(f"Loading environment from {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                # Remove quotes if present
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
else:
    # Try systemd environment file
    systemd_env = Path("/etc/moveware-ai.env")
    if systemd_env.exists():
        print(f"Loading environment from {systemd_env}")
        with open(systemd_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)
    else:
        print("⚠️  Warning: No .env file found. Make sure environment variables are set.")

from app.jira import JiraClient
from app.config import settings


def delete_stories_for_epic(epic_key: str, dry_run: bool = True):
    """Delete all Stories for an Epic."""
    jira = JiraClient()
    
    print(f"Fetching Stories for Epic {epic_key}...")
    stories = jira.get_stories_for_epic(epic_key)
    
    if not stories:
        print(f"✅ No Stories found for {epic_key}")
        return
    
    print(f"Found {len(stories)} Stories for {epic_key}")
    
    if dry_run:
        print("\n🔍 DRY RUN - Would delete the following Stories:")
        for story in stories:
            key = story.get("key")
            summary = (story.get("fields") or {}).get("summary", "No summary")
            print(f"  - {key}: {summary}")
        
        print(f"\n⚠️  This is a DRY RUN. No Stories were deleted.")
        print(f"To actually delete, run with: --confirm")
        return
    
    # Confirm deletion
    print(f"\n⚠️  WARNING: About to delete {len(stories)} Stories!")
    print(f"Epic: {epic_key}")
    
    confirm = input("\nType 'DELETE' to confirm: ")
    if confirm != "DELETE":
        print("❌ Deletion cancelled")
        return
    
    # Delete Stories
    print(f"\n🗑️  Deleting {len(stories)} Stories...")
    deleted_count = 0
    failed_count = 0
    
    for story in stories:
        key = story.get("key")
        summary = (story.get("fields") or {}).get("summary", "No summary")
        
        try:
            # Use Jira REST API to delete
            url = f"{jira.base_url}/rest/api/3/issue/{key}"
            import requests
            response = requests.delete(
                url,
                headers=jira._headers(),
                timeout=jira.timeout_s
            )
            
            if response.status_code in [204, 200]:
                deleted_count += 1
                print(f"  ✅ Deleted {key}: {summary[:60]}")
            else:
                failed_count += 1
                print(f"  ❌ Failed to delete {key}: HTTP {response.status_code}")
                print(f"     Response: {response.text[:200]}")
        
        except Exception as e:
            failed_count += 1
            print(f"  ❌ Error deleting {key}: {e}")
        
        # Rate limiting - be nice to Jira API
        time.sleep(0.5)
    
    print(f"\n✅ Deletion complete!")
    print(f"   Deleted: {deleted_count}")
    print(f"   Failed: {failed_count}")
    print(f"   Total: {len(stories)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/delete_duplicate_stories.py <EPIC_KEY> [--confirm]")
        print("\nExample:")
        print("  python scripts/delete_duplicate_stories.py OD-48          # Dry run")
        print("  python scripts/delete_duplicate_stories.py OD-48 --confirm  # Actually delete")
        sys.exit(1)
    
    epic_key = sys.argv[1]
    dry_run = "--confirm" not in sys.argv
    
    if not dry_run:
        print("⚠️  LIVE MODE - Stories WILL be deleted!")
    else:
        print("🔍 DRY RUN MODE - No changes will be made")
    
    print(f"\nEpic: {epic_key}")
    print(f"Jira: {settings.JIRA_BASE_URL}")
    print("-" * 60)
    
    delete_stories_for_epic(epic_key, dry_run=dry_run)


if __name__ == "__main__":
    main()
