# Build Accuracy Improvements

## Goal: Achieve 95%+ Build Success Rate

## Summary of Changes

### 1. Enhanced Error Classification System (`app/error_classifier.py`)

#### Added 6 New Error Patterns:
1. **eslint_config** - ESLint configuration errors and missing config packages
2. **module_exports_mismatch** - Specific handling for export name mismatches
3. **build_timeout** - Network errors and build timeouts
4. **next_config** - Next.js configuration errors
5. **duplicate_declaration** - Duplicate variable/function declarations
6. **async_import** - Async/await usage errors

Total error patterns: **19** (was 13)

#### Improved Error Hints:
- Added comprehensive fallback hint for **unknown errors** with step-by-step debugging guide
- Enhanced `get_comprehensive_hint()` to prioritize error types by fix difficulty
- Added strategic fix ordering (dependencies → imports → types → syntax)

### 2. Improved Fix Prompt (`app/executor.py`)

#### Key Enhancements:
- **Structured debugging process** with 4-step methodology:
  1. Read error message completely
  2. Read actual file contents
  3. Compare error vs reality
  4. Apply specific fix

- **Concrete examples** with ❌/✅ format showing:
  - What the error looks like
  - How to diagnose it
  - What the fix should be

- **Common mistakes section** to prevent repeated errors:
  - Don't guess file contents
  - Check export name casing
  - Verify exports exist before importing
  - Provide complete file content (not partial)

### 3. Enhanced Auto-Fix Capabilities

#### New Auto-Fixes:
1. **ESLint config packages** - Auto-install missing eslint-config-* packages
2. **Smart dev dependency detection** - Automatically use --save-dev for build tools
   - Packages: eslint, prettier, typescript, postcss, autoprefixer, tailwind

#### Existing Auto-Fixes:
- Missing npm packages
- Prisma generate
- Prettier formatting
- Prisma import type fixes

### 4. Improved File Context Extraction

#### Enhanced Path Resolution:
- **TypeScript path alias support** - Now extracts files from `@/` imports
  - Tries multiple extensions: .ts, .tsx, /index.ts, /index.tsx
  - Checks both `src/` prefix and root paths
  - Automatically includes source files mentioned in errors

#### Better Import Resolution:
- Resolves relative imports (../, ./)
- Extracts imports from error messages
- Includes directory listings for context

### 5. Increased Max Fix Attempts

- **Default changed from 5 to 7 attempts**
- Allows more opportunities to fix complex issues
- Balances accuracy improvement with cost
- Configurable via `MAX_FIX_ATTEMPTS` env var

### 6. Model Escalation Strategy

Current strategy (unchanged but documented):
- **Attempts 1-5**: Claude Sonnet 4 with extended thinking (8000 tokens)
- **Attempts 6-7**: OpenAI GPT (second opinion)

## Expected Impact

### Before:
- ~80% success rate
- Common failures: export mismatches, missing packages, type errors
- Generic error hints didn't guide AI effectively

### After:
- **Target: 95%+ success rate**
- Specific patterns for 19 error types
- Auto-fixes for common issues (eslint configs, packages)
- Clear step-by-step debugging instructions
- Better file context (path aliases, imports)
- More retry attempts (5 → 7)

## Testing Recommendations

1. Monitor success rate over next 50 runs
2. Review failed runs for new error patterns
3. Add new patterns to `ERROR_PATTERNS` as discovered
4. Adjust MAX_FIX_ATTEMPTS if needed (7-10 range)

## Maintenance

To add new error patterns:
1. Edit `app/error_classifier.py`
2. Add pattern to `ERROR_PATTERNS` dict with:
   - `patterns`: list of regex patterns
   - `fix_hint`: specific guidance for fixing
3. Test pattern matches expected errors
4. Update this document

## Files Modified

- `app/error_classifier.py` - Enhanced error patterns and hints
- `app/executor.py` - Improved fix prompt and auto-fixes
- `app/config.py` - Increased default MAX_FIX_ATTEMPTS
- `.env.example` - Updated documentation
- `app/templates/status.html` - Fixed stuck run detection (uses `locked_at` not `created_at`)

## Related Documentation

- Error patterns: `app/error_classifier.py`
- Self-healing logic: `app/executor.py` (lines 943-1700)
- Configuration: `app/config.py`
