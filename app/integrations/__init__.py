"""
External service integrations for the AI orchestrator.

These modules provide direct API access to external services, extending
the orchestrator's capabilities beyond LLM-based code generation.

Modules:
  figma          - Fetches design context from Figma URLs in Jira stories
  sentry_client  - Queries Sentry errors for AI-assisted bug remediation
  browserstack   - Runs cross-browser responsive design checks post-commit
  stripe_client  - Fetches Stripe account state (products, prices, webhooks)
  vercel_client  - Fetches Vercel project config, env vars, and build logs

Each integration is auto-activated when its credentials are set in .env.
"""
