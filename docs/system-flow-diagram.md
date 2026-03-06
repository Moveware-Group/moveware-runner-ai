# AI Orchestrator — System Flow Diagrams

Complete system architecture and workflow diagrams for the Moveware AI Runner.

---

## 1. End-to-End System Overview

```mermaid
flowchart TB
    subgraph JIRA["☁️ Jira Cloud"]
        J1[Epic created in Backlog]
        J2[Human reviews plan]
        J3[Human approves Epic]
        J4[Stories created automatically]
        J5[Subtasks created automatically]
        J6[Human reviews in Testing]
        J7[Human requests Rework]
    end

    subgraph WEBHOOK["🔗 Webhook Layer"]
        W1["POST /webhook/jira<br/>(secret verified)"]
        W2["POST /api/trigger<br/>(manual)"]
    end

    subgraph QUEUE["📋 Queue & Worker"]
        Q1[enqueue_run → DB]
        Q2[Worker poll loop<br/>every 2s]
        Q3[claim_next_run_smart<br/>priority + conflict avoidance]
        Q4["Router.decide(issue)"]
    end

    subgraph PLAN["📝 Planning Phase"]
        P1[PLAN_EPIC<br/>LLM generates plan]
        P2[Post plan to Jira]
        P3[REVISE_PLAN<br/>incorporate feedback]
        P4[EPIC_APPROVED<br/>create Stories]
    end

    subgraph STORY["📖 Story Phase"]
        S1[STORY_APPROVED<br/>create subtasks]
        S2["Create story/ branch"]
        S3[Enqueue first subtask]
        S4[CHECK_STORY_COMPLETION]
        S5[Story → In Testing]
    end

    subgraph EXEC["⚙️ Execution Phase"]
        E1[Checkout repo + branch]
        E2[Gather context<br/>repo + integrations]
        E3[Build LLM prompt]
        E4[Claude generates code]
        E5[Apply file changes]
    end

    subgraph VERIFY["🔍 Verification Phase"]
        V1[Pre-commit checks]
        V2[Build verification]
        V3[Self-healing loop<br/>up to 7 attempts]
        V4[Post-build checks]
    end

    subgraph GIT["🔀 Git & GitHub"]
        G1[Create rollback tag]
        G2[git add + commit]
        G3[git push origin]
        G4[Create/update PR]
        G5[Post-push checks]
    end

    subgraph NOTIFY["📢 Notifications"]
        N1[Jira comment<br/>completion summary]
        N2[Slack notification]
        N3[Next subtask auto-start]
    end

    J1 --> W1
    W1 --> Q1
    W2 --> Q1
    Q1 --> Q2
    Q2 --> Q3
    Q3 --> Q4

    Q4 -->|Epic in Backlog| P1
    Q4 -->|Epic in Plan Review| P3
    Q4 -->|Epic Approved| P4
    Q4 -->|Story Approved| S1
    Q4 -->|Subtask| E1
    Q4 -->|Subtask Done| S4

    P1 --> P2
    P2 -->|"Backlog → Plan Review"| J2
    J2 -->|Feedback| P3
    J2 -->|Approve| J3
    J3 --> P4
    P4 --> J4

    J4 --> S1
    S1 --> S2
    S2 --> S3
    S3 --> J5

    J5 --> E1
    E1 --> E2
    E2 --> E3
    E3 --> E4
    E4 --> E5
    E5 --> V1
    V1 --> V2
    V2 -->|Build fails| V3
    V3 -->|Fixed| V2
    V3 -->|Exhausted| N1
    V2 -->|Build passes| V4
    V4 --> G1
    G1 --> G2
    G2 --> G3
    G3 --> G4
    G4 --> G5
    G5 --> N1
    N1 --> N2
    N2 --> N3

    N3 -->|Next subtask| E1
    N3 -->|All done| S4
    S4 --> S5
    S5 --> J6
    J6 -->|Rework needed| J7
    J7 --> E1

    style JIRA fill:#e3f2fd,stroke:#1565c0
    style WEBHOOK fill:#fff3e0,stroke:#e65100
    style QUEUE fill:#f3e5f5,stroke:#6a1b9a
    style PLAN fill:#e8f5e9,stroke:#2e7d32
    style STORY fill:#fff8e1,stroke:#f9a825
    style EXEC fill:#fce4ec,stroke:#c62828
    style VERIFY fill:#e0f7fa,stroke:#00838f
    style GIT fill:#f1f8e9,stroke:#558b2f
    style NOTIFY fill:#ede7f6,stroke:#4527a0
```

---

## 2. Jira Status Transitions

```mermaid
stateDiagram-v2
    [*] --> Backlog: Epic/Story created

    state "Epic Flow" as epic {
        Backlog --> PlanReview: AI generates plan
        PlanReview --> PlanReview: Human requests revision
        PlanReview --> InProgress_E: Human approves → Stories created
        InProgress_E --> Done_E: All Stories completed
        Backlog --> Blocked_E: Planning error
    }

    state "Story Flow" as story {
        Backlog_S --> SelectedForDev: Auto-start or manual
        SelectedForDev --> InProgress_S: AI creates subtasks + branch
        InProgress_S --> InTesting_S: All subtasks done
        InTesting_S --> NeedsRework_S: Human finds issues
        NeedsRework_S --> InProgress_S: AI processes rework
        InTesting_S --> Done_S: Human approves
    }

    state "Subtask Flow" as subtask {
        InProgress_ST --> InTesting_ST: AI implements + pushes
        InTesting_ST --> NeedsRework_ST: Human finds issues
        NeedsRework_ST --> InProgress_ST: AI reworks code
        InTesting_ST --> Done_ST: Human approves
        InProgress_ST --> Blocked_ST: Execution error
        Blocked_ST --> InProgress_ST: Retry
    }
```

---

## 3. Subtask Execution Pipeline (Detailed)

```mermaid
flowchart TB
    START([Subtask claimed by Worker]) --> BRANCH

    subgraph CHECKOUT["1. Repository Setup"]
        BRANCH[Checkout repo]
        BRANCH --> DECIDE_BRANCH{Independent<br/>subtask?}
        DECIDE_BRANCH -->|Yes| AI_BRANCH["Branch: ai/{ISSUE-KEY}"]
        DECIDE_BRANCH -->|No| STORY_BRANCH["Branch: story/{PARENT-KEY}"]
    end

    subgraph CONTEXT["2. Context Gathering"]
        AI_BRANCH --> CTX_REPO["Repo context<br/>(git log, structure,<br/>package.json, relevant files)"]
        STORY_BRANCH --> CTX_REPO
        CTX_REPO --> CTX_SKILLS["Load AI skills<br/>(nextjs, prisma, stripe, etc.)"]
        CTX_SKILLS --> CTX_COMMENTS["Human comments<br/>from Jira"]
        CTX_COMMENTS --> CTX_INTEGRATIONS
    end

    subgraph INTEGRATIONS["3. External Context (Auto-detected)"]
        CTX_INTEGRATIONS["Check integrations"]
        CTX_INTEGRATIONS --> FIGMA["🎨 Figma<br/>Design specs from URLs"]
        CTX_INTEGRATIONS --> SENTRY["🐛 Sentry<br/>Stack traces for bugs"]
        CTX_INTEGRATIONS --> STRIPE["💳 Stripe<br/>Products, prices, webhooks"]
        CTX_INTEGRATIONS --> VERCEL["▲ Vercel<br/>Next.js best practices"]
    end

    subgraph GENERATE["4. Code Generation"]
        FIGMA --> BUILD_PROMPT
        SENTRY --> BUILD_PROMPT
        STRIPE --> BUILD_PROMPT
        VERCEL --> BUILD_PROMPT
        BUILD_PROMPT["Build LLM prompt<br/>(context + task + security rules)"]
        BUILD_PROMPT --> CLAUDE["☁️ Claude API call<br/>JSON response with files"]
        CLAUDE --> PARSE["Parse response<br/>implementation_plan, files[], summary"]
        PARSE --> APPLY["Apply file changes<br/>(create / update / delete)"]
    end

    subgraph PREVERIFY["5. Pre-Commit Verification"]
        APPLY --> PKG_JSON["📦 Package.json syntax"]
        PKG_JSON --> SEC_SCAN["🔒 Security scanner<br/>(regex: secrets, injection, XSS)"]
        SEC_SCAN --> SEMGREP["🛡️ Semgrep SAST<br/>(AST: OWASP data-flow)"]
        SEMGREP --> TSC["📘 TypeScript check<br/>(tsc --noEmit)"]
        TSC --> ESLINT["📏 ESLint"]
        ESLINT --> IMPORTS["📂 Import resolution"]
    end

    subgraph BUILD["6. Build Verification"]
        IMPORTS --> NPM_INSTALL["npm install"]
        NPM_INSTALL --> NPM_AUDIT_FIX["npm audit fix<br/>(safe patches)"]
        NPM_AUDIT_FIX --> NPM_AUDIT["npm audit<br/>(vulnerability report)"]
        NPM_AUDIT --> TSC2["tsc --noEmit<br/>(post-install)"]
        TSC2 --> NPM_BUILD["npm run build"]
        NPM_BUILD --> BUILD_OK{Build<br/>passed?}
    end

    BUILD_OK -->|Yes| POST_BUILD
    BUILD_OK -->|No| SELF_HEAL

    subgraph HEALING["7. Self-Healing Loop (max 7 attempts)"]
        SELF_HEAL["Classify error"]
        SELF_HEAL --> AUTO_FIX["Try auto-fixes<br/>(syntax, missing pkgs,<br/>Prettier, Prisma, env types)"]
        AUTO_FIX --> AUTO_OK{Fixed?}
        AUTO_OK -->|Yes| NPM_BUILD
        AUTO_OK -->|No| LLM_FIX["LLM fix attempt"]
        LLM_FIX --> ODD{Attempt<br/>number?}
        ODD -->|"Odd (1,3,5,7)"| CLAUDE_FIX["Claude fixes"]
        ODD -->|"Even (2,4,6)"| OPENAI_FIX["OpenAI fixes<br/>(fresh perspective)"]
        CLAUDE_FIX --> APPLY_FIX["Apply fix + rebuild"]
        OPENAI_FIX --> APPLY_FIX
        APPLY_FIX --> REBUILD_OK{Build<br/>passed?}
        REBUILD_OK -->|Yes| POST_BUILD
        REBUILD_OK -->|No, attempts left| SELF_HEAL
        REBUILD_OK -->|No, exhausted| POST_MORTEM["🔬 Post-Mortem Analysis"]
        POST_MORTEM --> PM_LEARN["Extract KB rules<br/>from full error chain"]
        PM_LEARN --> PM_ISSUE["Create GitHub Issue<br/>on runner repo"]
        PM_ISSUE --> PM_REQUEUE{First<br/>post-mortem?}
        PM_REQUEUE -->|Yes| REQUEUE["Re-queue run<br/>with new knowledge"]
        PM_REQUEUE -->|No| FAIL_COMMENT["Post failure<br/>to Jira"]
        REQUEUE --> SELF_HEAL
    end

    subgraph POSTBUILD["8. Post-Build Checks"]
        POST_BUILD["Post-build"]
        POST_BUILD --> PW_TEST["🎭 Playwright E2E tests"]
        POST_BUILD --> AUDIT_RPT["📋 npm audit report"]
    end

    subgraph GITFLOW["9. Git & GitHub"]
        PW_TEST --> ROLLBACK_TAG["Create rollback tag"]
        AUDIT_RPT --> ROLLBACK_TAG
        ROLLBACK_TAG --> GIT_COMMIT["git add -A && git commit"]
        GIT_COMMIT --> GIT_PUSH["git push origin"]
        GIT_PUSH --> PR_CREATE{Independent?}
        PR_CREATE -->|Yes| CREATE_PR["gh pr create<br/>ai/{ISSUE-KEY} → main"]
        PR_CREATE -->|No| UPDATE_PR["Update Story PR<br/>story/{PARENT-KEY}"]
    end

    subgraph POSTPUSH["10. Post-Push Checks (non-blocking)"]
        CREATE_PR --> GH_CI["✅ GitHub Actions CI"]
        UPDATE_PR --> GH_CI
        GH_CI --> AUDIT_JIRA["📋 npm audit → Jira"]
        AUDIT_JIRA --> PW_JIRA["🎭 Playwright → Jira"]
        PW_JIRA --> SG_JIRA["🛡️ Semgrep → Jira"]
        SG_JIRA --> ZAP_CHECK{Deployed<br/>URL?}
        ZAP_CHECK -->|Yes| BS["📱 BrowserStack responsive"]
        ZAP_CHECK -->|Yes| LH["⚡ Lighthouse performance"]
        ZAP_CHECK -->|Yes| ZAP["🔐 OWASP ZAP DAST"]
        ZAP_CHECK -->|No| COMPLETE
        BS --> COMPLETE
        LH --> COMPLETE
        ZAP --> COMPLETE
    end

    subgraph FINISH["11. Completion"]
        COMPLETE["Build Jira comment<br/>(summary + all check results)"]
        COMPLETE --> JIRA_COMMENT["📝 Post to Jira"]
        JIRA_COMMENT --> SLACK_NOTIFY["📢 Slack notification"]
        SLACK_NOTIFY --> TRANSITION["Subtask → In Testing<br/>Assign to human"]
        TRANSITION --> NEXT{More<br/>subtasks?}
        NEXT -->|Yes| NEXT_ST["Start next subtask"]
        NEXT -->|No| STORY_DONE["Story → In Testing"]
        NEXT_ST --> START
    end

    FAIL_COMMENT --> BLOCKED_ST2["Subtask → Blocked<br/>Assign to human"]

    style CHECKOUT fill:#e3f2fd,stroke:#1565c0
    style CONTEXT fill:#f3e5f5,stroke:#6a1b9a
    style INTEGRATIONS fill:#fff3e0,stroke:#e65100
    style GENERATE fill:#fce4ec,stroke:#c62828
    style PREVERIFY fill:#e0f7fa,stroke:#00838f
    style BUILD fill:#f1f8e9,stroke:#558b2f
    style HEALING fill:#fff8e1,stroke:#f9a825
    style POSTBUILD fill:#e8eaf6,stroke:#283593
    style GITFLOW fill:#f1f8e9,stroke:#558b2f
    style POSTPUSH fill:#ede7f6,stroke:#4527a0
    style FINISH fill:#e8f5e9,stroke:#2e7d32
```

---

## 4. Epic → Story → Subtask Lifecycle

```mermaid
flowchart LR
    subgraph EPIC["Epic Lifecycle"]
        E_BACK[Backlog] -->|AI plans| E_REVIEW[Plan Review]
        E_REVIEW -->|Human approves| E_PROG[In Progress]
        E_REVIEW -->|Human revises| E_REVIEW
        E_PROG -->|All stories done| E_DONE[Done]
        E_BACK -->|Error| E_BLOCK[Blocked]
    end

    subgraph STORIES["Stories (auto-created from plan)"]
        S_BACK[Backlog] -->|Auto-start| S_SEL[Selected for Dev]
        S_SEL -->|AI creates subtasks| S_PROG[In Progress]
        S_PROG -->|All subtasks done| S_TEST[In Testing]
        S_TEST -->|Human approves| S_DONE[Done]
        S_TEST -->|Issues found| S_REWORK[Needs Rework]
        S_REWORK -->|AI reworks| S_PROG
    end

    subgraph SUBTASKS["Subtasks (auto-created from story)"]
        ST_PROG[In Progress] -->|AI implements| ST_TEST[In Testing]
        ST_TEST -->|Human approves| ST_DONE[Done]
        ST_TEST -->|Issues found| ST_REWORK[Needs Rework]
        ST_REWORK -->|AI reworks| ST_PROG
        ST_PROG -->|Error| ST_BLOCK[Blocked]
        ST_BLOCK -->|Retry| ST_PROG
    end

    E_PROG -.->|Creates| S_BACK
    S_PROG -.->|Creates| ST_PROG
    ST_DONE -.->|All done| S_TEST
    S_DONE -.->|All done| E_DONE

    style EPIC fill:#e3f2fd,stroke:#1565c0
    style STORIES fill:#fff8e1,stroke:#f9a825
    style SUBTASKS fill:#fce4ec,stroke:#c62828
```

---

## 5. Branching & PR Strategy

```mermaid
gitgraph
    commit id: "main"
    branch "story/PROJ-10"
    checkout "story/PROJ-10"
    commit id: "PROJ-11: Header component"
    commit id: "PROJ-12: Navigation links"
    commit id: "PROJ-13: Mobile responsive"
    checkout main
    merge "story/PROJ-10" id: "Story PR merged"
    branch "ai/PROJ-20"
    checkout "ai/PROJ-20"
    commit id: "PROJ-20: Independent fix"
    checkout main
    merge "ai/PROJ-20" id: "Independent PR merged"
```

**Branching rules:**
- **Story subtasks** → all commit to `story/{PARENT-KEY}` branch → single Story PR
- **Independent subtasks** → each gets `ai/{ISSUE-KEY}` branch → individual PR
- **Rollback tags** → `rollback/{ISSUE-KEY}/{timestamp}` created before each commit

---

## 6. Security & Testing Layers

```mermaid
flowchart TB
    subgraph STATIC["🔒 Static Analysis (Pre-Commit)"]
        direction TB
        REGEX["Security Scanner<br/><i>Regex-based</i><br/>Hardcoded secrets, obvious injection"]
        SEMGREP2["Semgrep SAST<br/><i>AST-aware</i><br/>OWASP Top 10 data-flow tracking"]
        ESLINT2["ESLint<br/><i>Code quality</i><br/>Style, potential bugs"]
        TSC3["TypeScript<br/><i>Type safety</i><br/>tsc --noEmit"]
    end

    subgraph DEPS["📦 Dependency Analysis (Post-Install)"]
        NPM_AUDIT2["npm audit<br/><i>Known CVEs</i><br/>Critical/high vulnerability detection"]
        NPM_FIX["npm audit fix<br/><i>Auto-patch</i><br/>Safe non-breaking updates"]
    end

    subgraph FUNCTIONAL["🧪 Functional Testing (Post-Build)"]
        UNIT["Unit/Integration Tests<br/><i>npm run test</i><br/>Jest / Vitest"]
        E2E["Playwright E2E<br/><i>Browser automation</i><br/>Regression detection"]
        BS2["BrowserStack<br/><i>Cross-browser</i><br/>Responsive design validation"]
    end

    subgraph RUNTIME["🔐 Dynamic Analysis (Post-Deploy)"]
        ZAP2["OWASP ZAP DAST<br/><i>Attack simulation</i><br/>Injection, XSS, CSRF, auth"]
        LH2["Lighthouse<br/><i>Performance</i><br/>Core Web Vitals, a11y, SEO"]
    end

    subgraph CI["✅ CI/CD"]
        GH_ACTIONS["GitHub Actions<br/><i>Pipeline</i><br/>Automated checks on push"]
    end

    STATIC --> DEPS --> FUNCTIONAL --> RUNTIME
    FUNCTIONAL --> CI

    style STATIC fill:#ffebee,stroke:#c62828
    style DEPS fill:#fff3e0,stroke:#e65100
    style FUNCTIONAL fill:#e8f5e9,stroke:#2e7d32
    style RUNTIME fill:#e3f2fd,stroke:#1565c0
    style CI fill:#f3e5f5,stroke:#6a1b9a
```

---

## 7. Integration Architecture

```mermaid
flowchart LR
    subgraph INPUTS["📥 Context Inputs"]
        FIG[("🎨 Figma<br/>Design specs")]
        SEN[("🐛 Sentry<br/>Error traces")]
        STR[("💳 Stripe<br/>Account state")]
        VER[("▲ Vercel<br/>Best practices")]
    end

    subgraph CORE["⚙️ Orchestrator Core"]
        WORKER["Worker<br/>(claim + route)"]
        EXECUTOR["Executor<br/>(generate + verify)"]
        VERIFIER["Verifier<br/>(check pipeline)"]
        HEALER["Self-Healer<br/>(fix loop)"]
    end

    subgraph LLMS["🧠 LLM Providers"]
        CLAUDE2[("Claude<br/>Code generation<br/>+ fix attempts 1,3,5,7")]
        OPENAI[("OpenAI<br/>Planning<br/>+ fix attempts 2,4,6")]
    end

    subgraph QUALITY["🔍 Quality Gates"]
        SEC["Security Scanner"]
        SG["Semgrep SAST"]
        PW["Playwright E2E"]
        NA["npm audit"]
        ZP["OWASP ZAP"]
        LIG["Lighthouse"]
        BROW["BrowserStack"]
    end

    subgraph OUTPUTS["📤 Output Channels"]
        JIRA2[("📋 Jira<br/>Comments + transitions")]
        GITHUB2[("🔀 GitHub<br/>Branches + PRs")]
        SLACK2[("📢 Slack<br/>Notifications")]
    end

    FIG --> EXECUTOR
    SEN --> EXECUTOR
    STR --> EXECUTOR
    VER --> EXECUTOR

    WORKER --> EXECUTOR
    EXECUTOR --> VERIFIER
    VERIFIER --> HEALER
    HEALER --> EXECUTOR

    EXECUTOR <--> CLAUDE2
    EXECUTOR <--> OPENAI
    HEALER <--> CLAUDE2
    HEALER <--> OPENAI

    VERIFIER --> SEC
    VERIFIER --> SG
    VERIFIER --> PW
    VERIFIER --> NA
    VERIFIER --> ZP
    VERIFIER --> LIG
    VERIFIER --> BROW

    EXECUTOR --> JIRA2
    EXECUTOR --> GITHUB2
    WORKER --> SLACK2
    WORKER --> JIRA2

    style INPUTS fill:#fff3e0,stroke:#e65100
    style CORE fill:#fce4ec,stroke:#c62828
    style LLMS fill:#e8eaf6,stroke:#283593
    style QUALITY fill:#e0f7fa,stroke:#00838f
    style OUTPUTS fill:#e8f5e9,stroke:#2e7d32
```

---

## 8. Self-Healing Decision Tree

```mermaid
flowchart TB
    FAIL[Build fails] --> CLASSIFY["Classify error<br/>(type_error, import_error,<br/>syntax_error, config_error,<br/>module_not_found, etc.)"]

    CLASSIFY --> AUTO["Try auto-fixes"]

    AUTO --> SYNTAX["Syntax fixes<br/>(structural issues)"]
    AUTO --> GENERAL["General fixes<br/>(common patterns)"]
    AUTO --> MISSING_PKG["Missing npm packages<br/>(auto-install)"]
    AUTO --> ESLINT_CFG["Missing ESLint config<br/>(auto-install)"]
    AUTO --> PRISMA["Prisma generate<br/>(schema updates)"]
    AUTO --> PRETTIER["Prettier format<br/>(style errors)"]
    AUTO --> ENV_TYPE["Env type definitions<br/>(missing .d.ts)"]

    SYNTAX --> REBUILD{Rebuild}
    GENERAL --> REBUILD
    MISSING_PKG --> REBUILD
    ESLINT_CFG --> REBUILD
    PRISMA --> REBUILD
    PRETTIER --> REBUILD
    ENV_TYPE --> REBUILD

    REBUILD -->|Pass| DONE[Continue to commit]
    REBUILD -->|Fail| LOOP["Self-healing loop"]

    LOOP --> ATT1["Attempt 1: Claude"]
    ATT1 -->|Fail| ATT2["Attempt 2: OpenAI<br/>(fresh perspective)"]
    ATT2 -->|Fail| ATT3["Attempt 3: Claude<br/>+ self-reflection"]
    ATT3 -->|Fail| ATT4["Attempt 4: OpenAI<br/>+ pattern learning"]
    ATT4 -->|Fail| ATT5["...up to attempt 7"]
    ATT5 -->|Fail| EXHAUSTED["Post failure to Jira<br/>Subtask → Blocked"]

    ATT1 -->|Pass| DONE
    ATT2 -->|Pass| DONE
    ATT3 -->|Pass| DONE
    ATT4 -->|Pass| DONE
    ATT5 -->|Pass| DONE

    style FAIL fill:#ffcdd2,stroke:#c62828
    style DONE fill:#c8e6c9,stroke:#2e7d32
    style EXHAUSTED fill:#ffcdd2,stroke:#c62828
    style LOOP fill:#fff8e1,stroke:#f9a825
```

---

## Quick Reference: All Jira Statuses

| Status | Used By | Meaning |
|--------|---------|---------|
| **Backlog** | Epic, Story | Not yet started |
| **Plan Review** | Epic | AI plan awaiting human approval |
| **Selected for Development** | Story | Ready for AI to pick up |
| **In Progress** | Epic, Story, Subtask | AI is actively working |
| **In Testing** | Story, Subtask | AI finished, human reviewing |
| **Needs Rework** | Story, Subtask | Human found issues, sent back to AI |
| **Done** | Epic, Story, Subtask | Approved and complete |
| **Blocked** | Epic, Subtask | Error occurred, needs attention |

## Quick Reference: All Integrations

| Integration | Type | Trigger | Blocks Commit? |
|-------------|------|---------|----------------|
| Security Scanner | SAST (regex) | Every commit | Critical only |
| Semgrep | SAST (AST) | Every commit (if installed) | ERROR level |
| npm audit | SCA | After npm install | No (warnings) |
| Playwright | E2E | If playwright.config exists | Yes (failures) |
| OWASP ZAP | DAST | If deployed URL + ZAP running | High risk only |
| BrowserStack | Visual | If deployed URL + UI changes | No (warnings) |
| Lighthouse | Performance | If deployed URL + UI changes | No (warnings) |
| GitHub Actions | CI | Every push | No (informational) |
| Figma | Context | Figma URL in Jira description | N/A (input) |
| Sentry | Context | Sentry ref in Jira description | N/A (input) |
| Stripe | Context | Payment keywords in task | N/A (input) |
| Vercel | Context | Next.js project detected | N/A (input) |
| Slack | Notification | Task complete/fail/story done | N/A (output) |
