# Troubleshooting Transient Errors

Transient errors during AI processing (planning, execution, self-healing) are usually caused by API rate limits or temporary service issues.

## What Was Improved (Feb 2026)

The retry logic has been enhanced to better handle transient errors:

| Before | After |
|--------|-------|
| 3 retries | 5 retries |
| 1s initial delay | 2s initial delay |
| 2x backoff | 2.5x backoff |
| Generic "Transient error" | Logs actual error message |
| 180s timeout | 300s timeout (for extended thinking) |
| Fixed delays | Honors `Retry-After` header when API provides it |
| Limited error patterns | 502, 504, connection errors, etc. |

## Error Types Now Retried

- **429** - Rate limit exceeded
- **502** - Bad gateway
- **503** - Service unavailable
- **504** - Gateway timeout
- **Timeout** - Request took too long
- **Connection errors** - Network issues
- **Overloaded** - API capacity issues

## If Transient Errors Persist

### 1. Check the Logs for the Actual Error

The logs now show the first 150 characters of the error:

```
Transient error (attempt 1/5): Anthropic error 429: {"error":{"type":"rate_limit_error"...
Retrying in 60s...
```

This tells you exactly what's failing.

### 2. Anthropic Rate Limits

If you see **429** errors frequently:

- **Check your tier**: [Claude Console](https://console.anthropic.com) → Billing → Usage
- **RPM limits**: Requests per minute (tier-dependent)
- **Token limits**: Input/output tokens per minute
- **Solution**: Contact Anthropic for a tier upgrade, or reduce concurrency

### 3. Request Anthropic's Retry-After

When Anthropic returns 429, they include a `Retry-After` header. The improved retry logic now respects this and waits the recommended time before retrying.

### 4. Extended Thinking Timeouts

Extended thinking can take 2-5+ minutes for complex tasks. The timeout has been increased from 180s to 300s (5 minutes). If you still see timeouts:

- Consider simpler task breakdown
- Or increase timeout further in `app/llm_anthropic.py` (line with `timeout=300`)

### 5. Reduce Concurrent Load

If running multiple workers or processing many issues simultaneously:

- Use a single worker for pilot: `USE_SMART_QUEUE=true` already limits to 1 run per repo
- Space out Jira issue assignments
- Consider lowering polling frequency

### 6. Check API Status

- [Anthropic Status](https://status.anthropic.com)
- [OpenAI Status](https://status.openai.com)

## Configuration

No new environment variables are needed. The improvements are built-in.

## Monitoring

Watch logs for patterns:

```bash
# See transient error details
sudo journalctl -u moveware-ai-worker -f | grep -E "Transient|Retrying|error"
```

If errors cluster around specific times, it may indicate:
- Rate limit resets (often at minute boundaries)
- Shared API capacity during peak hours
- Network instability
