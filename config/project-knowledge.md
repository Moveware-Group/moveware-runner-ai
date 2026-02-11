# Project Knowledge for AI Planning

This file provides context about your infrastructure, architecture, and conventions. The AI Runner uses it when creating Epic plans so it does not ask basic questions it should already know.

Edit this file with facts specific to your environment.

## Infrastructure

- **Existing setup**: We already have infrastructure set up. Do not ask which cloud provider to use or whether accounts/infrastructure exist.
- **Cloud / hosting**: We run our own server for development and use an Azure server for production
- **Deployment**: We manually git pull at the moment but may add GitHub Actions in the future
- **Server environment**: Ubuntu 24.04, nginx, systemd services, nodejs v21

## Architecture Conventions

- **Monorepo vs multi-repo**: multi-repo
- **Branching**: main/develop, feature branches, PR workflow
- **Tech stack**: Next.js, Flutter

## Things the AI Should Assume (Do Not Ask)

- Infrastructure exists and is provisioned.
- Deployment pipelines are in place.
- Cloud/infrastructure provider decisions are already made.
- Branding can be extracted from /srv/ai/app/docs/DESIGN-TEMPLATE.md
- Moveware Rest API uses header based auth requiring mw-company-id, mw-username and mw-password
- Moveware API does not have any rate limiting
- Moveware API is documented at https://rest.swagger.moveconnect.com/index.html#/

## Resolved Q&A (from past Epics – do not re-ask)

Add Q&A from past plan discussions so the AI doesn't repeat them. Example format:

- **Moveware REST API v2 auth**: Header-based (mw-company-id, mw-username, mw-password, mw-correlation-id). Not API key or OAuth.
- **Moveware API rate limits**: None.
- **User provisioning**: Admin-provisioned initially; later extend to lookup company via Moveware REST API.
- **SSO**: Azure AD B2C.
- **Tenancy**: Multi-tenant Next.js platform.
- **Roles**: Security groups in Moveware; add matching RBAC later.
- **Tech stack**: React/Next.js on Node.js.
- **Compliance**: Security-first; aim for GDPR, SOC 2, HIPAA (clients worldwide).
- **Scale**: ~2000 users in first 12 months.
- **Moveware API docs**: Swagger, fully documented.
- **Design/brand**: See /srv/ai/app/docs/DESIGN-TEMPLATE.md.
- **High-traffic API endpoints**: jobs, inventory.
