# MCP Server Integrations

This document covers the Model Context Protocol (MCP) servers configured for use with Cursor IDE and the AI orchestrator. Each server extends the AI's capabilities with direct access to external services.

## Configuration

All MCP servers are defined in `.cursor/mcp.json` at the project level. Cursor loads these automatically when opening the workspace.

### Server Types

| Server | Type | Auth | Purpose |
|--------|------|------|---------|
| **Figma** | Remote (HTTP) | OAuth | Read designs, extract layout/styling, design-to-code |
| **Sentry** | Remote (HTTP) | OAuth | Error tracking, issue analysis, remediation |
| **BrowserStack** | Local (npx) | API Key | Cross-browser testing, responsiveness, accessibility |
| **Prisma** | Local (npx) | None | Database schema management, migrations, queries |
| **Stripe** | Remote (HTTP) | OAuth | Payment processing, subscriptions, billing |
| **Vercel** | Remote (HTTP) | OAuth | Deployment management, Next.js best practices |

## Setup Instructions

### 1. Figma

**What it does:** Reads Figma designs and converts them to code context for the AI. When a Jira story includes a Figma link, the AI can extract layout, colors, typography, and component structure.

**Setup:**
1. Open Cursor and go to Settings > MCP
2. The Figma server should appear as configured
3. On first use, you'll be prompted to authorize with your Figma account
4. Grant access to the files/projects needed

**Usage in stories:** Include Figma URLs in Jira story descriptions:
```
Design: https://www.figma.com/design/abc123/ProjectName?node-id=1-234
```

### 2. Sentry

**What it does:** Connects to your Sentry organization for error ingestion, issue analysis, and AI-assisted remediation. The AI can query errors, read stack traces, and generate targeted fixes.

**Setup:**
1. Open Cursor and go to Settings > MCP
2. Click "Start" on the Sentry server
3. Authorize with your Sentry organization via OAuth
4. Select the tool groups you want to enable

**For self-hosted Sentry:** Set these environment variables instead:
```
SENTRY_ACCESS_TOKEN=sntrys_xxx
SENTRY_HOST=https://your-sentry.example.com
SENTRY_ORG=your-org
```

**Associated skill:** `sentry-integration` - Add to repos that use Sentry.

### 3. BrowserStack

**What it does:** Runs cross-browser and cross-device tests to validate responsive design, accessibility compliance, and cross-platform rendering.

**Prerequisites:**
- Node.js 18+
- BrowserStack account (https://www.browserstack.com)

**Setup:**
1. Set environment variables:
   ```
   BROWSERSTACK_USERNAME=your-username
   BROWSERSTACK_ACCESS_KEY=your-access-key
   ```
2. Restart Cursor for the MCP server to pick up credentials
3. The server runs locally via `npx @browserstack/mcp-server@latest`

**Associated skill:** `browserstack-testing` - Add to web application repos.

### 4. Prisma

**What it does:** Provides real-time database schema introspection, migration management, and SQL query execution. The AI can understand your actual database schema when making changes.

**Prerequisites:**
- Node.js 18+
- A Prisma project with `schema.prisma`

**Setup:**
1. The server runs automatically via `npx prisma mcp`
2. No additional credentials needed for local databases
3. For Prisma Postgres (cloud): Authorize via OAuth when prompted

**Associated skill:** `prisma-database` - Add to repos using Prisma ORM.

### 5. Stripe

**What it does:** Direct access to Stripe APIs for creating products, prices, customers, subscriptions, and processing payments. Also provides access to Stripe's documentation and integration best practices.

**Setup:**
1. Open Cursor and go to Settings > MCP
2. Click "Start" on the Stripe server
3. Authorize with your Stripe account via OAuth
4. For development, authorize with your **test mode** account

**Associated skill:** `stripe-payments` - Add to repos implementing payments.

**Security note:** Use test mode (`sk_test_`) during development. Never commit live Stripe keys.

### 6. Vercel

**What it does:** Integrates Vercel deployment management, project inspection, and access to Next.js/React best practices from Vercel Engineering. Can analyze deployment logs and inspect failed deployments.

**Setup:**
1. Open Cursor and go to Settings > MCP
2. Click "Start" on the Vercel server
3. Authorize with your Vercel account via OAuth

**Usage:** Useful for:
- Debugging failed deployments
- Checking build logs
- Getting framework-specific guidance
- Managing environment variables on Vercel

## Mapping Skills to Repositories

Skills are assigned per-repository in `config/repos.json`. Each skill provides context-specific instructions that are injected into the AI's prompts when working on that repository.

### Example Configuration

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

### Available Integration Skills

| Skill | Use Case |
|-------|----------|
| `sentry-integration` | Error tracking, monitoring, AI-assisted debugging |
| `browserstack-testing` | Cross-browser testing, responsive design validation |
| `prisma-database` | Database schema design, migrations, query patterns |
| `stripe-payments` | Payment gateway, subscriptions, webhook handling |

### Pre-existing Skills

| Skill | Use Case |
|-------|----------|
| `nextjs-fullstack-dev` | Next.js App Router, Server Components, React patterns |
| `flutter-dev` | Flutter/Dart mobile app development |
| `nodejs-api-dev` | Node.js/Express REST API development |
| `python-dev` | Python with FastAPI, type hints, async patterns |
| `qa-tester` | Playwright E2E testing, test strategy |
| `security-tester` | OWASP, security reviews, vulnerability assessment |

## AI Orchestrator Integration

The MCP servers are primarily consumed through Cursor IDE during interactive development sessions. For the server-side AI orchestrator (`app/main.py` + `app/worker.py`), integration happens through:

1. **Skills** - The orchestrator loads skill content via `app/skill_loader.py` and injects it into LLM prompts, giving the AI knowledge of Sentry, Stripe, Prisma, and BrowserStack patterns
2. **Direct API calls** - For runtime integrations (e.g., Sentry error capture in production), add the relevant SDK to `requirements.txt` and configure in `app/config.py`
3. **Figma URLs in stories** - When Jira stories contain Figma links, the executor can reference design specifications from the story description

## Troubleshooting

### Server not appearing in Cursor
1. Restart Cursor completely (not just reload window)
2. Check `.cursor/mcp.json` syntax is valid JSON
3. For local servers (BrowserStack, Prisma), ensure Node.js 18+ is installed

### OAuth authorization fails
1. Check you're logged into the correct organization
2. Try revoking and re-authorizing the connection
3. For Sentry/Stripe, check your account has the necessary permissions

### BrowserStack tests fail to connect
1. Verify `BROWSERSTACK_USERNAME` and `BROWSERSTACK_ACCESS_KEY` are set
2. Check your BrowserStack plan has available parallel sessions
3. Ensure network connectivity to BrowserStack's cloud
