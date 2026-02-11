# Project Knowledge for AI Planning

This file provides context about your infrastructure, architecture, and conventions. The AI Runner uses it when creating Epic plans so it does not ask basic questions it should already know.

Edit this file with facts specific to your environment.

## Infrastructure

- **Existing setup**: We already have infrastructure set up. Do not ask which cloud provider to use or whether accounts/infrastructure exist.
- **Cloud / hosting**: (Specify provider if relevant: AWS, Azure, GCP, on-prem, etc.)
- **Deployment**: (e.g. GitHub Actions, systemd, Docker, Vercel.)
- **Server environment**: (e.g. Ubuntu 24.04, nginx, systemd services.)

## Architecture Conventions

- **Monorepo vs multi-repo**: (Your setup.)
- **Branching**: (e.g. main/develop, feature branches, PR workflow.)
- **Tech stack**: (Next.js, Flutter, Python, etc. per project—or list defaults.)

## Things the AI Should Assume (Do Not Ask)

- Infrastructure exists and is provisioned.
- Deployment pipelines are in place.
- Cloud/infrastructure provider decisions are already made.
