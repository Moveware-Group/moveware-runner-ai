"""
Syntax Auto-Fixer

Automatically fixes common syntax errors that AI struggles with.
Handles missing braces, comment markers, and other structural issues.
"""
import re
from pathlib import Path
from typing import Optional, Tuple


def auto_fix_missing_comment_opener(
    file_path: Path,
    error_msg: str
) -> Tuple[bool, str]:
    """
    Auto-fix missing comment opener (/** or /*).
    
    Common pattern:
      Line 186:   return result.count;
      Line 187:  * Check if ...  ← Missing /**
      Line 188:  */
    
    Args:
        file_path: Path to the file with the error
        error_msg: The build error message
    
    Returns:
        (fixed, description)
    """
    if not file_path.exists():
        return False, ""
    
    # Check if error mentions "Expression expected" near a comment-like line
    if "Expression expected" not in error_msg:
        return False, ""
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        # Look for pattern: line with just " * text" (missing opener)
        fixed = False
        for i, line in enumerate(lines):
            # Match lines that look like comment content without opener
            if re.match(r'^\s*\*\s+\w', line):
                # Check if previous line ends properly and next line is */
                if i > 0 and i < len(lines) - 1:
                    prev_line = lines[i-1].strip()
                    next_lines = lines[i+1:min(i+10, len(lines))]
                    
                    # If previous line ends with ; or } and we find */ ahead
                    has_closing = any(nl.strip() == '*/' for nl in next_lines[:5])
                    if prev_line.endswith((';', '}', ')')) and has_closing:
                        
                        # Add /** before this line
                        indent = len(line) - len(line.lstrip())
                        lines[i] = ' ' * indent + '/**\n' + line
                        fixed = True
                        print(f"Auto-fix: Added missing /** at line {i+1}")
                        break
        
        if fixed:
            new_content = '\n'.join(lines)
            file_path.write_text(new_content, encoding="utf-8")
            return True, f"Added missing comment opener (/**) at line {i+1}"
    
    except Exception as e:
        print(f"Warning: Could not auto-fix comment opener: {e}")
    
    return False, ""


def auto_fix_missing_closing_brace(
    file_path: Path,
    error_msg: str
) -> Tuple[bool, str]:
    """
    Auto-fix missing closing brace before comment.
    
    Common pattern:
      function foo() {
        ...
        return result.count;
      /** Comment ← Missing } before this
      */
      export function bar() {
    
    Args:
        file_path: Path to the file
        error_msg: Build error message
    
    Returns:
        (fixed, description)
    """
    if not file_path.exists():
        return False, ""
    
    if "Expected ';', '}' or <eof>" not in error_msg:
        return False, ""
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        # Extract error line number if available
        line_match = re.search(r':(\d+):\d+', error_msg)
        if not line_match:
            return False, ""
        
        error_line = int(line_match.group(1)) - 1  # 0-indexed
        
        if error_line >= len(lines):
            return False, ""
        
        # Look backwards from error line to find function start
        brace_balance = 0
        function_start = None
        
        for i in range(error_line - 1, max(0, error_line - 50), -1):
            line = lines[i]
            
            # Count braces
            brace_balance += line.count('}') - line.count('{')
            
            # If we find a function declaration and braces are unbalanced
            if re.search(r'(?:export\s+)?(?:async\s+)?function\s+\w+', line):
                function_start = i
                if brace_balance > 0:  # More closing than opening = missing closing brace
                    # Add closing brace before the comment/next function
                    insert_line = error_line
                    indent = len(lines[function_start]) - len(lines[function_start].lstrip())
                    lines.insert(insert_line, ' ' * indent + '}')
                    
                    new_content = '\n'.join(lines)
                    file_path.write_text(new_content, encoding="utf-8")
                    return True, f"Added missing closing brace at line {insert_line+1}"
                break
    
    except Exception as e:
        print(f"Warning: Could not auto-fix missing brace: {e}")
    
    return False, ""


def auto_fix_duplicate_comment_opener(
    file_path: Path,
    error_msg: str
) -> Tuple[bool, str]:
    """
    Fix duplicate /** in comments (AI sometimes adds it twice).
    
    Pattern:
      /**
      /**
       * Comment
       */
    """
    if not file_path.exists():
        return False, ""
    
    try:
        content = file_path.read_text(encoding="utf-8")
        
        # Look for /** followed immediately by another /**
        if re.search(r'/\*\*\s*/\*\*', content):
            new_content = re.sub(r'/\*\*\s*/\*\*', '/**', content)
            file_path.write_text(new_content, encoding="utf-8")
            return True, "Removed duplicate comment opener (/**)"
    
    except Exception as e:
        print(f"Warning: Could not fix duplicate comment opener: {e}")
    
    return False, ""


def try_syntax_auto_fixes(
    file_path: Path,
    error_msg: str
) -> Tuple[bool, str]:
    """
    Try all syntax auto-fixes.
    
    Args:
        file_path: Path to file with error
        error_msg: Build error message
    
    Returns:
        (fixed, description)
    """
    fixes = [
        auto_fix_missing_comment_opener,
        auto_fix_missing_closing_brace,
        auto_fix_duplicate_comment_opener,
    ]
    
    for fix_func in fixes:
        try:
            fixed, desc = fix_func(file_path, error_msg)
            if fixed:
                return True, desc
        except Exception as e:
            print(f"Warning: Syntax fix {fix_func.__name__} failed: {e}")
            continue
    
    return False, ""
