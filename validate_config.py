#!/usr/bin/env python3
"""
Configuration validator for AI Runner.

Checks that all required configuration is present and valid.
"""

import sys
import os
from pathlib import Path
import json

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))


def validate_env_vars():
    """Validate required environment variables."""
    print("\n" + "="*60)
    print("VALIDATING ENVIRONMENT VARIABLES")
    print("="*60 + "\n")
    
    # Load .env if exists
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)
        print(f"✓ Loaded .env file from {env_file}")
    else:
        print(f"⚠ No .env file found at {env_file}")
    
    required_vars = [
        ("LISTEN_HOST", "Server host (e.g., 127.0.0.1)"),
        ("LISTEN_PORT", "Server port (e.g., 8088)"),
        ("JIRA_BASE_URL", "Jira instance URL"),
        ("JIRA_EMAIL", "Jira user email"),
        ("JIRA_API_TOKEN", "Jira API token"),
        ("JIRA_AI_ACCOUNT_ID", "AI Runner Jira account ID"),
        ("JIRA_HUMAN_ACCOUNT_ID", "Human reviewer account ID"),
        ("JIRA_WEBHOOK_SECRET", "Webhook secret"),
        ("JIRA_STATUS_BACKLOG", "Backlog status name"),
        ("JIRA_STATUS_PLAN_REVIEW", "Plan Review status name"),
        ("JIRA_STATUS_SELECTED_FOR_DEV", "Selected for Development status name"),
        ("JIRA_STATUS_IN_PROGRESS", "In Progress status name"),
        ("JIRA_STATUS_IN_TESTING", "In Testing status name"),
        ("JIRA_STATUS_DONE", "Done status name"),
        ("JIRA_STATUS_BLOCKED", "Blocked status name"),
        ("REPO_SSH", "Git repository SSH URL"),
        ("REPO_WORKDIR", "Local working directory"),
        ("BASE_BRANCH", "Base branch name"),
        ("REPO_OWNER_SLUG", "GitHub owner/org"),
        ("REPO_NAME", "Repository name"),
        ("GH_TOKEN", "GitHub token"),
        ("OPENAI_API_KEY", "OpenAI API key"),
        ("OPENAI_MODEL", "OpenAI model"),
        ("OPENAI_BASE_URL", "OpenAI API base URL"),
        ("ANTHROPIC_API_KEY", "Anthropic API key"),
        ("ANTHROPIC_MODEL", "Anthropic model"),
        ("ANTHROPIC_BASE_URL", "Anthropic API base URL"),
    ]
    
    missing = []
    present = []
    
    for var_name, description in required_vars:
        value = os.getenv(var_name)
        if value:
            # Mask sensitive values
            if "KEY" in var_name or "TOKEN" in var_name or "SECRET" in var_name:
                display_value = value[:8] + "..." if len(value) > 8 else "***"
            else:
                display_value = value[:50]
            
            print(f"✅ {var_name:<30} = {display_value}")
            present.append(var_name)
        else:
            print(f"❌ {var_name:<30} - MISSING ({description})")
            missing.append(var_name)
    
    print()
    print(f"Present: {len(present)}/{len(required_vars)}")
    print(f"Missing: {len(missing)}")
    
    return len(missing) == 0


def validate_repos_config():
    """Validate repos.json if it exists."""
    print("\n" + "="*60)
    print("VALIDATING MULTI-REPO CONFIGURATION")
    print("="*60 + "\n")
    
    config_path = Path(__file__).parent / "config" / "repos.json"
    
    if not config_path.exists():
        print(f"⚠ No repos.json found at {config_path}")
        print(f"  This is normal for single-repo setups using .env")
        return True
    
    try:
        with open(config_path) as f:
            config = json.load(f)
        
        print(f"✅ repos.json is valid JSON")
        
        # Validate structure
        if "projects" not in config:
            print(f"❌ Missing 'projects' array")
            return False
        
        projects = config["projects"]
        print(f"✅ Found {len(projects)} project(s)")
        
        required_fields = ["jira_project_key", "repo_ssh", "repo_workdir", "base_branch", "repo_owner_slug", "repo_name"]
        
        all_valid = True
        for i, project in enumerate(projects):
            print(f"\n  Project {i+1}: {project.get('jira_project_key', 'UNKNOWN')}")
            
            for field in required_fields:
                if field in project:
                    print(f"    ✓ {field}")
                else:
                    print(f"    ✗ {field} - MISSING")
                    all_valid = False
        
        if "default_project_key" in config:
            print(f"\n✅ Default project: {config['default_project_key']}")
        else:
            print(f"\n⚠ No default_project_key set")
        
        return all_valid
        
    except json.JSONDecodeError as e:
        print(f"❌ repos.json has invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Error validating repos.json: {e}")
        return False


def validate_database():
    """Validate database connectivity."""
    print("\n" + "="*60)
    print("VALIDATING DATABASE")
    print("="*60 + "\n")
    
    try:
        from app.db import init_db, connect
        
        # Initialize database
        init_db()
        print(f"✅ Database initialized")
        
        # Test connection
        with connect() as conn:
            cursor = conn.cursor()
            
            # Check tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            required_tables = ["runs", "events", "plans"]
            for table in required_tables:
                if table in tables:
                    print(f"✅ Table '{table}' exists")
                else:
                    print(f"❌ Table '{table}' missing")
                    return False
            
            # Check for queue columns
            cursor.execute("PRAGMA table_info(runs)")
            columns = [row[1] for row in cursor.fetchall()]
            
            queue_columns = ["priority", "repo_key", "queue_position"]
            for col in queue_columns:
                if col in columns:
                    print(f"✅ Column 'runs.{col}' exists")
                else:
                    print(f"⚠ Column 'runs.{col}' missing (will be added on startup)")
            
            # Check metrics column
            if "metrics_json" in columns:
                print(f"✅ Column 'runs.metrics_json' exists")
            else:
                print(f"⚠ Column 'runs.metrics_json' missing (will be added on first metric save)")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def validate_git_config():
    """Validate git configuration."""
    print("\n" + "="*60)
    print("VALIDATING GIT CONFIGURATION")
    print("="*60 + "\n")
    
    try:
        import subprocess
        
        # Check git installed
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✅ Git installed: {result.stdout.strip()}")
        else:
            print(f"❌ Git not found")
            return False
        
        # Check gh CLI installed
        result = subprocess.run(["gh", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f"✅ GitHub CLI installed: {version}")
        else:
            print(f"❌ GitHub CLI (gh) not found")
            return False
        
        # Check gh authentication
        result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=5)
        if "Logged in" in result.stdout or "Logged in" in result.stderr:
            print(f"✅ GitHub CLI authenticated")
        else:
            print(f"⚠ GitHub CLI may not be authenticated")
            print(f"  Run: gh auth login")
        
        return True
        
    except FileNotFoundError as e:
        print(f"❌ Required tool not found: {e}")
        return False
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all validation checks."""
    print("\n" + "="*70)
    print("AI RUNNER CONFIGURATION VALIDATOR")
    print("="*70)
    
    checks = [
        ("Environment Variables", validate_env_vars),
        ("Multi-Repo Config", validate_repos_config),
        ("Database", validate_database),
        ("Git Configuration", validate_git_config),
    ]
    
    results = []
    for check_name, check_func in checks:
        try:
            passed = check_func()
            results.append((check_name, passed))
        except Exception as e:
            print(f"\n❌ {check_name} validation crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((check_name, False))
    
    # Final summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70 + "\n")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for check_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}  {check_name}")
    
    print("\n" + "="*70)
    
    if passed_count == total_count:
        print("✅ ALL VALIDATION CHECKS PASSED!")
        print("\nYour AI Runner is properly configured and ready to use.")
        print("="*70 + "\n")
        return 0
    else:
        print(f"❌ {total_count - passed_count} VALIDATION CHECK(S) FAILED")
        print("\nPlease fix the issues above before running the AI Runner.")
        print("="*70 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
