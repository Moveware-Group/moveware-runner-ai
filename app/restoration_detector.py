"""
Restoration Task Detection and Enhancement

Detects when a Story is asking to restore/bring back removed functionality
and provides enhanced context via git history analysis.
"""

import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class RestorationContext:
    """Context about code that needs to be restored."""
    is_restoration: bool
    keywords_found: List[str]
    referenced_story: Optional[str]  # e.g., "OD-48"
    referenced_commit: Optional[str]  # Git commit hash
    deleted_files: List[str]  # Files that were deleted
    modified_files: Dict[str, str]  # File path -> old content
    warnings: List[str]  # Missing information warnings


# Restoration keywords to detect
RESTORATION_KEYWORDS = [
    r'\brestore\b',
    r'\bre-implement\b',
    r'\breimplemented?\b',
    r'\bbring back\b',
    r'\bwas removed\b',
    r'\bwas deleted\b',
    r'\baccidentally removed\b',
    r'\bregressed\b',
    r'\bregression\b',
    r'\bmissing feature\b',
    r'\bno longer (works?|exists?)\b',
]

# Pattern to find story references (e.g., "OD-48", "removed in Story 1", "TB-123")
STORY_REFERENCE_PATTERN = r'\b([A-Z]+-\d+)\b|(?:story|issue|task)\s+#?(\d+)'


def detect_restoration_task(
    issue_summary: str,
    issue_description: str
) -> RestorationContext:
    """
    Detect if this is a restoration task based on keywords.
    
    Args:
        issue_summary: Jira issue summary
        issue_description: Jira issue description
        
    Returns:
        RestorationContext with detection results
    """
    combined_text = f"{issue_summary}\n{issue_description}".lower()
    
    # Find restoration keywords
    keywords_found = []
    for pattern in RESTORATION_KEYWORDS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            keywords_found.append(pattern.replace(r'\b', '').replace('\\', ''))
    
    is_restoration = len(keywords_found) > 0
    
    # Find story references
    referenced_story = None
    story_matches = re.findall(STORY_REFERENCE_PATTERN, combined_text, re.IGNORECASE)
    if story_matches:
        # Get first valid match
        for match in story_matches:
            if match[0]:  # Full story key like "OD-48"
                referenced_story = match[0].upper()
                break
            elif match[1]:  # Just number like "Story 1"
                referenced_story = f"#{match[1]}"
                break
    
    # Initialize with basic detection
    context = RestorationContext(
        is_restoration=is_restoration,
        keywords_found=keywords_found,
        referenced_story=referenced_story,
        referenced_commit=None,
        deleted_files=[],
        modified_files={},
        warnings=[]
    )
    
    # Add warnings if restoration detected but missing references
    if is_restoration:
        if not referenced_story:
            context.warnings.append(
                "⚠️ RESTORATION DETECTED but no story/commit referenced. "
                "Please add: 'Removed in Story OD-XX' or 'Commit: abc123'"
            )
        
        # Check for common missing information
        if 'screenshot' not in combined_text and 'image' not in combined_text:
            context.warnings.append(
                "⚠️ No screenshots referenced. Consider attaching screenshots of the original UI."
            )
        
        if 'file' not in combined_text and 'component' not in combined_text:
            context.warnings.append(
                "⚠️ No file/component names mentioned. Consider listing original file paths."
            )
    
    return context


def find_removal_commit(
    repo_path: Path,
    referenced_story: str,
    search_terms: List[str]
) -> Optional[str]:
    """
    Find the git commit that removed the code.
    
    Searches for:
    1. Commits mentioning the referenced story
    2. Commits with deletions matching search terms
    
    Args:
        repo_path: Path to git repository
        referenced_story: Story key (e.g., "OD-48")
        search_terms: Keywords to search in commit messages
        
    Returns:
        Commit hash if found, None otherwise
    """
    try:
        # Search for commits mentioning the story key
        if referenced_story and referenced_story.startswith(('OD-', 'TB-', 'MW-')):
            result = subprocess.run(
                ['git', 'log', '--all', '--grep', referenced_story, '--format=%H', '-n', '5'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                commits = result.stdout.strip().split('\n')
                # Return the most recent commit
                return commits[0]
        
        # Fallback: search for commits with search terms
        for term in search_terms:
            result = subprocess.run(
                ['git', 'log', '--all', '--grep', term, '--format=%H', '-n', '1'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        
        return None
        
    except Exception as e:
        print(f"⚠️ Git history search failed: {e}")
        return None


def get_deleted_files_from_commit(
    repo_path: Path,
    commit_hash: str
) -> List[str]:
    """
    Get list of files deleted in a commit.
    
    Args:
        repo_path: Path to git repository
        commit_hash: Git commit hash
        
    Returns:
        List of deleted file paths
    """
    try:
        # Get files deleted in this commit
        result = subprocess.run(
            ['git', 'diff-tree', '--no-commit-id', '--name-status', '--diff-filter=D', '-r', commit_hash],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            deleted_files = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    # Format: "D\tpath/to/file.ext"
                    parts = line.split('\t')
                    if len(parts) == 2 and parts[0] == 'D':
                        deleted_files.append(parts[1])
            return deleted_files
        
        return []
        
    except Exception as e:
        print(f"⚠️ Failed to get deleted files: {e}")
        return []


def get_file_content_before_deletion(
    repo_path: Path,
    commit_hash: str,
    file_path: str
) -> Optional[str]:
    """
    Get the content of a file before it was deleted.
    
    Args:
        repo_path: Path to git repository
        commit_hash: Commit where file was deleted
        file_path: Path to the file
        
    Returns:
        File content before deletion, or None if not found
    """
    try:
        # Get file content from parent commit (before deletion)
        result = subprocess.run(
            ['git', 'show', f'{commit_hash}~1:{file_path}'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return result.stdout
        
        return None
        
    except Exception as e:
        print(f"⚠️ Failed to get file content: {e}")
        return None


def analyze_git_history(
    repo_path: Path,
    context: RestorationContext,
    search_terms: List[str]
) -> RestorationContext:
    """
    Analyze git history to find removed code.
    
    Args:
        repo_path: Path to git repository
        context: Initial restoration context
        search_terms: Keywords to search for (e.g., ["companies", "branding"])
        
    Returns:
        Updated RestorationContext with git history data
    """
    if not context.is_restoration:
        return context
    
    print(f"🔍 Analyzing git history for restoration context...")
    
    # Find the commit that removed the code
    commit_hash = find_removal_commit(repo_path, context.referenced_story, search_terms)
    
    if commit_hash:
        print(f"✅ Found removal commit: {commit_hash}")
        context.referenced_commit = commit_hash
        
        # Get deleted files
        deleted_files = get_deleted_files_from_commit(repo_path, commit_hash)
        context.deleted_files = deleted_files
        
        print(f"📁 Found {len(deleted_files)} deleted files")
        
        # Get content of key deleted files (limit to avoid huge context)
        for file_path in deleted_files[:5]:  # Limit to 5 files
            # Skip non-code files
            if not any(file_path.endswith(ext) for ext in ['.ts', '.tsx', '.js', '.jsx', '.py', '.vue']):
                continue
            
            print(f"📄 Retrieving content: {file_path}")
            content = get_file_content_before_deletion(repo_path, commit_hash, file_path)
            
            if content:
                context.modified_files[file_path] = content
        
        print(f"✅ Retrieved content for {len(context.modified_files)} files")
    else:
        print(f"⚠️ Could not find removal commit")
        context.warnings.append(
            "⚠️ Could not automatically find the commit that removed this code. "
            "Please specify the commit hash in the description."
        )
    
    return context


def format_restoration_context_for_prompt(context: RestorationContext) -> str:
    """
    Format restoration context for inclusion in AI prompt.
    
    Args:
        context: RestorationContext with git history
        
    Returns:
        Formatted string for prompt
    """
    if not context.is_restoration:
        return ""
    
    lines = []
    lines.append("\n## 🔄 RESTORATION TASK DETECTED\n")
    lines.append("This is a restoration task - you need to bring back code that was removed.\n")
    
    if context.referenced_story:
        lines.append(f"**Referenced Story/Commit:** {context.referenced_story}\n")
    
    if context.referenced_commit:
        lines.append(f"**Removal Commit:** {context.referenced_commit}\n")
    
    if context.deleted_files:
        lines.append(f"\n**Files That Were Deleted ({len(context.deleted_files)}):**\n")
        for file_path in context.deleted_files[:10]:  # Show max 10
            lines.append(f"- `{file_path}`\n")
        if len(context.deleted_files) > 10:
            lines.append(f"- ... and {len(context.deleted_files) - 10} more\n")
    
    if context.modified_files:
        lines.append(f"\n**ORIGINAL CODE TO RESTORE:**\n")
        lines.append("Below is the code that was removed. Your task is to RE-IMPLEMENT this functionality.\n")
        lines.append("Use the original code as a reference, but adapt it if the codebase structure has changed.\n\n")
        
        for file_path, content in list(context.modified_files.items())[:3]:  # Show max 3 files
            lines.append(f"### Original: `{file_path}`\n")
            lines.append("```\n")
            # Truncate very long files
            if len(content) > 5000:
                lines.append(content[:5000])
                lines.append("\n... (truncated, file was longer)\n")
            else:
                lines.append(content)
            lines.append("```\n\n")
    
    if context.warnings:
        lines.append("\n**⚠️ WARNINGS:**\n")
        for warning in context.warnings:
            lines.append(f"- {warning}\n")
    
    lines.append("\n**IMPORTANT:**\n")
    lines.append("- This is a RESTORATION - replicate the functionality shown above\n")
    lines.append("- Preserve all existing features (this should be ADDITIVE)\n")
    lines.append("- Match the original structure and behavior as closely as possible\n")
    lines.append("- If the original code references files/components that no longer exist, adapt accordingly\n")
    
    return "".join(lines)


def check_restoration_quality(issue_description: str, context: RestorationContext) -> List[str]:
    """
    Check if a restoration Story has enough information for the AI to succeed.
    
    Args:
        issue_description: Jira issue description
        context: RestorationContext
        
    Returns:
        List of recommendations for improvement
    """
    recommendations = []
    
    if not context.is_restoration:
        return recommendations
    
    # Check for acceptance criteria
    if 'acceptance criteria' not in issue_description.lower():
        recommendations.append(
            "Add specific acceptance criteria (5-15 checkboxes) "
            "listing exactly what should be restored"
        )
    
    # Check for technical details
    if 'file' not in issue_description.lower() and not context.deleted_files:
        recommendations.append(
            "Specify which files/components need to be restored "
            "(e.g., 'Original file: app/settings/companies/page.tsx')"
        )
    
    # Check for preservation notes
    if 'keep' not in issue_description.lower() and 'preserve' not in issue_description.lower():
        recommendations.append(
            "Add preservation notes: specify what existing features should NOT be changed"
        )
    
    # Check for UI references
    if any(keyword in issue_description.lower() for keyword in ['ui', 'button', 'form', 'page', 'component']):
        if 'screenshot' not in issue_description.lower():
            recommendations.append(
                "Consider attaching screenshots of the original UI "
                "or referencing the commit/PR where it existed"
            )
    
    return recommendations
