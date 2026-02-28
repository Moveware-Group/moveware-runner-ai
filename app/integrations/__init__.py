"""
External service integrations for the AI orchestrator.

These modules extend the orchestrator's capabilities beyond LLM-based code
generation by providing external context during execution.

Modules:
  figma          - Fetches design context from Figma URLs in Jira stories
  sentry_client  - Queries Sentry errors for AI-assisted bug remediation
  browserstack   - Runs cross-browser responsive design checks post-commit
  stripe_client  - Fetches Stripe account state (products, prices, webhooks)
  vercel_client  - Injects Vercel Engineering best practices for Next.js/React

API-based modules (Figma, Sentry, BrowserStack, Stripe) auto-activate when
credentials are set in .env. Vercel activates automatically for Next.js projects.
"""
