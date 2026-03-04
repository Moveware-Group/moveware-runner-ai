"""
JSON Repair Utilities

Repairs common JSON formatting issues from LLM outputs.
Handles trailing commas, missing commas, unescaped strings, etc.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple


def repair_json(text: str) -> str:
    """
    Attempt to repair common JSON formatting issues.
    
    Args:
        text: Potentially malformed JSON string
    
    Returns:
        Repaired JSON string
    """
    # Remove markdown code fences
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        # Remove first line (opening fence)
        if lines[0].strip().startswith('```'):
            lines = lines[1:]
        # Remove last line (closing fence) 
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines)
    
    # Find JSON object boundaries
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        # No valid JSON found
        return text
    
    text = text[first_brace:last_brace+1]
    
    # Fix common issues
    
    # 1. Remove trailing commas before closing braces/brackets
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    
    # 2. Fix missing commas between array/object elements
    # Pattern: }\n\s*{ (missing comma between objects in array)
    text = re.sub(r'\}(\s*)\{', r'},\1{', text)
    # Pattern: ]\n\s*{ or }\n\s*[ (missing comma)
    text = re.sub(r'\](\s*)\{', r'],\1{', text)
    text = re.sub(r'\}(\s*)\[', r'},\1[', text)
    
    # 3. Fix unescaped quotes in strings (limited - only obvious cases)
    # This is tricky and can break things, so we're conservative
    
    # 4. Remove comments (JSON doesn't support them but LLMs sometimes add them)
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    
    # 5. Fix single quotes to double quotes (JSON requires double quotes)
    # Only for property names, not in values (too risky)
    text = re.sub(r"'([a-zA-Z_][a-zA-Z0-9_]*)'\s*:", r'"\1":', text)
    
    return text


def _fix_unescaped_control_chars(text: str) -> str:
    """Fix unescaped control characters inside JSON string values."""
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != '\\'):
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        elif in_string and ord(ch) < 0x20 and ch not in ('\n', '\r', '\t'):
            result.append(f'\\u{ord(ch):04x}')
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


def try_parse_json(text: str, max_repair_attempts: int = 3) -> Optional[Dict[str, Any]]:
    """
    Try to parse JSON with progressive repair attempts.
    
    Returns:
        Parsed JSON dict or None if all attempts fail
    """
    attempts = []

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

    # Attempt 4: Apply standard repairs
    for i in range(max_repair_attempts):
        try:
            repaired = repair_json(text)
            result = json.loads(repaired)
            print(f"✅ JSON repaired successfully on attempt {i+1}")
            return result
        except json.JSONDecodeError as e:
            attempts.append(f"Repair attempt {i+1} failed: {e}")
            if i == 0:
                text = re.sub(r'\s+', ' ', text)
            elif i == 1:
                first_brace = text.find('{')
                last_brace = text.rfind('}')
                if first_brace >= 0 and last_brace > first_brace:
                    text = text[first_brace:last_brace + 1]

    # Attempt 5: Fix unescaped control characters (common with code in JSON)
    try:
        balanced = _find_balanced_json(text) or text
        fixed = _fix_unescaped_control_chars(balanced)
        fixed = repair_json(fixed)
        result = json.loads(fixed)
        print("✅ JSON parsed after fixing unescaped control characters")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"Control char fix failed: {e}")

    # Attempt 6: Last resort — try python's json with strict=False
    try:
        balanced = _find_balanced_json(text) or text
        result = json.loads(balanced, strict=False)
        print("✅ JSON parsed with strict=False")
        return result
    except json.JSONDecodeError as e:
        attempts.append(f"strict=False failed: {e}")

    print(f"❌ JSON parsing failed after {len(attempts)} attempts:")
    for attempt in attempts:
        print(f"  - {attempt}")

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
