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
            "- Ensure all required properties are provided"
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
            "**PRISMA MODEL NOT FOUND:**\n"
            "- Only import types that exist in prisma/schema.prisma - check the schema!\n"
            "- If the model (e.g. Session, SSOProvider) is NOT in schema.prisma:\n"
            "  * Add the model to schema.prisma and run `npx prisma generate`, OR\n"
            "  * Use a type that exists, or define a local interface\n"
            "- If the model IS in schema.prisma: run `npx prisma generate`"
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
    
    return "unknown", "", matches


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
        return ""
    
    hints = []
    hints.append("**ERROR ANALYSIS:**")
    hints.append(f"Found {len(categories)} type(s) of errors:\n")
    
    for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        if category in ERROR_PATTERNS:
            hints.append(f"\n{count}x {category.upper().replace('_', ' ')}")
            hints.append(ERROR_PATTERNS[category]["fix_hint"])
    
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
