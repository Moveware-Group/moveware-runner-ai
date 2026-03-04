# DevOps & Ops Scripts

Scripts and configs for setting up new repos, nginx, and database when the AI Runner adds new applications.

## When to use

- **New repo / new app**: After the AI Runner creates a new app (e.g. Next.js + Prisma), you need to create the database, set `.env`, run migrations, and (optionally) add nginx.
- **Post-deploy tickets**: Enable `CREATE_POST_DEPLOY_TICKET=true` in `.env` so the runner creates a Jira subtask assigned to you with explicit steps; these scripts mirror that workflow.

## Contents

| Path | Purpose |
|------|--------|
| `nginx/example-server-block.conf` | Example nginx server block for a Next.js app (proxy to Node). |
| `scripts/setup-new-repo-env.sh` | Template script: `git pull`, create DB, copy .env.example → .env, `npm install`, `prisma generate`, `npm run build`, then print migration/seed/nginx next steps. Customize and run on the server. |

## Quick start: new app setup

1. **From Jira**: Use the post-deploy comment (or the “[Post-deploy] Database, .env & migrations” subtask if you enabled `CREATE_POST_DEPLOY_TICKET`).
2. **Or run the script** (customize first):
   ```bash
   # Copy and edit for your app name and paths
   cp ops/scripts/setup-new-repo-env.sh /tmp/setup-myapp.sh
   chmod +x /tmp/setup-myapp.sh
   # Edit APP_NAME, REPO_DIR, PORT, then:
   /tmp/setup-myapp.sh
   ```

## Nginx

- Use `nginx/example-server-block.conf` as a starting point.
- Copy into your nginx config (e.g. `/etc/nginx/sites-available/myapp`) and enable the site.
- Adjust `server_name`, `proxy_pass` port, and paths as needed.
- Reload nginx: `sudo nginx -t && sudo systemctl reload nginx`.

## Scripts

Scripts are intended to be copied and customized (app name, paths, ports). They are not executed by the AI Runner; run them manually or from your own CI/deploy pipeline.
