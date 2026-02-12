# Environment Variable Type Error - Intelligent Fix

## Problem

AI failed 5 times to fix this error:
```
Type error: Property 'JWT_SECRET' does not exist on type 
'{ NODE_ENV: "development" | "production" | "test"; DATABASE_URL: string; ENCRYPTION_KEY: string; }'.
```

The error is clear: The env object's TypeScript type is missing `JWT_SECRET`. But the AI kept trying wrong approaches instead of simply adding it to the type definition.

## Root Cause

The AI wasn't:
1. Reading the env schema file (src/env.ts or similar)
2. Understanding that it just needs to add the property to the type
3. Getting explicit instructions about env type definitions

## Solution Implemented

### 1. New Error Pattern: `env_type_missing`

Added to error classifier with specific detection:
```python
"env_type_missing": {
    "patterns": [
        r"Property ['\"](\w+)['\"] does not exist on type.*?env",
        r"does not exist on type.*?NODE_ENV.*?DATABASE_URL",
        r"Property ['\"]([A-Z_]+)['\"] does not exist on type"
    ],
    "fix_hint": "..." # Detailed step-by-step instructions
}
```

### 2. Automatic Env File Inclusion

When `env_type_missing` is detected, automatically include env schema files:
- src/env.ts
- src/lib/env.ts
- src/env.mjs
- lib/env.ts
- etc.

The AI gets the ACTUAL env schema to work with.

### 3. Intelligent Auto-Fix

**Before LLM attempts**, try to fix it automatically:

```python
# 1. Detect missing env var (e.g., "JWT_SECRET")
# 2. Find env schema file
# 3. Add property to env object:
#    JWT_SECRET: process.env.JWT_SECRET!
# 4. Re-run build
# 5. If successful, skip LLM entirely
```

Example auto-fix:
```typescript
// BEFORE
const env = {
  NODE_ENV: process.env.NODE_ENV,
  DATABASE_URL: process.env.DATABASE_URL!,
  ENCRYPTION_KEY: process.env.ENCRYPTION_KEY!,
};

// AFTER (auto-fixed)
const env = {
  NODE_ENV: process.env.NODE_ENV,
  DATABASE_URL: process.env.DATABASE_URL!,
  ENCRYPTION_KEY: process.env.ENCRYPTION_KEY!,
  JWT_SECRET: process.env.JWT_SECRET!, // ← Added automatically
};
```

### 4. Enhanced Fix Hint

If auto-fix doesn't work, LLM gets explicit instructions:

```
**MANDATORY STEPS:**
1. READ the env schema file (src/env.ts)
2. FIND the type definition with NODE_ENV, DATABASE_URL
3. ADD the missing property
4. ENSURE it matches the error

**EXAMPLE:**
❌ Error: Property 'JWT_SECRET' does not exist
✅ Add to env object: JWT_SECRET: process.env.JWT_SECRET!

**DO NOT:**
- Remove the usage of env.JWT_SECRET
- Use 'any' type
- Add to wrong file
```

## Expected Results

### Before:
- ❌ AI tried 5 times
- ❌ Kept making wrong changes
- ❌ Never read the env file
- **Success rate: 0%**

### After:
- ✅ Auto-fix tries first (no LLM cost)
- ✅ If auto-fix fails, env file is in context
- ✅ Explicit instructions on what to do
- **Expected success rate: 95%+**

## Testing

To test this fix works:

1. Create a TypeScript error referencing missing env var
2. System should:
   - Detect `env_type_missing` pattern
   - Attempt auto-fix (add property)
   - If successful, skip LLM entirely
   - If not, include env file in LLM context

## Cost Savings

**Auto-fix success:** 
- No LLM calls needed
- $0 cost
- Instant fix (~5 seconds)

**LLM fallback:**
- 1 attempt instead of 5
- ~$0.10 instead of $0.50
- Much faster resolution

## Files Modified

- `app/error_classifier.py` - Added `env_type_missing` pattern
- `app/executor.py` - Auto-fix logic + auto-include env files
- `IMPROVEMENTS.md` - Documentation updated

## Related Patterns

This same approach can be extended to other "missing type property" errors:
- Missing database schema types
- Missing API response types
- Missing config interface properties

The pattern is:
1. Detect specific error
2. Find relevant schema file
3. Auto-fix if pattern is simple
4. Include schema in LLM context if auto-fix fails
5. Provide explicit fix instructions
