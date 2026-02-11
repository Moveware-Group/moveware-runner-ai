# Per-Repository Skills

Assign framework-specific skills to each repository so the AI uses the right conventions (Next.js vs Flutter, etc.).

## Overview

Skills provide project-specific guidance:
- **nextjs-fullstack-dev** – Next.js 13+, App Router, React patterns
- **flutter-dev** – Flutter/Dart mobile app development

Without explicit skills, the default is `["nextjs-fullstack-dev"]`.

## Configuration

Add `skills` to each project in `config/repos.json`:

```json
{
  "projects": [
    {
      "jira_project_key": "OD",
      "jira_project_name": "Online Docs",
      "repo_ssh": "git@github.com:org/online-docs.git",
      "repo_workdir": "/srv/ai/repos/online-docs",
      "base_branch": "main",
      "repo_owner_slug": "org",
      "repo_name": "online-docs",
      "skills": ["nextjs-fullstack-dev"]
    },
    {
      "jira_project_key": "TB",
      "jira_project_name": "Moveware Go",
      "repo_ssh": "git@github.com:org/moveware-go.git",
      "repo_workdir": "/srv/ai/repos/moveware-go",
      "base_branch": "main",
      "repo_owner_slug": "org",
      "repo_name": "moveware-go",
      "skills": ["flutter-dev"]
    }
  ],
  "default_project_key": "OD"
}
```

## Available Skills

| Skill | Use For |
|-------|---------|
| `nextjs-fullstack-dev` | Next.js, React, TypeScript web apps |
| `flutter-dev` | Flutter/Dart mobile apps |
| `nodejs-api-dev` | Node.js APIs, Express |
| `python-dev` | Python, FastAPI, Flask |
| `qa-tester` | Testing, Playwright E2E |
| `security-tester` | Security reviews |

## Adding Custom Skills

1. Create `.cursor/skills/<skill-name>/SKILL.md`
2. Follow the format of existing skills (YAML frontmatter + Markdown content)
3. Add the skill name to `skills` in `repos.json`

## How It Works

When processing a Jira issue:
1. Issue key (e.g. `TB-1`) → project `TB`
2. Look up `TB` in repos.json
3. Load skills: `["flutter-dev"]`
4. Load `.cursor/skills/flutter-dev/SKILL.md`
5. Inject skill content into the system prompt
6. Claude uses Flutter conventions for implementation

## Branding

Branding remains global via `/srv/ai/app/docs/DESIGN-TEMPLATE.md`. All repos use the same design template unless they have their own `DESIGN.md`.
