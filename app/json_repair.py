"""
JSON Repair Utilities

Repairs common JSON formatting issues from LLM outputs.
Handles trailing commas, missing commas, unescaped strings, etc.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _apply_outside_strings(text: str, transform_fn) -> str:
    """
    Apply a transform function ONLY to text segments outside JSON string values.
    String values (containing code, etc.) are left untouched.
    """
    parts = []
    in_string = False
    seg_start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string:
            i += 2
            continue
        if ch == '"':
            if in_string:
                # End of string — include the closing quote in the string segment
                parts.append(text[seg_start:i + 1])
                seg_start = i + 1
                in_string = False
            else:
                # Start of string — transform the non-string segment before it
                non_str = text[seg_start:i]
                parts.append(transform_fn(non_str))
                seg_start = i
                in_string = True
            i += 1
            continue
        i += 1
    # Handle remaining text
    remaining = text[seg_start:]
    if in_string:
        parts.append(remaining)
    else:
        parts.append(transform_fn(remaining))
    return ''.join(parts)


def repair_json(text: str) -> str:
    """
    Attempt to repair common JSON formatting issues.
    All structural repairs are applied ONLY outside string values so that
    code embedded in "content" fields is not destroyed.
    """
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        if lines[0].strip().startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines)

    first_brace = text.find('{')
    last_brace = text.rfind('}')

    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        return text

    text = text[first_brace:last_brace + 1]

    def _structural_fixes(segment: str) -> str:
        # Trailing commas
        segment = re.sub(r',(\s*[}\]])', r'\1', segment)
        # Missing commas between objects/arrays
        segment = re.sub(r'\}(\s*)\{', r'},\1{', segment)
        segment = re.sub(r'\](\s*)\{', r'],\1{', segment)
        segment = re.sub(r'\}(\s*)\[', r'},\1[', segment)
        # Single-quoted keys → double-quoted
        segment = re.sub(r"'([a-zA-Z_][a-zA-Z0-9_]*)'\s*:", r'"\1":', segment)
        return segment

    text = _apply_outside_strings(text, _structural_fixes)
    return text


def _fix_unescaped_control_chars(text: str) -> str:
    """Fix unescaped control characters inside JSON string values."""
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string and i + 1 < len(text):
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        elif in_string and ord(ch) < 0x20:
            result.append(f'\\u{ord(ch):04x}')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _escape_unescaped_quotes_in_values(text: str) -> str:
    """
    Escape double quotes inside JSON string values that Claude forgot to escape.

    Common with JSX template literals like: `No results for "${var}"`
    which produce unescaped " inside JSON strings.

    Heuristic: when inside a JSON string, a " is structural (ends the string)
    only if what follows (after whitespace) is a JSON punctuation char: , : } ]
    Otherwise it's an unescaped content quote and gets escaped.
    """
    result = []
    in_string = False
    i = 0
    length = len(text)

    while i < length:
        ch = text[i]

        if ch == '\\' and in_string and i + 1 < length:
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue

        if ch == '"':
            if not in_string:
                in_string = True
                result.append(ch)
            else:
                rest = text[i + 1:]
                stripped = rest.lstrip(' \t\r\n')
                if not stripped or stripped[0] in ':,}]':
                    in_string = False
                    result.append(ch)
                else:
                    result.append('\\"')
        else:
            result.append(ch)
        i += 1

    return ''.join(result)


def _find_balanced_json(text: str) -> Optional[str]:
    """Find the outermost balanced { ... } in text, respecting string quoting."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string:
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return text[start:]


def _repair_truncated_json(text: str) -> str:
    """
    If the JSON is truncated (Claude hit token limit), try to close it cleanly.
    Finds the last complete file entry and closes the array/object.
    """
    # Check if JSON seems truncated (unbalanced braces)
    open_braces = 0
    open_brackets = 0
    in_string = False
    for i, ch in enumerate(text):
        if ch == '\\' and in_string:
            continue
        if ch == '"' and (i == 0 or text[i - 1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if ch == '{':
                open_braces += 1
            elif ch == '}':
                open_braces -= 1
            elif ch == '[':
                open_brackets += 1
            elif ch == ']':
                open_brackets -= 1

    if open_braces == 0 and open_brackets == 0:
        return text

    # Find the last complete "content": "..." value — look for the last `}, {` or `}]`
    # pattern at the boundary between file entries
    last_complete = -1
    depth = 0
    in_str = False
    for i, ch in enumerate(text):
        if ch == '\\' and in_str:
            continue
        if ch == '"' and (i == 0 or text[i - 1] != '\\'):
            in_str = not in_str
        elif not in_str:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                # depth 2 = inside a file object within the files array
                if depth == 1:
                    last_complete = i

    if last_complete > 0:
        truncated = text[:last_complete + 1]
        # Close any open arrays/brackets
        closing = ''
        if open_brackets > 0:
            closing += ']' * open_brackets
        closing += '}'  # Close the root object
        result = truncated + closing
        print(f"  Truncation repair: kept {last_complete + 1} of {len(text)} chars, closed with '{closing}'")
        return result

    return text


def try_parse_json(text: str, max_repair_attempts: int = 3) -> Optional[Dict[str, Any]]:
    """
    Try to parse JSON with progressive repair attempts.

    Returns:
        Parsed JSON dict or None if all attempts fail
    """
    attempts = []
    original_text = text

    # Attempt 1: Parse as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        attempts.append(f"Raw parse failed: {e}")

    # Attempt 2: Remove markdown and try again
    try:
        cleaned = text.strip()
        if '```' in cleaned:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        attempts.append(f"Markdown removal failed: {e}")

    # Attempt 3: Extract balanced JSON object (handles preamble text)
    try:
        balanced = _find_balanced_json(text)
        if balanced and balanced != text:
            result = json.loads(balanced)
            print("✅ JSON parsed after extracting balanced braces")
            return result
    except json.JSONDecodeError as e:
        attempts.append(f"Balanced extract failed: {e}")

    # Attempt 4: Fix control chars FIRST (most common issue with code content),
    # then apply string-aware structural repairs
    try:
        fixed = _fix_unescaped_control_chars(original_text)
        fixed = repair_json(fixed)
        result = json.loads(fixed)
        print("✅ JSON parsed after control-char fix + structural repair")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"Control-char + repair failed: {e}")

    # Attempt 5: Escape unescaped quotes in string values (JSX template literals etc.)
    try:
        fixed = _escape_unescaped_quotes_in_values(original_text)
        fixed = repair_json(fixed)
        result = json.loads(fixed)
        print("✅ JSON parsed after escaping unescaped quotes in string values")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"Unescaped-quote repair failed: {e}")

    # Attempt 6: Combined — control chars + unescaped quotes
    try:
        fixed = _fix_unescaped_control_chars(original_text)
        fixed = _escape_unescaped_quotes_in_values(fixed)
        fixed = repair_json(fixed)
        result = json.loads(fixed)
        print("✅ JSON parsed after control-char + quote-escape repair")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"Control-char + quote-escape failed: {e}")

    # Attempt 7: Extract balanced, fix control chars, repair
    try:
        balanced = _find_balanced_json(original_text) or original_text
        fixed = _fix_unescaped_control_chars(balanced)
        fixed = repair_json(fixed)
        result = json.loads(fixed)
        print("✅ JSON parsed after balanced extract + control-char fix")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"Balanced + control-char failed: {e}")

    # Attempt 8: Try strict=False with control-char + quote-escape fix
    try:
        fixed = _fix_unescaped_control_chars(original_text)
        fixed = _escape_unescaped_quotes_in_values(fixed)
        balanced = _find_balanced_json(fixed) or fixed
        result = json.loads(balanced, strict=False)
        print("✅ JSON parsed with strict=False after control-char + quote fix")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"strict=False + control-char + quote failed: {e}")

    # Attempt 9: Handle truncated JSON (Claude hit output token limit)
    try:
        fixed = _fix_unescaped_control_chars(original_text)
        fixed = _escape_unescaped_quotes_in_values(fixed)
        balanced = _find_balanced_json(fixed) or fixed
        repaired = _repair_truncated_json(balanced)
        if repaired != balanced:
            result = json.loads(repaired)
            print("✅ JSON parsed after truncation repair")
            return result
    except json.JSONDecodeError as e:
        attempts.append(f"Truncation repair failed: {e}")

    # Attempt 10: Last resort — strict=False on truncation-repaired text
    try:
        fixed = _fix_unescaped_control_chars(original_text)
        fixed = _escape_unescaped_quotes_in_values(fixed)
        balanced = _find_balanced_json(fixed) or fixed
        repaired = _repair_truncated_json(balanced)
        repaired = repair_json(repaired)
        result = json.loads(repaired, strict=False)
        print("✅ JSON parsed with strict=False after truncation + structural repair")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"Final strict=False failed: {e}")

    print(f"❌ JSON parsing failed after {len(attempts)} attempts:")
    for attempt in attempts:
        print(f"  - {attempt}")

    # Print context around the first parse error for debugging
    try:
        json.loads(original_text)
    except json.JSONDecodeError as e:
        pos = e.pos or 0
        snippet = original_text[max(0, pos - 50):pos + 50]
        print(f"  Context around error (pos {pos}): ...{repr(snippet)}...")

    return None


def extract_json_from_llm_response(response_text: str) -> Optional[str]:
    """
    Extract JSON from LLM response text.
    
    Handles various formats:
    - Plain JSON
    - JSON in markdown code blocks
    - JSON with explanatory text before/after
    
    Args:
        response_text: Full LLM response
    
    Returns:
        Extracted JSON string or None
    """
    text = response_text.strip()
    
    # Method 1: Look for markdown code block
    if '```' in text:
        # Try to find JSON in code block
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
    
    # Method 2: Find object boundaries
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    
    if first_brace >= 0 and last_brace > first_brace:
        return text[first_brace:last_brace+1]
    
    return None


def validate_plan_json(plan_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate that plan JSON has required structure.
    
    Args:
        plan_data: Parsed plan JSON
    
    Returns:
        (is_valid, errors)
    """
    errors = []
    
    # Check required fields
    if "stories" not in plan_data and "subtasks" not in plan_data:
        errors.append("Plan must include 'stories' or 'subtasks' array")
    
    # Validate stories structure
    if "stories" in plan_data:
        stories = plan_data["stories"]
        if not isinstance(stories, list):
            errors.append("'stories' must be an array")
        else:
            for i, story in enumerate(stories):
                if not isinstance(story, dict):
                    errors.append(f"Story {i+1} must be an object")
                    continue
                
                if "summary" not in story:
                    errors.append(f"Story {i+1} missing 'summary'")
                
                if "subtasks" in story and not isinstance(story["subtasks"], list):
                    errors.append(f"Story {i+1} 'subtasks' must be an array")
    
    is_valid = len(errors) == 0
    return is_valid, errors
