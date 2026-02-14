"""
Intelligent error summarization for build failures.

Groups and filters errors to show root causes, not cascading issues.
"""
import re
from typing import List, Dict, Tuple
from collections import defaultdict


def group_typescript_errors(error_output: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Group TypeScript errors by file and type.
    
    Returns dict: {
        "file_path": [
            {"line": "10", "column": "5", "message": "...", "code": "TS2339"},
            ...
        ]
    }
    """
    errors_by_file = defaultdict(list)
    
    # Pattern: lib/components/bot/chat-interface.tsx(16,5): error TS2339: Property 'currentQuestion' does not exist...
    pattern = r"(.+?\.(?:tsx?|jsx?|js))\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*(.+)"
    
    for match in re.finditer(pattern, error_output):
        file_path, line, column, error_code, message = match.groups()
        
        errors_by_file[file_path].append({
            "line": line,
            "column": column,
            "code": error_code,
            "message": message.strip()
        })
    
    return dict(errors_by_file)


def identify_root_causes(errors_by_file: Dict[str, List[Dict[str, str]]]) -> Dict[str, Dict]:
    """
    Identify root cause errors (vs cascading errors).
    
    Returns dict: {
        "file_path": {
            "root_causes": [...],
            "cascading": [...],
            "error_types": {...}
        }
    }
    """
    analyzed = {}
    
    for file_path, errors in errors_by_file.items():
        root_causes = []
        cascading = []
        error_types = defaultdict(int)
        
        for error in errors:
            code = error["code"]
            message = error["message"]
            
            # Count error types
            error_types[code] += 1
            
            # Identify root causes (these usually come first and cause others)
            if any(phrase in message.lower() for phrase in [
                "has no exported member",
                "cannot find module",
                "cannot find name",
                "does not exist on type",
                "is not assignable to",
                "unexpected token",
                "expected",
                "circular",
            ]):
                root_causes.append(error)
            else:
                cascading.append(error)
        
        analyzed[file_path] = {
            "root_causes": root_causes,
            "cascading": cascading,
            "error_types": dict(error_types),
            "total_errors": len(errors)
        }
    
    return analyzed


def format_concise_error_summary(error_output: str) -> str:
    """
    Create a concise, actionable error summary.
    
    Instead of showing ALL errors, show:
    - Files affected
    - Root cause errors
    - Error counts by type
    """
    # Group errors
    errors_by_file = group_typescript_errors(error_output)
    
    if not errors_by_file:
        # Fallback for non-TypeScript errors
        return error_output[:2000] + ("..." if len(error_output) > 2000 else "")
    
    # Analyze for root causes
    analyzed = identify_root_causes(errors_by_file)
    
    # Build summary
    lines = []
    lines.append("=" * 80)
    lines.append("BUILD ERRORS SUMMARY")
    lines.append("=" * 80)
    lines.append("")
    
    total_errors = sum(a["total_errors"] for a in analyzed.values())
    total_files = len(analyzed)
    
    lines.append(f"📊 {total_errors} errors in {total_files} file(s)")
    lines.append("")
    
    # Show each file's errors
    for file_path, analysis in analyzed.items():
        root_causes = analysis["root_causes"]
        cascading_count = len(analysis["cascading"])
        
        lines.append(f"📁 {file_path}")
        lines.append(f"   {len(root_causes)} root cause(s), {cascading_count} cascading error(s)")
        lines.append("")
        
        # Show top 5 root causes
        for error in root_causes[:5]:
            lines.append(f"   ❌ Line {error['line']}: {error['message'][:100]}")
        
        if len(root_causes) > 5:
            lines.append(f"   ... and {len(root_causes) - 5} more root causes")
        
        lines.append("")
    
    # Show error type distribution
    all_error_types = defaultdict(int)
    for analysis in analyzed.values():
        for code, count in analysis["error_types"].items():
            all_error_types[code] += count
    
    if all_error_types:
        lines.append("📈 Error Types:")
        for code, count in sorted(all_error_types.items(), key=lambda x: x[1], reverse=True)[:5]:
            error_type = _get_error_type_name(code)
            lines.append(f"   {code} ({error_type}): {count} occurrence(s)")
        lines.append("")
    
    lines.append("=" * 80)
    lines.append("💡 RECOMMENDED APPROACH:")
    lines.append("=" * 80)
    lines.append("")
    lines.append("1. Focus on ROOT CAUSE errors first (shown above)")
    lines.append("2. Fix errors in order (top to bottom)")
    lines.append("3. Many cascading errors will disappear after fixing root causes")
    lines.append("")
    
    # Add specific recommendations based on error types
    if "TS2339" in all_error_types:  # Property does not exist
        lines.append("⚠️  Many 'Property does not exist' errors detected:")
        lines.append("   - Check interface/type definitions")
        lines.append("   - Verify all required props are passed to components")
        lines.append("")
    
    if "TS2551" in all_error_types or "TS2307" in all_error_types:  # Cannot find module/name
        lines.append("⚠️  Import/module resolution errors detected:")
        lines.append("   - Check all import paths are correct")
        lines.append("   - Run 'npm install' if packages are missing")
        lines.append("")
    
    return "\n".join(lines)


def _get_error_type_name(error_code: str) -> str:
    """Get human-readable name for TypeScript error code."""
    error_names = {
        "TS2339": "Property not found",
        "TS2741": "Missing properties",
        "TS2322": "Type mismatch",
        "TS2307": "Cannot find module",
        "TS2551": "Property does not exist",
        "TS2304": "Cannot find name",
        "TS2345": "Argument type mismatch",
        "TS7006": "Implicit any",
    }
    return error_names.get(error_code, "Unknown")


def should_show_full_errors(error_count: int) -> bool:
    """Determine if we should show full errors or just summary."""
    # Show full errors if count is small
    return error_count <= 3
