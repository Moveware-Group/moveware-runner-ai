"""
External service integrations for the AI orchestrator.

These modules extend the orchestrator's capabilities beyond LLM-based code
generation by providing external context, notifications, and quality checks.

Modules:
  figma              - Fetches design context from Figma URLs in Jira stories
  sentry_client      - Queries Sentry errors for AI-assisted bug remediation
  browserstack       - Runs cross-browser responsive design checks post-commit
  stripe_client      - Fetches Stripe account state (products, prices, webhooks)
  vercel_client      - Injects Vercel Engineering best practices for Next.js/React
  slack_notifier     - Sends Slack notifications on task completion/failure
  github_ci          - Checks GitHub Actions CI status after push
  lighthouse         - Runs PageSpeed Insights performance audits
  npm_audit          - Scans npm dependencies for known security vulnerabilities
  playwright_runner  - Runs Playwright E2E tests for regression detection
  security_scanner   - Static security analysis (secrets, injection, XSS, config)
  semgrep_scanner    - AST-aware SAST with OWASP Top 10 data-flow analysis
  owasp_zap          - Dynamic application security testing (DAST) via ZAP proxy
  visual_testing     - Playwright screenshot-based visual regression detection

Auto-activation:
  Credentials in .env:  Figma, Sentry, BrowserStack, Stripe, Slack, ZAP
  Always on:            Vercel (Next.js projects), GitHub CI (uses GH_TOKEN),
                        Lighthouse (free API, optional key for higher limits),
                        npm audit, Security scanner, Playwright (if configured in repo),
                        Semgrep (if CLI installed),
                        Visual Testing (if Playwright pip pkg installed)
"""
