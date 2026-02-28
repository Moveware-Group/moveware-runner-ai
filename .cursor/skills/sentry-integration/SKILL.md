---
name: sentry-integration
description: Sentry error tracking integration for monitoring, log ingestion, and automated issue remediation. Use when setting up error tracking, debugging production issues, or when Sentry is mentioned.
---

# Sentry Integration

## Overview

Sentry provides real-time error tracking and performance monitoring. This skill covers integration patterns for both Next.js and Python backends, plus how to use Sentry's MCP server for AI-assisted remediation.

## MCP Server (Cursor IDE)

The Sentry MCP server is configured at `.cursor/mcp.json`. On first use, Cursor will prompt OAuth login to your Sentry organization.

**Available MCP tools:**
- List and search issues/errors across projects
- Get issue details, stack traces, and breadcrumbs
- Analyze error trends and frequency
- Access Sentry's Seer AI analysis for root cause suggestions
- List projects, teams, and organization data

## Next.js Integration

### Setup

```bash
npx @sentry/wizard@latest -i nextjs
```

This auto-generates `sentry.client.config.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts`, and updates `next.config.js`.

### Configuration

```typescript
// sentry.client.config.ts
import * as Sentry from "@sentry/nextjs"

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
  replaysSessionSampleRate: 0.1,
  replaysOnErrorSampleRate: 1.0,
  integrations: [
    Sentry.replayIntegration(),
    Sentry.browserTracingIntegration(),
  ],
})
```

### Error Boundaries

```tsx
"use client"
import * as Sentry from "@sentry/nextjs"

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  Sentry.captureException(error)

  return (
    <html>
      <body>
        <h2>Something went wrong</h2>
        <button onClick={() => reset()}>Try again</button>
      </body>
    </html>
  )
}
```

### API Route Instrumentation

```typescript
// app/api/example/route.ts
import * as Sentry from "@sentry/nextjs"

export async function GET(request: Request) {
  return Sentry.withServerActionInstrumentation(
    "GET /api/example",
    async () => {
      try {
        const data = await fetchData()
        return Response.json(data)
      } catch (error) {
        Sentry.captureException(error, {
          tags: { endpoint: "/api/example" },
          extra: { url: request.url },
        })
        return Response.json({ error: "Internal error" }, { status: 500 })
      }
    }
  )
}
```

## Python/FastAPI Integration

### Setup

```bash
pip install sentry-sdk[fastapi]
```

### Configuration

```python
import sentry_sdk

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("ENVIRONMENT", "development"),
    traces_sample_rate=0.1,
    profiles_sample_rate=0.1,
    send_default_pii=False,
)
```

FastAPI integration is auto-detected. All unhandled exceptions are captured automatically.

### Manual Capture

```python
import sentry_sdk

try:
    result = risky_operation()
except Exception as e:
    sentry_sdk.capture_exception(e)
    sentry_sdk.set_context("operation", {"input": sanitized_input})
    raise
```

## AI-Assisted Remediation Pattern

When the orchestrator encounters an error:

1. **Capture** - Sentry captures the error with full stack trace and context
2. **Query via MCP** - Use the Sentry MCP to fetch issue details, affected users, frequency
3. **Analyze** - Feed the error context + stack trace into the LLM for root cause analysis
4. **Fix** - Generate a targeted fix based on the analysis
5. **Verify** - Build and test the fix before committing

## Environment Variables

```
NEXT_PUBLIC_SENTRY_DSN=https://xxx@oXXX.ingest.sentry.io/XXX
SENTRY_AUTH_TOKEN=sntrys_xxx
SENTRY_ORG=your-org
SENTRY_PROJECT=your-project
```

## Best Practices

1. **Set sampling rates** - Don't send 100% of transactions in production
2. **Use breadcrumbs** - Add context before errors for better debugging
3. **Sanitize PII** - Never send passwords, tokens, or personal data
4. **Tag errors** - Use tags for filtering (e.g., `user_tier`, `feature_flag`)
5. **Source maps** - Upload source maps during build for readable stack traces
6. **Alert rules** - Configure alerts for new issues and regressions
