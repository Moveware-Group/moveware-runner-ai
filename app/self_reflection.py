"""
Self-Reflection System for Fix Attempts

Analyzes what went wrong after failed fix attempts to improve future attempts.
Uses lightweight reflection to understand mistakes and adjust strategy.
"""
from typing import Dict, List, Any, Optional
from .error_classifier import classify_error


def analyze_fix_failure(
    attempt_num: int,
    previous_error: str,
    new_error: str,
    fix_applied: Dict[str, Any],
    previous_attempts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze what went wrong in a failed fix attempt.
    
    Args:
        attempt_num: Current attempt number
        previous_error: The error we were trying to fix
        new_error: The new error after applying the fix
        fix_applied: The fix that was applied (files changed, strategy)
        previous_attempts: List of previous attempts with their outcomes
    
    Returns:
        Dict with analysis and recommendations for next attempt
    """
    analysis = {
        "attempt_num": attempt_num,
        "what_went_wrong": [],
        "recommendations": [],
        "files_to_read": [],
        "avoid_strategies": []
    }
    
    # Determine if error is same, worse, or different
    prev_category, _, _ = classify_error(previous_error)
    new_category, _, _ = classify_error(new_error)
    
    if new_category == prev_category:
        # Same category of error - fix didn't address root cause
        analysis["what_went_wrong"].append(
            f"Fix didn't resolve {prev_category} error - may have addressed symptom, not root cause"
        )
        analysis["recommendations"].append(
            "Read the ACTUAL file contents to understand what's exported/defined"
        )
        analysis["recommendations"].append(
            "Verify imports match exports exactly (check casing, spelling)"
        )
    elif new_category != "unknown" and new_category != prev_category:
        # Introduced a new type of error
        analysis["what_went_wrong"].append(
            f"Introduced new {new_category} error while trying to fix {prev_category}"
        )
        analysis["recommendations"].append(
            "Be more careful with fix - may have broken working code"
        )
        analysis["recommendations"].append(
            "Only change files directly related to the error"
        )
    
    # Check if same files are being changed repeatedly
    files_changed = set(fix_applied.get("files_changed", []))
    repeated_files = set()
    for prev_attempt in previous_attempts:
        prev_files = set(prev_attempt.get("files_changed", []))
        repeated_files.update(files_changed.intersection(prev_files))
    
    if repeated_files:
        analysis["what_went_wrong"].append(
            f"Repeatedly changing same files: {', '.join(list(repeated_files)[:3])}"
        )
        analysis["recommendations"].append(
            "These files may not be the problem - look for related files (imports/exports)"
        )
        # Suggest reading files that import the problem files
        for file in repeated_files:
            analysis["files_to_read"].append(file)
            # Suggest related files
            if "/repositories/" in file:
                analysis["files_to_read"].append(file.replace("/repositories/", "/services/"))
            if "/services/" in file:
                analysis["files_to_read"].append(file.replace("/services/", "/repositories/"))
    
    # Check for common mistake patterns in error messages
    if "has no exported member" in new_error:
        analysis["what_went_wrong"].append(
            "Still missing exports - either not added or wrong name"
        )
        analysis["recommendations"].append(
            "CRITICAL: Read the file and search for 'export' keyword - see what's ACTUALLY exported"
        )
        analysis["recommendations"].append(
            "Compare import name to export name - check for typos and casing (User vs user)"
        )
    
    if "cannot find module" in new_error.lower():
        analysis["what_went_wrong"].append(
            "Module still can't be found - path or package issue"
        )
        if any("node_modules" not in f for f in files_changed):
            analysis["recommendations"].append(
                "If it's an npm package, add to package.json dependencies"
            )
        analysis["recommendations"].append(
            "If it's a local file, verify path is correct and file exists"
        )
    
    if "does not exist on type" in new_error:
        analysis["what_went_wrong"].append(
            "Type/interface doesn't have the property being used"
        )
        analysis["recommendations"].append(
            "Read the type definition - see what properties it ACTUALLY has"
        )
        analysis["recommendations"].append(
            "Either add property to type OR use existing property name"
        )
    
    # Track strategies that haven't worked
    fix_strategy = fix_applied.get("strategy", "")
    analysis["avoid_strategies"].append(fix_strategy)
    
    # Add specific file recommendations based on error
    if "@prisma/client" in new_error:
        analysis["files_to_read"].append("prisma/schema.prisma")
        analysis["recommendations"].append(
            "Read prisma/schema.prisma to see actual model names and fields"
        )
    
    if "env" in new_error.lower() or "process.env" in new_error:
        analysis["files_to_read"].extend(["src/env.ts", "src/lib/env.ts", ".env.example"])
        analysis["recommendations"].append(
            "Read env schema file to see type definition"
        )
    
    # Progressive escalation recommendations
    if attempt_num == 2:
        analysis["recommendations"].append(
            "⚠️ Second attempt - read MORE files to get full context"
        )
    elif attempt_num == 3:
        analysis["recommendations"].append(
            "⚠️ Third attempt - consider if the problem is in a DIFFERENT file than you think"
        )
    elif attempt_num >= 4:
        analysis["recommendations"].append(
            "⚠️ Multiple failures - the root cause may be architectural, not just a simple fix"
        )
    
    return analysis


def format_reflection_guidance(analysis: Dict[str, Any]) -> str:
    """
    Format self-reflection analysis as guidance for next attempt.
    
    Args:
        analysis: Output from analyze_fix_failure
    
    Returns:
        Formatted string to add to fix prompt
    """
    lines = [
        f"\n**🔍 SELF-REFLECTION - Attempt #{analysis['attempt_num']}:**",
        ""
    ]
    
    if analysis["what_went_wrong"]:
        lines.append("**What went wrong last time:**")
        for issue in analysis["what_went_wrong"]:
            lines.append(f"  ❌ {issue}")
        lines.append("")
    
    if analysis["recommendations"]:
        lines.append("**What to do differently this time:**")
        for i, rec in enumerate(analysis["recommendations"], 1):
            lines.append(f"  {i}. {rec}")
        lines.append("")
    
    if analysis["files_to_read"]:
        lines.append("**CRITICAL - Read these files before fixing:**")
        for file in analysis["files_to_read"][:5]:  # Limit to 5
            lines.append(f"  📄 {file}")
        lines.append("")
    
    if analysis["avoid_strategies"]:
        lines.append("**Strategies that didn't work (don't repeat):**")
        for strategy in analysis["avoid_strategies"][:3]:  # Limit to 3
            lines.append(f"  ⛔ {strategy}")
        lines.append("")
    
    lines.append("**LEARN FROM MISTAKES:**")
    lines.append("- This is attempt #{} - previous approach didn't work".format(analysis["attempt_num"]))
    lines.append("- Try a DIFFERENT approach, don't repeat the same fix")
    lines.append("- READ files to verify assumptions, don't guess")
    lines.append("")
    
    return "\n".join(lines)


def extract_fix_metadata(fix_payload: Dict[str, Any], files_changed: List[str]) -> Dict[str, Any]:
    """
    Extract metadata from a fix attempt for analysis.
    
    Args:
        fix_payload: The JSON payload from the AI's fix
        files_changed: List of files that were modified
    
    Returns:
        Dict with relevant metadata
    """
    return {
        "strategy": fix_payload.get("summary", "") or fix_payload.get("implementation_plan", ""),
        "files_changed": files_changed,
        "file_count": len(files_changed)
    }
