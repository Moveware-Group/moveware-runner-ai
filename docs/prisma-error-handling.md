# Prisma Model Missing Error - Enhanced Handling

## Problem

AI repeatedly failed to fix Prisma model import errors like:
```
Type error: Module '"@prisma/client"' has no exported member 'SsoMapping'.
```

This happened because the AI:
1. Didn't read the actual schema.prisma file
2. Kept guessing model names without verification
3. Wasn't given clear enough instructions

## Solution Implemented

### 1. Intelligent Auto-Fix

When a Prisma model is missing, the system now:
1. Runs `npx prisma generate` (in case schema was updated)
2. If still failing, **reads the actual schema.prisma file**
3. **Extracts all actual model names** from the schema
4. **Checks for case mismatches** (SsoMapping vs SSOMapping)
5. **Finds similar model names** if exact match not found
6. **Adds CRITICAL hint** to error message with specific options

Example output added to error:
```
**CRITICAL SCHEMA ISSUE:**
Model 'SsoMapping' does NOT exist in prisma/schema.prisma.
Available models in schema: User, Organization, SSOMapping, Session, Account

**FIX OPTIONS:**
1. Use one of the existing models: SSOMapping (note the casing!)
2. Add 'model SsoMapping' to prisma/schema.prisma and run prisma generate
3. Define a local TypeScript interface instead of importing from @prisma/client
```

### 2. Enhanced Error Classifier

Updated `prisma_model_missing` pattern with:
- More explicit instructions
- Step-by-step mandatory process
- Concrete example with ❌/✅
- Common mistakes to avoid
- Emphasis on case sensitivity

### 3. Automatic Schema Inclusion

Schema.prisma is now **always included in context** when:
- Error category is `prisma_model_missing`
- Error category is `prisma_schema_mismatch`
- Error message contains `@prisma/client` (catch-all)

This ensures the AI has the actual model list to reference.

### 4. Improved Fix Prompt

The main fix prompt now emphasizes:
- **READ THE FILES** - don't guess
- Compare error vs actual file contents
- Use exact names from schema (case-sensitive)

## Testing This Fix

To test with the specific error:

```bash
# Simulate the error
cd /srv/ai/repos/online-docs
echo "import type { SsoMapping } from '@prisma/client';" > test-file.ts

# Run a build
npm run build

# Expected behavior:
# 1. Auto-fix runs prisma generate
# 2. Still fails → reads schema.prisma
# 3. Finds 'SSOMapping' exists (case mismatch)
# 4. Adds hint: "Use EXACT model name: 'SSOMapping'"
# 5. AI fix attempt should now succeed by fixing the casing
```

## Prevention

To prevent similar issues:
1. ✅ Always include relevant schema/config files in context
2. ✅ Provide concrete examples from actual files
3. ✅ Check for case sensitivity issues
4. ✅ List available options explicitly
5. ✅ Make "read the file" instructions impossible to miss

## Files Modified

- `app/executor.py` - Intelligent auto-fix with schema analysis
- `app/error_classifier.py` - Enhanced hint with mandatory steps
- Both files ensure schema.prisma is included in context

## Expected Outcome

This specific error (Prisma model missing) should now:
- Be fixed automatically if it's just a case mismatch
- Be fixed on first AI attempt (not 5+) due to explicit schema listing
- Never repeat the same wrong import multiple times

Success rate for Prisma model errors: **Should go from ~0% to 95%+**
