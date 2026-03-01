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
| **Stripe** | `app/integrations/stripe_client.py` | `stripe-payments` | `STRIPE_SECRET_KEY` |
| **Vercel** | `app/integrations/vercel_client.py` | - | Auto (detects Next.js projects) |
| **npm audit** | `app/integrations/npm_audit.py` | - | Auto (any Node.js project) |
| **Playwright** | `app/integrations/playwright_runner.py` | `qa-tester` | Auto (if `playwright.config` in repo) |
| **Security Scanner** | `app/integrations/security_scanner.py` | `security-tester` | Always on (all commits) |
| **Semgrep SAST** | `app/integrations/semgrep_scanner.py` | `security-tester` | Auto (if `semgrep` CLI installed) |
| **OWASP ZAP DAST** | `app/integrations/owasp_zap.py` | `security-tester` | `ZAP_API_URL` (+ Docker daemon) |
| **Prisma** | - (via skill + npx) | `prisma-database` | Skill added to repo config |

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

### Stripe (`app/integrations/stripe_client.py`)

**What it does:** When a Jira story involves payment functionality (detected by keywords like "payment", "checkout", "subscription", "stripe"), the executor fetches the actual Stripe account state - products, prices, webhook endpoints, and customer portal config. This gives Claude the real product/price IDs to reference in generated code.

**How it works:**
1. Executor scans issue summary and description for payment-related keywords
2. Calls the Stripe API to list products, prices, webhook endpoints, and portal config
3. Formats the account state (IDs, amounts, currencies, intervals) as LLM context
4. Claude uses the real IDs in generated code instead of placeholder values

**Setup:**
```bash
# In .env - use test key for development, live key for production
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx  # optional, for webhook validation
```

Generate keys at: https://dashboard.stripe.com/apikeys

**Security note:** Always use `sk_test_` keys during development. The orchestrator never exposes the secret key to the LLM - only the resulting account data (product names, price IDs, etc).

### Vercel (`app/integrations/vercel_client.py`)

**What it does:** Injects Vercel Engineering best practices for Next.js and React projects. This covers App Router patterns, Server Components, data fetching strategies, performance optimization, security, metadata/SEO, and project structure conventions. No API token needed - it auto-detects Next.js projects.

**How it works:**
1. Executor checks if the project is Next.js/React via:
   - Skills list containing `nextjs-fullstack-dev`
   - Next.js config files in the repo (`next.config.js`, `app/layout.tsx`, etc.)
   - Keywords in the task description (`next.js`, `server component`, `app router`, etc.)
2. If detected, injects a comprehensive best-practice reference into the LLM prompt

**Setup:** None required - activates automatically for Next.js/React projects.

**What the AI gets:**
- App Router and Server Component patterns (when to use `"use client"` vs server)
- Data fetching strategies (SSG, ISR, dynamic, Server Actions)
- Performance rules (`next/image`, `next/font`, `next/link`, dynamic imports)
- Metadata/SEO API usage
- API Routes and Server Actions conventions
- Middleware and authentication patterns
- TypeScript and Zod validation patterns
- Project structure recommendations
- Common anti-patterns to avoid

### npm audit (`app/integrations/npm_audit.py`)

**What it does:** After `npm install`, runs `npm audit` to detect known security vulnerabilities in dependencies. Reports severity-classified findings (critical, high, moderate, low) as Jira comments and provides context for the LLM. Automatically runs `npm audit fix` for safe, non-breaking fixes.

**How it works:**
1. After `npm install` succeeds, runs `npm audit fix` (safe patches only)
2. Then runs `npm audit --json` for a full vulnerability report
3. Parses severity levels and affected packages
4. Critical/high findings are reported in Jira and injected into LLM context
5. Post-push: a summary of remaining vulnerabilities is attached to the Jira comment

**Setup:** None required — uses npm's built-in advisory database.

**What gets reported:**
- Total vulnerability count by severity (critical, high, moderate, low)
- Package name, advisory title, and fix availability for critical/high issues
- Advisory URLs for manual review

### Playwright E2E Tests (`app/integrations/playwright_runner.py`)

**What it does:** Executes the target repo's Playwright E2E test suite after code changes. Catches functional regressions before the PR is created. Failed test details (test name, error message, code snippet) are fed back to the LLM self-healing loop.

**How it works:**
1. Detects `playwright.config.ts` (or `.js`/`.mjs`) in the repo
2. Identifies test directories (`tests/`, `e2e/`, `test/`)
3. Finds tests related to changed source files by name matching
4. Runs Playwright with `--reporter json` for structured output
5. Parses pass/fail/skip counts and failure details
6. Failed tests trigger the self-healing loop; results are reported to Jira

**Setup:** The target repository must have Playwright installed:
```bash
npm install -D @playwright/test
npx playwright install chromium
```

**Integration points:**
- **Pre-commit:** Runs as part of `run_all_verifications()` — test failures block the commit
- **Post-push:** Runs independently and reports to Jira as an informational comment
- **Self-healing:** Test failures are formatted as LLM context so Claude can fix the implementation (not the tests)

### Security Scanner (`app/integrations/security_scanner.py`)

**What it does:** Static analysis of changed files for common security vulnerabilities. Scans for hardcoded secrets, injection patterns (SQL, XSS, command), insecure configurations, weak cryptography, and OWASP-style issues. Critical findings (e.g., exposed API keys) block the commit.

**How it works:**
1. Runs as a pre-commit check in the verification pipeline
2. Scans only the files changed by the AI (not the whole codebase)
3. Applies regex-based rules across multiple categories
4. Filters false positives (test files, examples, env var references)
5. Reports findings by severity: critical (blocking), high, medium, low (warnings)

**Setup:** None required — runs automatically on every commit.

**Security categories checked:**
| Category | Severity | Examples |
|----------|----------|---------|
| Hardcoded Secrets | Critical | API keys, tokens, private keys in source |
| Stripe/AWS/GitHub Keys | Critical | Specific key pattern detection |
| SQL Injection | High | String interpolation in queries |
| XSS (innerHTML) | High | Dynamic innerHTML without sanitization |
| Command Injection | High | Shell exec with string concatenation |
| eval() usage | High | Dynamic code execution |
| Insecure Randomness | High | Math.random() for tokens |
| TLS Disabled | High | Certificate verification turned off |
| Weak Hashing | Medium | MD5/SHA1 for passwords |
| Insecure Cookies | Medium | Missing httpOnly/secure flags |
| CORS Wildcard | Medium | `Access-Control-Allow-Origin: *` |
| Debug Mode | Low | Debug flags enabled |

### Semgrep SAST (`app/integrations/semgrep_scanner.py`)

**What it does:** Runs Semgrep's AST-aware static analysis to detect OWASP Top 10 vulnerabilities with data-flow tracking, cross-file analysis, and framework-specific rules. Unlike the regex-based security scanner, Semgrep understands code structure — it tracks tainted data from user inputs through variable assignments and function calls to dangerous sinks (SQL queries, HTML rendering, shell commands).

**How it works:**
1. Checks if the `semgrep` CLI is installed
2. If `SEMGREP_APP_TOKEN` is set, uses the Pro engine with full OWASP rule coverage
3. Otherwise, uses the open-source engine with community rules (`--config auto`)
4. Scans only the changed files (not the whole repo) for fast feedback
5. Parses JSON output with OWASP/CWE tags, severity levels, and fix suggestions
6. ERROR-level findings block the commit; warnings are reported to Jira

**Setup:**
```bash
# Install the CLI (Python 3.9+)
pip install semgrep

# (Optional) For full Pro OWASP coverage, sign up free at https://semgrep.dev
# Then set in .env:
SEMGREP_APP_TOKEN=your-token-here
```

**What Semgrep catches that regex scanners miss:**
- Taint tracking: user input flowing through 5+ function calls into a SQL query
- Framework-aware: knows that `req.body` in Express, `request.form` in Flask, and `searchParams` in Next.js are user-controlled
- Cross-file: import chains where a util function wraps an unsafe operation
- Constant propagation: detects when a "constant" is actually derived from user input
- Type-aware: distinguishes `innerHTML` on a trusted element vs. user-controlled content

**OWASP coverage:**
| OWASP Category | Examples |
|----------------|----------|
| A01: Broken Access Control | Missing auth checks, IDOR, path traversal |
| A02: Cryptographic Failures | Weak algorithms, hardcoded keys, insecure random |
| A03: Injection | SQL, NoSQL, LDAP, OS command, XSS |
| A04: Insecure Design | Mass assignment, race conditions |
| A05: Security Misconfiguration | Debug mode, permissive CORS, insecure headers |
| A06: Vulnerable Components | (handled by npm audit) |
| A07: Auth Failures | Weak passwords, missing rate limiting |
| A08: Data Integrity | Deserialization, unsigned updates |
| A09: Logging Failures | Sensitive data in logs |
| A10: SSRF | Unvalidated URL fetching |

### OWASP ZAP DAST (`app/integrations/owasp_zap.py`)

**What it does:** Dynamic Application Security Testing — ZAP acts as an attacker, actively probing the running application for vulnerabilities that static analysis cannot detect. It crawls pages, submits forms with injection payloads, tests authentication flows, and checks for XSS, CSRF, insecure headers, and session management issues.

**How it works:**
1. ZAP runs as a daemon (Docker container recommended)
2. The orchestrator sends API requests to ZAP's REST API
3. **Baseline scan (passive):** Spiders the target and applies passive rules — safe for production
4. **Active scan:** Sends injection probes, fuzzes parameters — staging/preview only
5. **API scan:** Imports OpenAPI/Swagger spec and tests all endpoints with proper parameter types
6. Alerts are classified by risk (High, Medium, Low, Informational) with CWE IDs
7. High-risk findings are reported to Jira with fix recommendations

**Setup:**
```bash
# Start ZAP in daemon mode via Docker
docker run -u zap -p 8080:8080 -d zaproxy/zap-stable \
  zap.sh -daemon -host 0.0.0.0 -port 8080 \
  -config api.addrs.addr.name=.* -config api.addrs.addr.regex=true

# In .env
ZAP_API_URL=http://localhost:8080
# ZAP_API_KEY=your-api-key  # Optional, for authenticated access
```

**Scan types:**
| Type | Duration | Safe for Prod | What it does |
|------|----------|---------------|-------------|
| Baseline | 1-2 min | Yes | Spider + passive rules (headers, cookies, info leaks) |
| Active | 5-15 min | No | Injection probes, parameter fuzzing, auth testing |
| API | 5-15 min | No | OpenAPI-driven endpoint testing with typed parameters |

**What ZAP catches that static analysis misses:**
- Missing HTTP security headers (CSP, HSTS, X-Frame-Options)
- Insecure cookie flags in the actual HTTP response
- CSRF vulnerabilities in real form submissions
- Open redirects that only manifest at runtime
- Session fixation and management issues
- Actual XSS that bypasses server-side sanitization
- Information disclosure in error pages
- Server misconfiguration (directory listing, debug endpoints)

**Note:** The baseline scan is non-blocking (warnings only). Active scan high-risk findings block the commit. ZAP requires a reachable URL — most useful with staging/preview deployments.

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
Auto-detect & fetch external context:
  Figma:       Scan description for Figma URLs → fetch design specs
  Sentry:      Scan for Sentry refs → fetch stack traces & breadcrumbs
  Stripe:      Detect payment keywords → fetch products, prices, webhooks
  Vercel:      Detect Next.js project → inject best practices
  ↓
Build LLM prompt (skills + Figma + Sentry + Stripe + Vercel + security rules + repo)
  ↓
Claude generates implementation
  ↓
PRE-COMMIT VERIFICATION:
  Security scanner:  Regex-based static analysis for secrets, injection, XSS
  Semgrep SAST:      AST-aware analysis with OWASP Top 10 data-flow tracking
  Package.json:      JSON syntax check
  TypeScript:        tsc --noEmit type checking
  ESLint:            Code style and potential bugs
  Import resolution: Relative import path validation
  ↓
BUILD VERIFICATION:
  npm install →  npm audit fix + npm audit (vulnerability report)
  tsc --noEmit → npm run build
  ↓ (if build fails, self-healing loop with up to 7 LLM fix attempts)
  ↓
POST-BUILD CHECKS:
  Playwright E2E:  Run repo's test suite → failures feed self-healing loop
  npm audit:       Report remaining vulnerabilities to Jira
  ↓
Commit, push → GitHub CI check
  ↓
POST-PUSH CHECKS (non-blocking):
  GitHub Actions:  Check CI status
  Semgrep SAST:    Full security scan report for Jira
  Playwright E2E:  Full regression test report for Jira
  npm audit:       Dependency vulnerability report
  BrowserStack:    Screenshot responsive check (if UI files changed)
  Lighthouse:      Performance audit (if deployed URL available)
  OWASP ZAP:       Dynamic security scan (if ZAP configured + deployed URL)
  ↓
Create PR → report to Jira (with all check results)
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

### Stripe context not loading
1. Verify `STRIPE_SECRET_KEY` is set in `.env`
2. Use `sk_test_` keys for development environments
3. Look for `💳 Stripe account context loaded` in worker logs
4. Ensure the key has read access to products, prices, and webhook endpoints

### Vercel best practices not injecting
1. Ensure the repo has `nextjs-fullstack-dev` in its skills list in `repos.json`
2. Or ensure the repo has `next.config.js` / `app/layout.tsx` present
3. Look for `▲ Vercel best practices injected` in worker logs

### npm audit not reporting
1. Ensure `node_modules/` exists (runs after `npm install`)
2. Check worker logs for `npm audit:` messages
3. Low/moderate vulnerabilities are logged but don't appear in Jira unless critical/high

### Playwright tests not running
1. Ensure the target repo has `playwright.config.ts` (or `.js`/`.mjs`)
2. Playwright must be installed: `npm i -D @playwright/test`
3. Browsers must be installed: `npx playwright install chromium`
4. Check worker logs for `Running Playwright E2E` messages
5. If "no tests found" — ensure tests are in `tests/`, `e2e/`, or `test/` directories

### Semgrep not running
1. Ensure the CLI is installed: `pip install semgrep` (requires Python 3.9+)
2. Run `semgrep --version` to verify it's on the PATH
3. For full OWASP coverage, set `SEMGREP_APP_TOKEN` in `.env` (free at https://semgrep.dev)
4. Check worker logs for `Running Semgrep SAST scan` messages
5. If scanning is slow on large repos, Semgrep may need more memory — check for timeout messages

### OWASP ZAP not scanning
1. Ensure ZAP daemon is running: `docker ps | grep zap`
2. Test reachability: `curl http://localhost:8080/JSON/core/view/version/`
3. Verify `ZAP_API_URL` in `.env` matches the ZAP daemon address
4. If using `ZAP_API_KEY`, ensure it matches the daemon's API key config
5. The target URL must be reachable from the ZAP container (use `--network host` if needed)
6. Check worker logs for `Running OWASP ZAP` messages

### Security scanner false positives
1. Test/mock files with fake secrets are automatically excluded
2. Environment variable references (`process.env.X`) are excluded
3. Type definition files (`.d.ts`) are excluded
4. If persistent false positives occur, add patterns to `_is_likely_false_positive()` in `security_scanner.py`

### Skills not loading
1. Skill names in `repos.json` must match folder names in `.cursor/skills/`
2. Check worker logs for `Skill not found: <name>` messages
3. Verify `SKILL.md` exists in the skill directory
