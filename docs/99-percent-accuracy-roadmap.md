# Roadmap to 99% Build Accuracy

## Current State vs Target

**Current:** ~80-85% → **Target after recent improvements:** 95% → **Ultimate Goal:** 99%

Getting from 95% to 99% means **reducing failures by 80%** (from 5% fail rate to 1%). This requires advanced techniques beyond pattern matching.

## Key Challenges

The remaining 5% of failures typically fall into these categories:
1. **Complex multi-file dependencies** - Fix requires changes across 5+ files
2. **Ambiguous errors** - Error message doesn't clearly indicate root cause
3. **State/race conditions** - Build passes locally but fails in CI
4. **Deep architectural issues** - Requires understanding of project structure
5. **Novel error patterns** - Never seen before, no pattern match

## Strategies to Reach 99%

### 1. **Learning from Past Failures** 🎯 High Impact

**Implementation:**
- Store all failed build attempts in database with:
  - Error pattern
  - Files involved
  - What the AI tried
  - What actually worked (if eventually fixed manually)
- On new build error, search similar past failures
- Provide successful fix examples as context

**Database Schema:**
```sql
CREATE TABLE error_patterns (
    id INTEGER PRIMARY KEY,
    error_hash TEXT,  -- Hash of normalized error
    error_text TEXT,
    error_category TEXT,
    files_involved TEXT,  -- JSON array
    attempted_fixes TEXT,  -- JSON array of what didn't work
    successful_fix TEXT,  -- What actually worked
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    created_at INTEGER
);
```

**Expected Impact:** +2-3% accuracy (reduces repeat failures)

### 2. **Multi-Stage Fix Strategy** 🎯 High Impact

Instead of jumping straight to fix, use a structured approach:

```
Stage 1: ANALYZE (5s)
- Read error message
- Read mentioned files
- Identify error category
- List affected components

Stage 2: PLAN (10s)
- Determine root cause
- List files that need changes
- Verify files exist and are readable
- Check for similar past issues

Stage 3: VALIDATE PLAN (5s)
- Ensure all mentioned files exist
- Verify imports/exports are resolvable
- Check if plan addresses all errors

Stage 4: EXECUTE (20s)
- Apply planned changes
- Run build
- If fails, analyze what was wrong with plan

Stage 5: REFLECT (if failed)
- What did I misunderstand?
- What file did I not read that I should have?
- Adjust approach for next attempt
```

**Expected Impact:** +1-2% accuracy (better reasoning)

### 3. **Expanded Auto-Fix Library** 🎯 Medium Impact

Add auto-fixes for 20+ common patterns:

```python
AUTO_FIX_PATTERNS = {
    # TypeScript strict mode errors
    "implicit_any": auto_add_type_annotations,
    "strict_null_check": auto_add_null_checks,
    
    # Import/Export patterns
    "circular_dependency": auto_restructure_imports,
    "barrel_export_missing": auto_add_barrel_export,
    
    # React patterns
    "missing_key_prop": auto_add_keys_to_lists,
    "unsafe_lifecycle": auto_convert_to_hooks,
    
    # Package.json issues
    "peer_dependency": auto_install_peer_deps,
    "outdated_types": auto_update_types_package,
    
    # Environment variables
    "missing_env_var": auto_add_to_env_example,
    
    # Database/Prisma
    "prisma_migration": auto_run_prisma_migrate,
    "seed_data_missing": auto_run_seed,
}
```

**Expected Impact:** +1% accuracy (handles trivial issues)

### 4. **Enhanced Context Extraction** 🎯 High Impact

**Current:** Extract ~5-10 files mentioned in errors
**Improved:** Extract all relevant files proactively

```python
def get_comprehensive_context(error_msg, repo_path):
    """Get ALL files that might be relevant."""
    files = set()
    
    # 1. Direct mentions in error
    files.update(extract_paths_from_error(error_msg))
    
    # 2. Imports from those files
    for f in list(files):
        files.update(extract_all_imports(repo_path / f))
    
    # 3. Files that import the error files
    for f in list(files):
        files.update(find_files_importing(repo_path, f))
    
    # 4. Shared utilities/types
    files.update(find_common_utilities(repo_path))
    
    # 5. Config files that might affect build
    files.update(['tsconfig.json', 'next.config.js', '.eslintrc.json'])
    
    # 6. Package.json for dependency checks
    files.add('package.json')
    
    return files
```

**Expected Impact:** +1-2% accuracy (better context = better fixes)

### 5. **Validation Before Apply** 🎯 Medium Impact

Before applying a fix, validate it will work:

```python
def validate_fix_before_apply(fix_payload, repo_path, error_msg):
    """Check if fix is likely to work before applying."""
    
    validation_errors = []
    
    for file_change in fix_payload['files']:
        path = file_change['path']
        content = file_change['content']
        
        # Check 1: File path is valid
        if not is_valid_relative_path(path):
            validation_errors.append(f"Invalid path: {path}")
        
        # Check 2: If fixing import error, verify export exists
        if "has no exported member" in error_msg:
            missing_export = extract_missing_export(error_msg)
            if missing_export not in content:
                validation_errors.append(
                    f"Fix doesn't add missing export '{missing_export}'"
                )
        
        # Check 3: No obvious syntax errors in TypeScript
        if path.endswith(('.ts', '.tsx')):
            syntax_errors = check_typescript_syntax(content)
            if syntax_errors:
                validation_errors.append(f"Syntax errors in {path}: {syntax_errors}")
        
        # Check 4: All imports in fix have corresponding exports
        imports = extract_imports(content)
        for imp in imports:
            if not can_resolve_import(imp, repo_path):
                validation_errors.append(f"Import '{imp}' cannot be resolved")
    
    if validation_errors:
        return False, validation_errors
    
    return True, []
```

**Expected Impact:** +0.5-1% accuracy (prevents bad fixes)

### 6. **Iterative Self-Reflection** 🎯 High Impact

After each failed attempt, AI analyzes what went wrong:

```python
def analyze_fix_failure(attempt_num, previous_error, new_error, fix_applied):
    """Learn from what went wrong."""
    
    reflection_prompt = f"""
    ATTEMPT {attempt_num} FAILED. Analyze what went wrong:
    
    **Previous Error:**
    {previous_error}
    
    **Your Fix:**
    {fix_applied}
    
    **New Error:**
    {new_error}
    
    **Critical Analysis Questions:**
    1. Did I actually READ the files I needed to? Or did I guess?
    2. Did I address the ROOT CAUSE or just the symptom?
    3. Did I verify exports exist before changing imports?
    4. Did I introduce new errors while fixing old ones?
    5. What file did I NOT read that I should have?
    
    **Provide:**
    - What I did wrong
    - What I should do differently next attempt
    - Which specific files I need to read next
    """
    
    reflection = call_llm(reflection_prompt, model="fast")
    return reflection
```

**Expected Impact:** +1-2% accuracy (learns during same run)

### 7. **Pattern Learning Database** 🎯 Medium-High Impact

Build a knowledge base of successful fixes:

```python
class FixPatternLearner:
    def record_successful_fix(self, error_pattern, fix_strategy, files_changed):
        """Store successful fix for future reference."""
        
        pattern_hash = hash_error_pattern(error_pattern)
        
        # Update pattern database
        db.execute("""
            INSERT INTO fix_patterns (error_hash, error_category, strategy, files, success_count)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(error_hash) DO UPDATE SET
                success_count = success_count + 1,
                last_success = ?
        """, (pattern_hash, categorize(error_pattern), fix_strategy, json.dumps(files_changed), time.time()))
    
    def get_similar_successful_fixes(self, error_msg):
        """Find similar errors that were fixed successfully."""
        
        pattern_hash = hash_error_pattern(error_msg)
        
        # Exact match first
        exact = db.execute("""
            SELECT strategy, files, success_count
            FROM fix_patterns
            WHERE error_hash = ?
            ORDER BY success_count DESC
            LIMIT 1
        """, (pattern_hash,))
        
        if exact:
            return exact
        
        # Similar matches (fuzzy)
        category = categorize(error_msg)
        similar = db.execute("""
            SELECT strategy, files, success_count
            FROM fix_patterns
            WHERE error_category = ?
            ORDER BY success_count DESC
            LIMIT 5
        """, (category,))
        
        return similar
```

**Expected Impact:** +1-2% accuracy (learns from history)

### 8. **Better Model Selection** 🎯 Low-Medium Impact

Use different models for different tasks:

```python
# Current: Claude for all attempts 1-5, OpenAI for 6-7
# Improved:

ATTEMPT_STRATEGY = {
    1: {"model": "claude-sonnet-4", "thinking": 8000, "temperature": 0.3},  # Careful
    2: {"model": "claude-sonnet-4", "thinking": 10000, "temperature": 0.5}, # Slightly creative
    3: {"model": "gpt-5.2-codex", "temperature": 0.3},  # Different perspective
    4: {"model": "claude-sonnet-4", "thinking": 15000, "temperature": 0.7}, # More creative
    5: {"model": "gpt-5.2-codex", "temperature": 0.5},  # OpenAI again
    6: {"model": "claude-sonnet-4", "thinking": 20000, "temperature": 0.2}, # Very careful
    7: {"model": "gpt-5.2-codex", "temperature": 0.1},  # Most conservative
}
```

**Expected Impact:** +0.5% accuracy (better model fit)

### 9. **Proactive Dependency Management** 🎯 Medium Impact

Before build, check for common issues:

```python
def proactive_checks(repo_path):
    """Run checks before attempting build."""
    
    fixes_applied = []
    
    # Check 1: Missing peer dependencies
    peer_deps = check_peer_dependencies(repo_path)
    if peer_deps:
        install_peer_dependencies(peer_deps)
        fixes_applied.append(f"Installed peer deps: {peer_deps}")
    
    # Check 2: Outdated @types packages
    types_packages = check_types_packages(repo_path)
    if types_packages:
        update_types_packages(types_packages)
        fixes_applied.append(f"Updated @types: {types_packages}")
    
    # Check 3: Prisma client out of sync
    if needs_prisma_generate(repo_path):
        run_prisma_generate(repo_path)
        fixes_applied.append("Ran prisma generate")
    
    # Check 4: Lock file out of sync
    if package_json_newer_than_lock(repo_path):
        run_npm_install(repo_path)
        fixes_applied.append("Updated lock file")
    
    return fixes_applied
```

**Expected Impact:** +0.5-1% accuracy (prevents some failures)

### 10. **Human Feedback Loop** 🎯 Low Impact (Manual)

When a build fails after max attempts:
1. Post detailed error analysis to Jira
2. **Store the manual fix** when human fixes it
3. Use as training example for similar future errors

**Expected Impact:** +0.5% accuracy over time (learns from humans)

## Implementation Priority

### Phase 1: Quick Wins (1-2 weeks)
- ✅ Enhanced error patterns (DONE)
- ✅ Better fix prompt (DONE)
- ✅ Prisma intelligence (DONE)
- 🔲 Expanded auto-fix library
- 🔲 Proactive dependency checks
- 🔲 Better model selection

**Expected: 95% → 96-97%**

### Phase 2: Advanced Features (2-4 weeks)
- 🔲 Multi-stage fix strategy
- 🔲 Enhanced context extraction
- 🔲 Validation before apply
- 🔲 Iterative self-reflection

**Expected: 96-97% → 98%**

### Phase 3: Learning System (4-8 weeks)
- 🔲 Pattern learning database
- 🔲 Learning from past failures
- 🔲 Human feedback loop
- 🔲 Continuous pattern refinement

**Expected: 98% → 99%+**

## Cost Considerations

Higher accuracy = more tokens:

**Current (95%):**
- Avg 5-7 attempts per failed build
- ~50K tokens per failed build
- Cost: ~$0.50 per failed build

**Target (99%):**
- More comprehensive context (2x tokens)
- Multi-stage analysis (1.5x tokens)
- Better reasoning (extended thinking: 1.3x tokens)
- Cost: ~$1.00-1.50 per failed build
- But 80% fewer failures (5% → 1%)
- **Net cost: Similar or lower**

## Success Metrics

Track these metrics to measure progress:

```sql
-- Build success rate by week
SELECT 
    strftime('%Y-W%W', date(created_at, 'unixepoch')) as week,
    COUNT(*) as total_builds,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
    ROUND(100.0 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM runs
GROUP BY week
ORDER BY week DESC;

-- Most common error categories
SELECT 
    json_extract(metrics_json, '$.error_category') as category,
    COUNT(*) as occurrences
FROM runs
WHERE status = 'failed'
GROUP BY category
ORDER BY occurrences DESC;

-- Average fix attempts before success
SELECT 
    AVG(json_extract(metrics_json, '$.self_heal_attempts')) as avg_attempts
FROM runs
WHERE status = 'completed' AND json_extract(metrics_json, '$.self_heal_attempts') > 0;
```

## Conclusion

**Yes, 99% is achievable** with:
1. ✅ Better patterns (DONE)
2. 🔲 Multi-stage reasoning
3. 🔲 Learning from past failures
4. 🔲 More auto-fixes
5. 🔲 Better context extraction

**Timeline:** 2-3 months for full implementation
**Cost:** Similar or lower (fewer failures offset higher per-attempt cost)
**Effort:** Medium-High (requires database schema changes, new analysis stages)

The key is shifting from "pattern matching + retry" to "understand, learn, and prevent" approach.
