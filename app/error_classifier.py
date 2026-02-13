"""
Error classification system for build failures.

Categorizes common errors and provides targeted fix hints.
"""
import re
from typing import Tuple, List, Dict


# Error pattern database for common issues
ERROR_PATTERNS = {
    "missing_export": {
        "patterns": [
            r"(?:not exported|has no exported member|cannot find name)",
            r"(?:'(\w+)' is not exported)",
            r"Module ['\"].*?['\"] has no exported member"
        ],
        "fix_hint": (
            "**MISSING EXPORT ERROR:**\n"
            "- Check if variable/function is declared but not exported\n"
            "- Add 'export' keyword before declaration (e.g., `export const x = ...`)\n"
            "- Verify import path matches export location\n"
            "- Check for typos in the exported name"
        )
    },
    "tailwind_invalid_class": {
        "patterns": [
            r"(?:Unknown at rule|Unexpected unknown at-rule)",
            r"(?:class .* is not a valid Tailwind)",
            r"@apply.*?does not exist"
        ],
        "fix_hint": (
            "**TAILWIND CSS ERROR:**\n"
            "- Use only standard Tailwind classes (no custom @apply syntax in className)\n"
            "- Check Tailwind docs: https://tailwindcss.com/docs\n"
            "- Remove @ syntax from regular className attributes\n"
            "- Move @apply to CSS files, not JSX className"
        )
    },
    "import_resolution": {
        "patterns": [
            r"Cannot find module ['\"](.*?)['\"]",
            r"Module not found: Can't resolve ['\"](.*?)['\"]",
            r"Unable to resolve path to module"
        ],
        "fix_hint": (
            "**IMPORT RESOLUTION ERROR:**\n"
            "- If the module is an npm package (e.g. autoprefixer, postcss, tailwindcss): add it to package.json "
            "dependencies or devDependencies, then run npm install\n"
            "- If it's a local file: verify path exists, check extension (.ts/.tsx/.js/.jsx)\n"
            "- Use relative paths correctly (../ for parent directory)\n"
            "- Check tsconfig.json paths alias configuration"
        )
    },
    "type_error": {
        "patterns": [
            r"Type '(.*)' is not assignable to type '(.*)'",
            r"Property '(.*)' does not exist on type '(.*)'",
            r"Argument of type '.*?' is not assignable"
        ],
        "fix_hint": (
            "**TYPESCRIPT TYPE ERROR:**\n"
            "- Verify interface/type definitions match usage\n"
            "- Add missing properties to interfaces\n"
            "- Use proper type assertions if needed (value as Type)\n"
            "- Check for typos in property names\n"
            "- Ensure all required properties are provided\n\n"
            "**COMMON TYPE CONVERSIONS:**\n"
            "- number → string: Use String(value) or value.toString() or `${value}`\n"
            "- string → number: Use Number(value) or parseInt(value) or parseFloat(value)\n"
            "- undefined/null → required: Add null check or use ?? default operator\n"
            "- union types: Narrow with typeof or instanceof checks"
        )
    },
    "react_hook_error": {
        "patterns": [
            r"React Hook .* is called conditionally",
            r"React Hook .* cannot be called inside a callback",
            r"Hooks can only be called inside"
        ],
        "fix_hint": (
            "**REACT HOOKS ERROR:**\n"
            "- Hooks must be called at the top level (not in conditionals/loops)\n"
            "- Hooks must be called in the same order every render\n"
            "- Don't call hooks inside callbacks or event handlers\n"
            "- Move hook calls to component body"
        )
    },
    "undefined_variable": {
        "patterns": [
            r"'(\w+)' is not defined",
            r"Cannot find name '(\w+)'",
            r"ReferenceError: \w+ is not defined"
        ],
        "fix_hint": (
            "**UNDEFINED VARIABLE ERROR:**\n"
            "- Check if variable is declared before use\n"
            "- Verify import statement for external dependencies\n"
            "- Check spelling of variable name\n"
            "- Ensure variable is in scope (not inside different function/block)"
        )
    },
    "missing_dependency": {
        "patterns": [
            r"Cannot find package ['\"](.*?)['\"]",
            r"Module .* was not found",
            r"Could not resolve dependency"
        ],
        "fix_hint": (
            "**MISSING DEPENDENCY ERROR:**\n"
            "- Package may need to be installed: npm install <package>\n"
            "- Check if package is listed in package.json dependencies\n"
            "- Verify package name spelling\n"
            "- Check if package is compatible with your Node version"
        )
    },
    "syntax_error": {
        "patterns": [
            r"Unexpected token",
            r"SyntaxError",
            r"Parse error",
            r"Expected.*?but found"
        ],
        "fix_hint": (
            "**SYNTAX ERROR:**\n"
            "- Check for missing/extra brackets, braces, or parentheses\n"
            "- Verify commas between object/array elements\n"
            "- Check for proper JSX closing tags\n"
            "- Ensure all strings are properly quoted"
        )
    },
    "prettier": {
        "patterns": [
            r"prettier/prettier",
            r"Insert `[^`]+`\s+prettier",
            r"Replace `[^`]+` with .*prettier"
        ],
        "fix_hint": (
            "**PRETTIER FORMATTING ERROR:**\n"
            "- Add trailing commas where required (after last object property, array element)\n"
            "- Fix line breaks: break long parameter lists onto separate lines\n"
            "- Run `npx prettier --write <file>` to auto-format"
        )
    },
    "prisma_model_missing": {
        "patterns": [
            r"@prisma/client['\"].*?has no exported member",
            r"Module ['\"]@prisma/client['\"] has no exported member ['\"](\w+)['\"]"
        ],
        "fix_hint": (
            "**PRISMA MODEL NOT FOUND - CRITICAL:**\n"
            "The model you're trying to import does NOT exist in the Prisma schema.\n\n"
            "**MANDATORY STEPS:**\n"
            "1. **READ prisma/schema.prisma** (it should be in your context)\n"
            "2. **FIND ALL MODELS** - Look for lines starting with 'model ModelName {'\n"
            "3. **CHECK THE EXACT NAME** - Prisma is case-sensitive! SsoMapping ≠ SSOMapping\n"
            "4. **CHOOSE ONE FIX:**\n"
            "   a) **Use existing model**: Change import to match what's actually in schema\n"
            "   b) **Add new model**: Add 'model YourModel { ... }' to schema.prisma, include updated schema in files\n"
            "   c) **Use local interface**: Define 'interface YourType { ... }' in the same file instead\n\n"
            "**EXAMPLE:**\n"
            "❌ Error: Module has no exported member 'SsoMapping'\n"
            "✅ Read schema.prisma → Find 'model SSOMapping' exists (different casing!)\n"
            "✅ Fix: Change `import type { SsoMapping }` to `import type { SSOMapping }`\n\n"
            "**DO NOT:**\n"
            "- Guess model names without reading schema\n"
            "- Keep trying to import a model that doesn't exist\n"
            "- Ignore case differences (User ≠ user)"
        )
    },
    "missing_env_vars": {
        "patterns": [
            r"Missing or invalid environment variables",
            r"Required environment variable .* is not set",
            r"Please check your \.env file"
        ],
        "fix_hint": (
            "**MISSING ENVIRONMENT VARIABLES:**\n"
            "- The build validates env vars at import time. Ensure .env exists with required vars.\n"
            "- Copy .env.example to .env and fill in values (or use placeholders for build verification).\n"
            "- Common required vars: DATABASE_URL, ENCRYPTION_KEY, JWT_SECRET, MOVEWARE_API_URL, NEXTAUTH_SECRET."
        )
    },
    "env_type_missing": {
        "patterns": [
            r"Property ['\"](\w+)['\"] does not exist on type.*?env",
            r"does not exist on type.*?NODE_ENV.*?DATABASE_URL",
            r"Property ['\"]([A-Z_]+)['\"] does not exist on type"
        ],
        "fix_hint": (
            "**ENVIRONMENT VARIABLE TYPE MISSING:**\n"
            "The TypeScript type definition for your env object is incomplete.\n\n"
            "**MANDATORY STEPS:**\n"
            "1. **READ the env schema file** (typically src/env.ts, src/lib/env.ts, or similar)\n"
            "2. **FIND the type definition** - Look for interface/type with NODE_ENV, DATABASE_URL, etc.\n"
            "3. **ADD the missing property** to the type definition\n"
            "4. **ENSURE it matches the error** - If error says 'JWT_SECRET', add JWT_SECRET: string\n\n"
            "**EXAMPLE FIX:**\n"
            "❌ Error: Property 'JWT_SECRET' does not exist on type '{ DATABASE_URL: string }'\n"
            "✅ Read env.ts → Find interface\n"
            "✅ Add: JWT_SECRET: string\n\n"
            "**Common pattern in Next.js:**\n"
            "```typescript\n"
            "const env = {\n"
            "  NODE_ENV: process.env.NODE_ENV,\n"
            "  DATABASE_URL: process.env.DATABASE_URL!,\n"
            "  JWT_SECRET: process.env.JWT_SECRET!,  // ← Add this\n"
            "};\n"
            "```\n\n"
            "**DO NOT:**\n"
            "- Remove the usage of env.JWT_SECRET (it's needed!)\n"
            "- Use 'any' type (defeats type safety)\n"
            "- Add to wrong file (find the actual env schema)"
        )
    },
    "import_type_prisma": {
        "patterns": [
            r"cannot be used as a value because it was imported using ['\"]import type['\"]",
            r"'Prisma' cannot be used as a value"
        ],
        "fix_hint": (
            "**PRISMA IMPORT TYPE ERROR:**\n"
            "- When using Prisma at runtime (e.g. `error instanceof Prisma.PrismaClientKnownRequestError`), "
            "Prisma must be a value import, not type-only.\n"
            "- Change: `import type { Prisma }` to `import { Prisma }`\n"
            "- Or use inline type: `import { type Session, Prisma } from '@prisma/client'` - Prisma without 'type'"
        )
    },
    "prisma_model_missing": {
        "patterns": [
            r"Property ['\"](\w+)['\"] does not exist on type ['\"]PrismaClient",
            r"does not exist on type ['\"]PrismaClient<.*?>['\"]\."
        ],
        "fix_hint": (
            "**PRISMA MODEL MISSING FROM CLIENT:**\n"
            "The code is trying to access a Prisma model that doesn't exist in the generated client.\n\n"
            "**MANDATORY STEPS:**\n"
            "1. **READ prisma/schema.prisma** - See what models ACTUALLY exist\n"
            "2. **CHECK THE MODEL NAME** - Prisma uses camelCase for model accessors:\n"
            "   - Schema: `model MovewareCredential` → Client: `db.movewareCredential` (lowercase first letter)\n"
            "   - Schema: `model User` → Client: `db.user`\n"
            "   - Schema: `model TenantSettings` → Client: `db.tenantSettings`\n\n"
            "**FIX OPTIONS:**\n"
            "**Option 1:** Model doesn't exist in schema → Add it\n"
            "```prisma\n"
            "model MovewareCredential {\n"
            "  id        String   @id @default(cuid())\n"
            "  tenantId  String   @unique\n"
            "  apiKey    String\n"
            "  createdAt DateTime @default(now())\n"
            "}\n"
            "```\n"
            "Then run: `npx prisma generate`\n\n"
            "**Option 2:** Model exists with different name → Use correct name\n"
            "- Check schema for similar models (Credential, Tenant, etc.)\n"
            "- Match the exact model name from schema (case-sensitive!)\n\n"
            "**Option 3:** Use existing related model\n"
            "- Maybe credentials are stored in `Tenant` model?\n"
            "- Read schema to understand the data structure\n\n"
            "**CRITICAL:** Always read prisma/schema.prisma first - don't guess model names!"
        )
    },
    "prisma_schema_mismatch": {
        "patterns": [
            r"Object literal may only specify known properties",
            r"does not exist in type ['\"].*CreateInput['\"]",
            r"'(\\w+)' does not exist in type ['\"].*(?:CreateInput|UpdateInput)['\"]"
        ],
        "fix_hint": (
            "**PRISMA SCHEMA MISMATCH:**\n"
            "- The property you're passing does NOT exist in the Prisma schema for this model.\n"
            "- **Fix 1:** Check prisma/schema.prisma - what fields does the model actually have?\n"
            "- **Fix 2:** Remove the invalid property from the create/update object if the schema doesn't need it.\n"
            "- **Fix 3:** If the schema uses different names (e.g. first_name vs firstName, is_active vs isActive), "
            "use the EXACT field names from the schema - Prisma generates TypeScript types from schema.prisma.\n"
            "- **Fix 4:** To add a new field: add it to schema.prisma, run `npx prisma generate`, then use it.\n"
            "- **CRITICAL:** Include schema.prisma in your context and match the exact field names."
        )
    },
    "eslint_config": {
        "patterns": [
            r"eslint-config-[^\s]+",
            r"ESLint configuration.*?is invalid",
            r"Error: Failed to load config",
            r"Cannot find module ['\"]eslint-config-"
        ],
        "fix_hint": (
            "**ESLINT CONFIGURATION ERROR:**\n"
            "- Missing ESLint configuration package (e.g. eslint-config-next)\n"
            "- Add the package to package.json devDependencies: `\"eslint-config-next\": \"^14.0.0\"`\n"
            "- Ensure .eslintrc.json extends the correct config\n"
            "- Run npm install to install missing dependencies"
        )
    },
    "module_exports_mismatch": {
        "patterns": [
            r"Module ['\"]@/[^'\"]+['\"] has no exported member ['\"](\w+)['\"]",
            r"has no exported member ['\"](\w+)['\"]",
            r"export ['\"](\w+)['\"] was not found"
        ],
        "fix_hint": (
            "**MODULE EXPORT MISMATCH:**\n"
            "- The module exists but doesn't export the member you're trying to import\n"
            "- **CRITICAL STEPS:**\n"
            "  1. Read the source file to see what it ACTUALLY exports\n"
            "  2. Check for typos in the import name (case sensitive!)\n"
            "  3. Either: add the missing export to the source file, OR update import to use existing export name\n"
            "- Common mistake: importing { userRepository } when file exports { UserRepository } (capital U)"
        )
    },
    "build_timeout": {
        "patterns": [
            r"Build timed out",
            r"ETIMEDOUT",
            r"socket hang up",
            r"ECONNRESET"
        ],
        "fix_hint": (
            "**BUILD TIMEOUT/CONNECTION ERROR:**\n"
            "- Network error or build process taking too long\n"
            "- Check for infinite loops or blocking operations during build\n"
            "- Verify external API calls don't run at build time\n"
            "- Use dynamic imports for heavy dependencies"
        )
    },
    "next_config": {
        "patterns": [
            r"Invalid next.config",
            r"next\.config\.(js|mjs|ts) is invalid",
            r"Error in next\.config"
        ],
        "fix_hint": (
            "**NEXT.JS CONFIG ERROR:**\n"
            "- Syntax error in next.config.js/ts\n"
            "- Ensure config exports proper object: `module.exports = { ... }`\n"
            "- Check for missing commas, brackets, or quotes\n"
            "- Validate experimental features are properly formatted"
        )
    },
    "duplicate_declaration": {
        "patterns": [
            r"Duplicate identifier ['\"](\w+)['\"]",
            r"Cannot redeclare block-scoped variable",
            r"'(\w+)' has already been declared"
        ],
        "fix_hint": (
            "**DUPLICATE DECLARATION:**\n"
            "- Variable, function, or type declared multiple times\n"
            "- Check for duplicate exports or imports\n"
            "- Rename one of the declarations or remove duplicate\n"
            "- Check if variable is imported AND declared locally"
        )
    },
    "async_import": {
        "patterns": [
            r"Top-level await is not available",
            r"Cannot use keyword 'await' outside an async function",
            r"'await' expressions are only allowed within async functions"
        ],
        "fix_hint": (
            "**ASYNC/AWAIT ERROR:**\n"
            "- Using await outside async function\n"
            "- Wrap code in async function: `async function name() { await ... }`\n"
            "- For top-level: ensure module is ES module (.mjs) or package.json has \"type\": \"module\"\n"
            "- In React: use useEffect with async function inside it"
        )
    },
}


def classify_error(error_msg: str) -> Tuple[str, str, List[str]]:
    """
    Classify error and return category with specific hints.
    
    Args:
        error_msg: The error message from build output
    
    Returns:
        Tuple of (category, hint, matched_patterns)
        Category is "unknown" if no match found.
    """
    matches = []
    
    for category, config in ERROR_PATTERNS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, error_msg, re.IGNORECASE | re.MULTILINE):
                matches.append(category)
                return category, config["fix_hint"], matches
    
    # Fallback hint for unknown errors
    fallback_hint = (
        "**UNKNOWN ERROR TYPE:**\n"
        "- This error pattern isn't in our classifier yet\n"
        "- **CRITICAL DEBUGGING STEPS:**\n"
        "  1. Read the COMPLETE error message carefully - it tells you what's wrong\n"
        "  2. Identify the file and line number mentioned in the error\n"
        "  3. Read that file's ACTUAL contents to see the current code\n"
        "  4. Compare what the error says is wrong vs what's actually in the file\n"
        "  5. Fix the specific issue mentioned (missing export, type mismatch, syntax error, etc.)\n"
        "- **COMMON FIXES:**\n"
        "  * Missing export → Add 'export' keyword: `export const name = ...`\n"
        "  * Module not found → Add to package.json dependencies and ensure file exists\n"
        "  * Type error → Check interface matches usage, add missing properties\n"
        "  * Syntax error → Check brackets, quotes, commas, semicolons\n"
        "- **READ THE FILES MENTIONED IN THE ERROR** - don't guess what they contain!"
    )
    
    return "unknown", fallback_hint, matches


def classify_multiple_errors(error_msg: str) -> Dict[str, int]:
    """
    Classify all errors in a message and return frequency.
    
    Args:
        error_msg: Full build error output
    
    Returns:
        Dict mapping error categories to occurrence count
    """
    categories = {}
    
    # Split into individual error lines
    lines = error_msg.split('\n')
    
    for line in lines:
        category, _, _ = classify_error(line)
        if category != "unknown":
            categories[category] = categories.get(category, 0) + 1
    
    return categories


def get_comprehensive_hint(error_msg: str) -> str:
    """
    Get comprehensive fix hint for all error types found.
    
    Args:
        error_msg: Full build error output
    
    Returns:
        Combined hints for all detected error types
    """
    categories = classify_multiple_errors(error_msg)
    
    if not categories:
        # No classified errors - provide generic debugging guidance
        return (
            "**ERROR ANALYSIS:**\n"
            "No specific error patterns detected. Follow these steps:\n"
            "1. Read the error message completely - it contains critical clues\n"
            "2. Identify which file(s) have errors (look for file paths)\n"
            "3. Read those files to understand the current code\n"
            "4. Apply the fix the error message suggests\n"
            "5. If the error mentions missing exports/imports, check what's actually exported\n"
            "6. If it mentions types, check the interface definitions\n"
            "7. Re-read the files after making changes to ensure consistency"
        )
    
    hints = []
    hints.append("**ERROR ANALYSIS:**")
    hints.append(f"Found {len(categories)} type(s) of errors. Fix them in this priority order:\n")
    
    # Prioritize certain error types
    priority_order = [
        "missing_dependency",
        "eslint_config", 
        "prisma_model_missing",
        "import_resolution",
        "missing_export",
        "module_exports_mismatch",
        "type_error",
        "syntax_error",
    ]
    
    # Sort by priority, then by count
    sorted_categories = []
    for priority_cat in priority_order:
        if priority_cat in categories:
            sorted_categories.append((priority_cat, categories[priority_cat]))
    
    # Add remaining categories
    for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        if category not in [c[0] for c in sorted_categories]:
            sorted_categories.append((category, count))
    
    for category, count in sorted_categories:
        if category in ERROR_PATTERNS:
            hints.append(f"\n{count}x {category.upper().replace('_', ' ')}")
            hints.append(ERROR_PATTERNS[category]["fix_hint"])
    
    hints.append("\n**FIX STRATEGY:**")
    hints.append("1. Start with dependency/config errors (install missing packages)")
    hints.append("2. Fix import/export mismatches (read source files to see actual exports)")
    hints.append("3. Fix type errors (check interfaces and add missing properties)")
    hints.append("4. Fix syntax errors last (formatting, missing brackets)")
    hints.append("\n**CRITICAL:** Read the actual file contents before making changes!")
    
    return "\n".join(hints)


def extract_error_context(error_msg: str, max_context_lines: int = 5) -> List[str]:
    """
    Extract key error lines with context for debugging.
    
    Args:
        error_msg: Full error output
        max_context_lines: Maximum lines to extract per error
    
    Returns:
        List of important error excerpts
    """
    important_patterns = [
        r"Error:",
        r"TypeError:",
        r"SyntaxError:",
        r"Module not found:",
        r"Cannot find",
        r"failed to compile",
        r"\s+at\s+",  # Stack trace
    ]
    
    lines = error_msg.split('\n')
    important_lines = []
    
    for i, line in enumerate(lines):
        for pattern in important_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                # Get context: 2 lines before, current, 2 lines after
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                context = lines[start:end]
                important_lines.append('\n'.join(context))
                break
    
    return important_lines[:max_context_lines]
