# External Service Integrations

This document covers the external service integrations built into the AI orchestrator (`app/main.py` + `app/worker.py`). These extend the orchestrator's capabilities with design context, error tracking, cross-browser testing, and framework-specific knowledge.

## Architecture

Integrations work at two levels:

1. **Python API modules** (`app/integrations/`) - Direct API calls to external services during execution. Auto-activated when credentials are configured in `.env`.
2. **AI Skills** (`.cursor/skills/`) - Framework-specific knowledge injected into LLM prompts via `skill_loader.py`, giving the AI patterns and best practices for each service.

### Integration Summary

| Service | API Module | Skill | Activation |
|---------|-----------|-------|------------|
| **Figma** | `app/integrations/figma.py` | - | `FIGMA_ACCESS_TOKEN` |
| **Sentry** | `app/integrations/sentry_client.py` | `sentry-integration` | `SENTRY_ACCESS_TOKEN` + `SENTRY_ORG` |
| **BrowserStack** | `app/integrations/browserstack.py` | `browserstack-testing` | `BROWSERSTACK_USERNAME` + `BROWSERSTACK_ACCESS_KEY` |
| **Prisma** | - (via skill + npx) | `prisma-database` | Skill added to repo config |
| **Stripe** | - (via skill) | `stripe-payments` | Skill added to repo config |
| **Vercel** | - (via skill) | - | Next.js skill covers patterns |

## API Integrations (Python Modules)

### Figma (`app/integrations/figma.py`)

**What it does:** When a Jira story description contains a Figma URL, the orchestrator automatically fetches design context (colors, fonts, dimensions, component structure, layout) and injects it into the LLM prompt. This gives the AI precise design specs when generating UI code.

**How it works:**
1. Executor scans issue description for Figma URLs (`figma.com/design/...`)
2. Extracts file key and node ID from the URL
3. Calls Figma REST API to get the node tree
4. Parses colors, fonts, components, and layout structure
5. Formats as context and appends to the LLM prompt

**Setup:**
```bash
# In .env
FIGMA_ACCESS_TOKEN=figd_xxx
```
Generate a Personal Access Token at: https://www.figma.com/developers/api#access-tokens

**Usage in Jira stories:**
```
Design: https://www.figma.com/design/abc123/ProjectName?node-id=1-234
```

### Sentry (`app/integrations/sentry_client.py`)

**What it does:** When the AI processes a bug-fix task, it queries Sentry for related errors, providing the LLM with actual stack traces, breadcrumbs, and error frequency. This enables targeted root-cause fixes rather than guesswork.

**How it works:**
1. Executor checks issue description for Sentry references (`SENTRY-123`, Sentry URLs)
2. Fetches issue details including latest event's stack trace and breadcrumbs
3. If no explicit reference but project is known, searches for matching unresolved errors
4. Injects error context into the LLM prompt

**Setup:**
```bash
# In .env
SENTRY_ACCESS_TOKEN=sntrys_xxx
SENTRY_HOST=https://sentry.io
SENTRY_ORG=your-org-slug
```

**Referencing Sentry in Jira stories:**
```
Bug: Users see a 500 error on the dashboard
Sentry: https://your-org.sentry.io/issues/12345/
```

### BrowserStack (`app/integrations/browserstack.py`)

**What it does:** After the AI commits UI changes, the verifier can run BrowserStack screenshot tests across multiple browsers and devices to catch responsive design issues. Results are reported as Jira comments.

**How it works:**
1. Verifier detects UI-related file changes (`.tsx`, `.jsx`, `.css`)
2. Submits screenshot requests to BrowserStack for multiple viewports
3. Polls for completion and collects screenshot URLs
4. Reports pass/fail per viewport in the Jira comment

**Setup:**
```bash
# In .env
BROWSERSTACK_USERNAME=your-username
BROWSERSTACK_ACCESS_KEY=your-access-key
```

**Note:** BrowserStack checks run as warnings (non-blocking) since they require a publicly accessible URL. Most useful for staging/preview deployments.

## Skill-Based Integrations (Prompt Injection)

These services are integrated through AI skills - markdown files loaded by `skill_loader.py` and injected into LLM prompts. The AI uses this knowledge to generate correct implementation patterns.

### Prisma Database (`prisma-database`)

Provides schema design conventions, migration workflows, query patterns, and Prisma Client best practices. The executor already runs `npx prisma` commands as part of its subprocess toolkit.

### Stripe Payments (`stripe-payments`)

Covers Checkout integration, webhook handling, subscription management, Customer Portal, and PCI compliance patterns. The AI generates correct Stripe code using these patterns.

### Sentry Integration (`sentry-integration`)

Complements the API module with implementation patterns: Next.js/Python SDK setup, error boundaries, API route instrumentation, and breadcrumb configuration.

### BrowserStack Testing (`browserstack-testing`)

Complements the API module with responsive testing patterns: viewport configurations, Playwright integration, accessibility scanning, and cross-browser test matrices.

## Mapping Skills to Repositories

Skills are assigned per-repository in `config/repos.json`:

```json
{
  "projects": [
    {
      "jira_project_key": "OD",
      "repo_name": "online-docs",
      "skills": [
        "nextjs-fullstack-dev",
        "prisma-database",
        "stripe-payments",
        "sentry-integration",
        "browserstack-testing"
      ]
    }
  ]
}
```

### All Available Skills

| Skill | Use Case |
|-------|----------|
| `nextjs-fullstack-dev` | Next.js App Router, Server Components, React patterns |
| `flutter-dev` | Flutter/Dart mobile app development |
| `nodejs-api-dev` | Node.js/Express REST API development |
| `python-dev` | Python with FastAPI, type hints, async patterns |
| `qa-tester` | Playwright E2E testing, test strategy |
| `security-tester` | OWASP, security reviews, vulnerability assessment |
| `sentry-integration` | Error tracking, monitoring, AI-assisted debugging |
| `browserstack-testing` | Cross-browser testing, responsive design validation |
| `prisma-database` | Database schema design, migrations, query patterns |
| `stripe-payments` | Payment gateway, subscriptions, webhook handling |

## Execution Flow

```
Jira Story arrives → Worker claims run
  ↓
Executor loads repo context + skills
  ↓
Figma: Scan description for Figma URLs → fetch design context
Sentry: Scan for Sentry refs → fetch error details
  ↓
Build LLM prompt with all context (skills + Figma + Sentry + repo)
  ↓
Claude generates implementation
  ↓
Verifier runs checks (TypeScript, ESLint, tests)
  ↓
BrowserStack: If UI files changed → screenshot responsive check
  ↓
Commit, push, create PR → report to Jira
```

## Troubleshooting

### Figma context not loading
1. Check `FIGMA_ACCESS_TOKEN` is set in `.env`
2. Ensure the token has access to the file (check sharing permissions)
3. Look for `🎨 Figma design context loaded` or error messages in worker logs

### Sentry context not loading
1. Verify `SENTRY_ACCESS_TOKEN`, `SENTRY_ORG`, and `SENTRY_HOST` are set
2. Token needs `event:read`, `project:read`, `org:read` scopes
3. Look for `🐛 Sentry error context loaded` in worker logs

### BrowserStack tests not running
1. Verify `BROWSERSTACK_USERNAME` and `BROWSERSTACK_ACCESS_KEY` are set
2. Check your BrowserStack plan has available parallel sessions
3. The tested URL must be publicly accessible (or use BrowserStack Local)

### Skills not loading
1. Skill names in `repos.json` must match folder names in `.cursor/skills/`
2. Check worker logs for `Skill not found: <name>` messages
3. Verify `SKILL.md` exists in the skill directory
