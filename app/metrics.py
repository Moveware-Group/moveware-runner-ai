"""
Metrics collection for AI Runner performance tracking.

Tracks key metrics like execution time, costs, success rates, and error categories.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
import json


@dataclass
class ExecutionMetrics:
    """Metrics for a single execution run."""
    
    # Identifiers
    run_id: int
    issue_key: str
    issue_type: str  # "subtask", "story", "epic"
    
    # Timing
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    
    # Outcomes
    success: bool
    status: str  # "completed", "failed", "blocked"
    error_category: str = ""
    error_message: str = ""
    
    # LLM Usage
    model_used: str = ""  # "claude", "openai", "both"
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    
    # Build/Test
    build_attempts: int = 0
    self_heal_attempts: int = 0
    pre_commit_passed: bool = True
    tests_run: bool = False
    tests_passed: bool = True
    
    # Files
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    
    # Costs (USD)
    estimated_cost: float = 0.0
    
    # Additional metadata
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        data = asdict(self)
        # Convert datetime to ISO string
        data["start_time"] = self.start_time.isoformat()
        data["end_time"] = self.end_time.isoformat()
        return data
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionMetrics":
        """Create from dictionary."""
        # Convert ISO strings back to datetime
        data["start_time"] = datetime.fromisoformat(data["start_time"])
        data["end_time"] = datetime.fromisoformat(data["end_time"])
        return cls(**data)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0
) -> float:
    """
    Calculate estimated API cost in USD.
    
    Pricing as of 2024:
    - Claude Sonnet 4: $3/1M input, $15/1M output
    - Claude Sonnet 4 (cached): $0.30/1M input
    - OpenAI GPT-4: $2.50/1M input, $10/1M output
    """
    # Pricing per 1M tokens
    prices = {
        "claude": {"input": 3.0, "output": 15.0, "cached": 0.30},
        "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cached": 0.30},
        "openai": {"input": 2.5, "output": 10.0, "cached": 2.5},
        "gpt-4": {"input": 2.5, "output": 10.0, "cached": 2.5},
    }
    
    # Default to Claude pricing
    model_key = "claude"
    for key in prices:
        if key in model.lower():
            model_key = key
            break
    
    pricing = prices[model_key]
    
    # Calculate cost
    regular_input = max(0, input_tokens - cached_tokens)
    cost = (
        (regular_input * pricing["input"] / 1_000_000) +
        (cached_tokens * pricing["cached"] / 1_000_000) +
        (output_tokens * pricing["output"] / 1_000_000)
    )
    
    return round(cost, 4)


def save_metrics(metrics: ExecutionMetrics) -> None:
    """
    Save execution metrics to database.
    
    Stores in the runs table or a separate metrics table.
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Check if metrics column exists in runs table
            cursor.execute("PRAGMA table_info(runs)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if "metrics_json" not in columns:
                # Add metrics column if it doesn't exist
                cursor.execute("ALTER TABLE runs ADD COLUMN metrics_json TEXT")
                conn.commit()
            
            # Store metrics as JSON
            cursor.execute(
                "UPDATE runs SET metrics_json = ? WHERE id = ?",
                (metrics.to_json(), metrics.run_id)
            )
            conn.commit()
            
    except Exception as e:
        print(f"Warning: Could not save metrics: {e}")


def get_metrics(run_id: int) -> Optional[ExecutionMetrics]:
    """
    Retrieve metrics for a specific run.
    
    Args:
        run_id: The run ID to get metrics for
    
    Returns:
        ExecutionMetrics if found, None otherwise
    """
    from .db import connect
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT metrics_json FROM runs WHERE id = ?",
                (run_id,)
            )
            row = cursor.fetchone()
            
            if row and row[0]:
                data = json.loads(row[0])
                return ExecutionMetrics.from_dict(data)
    
    except Exception as e:
        print(f"Warning: Could not retrieve metrics: {e}")
    
    return None


def get_summary_stats(hours: int = 24) -> Dict[str, Any]:
    """
    Get summary statistics for the last N hours.
    
    Args:
        hours: Number of hours to look back
    
    Returns:
        Dictionary with summary statistics
    """
    from .db import connect
    import time
    
    cutoff_time = int(time.time()) - (hours * 3600)
    
    try:
        with connect() as conn:
            cursor = conn.cursor()
            
            # Get all runs in time period
            cursor.execute(
                """
                SELECT status, metrics_json 
                FROM runs 
                WHERE created_at > ?
                """,
                (cutoff_time,)
            )
            
            rows = cursor.fetchall()
            
            total_runs = len(rows)
            completed = sum(1 for row in rows if row[0] == "completed")
            failed = sum(1 for row in rows if row[0] == "failed")
            
            # Parse metrics
            all_metrics = []
            for row in rows:
                if row[1]:
                    try:
                        data = json.loads(row[1])
                        all_metrics.append(ExecutionMetrics.from_dict(data))
                    except:
                        pass
            
            # Calculate aggregates
            total_cost = sum(m.estimated_cost for m in all_metrics)
            avg_duration = sum(m.duration_seconds for m in all_metrics) / len(all_metrics) if all_metrics else 0
            total_tokens = sum(m.total_input_tokens + m.total_output_tokens for m in all_metrics)
            
            # Error categories
            error_categories = {}
            for m in all_metrics:
                if m.error_category:
                    error_categories[m.error_category] = error_categories.get(m.error_category, 0) + 1
            
            return {
                "period_hours": hours,
                "total_runs": total_runs,
                "completed": completed,
                "failed": failed,
                "success_rate": round(completed / total_runs * 100, 1) if total_runs > 0 else 0,
                "total_cost_usd": round(total_cost, 2),
                "avg_duration_seconds": round(avg_duration, 1),
                "total_tokens": total_tokens,
                "error_categories": error_categories,
                "avg_self_heal_attempts": round(
                    sum(m.self_heal_attempts for m in all_metrics) / len(all_metrics), 1
                ) if all_metrics else 0
            }
    
    except Exception as e:
        print(f"Warning: Could not calculate summary stats: {e}")
        return {}
