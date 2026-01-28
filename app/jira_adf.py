"""Convert Jira wiki markup to Atlassian Document Format (ADF)."""
from typing import Any, Dict, List
import re


def wiki_to_adf(text: str) -> Dict[str, Any]:
    """Convert Jira wiki markup to ADF format.
    
    Supports:
    - h3. headings
    - Bullet lists (- item)
    - Numbered lists (1. item)
    - Bold text (*text*)
    - Code blocks {code:json}...{code}
    - Horizontal rules (----)
    """
    lines = text.split('\n')
    content: List[Dict[str, Any]] = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Empty line
        if not line.strip():
            i += 1
            continue
        
        # Heading (h3.)
        if line.startswith('h3. '):
            content.append({
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": line[4:]}]
            })
            i += 1
            continue
        
        # Horizontal rule (----)
        if line.strip() == '----':
            content.append({"type": "rule"})
            i += 1
            continue
        
        # Code block {code:json}
        if line.strip().startswith('{code'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('{code}'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # Skip closing {code}
            
            content.append({
                "type": "codeBlock",
                "attrs": {"language": "json"},
                "content": [{"type": "text", "text": '\n'.join(code_lines)}]
            })
            continue
        
        # Bullet list (- item)
        if line.strip().startswith('- '):
            list_items = []
            while i < len(lines) and lines[i].strip().startswith('- '):
                item_text = lines[i].strip()[2:]  # Remove '- '
                list_items.append({
                    "type": "listItem",
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": item_text}]
                    }]
                })
                i += 1
            
            content.append({
                "type": "bulletList",
                "content": list_items
            })
            continue
        
        # Numbered list (1. item)
        if re.match(r'^\d+\.\s', line.strip()):
            list_items = []
            while i < len(lines) and re.match(r'^\d+\.\s', lines[i].strip()):
                item_text = re.sub(r'^\d+\.\s+', '', lines[i].strip())
                # Handle bold text (*text*)
                item_content = parse_inline_formatting(item_text)
                list_items.append({
                    "type": "listItem",
                    "content": [{
                        "type": "paragraph",
                        "content": item_content
                    }]
                })
                i += 1
            
            content.append({
                "type": "orderedList",
                "content": list_items
            })
            continue
        
        # Regular paragraph
        paragraph_content = parse_inline_formatting(line)
        content.append({
            "type": "paragraph",
            "content": paragraph_content
        })
        i += 1
    
    return {
        "type": "doc",
        "version": 1,
        "content": content
    }


def parse_inline_formatting(text: str) -> List[Dict[str, Any]]:
    """Parse inline formatting like bold (*text*)."""
    content = []
    
    # Split by bold markers (*text*)
    parts = re.split(r'(\*[^*]+\*)', text)
    
    for part in parts:
        if not part:
            continue
        
        if part.startswith('*') and part.endswith('*'):
            # Bold text
            content.append({
                "type": "text",
                "text": part[1:-1],
                "marks": [{"type": "strong"}]
            })
        else:
            # Regular text
            if part:
                content.append({
                    "type": "text",
                    "text": part
                })
    
    # If no content, add empty text
    if not content:
        content = [{"type": "text", "text": text}]
    
    return content
