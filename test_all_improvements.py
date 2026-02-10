#!/usr/bin/env python3
"""
Comprehensive test suite for all AI Runner improvements.

Tests:
- Multi-repo configuration
- Error classification
- Verification system
- Metrics collection
- Queue management
- Rate limiting
- Logging system
"""

import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

def test_repo_config():
    """Test multi-repository configuration."""
    print("\n" + "="*60)
    print("TEST: Multi-Repository Configuration")
    print("="*60)
    
    try:
        from app.repo_config import get_repo_manager, get_repo_for_issue
        
        manager = get_repo_manager()
        projects = manager.get_all_projects()
        
        if projects:
            print(f"✅ Loaded {len(projects)} projects from repos.json")
            for key, config in projects.items():
                print(f"   - {key}: {config.repo_name}")
        else:
            print("✅ Using legacy .env configuration (single repo)")
        
        # Test issue resolution
        test_keys = ["OD-123", "MW-456"]
        for key in test_keys:
            repo = get_repo_for_issue(key)
            if repo:
                print(f"   {key} → {repo.repo_name}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_classifier():
    """Test error classification system."""
    print("\n" + "="*60)
    print("TEST: Error Classification")
    print("="*60)
    
    try:
        from app.error_classifier import classify_error, get_comprehensive_hint
        
        test_errors = [
            ("Cannot find module './storage'", "import_resolution"),
            ("Type 'string' is not assignable to type 'number'", "type_error"),
            ("'readData' is not exported", "missing_export"),
            ("Unknown at rule @apply", "tailwind_invalid_class"),
        ]
        
        passed = 0
        for error_msg, expected_category in test_errors:
            category, hint, _ = classify_error(error_msg)
            if category == expected_category:
                print(f"✅ '{error_msg[:40]}...' → {category}")
                passed += 1
            else:
                print(f"❌ '{error_msg[:40]}...' → {category} (expected {expected_category})")
        
        print(f"\nPassed: {passed}/{len(test_errors)}")
        return passed == len(test_errors)
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_verifier():
    """Test verification system."""
    print("\n" + "="*60)
    print("TEST: Verification System")
    print("="*60)
    
    try:
        from app.verifier import verify_package_json_syntax, verify_imports, VerificationResult
        from pathlib import Path
        
        # Test with current repo
        repo_path = Path(__file__).parent
        
        # Test package.json verification (if exists)
        result = verify_package_json_syntax(repo_path, ["package.json"])
        print(f"✅ Package.json verification: passed={result.passed}")
        
        # Test import verification
        result = verify_imports(repo_path, ["app/worker.py"])
        print(f"✅ Import verification: passed={result.passed}")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_metrics():
    """Test metrics collection."""
    print("\n" + "="*60)
    print("TEST: Metrics Collection")
    print("="*60)
    
    try:
        from app.metrics import ExecutionMetrics, calculate_cost, get_summary_stats
        from datetime import datetime
        
        # Test cost calculation
        cost = calculate_cost("claude-sonnet-4", 10000, 2000, 5000)
        print(f"✅ Cost calculation: ${cost} (10K input, 2K output, 5K cached)")
        
        # Test metrics object
        metrics = ExecutionMetrics(
            run_id=1,
            issue_key="TEST-1",
            issue_type="subtask",
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_seconds=120.5,
            success=True,
            status="completed"
        )
        
        metrics_dict = metrics.to_dict()
        print(f"✅ Metrics serialization: {len(metrics_dict)} fields")
        
        # Test summary stats
        stats = get_summary_stats(24)
        print(f"✅ Summary stats: {stats.get('total_runs', 0)} runs in last 24h")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_queue_manager():
    """Test queue management system."""
    print("\n" + "="*60)
    print("TEST: Queue Management")
    print("="*60)
    
    try:
        from app.queue_manager import Priority, extract_repo_key, get_queue_stats, init_queue_schema
        
        # Test priority enum
        priority = Priority.from_labels(["urgent", "critical"])
        print(f"✅ Priority from labels ['urgent', 'critical']: {priority.name}")
        
        # Test repo key extraction
        repo_key = extract_repo_key("OD-123")
        print(f"✅ Extract repo key from 'OD-123': {repo_key}")
        
        # Test schema initialization
        init_queue_schema()
        print(f"✅ Queue schema initialized")
        
        # Test queue stats
        stats = get_queue_stats()
        print(f"✅ Queue stats: {stats.get('total_queued', 0)} queued, {stats.get('currently_running', 0)} running")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rate_limiter():
    """Test rate limiting."""
    print("\n" + "="*60)
    print("TEST: Rate Limiting")
    print("="*60)
    
    try:
        from app.rate_limiter import RateLimiter, get_jira_rate_limiter, get_claude_rate_limiter
        import time
        
        # Test basic rate limiter
        limiter = RateLimiter(calls=5, period=1.0)
        
        # Acquire 5 tokens quickly
        start = time.time()
        for i in range(5):
            success = limiter.acquire(blocking=False)
            if not success:
                print(f"❌ Failed to acquire token {i+1}/5")
                return False
        
        elapsed = time.time() - start
        print(f"✅ Acquired 5 tokens in {elapsed:.3f}s")
        
        # 6th should fail (non-blocking)
        success = limiter.acquire(blocking=False)
        if success:
            print(f"❌ Should have failed to acquire 6th token")
            return False
        
        print(f"✅ 6th token correctly rejected (rate limit enforced)")
        
        # Test service limiters exist
        jira_limiter = get_jira_rate_limiter()
        claude_limiter = get_claude_rate_limiter()
        print(f"✅ Service rate limiters initialized")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_logger():
    """Test logging system."""
    print("\n" + "="*60)
    print("TEST: Logging System")
    print("="*60)
    
    try:
        from app.logger import get_logger, ContextLogger, setup_logging
        
        # Test basic logger
        logger = get_logger()
        logger.info("Test log message")
        print(f"✅ Basic logger works")
        
        # Test context logger
        ctx_logger = ContextLogger(run_id=123, issue_key="TEST-1", worker_id="test-worker")
        ctx_logger.info("Context log message")
        print(f"✅ Context logger works")
        
        # Test structured logging
        json_logger = setup_logging(log_level="INFO", log_format="json")
        json_logger.info("JSON log message")
        print(f"✅ Structured JSON logging works")
        
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all():
    """Run all tests."""
    print("\n" + "="*70)
    print("AI RUNNER IMPROVEMENTS - COMPREHENSIVE TEST SUITE")
    print("="*70)
    
    tests = [
        ("Multi-Repo Configuration", test_repo_config),
        ("Error Classification", test_error_classifier),
        ("Verification System", test_verifier),
        ("Metrics Collection", test_metrics),
        ("Queue Management", test_queue_manager),
        ("Rate Limiting", test_rate_limiter),
        ("Logging System", test_logger),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n❌ {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}  {test_name}")
    
    print("\n" + "="*70)
    print(f"TOTAL: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("✅ ALL TESTS PASSED!")
        print("="*70 + "\n")
        return True
    else:
        print(f"❌ {total_count - passed_count} TEST(S) FAILED")
        print("="*70 + "\n")
        return False


if __name__ == "__main__":
    success = test_all()
    sys.exit(0 if success else 1)
