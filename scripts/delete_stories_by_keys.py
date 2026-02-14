#!/usr/bin/env python3
"""
Delete Stories by key range without using search API.

Directly tries to delete each key in the range, bypassing the search endpoint.

Usage:
    python3 scripts/delete_stories_by_keys.py OD 540 1130 [--confirm]

Examples:
    python3 scripts/delete_stories_by_keys.py OD 540 1130          # Dry run
    python3 scripts/delete_stories_by_keys.py OD 540 1130 --confirm  # Actually delete
"""
import os
import sys
import time
from pathlib import Path

# Load environment variables
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    print(f"Loading environment from {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
else:
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

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
import requests
import base64


def get_auth_header():
    """Get Jira authentication header."""
    token = base64.b64encode(f"{settings.JIRA_EMAIL}:{settings.JIRA_API_TOKEN}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def check_issue_exists(base_url: str, auth_header: str, issue_key: str) -> tuple[bool, str, str]:
    """
    Check if an issue exists and return its type and summary.
    Returns: (exists, issue_type, summary)
    """
    url = f"{base_url}/rest/api/3/issue/{issue_key}"
    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            fields = data.get("fields", {})
            issue_type = (fields.get("issuetype") or {}).get("name", "Unknown")
            summary = fields.get("summary", "No summary")
            return True, issue_type, summary
        elif r.status_code == 404:
            return False, "", ""
        else:
            return False, "", f"HTTP {r.status_code}"
    except Exception as e:
        return False, "", str(e)


def delete_issue(base_url: str, auth_header: str, issue_key: str) -> tuple[bool, str]:
    """
    Delete an issue.
    Returns: (success, error_message)
    """
    url = f"{base_url}/rest/api/3/issue/{issue_key}"
    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
    }
    
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code in [204, 200]:
            return True, ""
        else:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 scripts/delete_stories_by_keys.py <PROJECT> <START_NUM> <END_NUM> [--confirm]")
        print("\nExamples:")
        print("  python3 scripts/delete_stories_by_keys.py OD 540 1130          # Dry run")
        print("  python3 scripts/delete_stories_by_keys.py OD 540 1130 --confirm  # Actually delete")
        sys.exit(1)
    
    project_key = sys.argv[1]
    start_num = int(sys.argv[2])
    end_num = int(sys.argv[3])
    dry_run = "--confirm" not in sys.argv
    
    if not dry_run:
        print("⚠️  LIVE MODE - Issues WILL be deleted!")
    else:
        print("🔍 DRY RUN MODE - No changes will be made")
    
    print(f"\nProject: {project_key}")
    print(f"Range: {project_key}-{start_num} to {project_key}-{end_num}")
    print(f"Jira: {settings.JIRA_BASE_URL}")
    print("-" * 60)
    
    base_url = settings.JIRA_BASE_URL.rstrip("/")
    auth_header = get_auth_header()
    
    # First, scan to find what exists
    print(f"\n🔍 Scanning for existing issues in range...")
    existing_issues = []
    
    for num in range(start_num, end_num + 1):
        issue_key = f"{project_key}-{num}"
        exists, issue_type, summary = check_issue_exists(base_url, auth_header, issue_key)
        
        if exists:
            existing_issues.append({
                "key": issue_key,
                "type": issue_type,
                "summary": summary
            })
            
            # Show progress every 50 issues
            if len(existing_issues) % 50 == 0:
                print(f"  Found {len(existing_issues)} issues so far...")
        
        # Rate limiting
        time.sleep(0.1)
    
    print(f"\n✅ Found {len(existing_issues)} existing issues in range {project_key}-{start_num} to {project_key}-{end_num}")
    
    if not existing_issues:
        print("Nothing to delete!")
        return
    
    # Show what we found
    print(f"\n📋 Issues found:")
    stories = [i for i in existing_issues if i["type"] == "Story"]
    others = [i for i in existing_issues if i["type"] != "Story"]
    
    print(f"  Stories: {len(stories)}")
    if others:
        print(f"  Other types: {len(others)}")
        for issue in others[:10]:
            print(f"    - {issue['key']}: {issue['type']} - {issue['summary'][:60]}")
        if len(others) > 10:
            print(f"    ... and {len(others) - 10} more")
    
    # Show sample Stories
    print(f"\n  Sample Stories (first 10):")
    for issue in stories[:10]:
        print(f"    - {issue['key']}: {issue['summary'][:60]}")
    if len(stories) > 10:
        print(f"    ... and {len(stories) - 10} more")
    
    if dry_run:
        print(f"\n⚠️  This is a DRY RUN. No issues were deleted.")
        print(f"To actually delete, run with: --confirm")
        return
    
    # Confirm deletion
    print(f"\n⚠️  WARNING: About to delete {len(existing_issues)} issues!")
    print(f"  - Stories: {len(stories)}")
    if others:
        print(f"  - Other types: {len(others)}")
    
    confirm = input("\nType 'DELETE' to confirm: ")
    if confirm != "DELETE":
        print("❌ Deletion cancelled")
        return
    
    # Delete issues
    print(f"\n🗑️  Deleting {len(existing_issues)} issues...")
    deleted_count = 0
    failed_count = 0
    
    for issue in existing_issues:
        issue_key = issue["key"]
        summary = issue["summary"]
        
        success, error = delete_issue(base_url, auth_header, issue_key)
        
        if success:
            deleted_count += 1
            print(f"  ✅ Deleted {issue_key}: {summary[:60]}")
        else:
            failed_count += 1
            print(f"  ❌ Failed to delete {issue_key}: {error}")
        
        # Rate limiting
        time.sleep(0.5)
    
    print(f"\n✅ Deletion complete!")
    print(f"   Deleted: {deleted_count}")
    print(f"   Failed: {failed_count}")
    print(f"   Total: {len(existing_issues)}")


if __name__ == "__main__":
    main()
