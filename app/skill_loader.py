"""
Skill loader - loads framework/project-specific guidance for the AI.

Skills are stored in .cursor/skills/<name>/SKILL.md and provide
context-specific instructions (e.g., Next.js vs Flutter conventions).
"""
from pathlib import Path
from typing import List, Optional


SKILLS_DIR = Path(__file__).parent.parent / ".cursor" / "skills"


def load_skill(skill_name: str) -> Optional[str]:
    """
    Load skill content by name.
    
    Args:
        skill_name: Skill identifier (e.g., "nextjs-fullstack-dev", "flutter-dev")
    
    Returns:
        Skill content as string, or None if not found
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    
    if not skill_path.exists():
        print(f"Skill not found: {skill_name} (looked at {skill_path})")
        return None
    
    try:
        return skill_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Failed to load skill {skill_name}: {e}")
        return None


def load_skills(skill_names: List[str], max_total_chars: int = 15000) -> str:
    """
    Load and combine multiple skills.
    
    Args:
        skill_names: List of skill names to load
        max_total_chars: Maximum total characters (to avoid token limits)
    
    Returns:
        Combined skill content for inclusion in prompts
    """
    if not skill_names:
        return ""
    
    parts = []
    total_len = 0
    
    for name in skill_names:
        content = load_skill(name)
        if content and total_len < max_total_chars:
            # Strip YAML frontmatter (between --- and ---)
            if content.startswith("---"):
                parts_to_skip = content.split("---", 2)
                if len(parts_to_skip) >= 3:
                    content = parts_to_skip[2].strip()
            
            remaining = max_total_chars - total_len
            if len(content) > remaining:
                content = content[:remaining] + "\n... (truncated)"
            
            parts.append(f"## Skill: {name}\n\n{content}")
            total_len += len(parts[-1])
    
    if not parts:
        return ""
    
    return (
        "**Project-Specific Conventions (follow these for this repository):**\n\n"
        + "\n\n---\n\n".join(parts)
    )
