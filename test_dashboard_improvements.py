#!/usr/bin/env python3
"""
Test script for dashboard improvements (time filtering and cost tracking).

Usage:
    python test_dashboard_improvements.py
"""

import requests
import sys
from typing import Dict, Any

# Base URL for the API (adjust if needed)
BASE_URL = "http://localhost:8088"


def test_status_api_with_time_filter():
    """Test /api/status endpoint with different time filters."""
    print("\n" + "="*60)
    print("Testing /api/status endpoint with time filters")
    print("="*60)
    
    time_filters = ["1", "6", "12", "24", "168", "all"]
    
    for hours in time_filters:
        try:
            response = requests.get(f"{BASE_URL}/api/status", params={"hours": hours})
            response.raise_for_status()
            data = response.json()
            
            runs_count = len(data.get("runs", []))
            print(f"\n✅ hours={hours:>3}: {runs_count} runs returned")
            
            if runs_count > 0:
                first_run = data["runs"][0]
                print(f"   Latest run: {first_run.get('issue_key')} ({first_run.get('status')})")
        
        except requests.exceptions.ConnectionError:
            print(f"\n❌ Connection failed: Is the server running at {BASE_URL}?")
            return False
        except Exception as e:
            print(f"\n❌ hours={hours}: Error - {e}")
            return False
    
    return True


def test_metrics_api_with_time_filter():
    """Test /api/metrics/summary endpoint with different time filters."""
    print("\n" + "="*60)
    print("Testing /api/metrics/summary endpoint with time filters")
    print("="*60)
    
    time_filters = [1, 6, 12, 24, 168]
    
    for hours in time_filters:
        try:
            response = requests.get(f"{BASE_URL}/api/metrics/summary", params={"hours": hours})
            response.raise_for_status()
            data = response.json()
            
            total_runs = data.get("total_runs", 0)
            cost = data.get("total_cost_usd", 0)
            success_rate = data.get("success_rate", 0)
            
            print(f"\n✅ hours={hours:>3}:")
            print(f"   Total runs: {total_runs}")
            print(f"   Success rate: {success_rate}%")
            print(f"   Total cost: ${cost:.2f}")
            print(f"   Total tokens: {data.get('total_tokens', 0):,}")
            
            if data.get("error_categories"):
                print(f"   Error categories: {data['error_categories']}")
        
        except requests.exceptions.ConnectionError:
            print(f"\n❌ Connection failed: Is the server running at {BASE_URL}?")
            return False
        except Exception as e:
            print(f"\n❌ hours={hours}: Error - {e}")
            return False
    
    return True


def test_cost_tracking_verification():
    """Verify that cost tracking is working by checking recent runs."""
    print("\n" + "="*60)
    print("Testing cost tracking in metrics")
    print("="*60)
    
    try:
        # Get recent runs
        response = requests.get(f"{BASE_URL}/api/metrics/summary", params={"hours": 24})
        response.raise_for_status()
        data = response.json()
        
        total_cost = data.get("total_cost_usd", 0)
        total_runs = data.get("total_runs", 0)
        
        print(f"\n📊 Last 24 hours:")
        print(f"   Total runs: {total_runs}")
        print(f"   Total cost: ${total_cost:.4f}")
        
        if total_runs > 0:
            if total_cost > 0:
                avg_cost = total_cost / total_runs
                print(f"   Average cost per run: ${avg_cost:.4f}")
                print("\n✅ Cost tracking is working!")
                return True
            else:
                print("\n⚠️  Cost is $0 - this might indicate:")
                print("   1. Recent runs haven't completed yet")
                print("   2. Metrics aren't being saved (check executor.py)")
                print("   3. No runs have been executed in the last 24 hours")
                return False
        else:
            print("\n⚠️  No runs in the last 24 hours")
            print("   To test cost tracking:")
            print("   1. Trigger a run through Jira")
            print("   2. Wait for it to complete")
            print("   3. Run this test again")
            return True  # Not a failure, just no data
    
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection failed: Is the server running at {BASE_URL}?")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def test_dashboard_rendering():
    """Test that the dashboard page loads successfully."""
    print("\n" + "="*60)
    print("Testing dashboard page rendering")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/status")
        response.raise_for_status()
        
        html = response.text
        
        # Check for key elements
        checks = [
            ("Time filter dropdown", 'id="timeFilter"'),
            ("Metrics section", 'id="metricsSection"'),
            ("Success rate metric", 'id="successRate"'),
            ("Total cost metric", 'id="totalCost"'),
            ("Runs container", 'id="runsContainer"'),
            ("Last Hour option", '<option value="1">Last Hour</option>'),
            ("Last 24 Hours option", '<option value="24" selected>Last 24 Hours</option>'),
            ("All Time option", '<option value="all">All Time</option>'),
        ]
        
        all_passed = True
        for name, check_string in checks:
            if check_string in html:
                print(f"✅ {name}: Found")
            else:
                print(f"❌ {name}: NOT FOUND")
                all_passed = False
        
        return all_passed
    
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection failed: Is the server running at {BASE_URL}?")
        return False
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Dashboard Improvements Test Suite")
    print("="*60)
    print(f"Testing server at: {BASE_URL}")
    
    results = {
        "Status API": test_status_api_with_time_filter(),
        "Metrics API": test_metrics_api_with_time_filter(),
        "Cost Tracking": test_cost_tracking_verification(),
        "Dashboard Rendering": test_dashboard_rendering(),
    }
    
    # Summary
    print("\n" + "="*60)
    print("Test Results Summary")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:25s} : {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✅ All tests passed!")
        print(f"\nDashboard available at: {BASE_URL}/status")
        return 0
    else:
        print("\n❌ Some tests failed. Check the output above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
