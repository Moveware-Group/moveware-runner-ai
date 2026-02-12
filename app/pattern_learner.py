"""
Pattern Learning System for Build Error Fixes

Tracks successful and failed fix attempts to learn from history.
Provides similar fix examples when encountering known error patterns.
"""
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import connect, now
from .error_classifier import classify_error


def init_pattern_learning_schema() -> None:
    """Initialize database schema for pattern learning."""
    with connect() as conn:
        # Error patterns table: stores successful fixes for similar errors
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_hash TEXT NOT NULL UNIQUE,
                error_text TEXT NOT NULL,
                error_category TEXT NOT NULL,
                files_involved TEXT,
                attempted_fixes TEXT,
                successful_fix TEXT,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_success_at INTEGER,
                last_fail_at INTEGER,
                metadata_json TEXT
            )
        """)
        
        # Fix attempts table: detailed log of all fix attempts (for analysis)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fix_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                issue_key TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                error_hash TEXT NOT NULL,
                error_text TEXT NOT NULL,
                error_category TEXT NOT NULL,
                fix_strategy TEXT NOT NULL,
                files_changed TEXT,
                model_used TEXT,
                success BOOLEAN NOT NULL,
                duration_seconds REAL,
                created_at INTEGER NOT NULL,
                metadata_json TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_error_patterns_hash ON error_patterns(error_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_error_patterns_category ON error_patterns(error_category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fix_attempts_hash ON fix_attempts(error_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fix_attempts_run ON fix_attempts(run_id)")
        
        print("✓ Pattern learning database schema initialized")


@dataclass
class FixPattern:
    """Represents a known fix pattern for an error."""
    error_hash: str
    error_category: str
    successful_fix: str
    files_involved: List[str]
    success_count: int
    confidence: float  # 0.0 to 1.0


def _hash_error_pattern(error_msg: str) -> str:
    """
    Generate a normalized hash for an error message.
    Removes line numbers, file paths, and variable names to match similar errors.
    """
    # Normalize the error: remove line numbers, specific paths, variable names
    normalized = error_msg.lower()
    
    # Remove line numbers (e.g., "src/file.ts:42:17" -> "src/file.ts")
    normalized = re.sub(r':\d+:\d+', '', normalized)
    normalized = re.sub(r'line \d+', 'line N', normalized)
    
    # Remove specific file paths but keep structure (e.g., "src/lib/auth.ts" -> "src/lib/*.ts")
    # Keep directory structure for pattern matching
    normalized = re.sub(r'/[a-z0-9_-]+\.', '/*.', normalized)
    
    # Remove specific variable/function names in quotes but keep the error type
    normalized = re.sub(r"['\"]\w+['\"]", "'VAR'", normalized)
    
    # Remove timestamps
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', normalized)
    normalized = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', normalized)
    
    # Generate hash
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def record_fix_attempt(
    run_id: int,
    issue_key: str,
    attempt_number: int,
    error_msg: str,
    fix_strategy: str,
    files_changed: List[str],
    model_used: str,
    success: bool,
    duration_seconds: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Record a fix attempt for later analysis and learning.
    
    Args:
        run_id: Run identifier
        issue_key: Jira issue key
        attempt_number: Which attempt (1, 2, 3, etc.)
        error_msg: The error message being fixed
        fix_strategy: Description of what was tried
        files_changed: List of files that were modified
        model_used: Which AI model was used (claude, openai, etc.)
        success: Whether the fix worked
        duration_seconds: How long the fix attempt took
        metadata: Additional context (tokens, cost, etc.)
    """
    error_hash = _hash_error_pattern(error_msg)
    error_category, _, _ = classify_error(error_msg)
    ts = now()
    
    with connect() as conn:
        conn.execute("""
            INSERT INTO fix_attempts (
                run_id, issue_key, attempt_number, error_hash, error_text, 
                error_category, fix_strategy, files_changed, model_used, 
                success, duration_seconds, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, issue_key, attempt_number, error_hash, error_msg[:2000],
            error_category, fix_strategy, json.dumps(files_changed), model_used,
            success, duration_seconds, ts, json.dumps(metadata or {})
        ))


def record_successful_fix(
    error_msg: str,
    fix_strategy: str,
    files_changed: List[str],
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Record a successful fix to the pattern database.
    This is the key to learning - when a fix works, we store it for reuse.
    
    Args:
        error_msg: The error that was fixed
        fix_strategy: What worked (description of the fix)
        files_changed: Which files were modified
        metadata: Additional context
    """
    error_hash = _hash_error_pattern(error_msg)
    error_category, _, _ = classify_error(error_msg)
    ts = now()
    
    with connect() as conn:
        # Check if pattern already exists
        existing = conn.execute(
            "SELECT id, success_count FROM error_patterns WHERE error_hash = ?",
            (error_hash,)
        ).fetchone()
        
        if existing:
            # Update existing pattern (increment success count)
            pattern_id, current_count = existing
            conn.execute("""
                UPDATE error_patterns 
                SET success_count = ?, 
                    last_success_at = ?,
                    successful_fix = ?
                WHERE id = ?
            """, (current_count + 1, ts, fix_strategy, pattern_id))
        else:
            # Create new pattern
            conn.execute("""
                INSERT INTO error_patterns (
                    error_hash, error_text, error_category, files_involved,
                    successful_fix, success_count, created_at, last_success_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                error_hash, error_msg[:2000], error_category,
                json.dumps(files_changed), fix_strategy, 1, ts, ts,
                json.dumps(metadata or {})
            ))


def record_failed_fix(
    error_msg: str,
    fix_strategy: str,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Record a failed fix attempt to learn what doesn't work.
    
    Args:
        error_msg: The error that wasn't fixed
        fix_strategy: What was tried (but didn't work)
        metadata: Additional context
    """
    error_hash = _hash_error_pattern(error_msg)
    error_category, _, _ = classify_error(error_msg)
    ts = now()
    
    with connect() as conn:
        # Check if pattern exists
        existing = conn.execute(
            "SELECT id, fail_count, attempted_fixes FROM error_patterns WHERE error_hash = ?",
            (error_hash,)
        ).fetchone()
        
        if existing:
            pattern_id, current_fail_count, attempted_fixes_json = existing
            
            # Add to list of attempted fixes
            attempted_fixes = json.loads(attempted_fixes_json or "[]")
            attempted_fixes.append(fix_strategy)
            
            conn.execute("""
                UPDATE error_patterns 
                SET fail_count = ?,
                    last_fail_at = ?,
                    attempted_fixes = ?
                WHERE id = ?
            """, (current_fail_count + 1, ts, json.dumps(attempted_fixes), pattern_id))
        else:
            # Create pattern with failed attempt
            conn.execute("""
                INSERT INTO error_patterns (
                    error_hash, error_text, error_category, attempted_fixes,
                    fail_count, created_at, last_fail_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                error_hash, error_msg[:2000], error_category,
                json.dumps([fix_strategy]), 1, ts, ts,
                json.dumps(metadata or {})
            ))


def get_similar_successful_fixes(
    error_msg: str,
    limit: int = 5
) -> List[FixPattern]:
    """
    Find similar errors that were successfully fixed in the past.
    
    Args:
        error_msg: The current error to find fixes for
        limit: Maximum number of similar fixes to return
    
    Returns:
        List of FixPattern objects, sorted by confidence (best matches first)
    """
    error_hash = _hash_error_pattern(error_msg)
    error_category, _, _ = classify_error(error_msg)
    
    patterns: List[FixPattern] = []
    
    with connect() as conn:
        # First: Try exact hash match (highest confidence)
        exact_match = conn.execute("""
            SELECT error_hash, error_category, successful_fix, files_involved,
                   success_count, fail_count
            FROM error_patterns
            WHERE error_hash = ? AND successful_fix IS NOT NULL
            ORDER BY success_count DESC
            LIMIT 1
        """, (error_hash,)).fetchone()
        
        if exact_match:
            eh, ec, fix, files_json, succ, fail = exact_match
            confidence = succ / (succ + fail) if (succ + fail) > 0 else 0.5
            patterns.append(FixPattern(
                error_hash=eh,
                error_category=ec,
                successful_fix=fix,
                files_involved=json.loads(files_json or "[]"),
                success_count=succ,
                confidence=min(0.95, confidence)  # Exact match: high confidence
            ))
        
        # Second: Try same category (medium confidence)
        if len(patterns) < limit:
            category_matches = conn.execute("""
                SELECT error_hash, error_category, successful_fix, files_involved,
                       success_count, fail_count
                FROM error_patterns
                WHERE error_category = ? 
                  AND successful_fix IS NOT NULL
                  AND error_hash != ?
                ORDER BY success_count DESC
                LIMIT ?
            """, (error_category, error_hash, limit - len(patterns))).fetchall()
            
            for eh, ec, fix, files_json, succ, fail in category_matches:
                confidence = (succ / (succ + fail)) * 0.7 if (succ + fail) > 0 else 0.3
                patterns.append(FixPattern(
                    error_hash=eh,
                    error_category=ec,
                    successful_fix=fix,
                    files_involved=json.loads(files_json or "[]"),
                    success_count=succ,
                    confidence=confidence
                ))
    
    return patterns


def get_pattern_statistics() -> Dict[str, Any]:
    """Get overall statistics about learned patterns."""
    with connect() as conn:
        stats = {}
        
        # Total patterns learned
        total = conn.execute("SELECT COUNT(*) FROM error_patterns").fetchone()[0]
        stats["total_patterns"] = total
        
        # Successful patterns (have a working fix)
        successful = conn.execute(
            "SELECT COUNT(*) FROM error_patterns WHERE successful_fix IS NOT NULL"
        ).fetchone()[0]
        stats["successful_patterns"] = successful
        
        # Category breakdown
        categories = conn.execute("""
            SELECT error_category, COUNT(*) as count, SUM(success_count) as successes
            FROM error_patterns
            GROUP BY error_category
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        stats["top_categories"] = [
            {"category": cat, "count": count, "successes": succ}
            for cat, count, succ in categories
        ]
        
        # Recent learning (last 7 days)
        week_ago = now() - (7 * 24 * 3600)
        recent = conn.execute(
            "SELECT COUNT(*) FROM error_patterns WHERE created_at > ?",
            (week_ago,)
        ).fetchone()[0]
        stats["patterns_learned_last_week"] = recent
        
        return stats


def format_fix_suggestions(patterns: List[FixPattern]) -> str:
    """
    Format fix pattern suggestions as a readable prompt addition.
    
    Args:
        patterns: List of similar fix patterns
    
    Returns:
        Formatted string to add to fix prompt
    """
    if not patterns:
        return ""
    
    lines = [
        "\n**📚 SIMILAR ERRORS FIXED IN THE PAST:**",
        "The system has successfully fixed similar errors before. Use these as guidance:\n"
    ]
    
    for i, pattern in enumerate(patterns, 1):
        confidence_pct = int(pattern.confidence * 100)
        lines.append(f"{i}. **{pattern.error_category}** (confidence: {confidence_pct}%, fixed {pattern.success_count}x)")
        lines.append(f"   **What worked:** {pattern.successful_fix}")
        
        if pattern.files_involved:
            files_str = ", ".join(pattern.files_involved[:3])
            if len(pattern.files_involved) > 3:
                files_str += f" (+{len(pattern.files_involved)-3} more)"
            lines.append(f"   **Files changed:** {files_str}")
        lines.append("")
    
    lines.append("**IMPORTANT:** Learn from these patterns but adapt to your specific context.")
    lines.append("Don't blindly copy - verify the fix makes sense for your files.\n")
    
    return "\n".join(lines)
