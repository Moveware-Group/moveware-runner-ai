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


def get_stories_for_epic_alternative(jira: JiraClient, epic_key: str):
    """Alternative method to get Stories - try multiple approaches."""
    import requests
    
    # Method 1: Try with 'Parent' field
    jql1 = f'parent = {epic_key} AND issuetype = Story'
    print(f"Trying JQL: {jql1}")
    
    url = f"{jira.base_url}/rest/api/3/search"
    params = {
        "jql": jql1,
        "maxResults": 1000,
        "fields": "summary,status,assignee,parent,issuetype"
    }
    
    try:
        r = requests.get(url, headers=jira._headers(), params=params, timeout=jira.timeout_s)
        if r.status_code == 200:
            result = r.json()
            stories = result.get("issues", [])
            if stories:
                print(f"✅ Method 1 succeeded: Found {len(stories)} Stories")
                return stories
        else:
            print(f"⚠️  Method 1 failed: HTTP {r.status_code}")
    except Exception as e:
        print(f"⚠️  Method 1 failed: {e}")
    
    # Method 2: Try with Epic Link field (common custom field)
    for epic_link_field in ["customfield_10014", "customfield_10008", "customfield_10100"]:
        jql2 = f'"{epic_link_field}" = {epic_key} AND issuetype = Story'
        print(f"Trying JQL with {epic_link_field}: {jql2}")
        
        params["jql"] = jql2
        try:
            r = requests.get(url, headers=jira._headers(), params=params, timeout=jira.timeout_s)
            if r.status_code == 200:
                result = r.json()
                stories = result.get("issues", [])
                if stories:
                    print(f"✅ Method 2 ({epic_link_field}) succeeded: Found {len(stories)} Stories")
                    return stories
        except Exception:
            pass
    
    # Method 3: Get Epic and extract linked issues
    print(f"Trying method 3: Get Epic {epic_key} and extract children...")
    try:
        epic = jira.get_issue(epic_key)
        fields = epic.get("fields", {})
        
        # Look for subtasks or children
        subtasks = fields.get("subtasks", [])
        stories = [st for st in subtasks if st.get("fields", {}).get("issuetype", {}).get("name") == "Story"]
        
        if stories:
            print(f"✅ Method 3 succeeded: Found {len(stories)} Stories in Epic children")
            # Fetch full details
            full_stories = []
            for st in stories:
                st_key = st.get("key")
                if st_key:
                    full_stories.append(jira.get_issue(st_key))
            return full_stories
    except Exception as e:
        print(f"⚠️  Method 3 failed: {e}")
    
    return []


def delete_stories_for_epic(epic_key: str, dry_run: bool = True):
    """Delete all Stories for an Epic."""
    jira = JiraClient()
    
    print(f"Fetching Stories for Epic {epic_key}...")
    
    # Try the standard method first
    stories = jira.get_stories_for_epic(epic_key)
    
    # If that failed, try alternative methods
    if not stories:
        print("Standard method failed, trying alternative approaches...")
        stories = get_stories_for_epic_alternative(jira, epic_key)
    
    if not stories:
        print(f"✅ No Stories found for {epic_key}")
        print("\nNote: If you can see Stories in Jira but this script can't find them,")
        print("      the Stories might be linked differently (not as parent-child).")
        print("      You may need to delete them manually via Jira UI.")
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


def find_stories_by_key_range(jira: JiraClient, project_key: str, start_num: int, end_num: int):
    """Find Stories by key range (e.g., OD-540 to OD-1130)."""
    import requests
    
    print(f"Searching for Stories {project_key}-{start_num} to {project_key}-{end_num}...")
    
    # Build JQL to find Stories in key range
    jql = f'project = {project_key} AND issuetype = Story AND key >= {project_key}-{start_num} AND key <= {project_key}-{end_num}'
    
    url = f"{jira.base_url}/rest/api/3/search"
    params = {
        "jql": jql,
        "maxResults": 1000,
        "fields": "summary,status,assignee,parent,issuetype,created"
    }
    
    try:
        r = requests.get(url, headers=jira._headers(), params=params, timeout=jira.timeout_s)
        r.raise_for_status()
        result = r.json()
        stories = result.get("issues", [])
        print(f"✅ Found {len(stories)} Stories in key range")
        return stories
    except Exception as e:
        print(f"❌ Failed to search by key range: {e}")
        return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/delete_duplicate_stories.py <EPIC_KEY or KEY_RANGE> [--confirm]")
        print("\nExamples:")
        print("  python3 scripts/delete_duplicate_stories.py OD-48          # Find Stories by Epic")
        print("  python3 scripts/delete_duplicate_stories.py OD-540:1130    # Find Stories by key range")
        print("  python3 scripts/delete_duplicate_stories.py OD-48 --confirm  # Actually delete")
        sys.exit(1)
    
    arg = sys.argv[1]
    dry_run = "--confirm" not in sys.argv
    
    if not dry_run:
        print("⚠️  LIVE MODE - Stories WILL be deleted!")
    else:
        print("🔍 DRY RUN MODE - No changes will be made")
    
    print(f"Jira: {settings.JIRA_BASE_URL}")
    print("-" * 60)
    
    # Check if argument is a key range (e.g., OD-540:1130)
    if ":" in arg:
        project_key, range_part = arg.split("-", 1)
        start_str, end_str = range_part.split(":")
        start_num = int(start_str)
        end_num = int(end_str)
        
        jira = JiraClient()
        stories = find_stories_by_key_range(jira, project_key, start_num, end_num)
        
        if not stories:
            print(f"✅ No Stories found in range {arg}")
            return
        
        # Continue with deletion logic...
        print(f"Found {len(stories)} Stories in key range {arg}")
        
        if dry_run:
            print("\n🔍 DRY RUN - Would delete the following Stories:")
            for story in stories[:20]:  # Show first 20
                key = story.get("key")
                summary = (story.get("fields") or {}).get("summary", "No summary")
                print(f"  - {key}: {summary[:60]}")
            if len(stories) > 20:
                print(f"  ... and {len(stories) - 20} more")
            
            print(f"\n⚠️  This is a DRY RUN. No Stories were deleted.")
            print(f"To actually delete, run with: --confirm")
            return
        
        # Confirm and delete (reuse logic from delete_stories_for_epic)
        print(f"\n⚠️  WARNING: About to delete {len(stories)} Stories!")
        confirm = input("\nType 'DELETE' to confirm: ")
        if confirm != "DELETE":
            print("❌ Deletion cancelled")
            return
        
        # Delete stories (reuse deletion logic)
        print(f"\n🗑️  Deleting {len(stories)} Stories...")
        deleted_count = 0
        failed_count = 0
        
        for story in stories:
            key = story.get("key")
            summary = (story.get("fields") or {}).get("summary", "No summary")
            
            try:
                import requests
                url = f"{jira.base_url}/rest/api/3/issue/{key}"
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
            except Exception as e:
                failed_count += 1
                print(f"  ❌ Error deleting {key}: {e}")
            
            time.sleep(0.5)
        
        print(f"\n✅ Deletion complete!")
        print(f"   Deleted: {deleted_count}")
        print(f"   Failed: {failed_count}")
        print(f"   Total: {len(stories)}")
    else:
        # Original Epic-based deletion
        epic_key = arg
        print(f"\nEpic: {epic_key}")
        delete_stories_for_epic(epic_key, dry_run=dry_run)


if __name__ == "__main__":
    main()
