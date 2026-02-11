# Dashboard Improvements - Time Filtering and Cost Tracking

## Summary

This document outlines the improvements made to the AI Runner Status Dashboard to add time-based filtering and fix cost tracking issues.

## Changes Made

### 1. Time Filter Dropdown (Frontend)

**File: `app/templates/status.html`**

Added a dropdown menu in the dashboard header that allows users to filter runs by time period:

- **Last Hour**: Shows runs from the past 60 minutes
- **Last 6 Hours**: Shows runs from the past 6 hours
- **Last 12 Hours**: Shows runs from the past 12 hours  
- **Last 24 Hours**: Shows runs from the past day (default)
- **Last Week**: Shows runs from the past 7 days
- **All Time**: Shows all runs in the database (limited to 200 most recent)

**Implementation Details:**
- Added HTML `<select>` element with time filter options
- JavaScript variable `timeFilter` tracks currently selected time period
- Event listener on dropdown triggers data refresh when selection changes
- Metrics section title updates dynamically to show selected time range
- Both status API and metrics API use the same time filter

### 2. Backend API Updates

**File: `app/main.py`**

Updated the `/api/status` endpoint to accept an `hours` parameter:

```python
@app.get("/api/status")
async def status_api(detail: str = "summary", hours: str = "24") -> Dict[str, Any]:
```

**Changes:**
- Added `hours` parameter (accepts integer or "all")
- Calculates time cutoff based on hours parameter
- Returns runs filtered by creation time
- Limits to 200 most recent runs for performance

### 3. Cost Tracking Fix

**File: `app/executor.py`**

Fixed the issue where costs weren't showing in the dashboard by implementing proper token usage tracking:

#### 3.1 Token Usage Extraction

Added code to extract token usage from Anthropic API responses:

```python
# Extract token usage from response
if metrics and raw.get("usage"):
    usage = raw["usage"]
    metrics.total_input_tokens = usage.get("input_tokens", 0)
    metrics.total_output_tokens = usage.get("output_tokens", 0)
    metrics.cached_tokens = usage.get("cache_read_input_tokens", 0)
    
    # Calculate cost
    metrics.estimated_cost = calculate_cost(
        settings.ANTHROPIC_MODEL,
        metrics.total_input_tokens,
        metrics.total_output_tokens,
        metrics.cached_tokens
    )
```

#### 3.2 Self-Healing Token Tracking

Added token tracking for fix attempts (when build fails and Claude/OpenAI retry):

```python
# Track token usage for fix attempts
if metrics and fix_raw.get("usage"):
    usage = fix_raw["usage"]
    metrics.total_input_tokens += usage.get("input_tokens", 0)
    metrics.total_output_tokens += usage.get("output_tokens", 0)
    metrics.cached_tokens += usage.get("cache_read_input_tokens", 0)
    metrics.self_heal_attempts += 1
    
    # Recalculate cost
    metrics.estimated_cost = calculate_cost(...)
```

#### 3.3 Error Metrics Tracking

Added try-except wrapper to ensure metrics are saved even when execution fails:

```python
def execute_subtask(issue: JiraIssue, run_id: Optional[int] = None) -> ExecutionResult:
    # Initialize metrics
    start_time = datetime.now()
    metrics = ExecutionMetrics(...)
    
    try:
        return _execute_subtask_impl(issue, run_id, metrics, start_time)
    except Exception as e:
        # Save metrics even on failure
        if metrics:
            metrics.end_time = datetime.now()
            metrics.duration_seconds = (end_time - start_time).total_seconds()
            metrics.success = False
            metrics.status = "failed"
            metrics.error_message = str(e)
            metrics.error_category = classify_error(str(e))[0]
            
            save_metrics(metrics)
        
        raise  # Re-raise the original error
```

## Why Costs Weren't Showing

The root cause of costs not appearing was:

1. **Token usage wasn't being extracted** from API responses
2. **Metrics object had zero values** for `total_input_tokens`, `total_output_tokens`, and `estimated_cost`
3. **Cost calculation never happened** even though the `calculate_cost()` function existed

The fix extracts usage data from the Anthropic API response and calculates costs using the existing pricing model:
- Claude Sonnet 4: $3/1M input, $15/1M output, $0.30/1M cached

## Benefits

1. **Better visibility**: Users can now see runs from any time period
2. **Accurate cost tracking**: All API costs are now properly tracked and displayed
3. **Failed run metrics**: Even failed runs now save metrics for analysis
4. **Self-healing costs**: Token usage from automatic fix attempts is tracked
5. **Historical analysis**: Users can analyze performance over different time periods

## Testing

To test the changes:

1. **Time Filter**: 
   - Open dashboard at http://localhost:8088/status
   - Change time filter dropdown
   - Verify metrics section title updates
   - Verify runs list updates

2. **Cost Tracking**:
   - Trigger a new run through Jira
   - Wait for completion
   - Check dashboard metrics section
   - Verify "TOTAL COST" shows actual dollar amount (not $0)
   - Check `/api/metrics/summary?hours=24` endpoint directly

3. **Error Metrics**:
   - Trigger a run that will fail
   - Verify metrics are still saved
   - Check error_category is populated

## API Endpoints

### `/api/status?hours={N}`
Returns runs from the last N hours, or all runs if hours="all"

Example:
```
GET /api/status?hours=6&detail=summary
```

### `/api/metrics/summary?hours={N}`
Returns summary metrics for the last N hours

Example:
```
GET /api/metrics/summary?hours=24
```

Response:
```json
{
  "period_hours": 24,
  "total_runs": 10,
  "completed": 8,
  "failed": 2,
  "success_rate": 80.0,
  "total_cost_usd": 1.23,
  "avg_duration_seconds": 145.5,
  "total_tokens": 245000,
  "error_categories": {
    "build_error": 1,
    "import_error": 1
  }
}
```

## Future Enhancements

Potential improvements:
1. Add date range picker for custom time ranges
2. Export metrics as CSV or JSON
3. Add charts/graphs for visualizing trends over time
4. Per-repository cost breakdown
5. Cost projections based on current usage
6. Alert thresholds for high costs

## Notes

- Time filtering is done server-side for performance
- All times are in Unix timestamps (seconds since epoch)
- Cached tokens are tracked separately and cost less
- The dashboard auto-refreshes every 5 seconds
- Metrics are stored in the `runs` table in the `metrics_json` column
