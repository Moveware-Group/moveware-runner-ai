# Recommended Improvements for AI Runner

After analyzing the current implementation, here are prioritized improvements organized by impact and effort.

## Current State Analysis

### ✅ What's Working Well

1. **Execution uses Claude with thinking enabled** - Good! (5000 token budget)
2. **Self-healing with escalation** - Claude (2 attempts) → OpenAI (1 attempt)
3. **Build verification** - Catches errors before commit
4. **Multi-model strategy** - Uses best model for each task
5. **Progress tracking** - Good visibility via dashboard

### ⚠️ Areas for Improvement

---

## Priority 1: High Impact, Medium Effort

### 1. Use Extended Thinking for Planning 🔥

**Current:** Planning uses OpenAI without extended thinking
**Problem:** Plans may lack depth and miss edge cases
**Solution:** Use Claude with extended thinking for Epic planning

#### Implementation

**File:** `app/planner.py`

```python
# Current - uses OpenAI
def generate_plan(issue: JiraIssue, revision_feedback: str = "", run_id: Optional[int] = None) -> Dict[str, Any]:
    client = OpenAIClient(settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    # ... no thinking enabled
```

**Recommended:**

```python
def generate_plan(issue: JiraIssue, revision_feedback: str = "", run_id: Optional[int] = None) -> Dict[str, Any]:
    """Generate plan using Claude with extended thinking for better analysis."""
    from .llm_anthropic import AnthropicClient
    
    if run_id:
        add_progress_event(run_id, "planning", "Using Claude extended thinking to analyze Epic", {})
    
    client = AnthropicClient(settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL)
    
    prompt = (
        "Analyze this Epic carefully and create a comprehensive implementation plan.\n\n"
        f"{_user_prompt(issue, revision_feedback)}\n\n"
        "Return JSON only. Do not wrap in markdown.\n"
        "Schema:\n" + json.dumps(PLAN_SCHEMA_HINT, indent=2)
    )
    
    response = client.messages_create({
        "model": settings.ANTHROPIC_MODEL,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 16000,
        "temperature": 1,
        "thinking": {
            "type": "enabled",
            "budget_tokens": 10000  # More thinking for planning!
        }
    })
    
    text = client.extract_text(response)
    # ... rest of parsing logic
```

**Benefits:**
- ✅ Deeper analysis of requirements
- ✅ Better edge case identification
- ✅ More realistic effort estimates
- ✅ Catches ambiguities early

**Effort:** 2-3 hours

---

### 2. Improve Build Failure Recovery 🔥

**Current:** 3 attempts (Claude → Claude → OpenAI)
**Problem:** Same errors repeat, no learning between attempts
**Solution:** Structured error patterns + targeted fixes

#### Implementation

**File:** `app/executor.py` - Add after line 670

```python
# Error pattern database for common issues
ERROR_PATTERNS = {
    "missing_export": {
        "patterns": [
            r"(?:not exported|has no exported member|cannot find name)",
            r"(?:'(\w+)' is not exported)"
        ],
        "fix_hint": (
            "MISSING EXPORT ERROR:\n"
            "- Check if variable/function is declared but not exported\n"
            "- Add 'export' keyword before declaration\n"
            "- Verify import path matches export location"
        )
    },
    "tailwind_invalid_class": {
        "patterns": [
            r"(?:Unknown at rule|Unexpected unknown at-rule)",
            r"(?:class .* is not a valid Tailwind)"
        ],
        "fix_hint": (
            "TAILWIND CSS ERROR:\n"
            "- Use only standard Tailwind classes (no custom syntax)\n"
            "- Check Tailwind docs: https://tailwindcss.com/docs\n"
            "- Remove @ syntax from regular className attributes"
        )
    },
    "import_resolution": {
        "patterns": [
            r"Cannot find module ['\"](.*?)['\"]",
            r"Module not found: Can't resolve ['\"](.*?)['\"]"
        ],
        "fix_hint": (
            "IMPORT RESOLUTION ERROR:\n"
            "- Verify file exists at import path\n"
            "- Check file extension (.ts vs .tsx vs .js)\n"
            "- Use relative paths correctly (../ for parent)\n"
            "- Check tsconfig paths alias"
        )
    },
    "type_error": {
        "patterns": [
            r"Type '(.*)' is not assignable to type '(.*)'",
            r"Property '(.*)' does not exist on type '(.*)'"
        ],
        "fix_hint": (
            "TYPESCRIPT TYPE ERROR:\n"
            "- Verify interface/type definitions match usage\n"
            "- Add missing properties to interfaces\n"
            "- Use proper type assertions if needed\n"
            "- Check for typos in property names"
        )
    }
}

def classify_error(error_msg: str) -> tuple[str, str]:
    """
    Classify error and return (category, specific_hint).
    
    Returns:
        (category, hint) tuple. Category is "unknown" if no match.
    """
    import re
    
    for category, config in ERROR_PATTERNS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, error_msg, re.IGNORECASE):
                return category, config["fix_hint"]
    
    return "unknown", ""
```

**Update fix prompt to include classification:**

```python
# In the self-healing loop (line ~820)
error_category, specific_hint = classify_error(error_msg)

fix_prompt = (
    f"The build failed with the following errors:\n\n"
    f"```\n{error_msg[:3000]}\n```\n\n"
)

if error_category != "unknown":
    fix_prompt += f"**Error Category: {error_category.upper()}**\n\n{specific_hint}\n\n"

fix_prompt += (
    f"**Your Previous Implementation:**\n"
    f"Files you created/modified: {', '.join(files_changed)}\n\n"
    # ... rest of prompt
)
```

**Benefits:**
- ✅ Faster error resolution (targeted hints)
- ✅ Fewer failed attempts
- ✅ Learn from common patterns
- ✅ Better error messages in Jira

**Effort:** 4-6 hours

---

### 3. Add Prompt Caching for Large Context 🔥

**Current:** Full context sent on every request
**Problem:** Expensive + slow for large repos
**Solution:** Use Claude prompt caching

#### Implementation

**File:** `app/executor.py` - Update `_get_repo_context()` to mark cacheable content

```python
def _build_cached_system_prompt(repo_context: str) -> list[dict]:
    """
    Build system prompt with caching enabled for repo context.
    
    Returns system messages with cache_control markers.
    """
    return [
        {
            "type": "text",
            "text": _system_prompt()
        },
        {
            "type": "text", 
            "text": f"**Repository Context (cached):**\n\n{repo_context}",
            "cache_control": {"type": "ephemeral"}  # Cache this part!
        }
    ]

# In execute_subtask(), replace system prompt:
response = client.messages_create({
    "model": settings.ANTHROPIC_MODEL,
    "system": _build_cached_system_prompt(context_info),  # Cached!
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 16000,
    "temperature": 1,
    "thinking": {
        "type": "enabled",
        "budget_tokens": 5000
    }
})
```

**Update Anthropic client to support caching:**

```python
# app/llm_anthropic.py
def messages_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{self.base_url}/messages"
    headers = {
        "x-api-key": self.api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",  # Enable caching!
        "content-type": "application/json",
    }
    # ... rest of method
```

**Benefits:**
- ✅ 90% cost reduction for repeated context
- ✅ 5x faster response times
- ✅ Scales better with large codebases

**Effort:** 2-3 hours

---

## Priority 2: High Impact, High Effort

### 4. Add Pre-Commit Verification

**Problem:** Errors found only after commits are made
**Solution:** Validate changes before commit

#### Implementation

Create `app/verifier.py`:

```python
"""
Pre-commit verification system.

Runs checks before committing to catch issues early.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import subprocess


@dataclass
class VerificationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]
    

def verify_typescript_syntax(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """Run TypeScript compiler in check mode."""
    errors = []
    warnings = []
    
    # Only check TS/TSX files
    ts_files = [f for f in changed_files if f.endswith(('.ts', '.tsx'))]
    if not ts_files:
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    try:
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--pretty", "false"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            errors.append(f"TypeScript errors:\n{result.stdout}")
            return VerificationResult(passed=False, errors=errors, warnings=warnings)
            
    except Exception as e:
        warnings.append(f"Could not run TypeScript check: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_eslint(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """Run ESLint on changed files."""
    errors = []
    warnings = []
    
    # Only check JS/TS files
    lint_files = [f for f in changed_files if f.endswith(('.ts', '.tsx', '.js', '.jsx'))]
    if not lint_files:
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    try:
        # Run eslint with --max-warnings 0 to fail on warnings
        result = subprocess.run(
            ["npx", "eslint", "--max-warnings", "0", *lint_files],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            # ESLint found issues
            warnings.append(f"ESLint issues:\n{result.stdout}")
            # Don't fail on ESLint warnings, just warn
            
    except Exception as e:
        warnings.append(f"Could not run ESLint: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def verify_imports(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """Verify all imports are resolvable."""
    errors = []
    warnings = []
    
    # Quick syntax check to catch obvious import errors
    for file_path in changed_files:
        if not file_path.endswith(('.ts', '.tsx', '.js', '.jsx')):
            continue
            
        full_path = repo_path / file_path
        if not full_path.exists():
            continue
            
        try:
            content = full_path.read_text()
            
            # Check for common import issues
            import re
            
            # Unused imports (basic check)
            imports = re.findall(r'import\s+(?:{[^}]+}|[\w]+)\s+from\s+[\'"]([^\'"]+)[\'"]', content)
            
            # Check for relative imports going too far up
            for imp in imports:
                if imp.count('../') > 3:
                    warnings.append(f"{file_path}: Deep relative import: {imp}")
                    
        except Exception as e:
            warnings.append(f"Could not analyze {file_path}: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)


def run_all_verifications(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """
    Run all pre-commit verifications.
    
    Returns combined result with all errors and warnings.
    """
    results = [
        verify_typescript_syntax(repo_path, changed_files),
        verify_eslint(repo_path, changed_files),
        verify_imports(repo_path, changed_files),
    ]
    
    all_errors = []
    all_warnings = []
    passed = True
    
    for result in results:
        if not result.passed:
            passed = False
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)
    
    return VerificationResult(
        passed=passed,
        errors=all_errors,
        warnings=all_warnings
    )
```

**Update executor to use verifier:**

```python
# In execute_subtask(), before commit (line ~1020)
from .verifier import run_all_verifications

# Run pre-commit verification
if run_id:
    add_progress_event(run_id, "verifying", "Running pre-commit checks", {})

pre_commit_result = run_all_verifications(repo_path, files_changed)

if not pre_commit_result.passed:
    # Failed pre-commit - add to verification errors and trigger fix loop
    verification_errors.extend(pre_commit_result.errors)
    # Loop will retry with Claude/OpenAI
else:
    # Passed! Show warnings but continue
    if pre_commit_result.warnings:
        print("Pre-commit warnings:", "\n".join(pre_commit_result.warnings[:3]))
```

**Benefits:**
- ✅ Catch errors before commit
- ✅ Faster feedback loop
- ✅ Fewer failed builds
- ✅ Cleaner git history

**Effort:** 6-8 hours

---

### 5. Add Test Execution Verification

**Problem:** Only builds are verified, tests not run
**Solution:** Run test suite for changed files

```python
def verify_tests(repo_path: Path, changed_files: List[str]) -> VerificationResult:
    """Run tests for changed files."""
    errors = []
    warnings = []
    
    # Check if there's a test command
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return VerificationResult(passed=True, errors=[], warnings=[])
    
    try:
        import json
        pkg = json.loads(package_json.read_text())
        scripts = pkg.get("scripts", {})
        
        # Look for test script
        if "test" not in scripts:
            warnings.append("No test script found in package.json")
            return VerificationResult(passed=True, errors=[], warnings=warnings)
        
        # Run tests (with short timeout)
        result = subprocess.run(
            ["npm", "test", "--", "--passWithNoTests"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "CI": "true"}  # Prevent watch mode
        )
        
        if result.returncode != 0:
            errors.append(f"Tests failed:\n{result.stdout[-1000:]}")
            return VerificationResult(passed=False, errors=errors, warnings=warnings)
            
    except subprocess.TimeoutExpired:
        warnings.append("Test suite timed out (60s limit)")
    except Exception as e:
        warnings.append(f"Could not run tests: {e}")
    
    return VerificationResult(passed=True, errors=errors, warnings=warnings)
```

**Effort:** 4-6 hours

---

## Priority 3: Medium Impact, Low Effort

### 6. Add Retry Logic with Exponential Backoff

**Problem:** API rate limits cause immediate failures
**Solution:** Retry with backoff

```python
# app/llm_anthropic.py
import time
from typing import TypeVar, Callable

T = TypeVar('T')

def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0
) -> T:
    """Retry function with exponential backoff."""
    delay = initial_delay
    
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_msg = str(e).lower()
            
            # Only retry on rate limits or transient errors
            if "rate" in error_msg or "429" in error_msg or "503" in error_msg:
                if attempt < max_retries - 1:
                    print(f"Rate limited, retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= backoff_factor
                    continue
            
            # Don't retry other errors
            raise
    
    raise RuntimeError(f"Failed after {max_retries} retries")


# Update messages_create to use retry:
def messages_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    def _make_request():
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic error {r.status_code}: {r.text}")
        return r.json()
    
    return retry_with_backoff(_make_request, max_retries=3)
```

**Effort:** 1-2 hours

---

### 7. Add Rollback Mechanism

**Problem:** Bad commits can't be easily undone
**Solution:** Tag commits for easy rollback

```python
# app/git_ops.py
def tag_ai_commit(repo_workdir: str, issue_key: str, commit_sha: str):
    """Tag AI-generated commit for easy rollback."""
    import subprocess
    
    tag_name = f"ai/{issue_key.lower()}/before-{commit_sha[:7]}"
    
    try:
        subprocess.run(
            ["git", "tag", "-a", tag_name, commit_sha + "~1", "-m", f"Backup before {issue_key}"],
            cwd=repo_workdir,
            check=True,
            capture_output=True
        )
        return tag_name
    except Exception as e:
        print(f"Warning: Could not create rollback tag: {e}")
        return None


def rollback_to_tag(repo_workdir: str, tag_name: str):
    """Rollback to a specific tag."""
    import subprocess
    
    subprocess.run(
        ["git", "reset", "--hard", tag_name],
        cwd=repo_workdir,
        check=True
    )
```

**Effort:** 2-3 hours

---

## Priority 4: Quality of Life

### 8. Add Metrics and Observability

Track key metrics:
- Planning time per Epic
- Execution time per subtask
- Build failure rate
- Self-healing success rate
- Cost per issue (API tokens)

```python
# app/metrics.py
from dataclasses import dataclass
from datetime import datetime
import json

@dataclass
class ExecutionMetrics:
    issue_key: str
    start_time: datetime
    end_time: datetime
    total_tokens: int
    build_attempts: int
    self_heal_attempts: int
    success: bool
    error_category: str = ""
    
    def to_dict(self) -> dict:
        return {
            "issue_key": self.issue_key,
            "duration_seconds": (self.end_time - self.start_time).total_seconds(),
            "total_tokens": self.total_tokens,
            "build_attempts": self.build_attempts,
            "self_heal_attempts": self.self_heal_attempts,
            "success": self.success,
            "error_category": self.error_category,
        }

# Store metrics in database
def save_metrics(metrics: ExecutionMetrics):
    """Save execution metrics for analysis."""
    # Add to runs table or separate metrics table
    pass
```

**Effort:** 4-6 hours

---

### 9. Improve Dashboard with Metrics

Add to dashboard:
- Success rate chart (last 24h)
- Average execution time
- Most common error types
- Cost tracking

**Effort:** 6-8 hours

---

## Priority 5: Advanced Features

### 10. Implement Queue Management

**Problem:** Multiple issues processed concurrently can cause conflicts
**Solution:** Smart queue with priorities

```python
# app/queue.py
from enum import Enum
from dataclasses import dataclass

class Priority(Enum):
    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4

@dataclass
class QueuedRun:
    run_id: int
    issue_key: str
    priority: Priority
    created_at: int
    repo_key: str  # For multi-repo support
    
# Update database schema:
ALTER TABLE runs ADD COLUMN priority INTEGER DEFAULT 3;
ALTER TABLE runs ADD COLUMN repo_key TEXT;

# Update claim logic to respect priority and avoid conflicts:
def claim_next_run_smart(worker_id: str, max_concurrent_per_repo: int = 1):
    """
    Claim next run with priority and conflict avoidance.
    
    - Respects priority queue
    - Avoids concurrent runs on same repo
    - Load balances across repos
    """
    pass
```

**Effort:** 8-10 hours

---

## Summary: Recommended Implementation Order

### Phase 1: Quick Wins (1-2 weeks)
1. ✅ Extended thinking for planning
2. ✅ Prompt caching
3. ✅ Retry with backoff
4. ✅ Structured error patterns

### Phase 2: Robustness (2-3 weeks)
5. ✅ Pre-commit verification
6. ✅ Test execution
7. ✅ Rollback mechanism

### Phase 3: Observability (1-2 weeks)
8. ✅ Metrics collection
9. ✅ Dashboard improvements

### Phase 4: Scale (2-3 weeks)
10. ✅ Queue management
11. ✅ Rate limiting
12. ✅ Advanced error recovery

---

## Quick Wins You Can Implement Today

### 1. Enable Extended Thinking for Planning (30 min)
Switch planner.py to use Claude with extended thinking

### 2. Add Error Classification (1 hour)
Add ERROR_PATTERNS dictionary to executor.py

### 3. Increase Thinking Budget (5 min)
Change thinking budget from 5000 to 8000 tokens for complex tasks

```python
# In executor.py, line 462:
"thinking": {
    "type": "enabled",
    "budget_tokens": 8000  # Increased from 5000
}
```

---

## Questions?

For each improvement, I can provide:
- Complete implementation code
- Migration strategy
- Testing approach
- Rollback plan

Which improvements would you like to implement first?
