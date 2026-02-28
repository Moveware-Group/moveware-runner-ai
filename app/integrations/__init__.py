"""
External service integrations for the AI orchestrator.

These modules extend the orchestrator's capabilities beyond LLM-based code
generation by providing external context, notifications, and quality checks.

Modules:
  figma           - Fetches design context from Figma URLs in Jira stories
  sentry_client   - Queries Sentry errors for AI-assisted bug remediation
  browserstack    - Runs cross-browser responsive design checks post-commit
  stripe_client   - Fetches Stripe account state (products, prices, webhooks)
  vercel_client   - Injects Vercel Engineering best practices for Next.js/React
  slack_notifier  - Sends Slack notifications on task completion/failure
  github_ci       - Checks GitHub Actions CI status after push
  lighthouse      - Runs PageSpeed Insights performance audits

Auto-activation:
  Credentials in .env:  Figma, Sentry, BrowserStack, Stripe, Slack
  Always on:            Vercel (Next.js projects), GitHub CI (uses GH_TOKEN),
                        Lighthouse (free API, optional key for higher limits)
"""
