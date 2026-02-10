#!/usr/bin/env python3
"""
Test script for multi-repository configuration.

Usage:
    python test_repo_config.py

This script tests that the repository configuration system is working correctly.
"""

import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from app.repo_config import get_repo_manager, get_repo_for_issue
    
    print("=" * 60)
    print("Multi-Repository Configuration Test")
    print("=" * 60)
    
    # Initialize manager
    manager = get_repo_manager()
    
    # List all configured projects
    projects = manager.get_all_projects()
    
    if not projects:
        print("\n⚠️  No projects configured in repos.json")
        print("   Falling back to environment variables (.env)")
        print("   This is normal for single-repository setups.")
    else:
        print(f"\n✅ Found {len(projects)} configured project(s):")
        print()
        for key, config in projects.items():
            print(f"  Project: {key}")
            print(f"    Name: {config.jira_project_name or 'N/A'}")
            print(f"    Repo: {config.repo_name}")
            print(f"    SSH: {config.repo_ssh}")
            print(f"    Path: {config.repo_workdir}")
            print(f"    Branch: {config.base_branch}")
            print()
    
    # Test issue key resolution
    print("-" * 60)
    print("Testing Issue Key Resolution:")
    print("-" * 60)
    
    test_keys = []
    
    # Add configured projects
    for key in projects.keys():
        test_keys.append(f"{key}-123")
    
    # Add some common test cases
    if not test_keys:
        test_keys = ["OD-123", "MW-456", "API-789"]
    
    # Add an unknown project
    test_keys.append("UNKNOWN-999")
    
    print()
    for issue_key in test_keys:
        repo = get_repo_for_issue(issue_key)
        project_key = issue_key.split("-")[0]
        
        if repo:
            print(f"  ✅ {issue_key:<15} → {repo.repo_name:<20} ({repo.repo_workdir})")
        else:
            print(f"  ⚠️  {issue_key:<15} → NO CONFIG (will use .env fallback)")
    
    print()
    print("-" * 60)
    print("Configuration Test Complete!")
    print("-" * 60)
    
    if projects:
        print("\n✅ Multi-repository configuration is active")
        print(f"   Using: config/repos.json")
    else:
        print("\n✅ Single-repository mode (using .env)")
        print("   To enable multi-repo: Create config/repos.json")
    
    print()
    
except Exception as e:
    print(f"\n❌ Error testing configuration: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
