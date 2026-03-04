#!/usr/bin/env bash
# Template: setup database, .env, and run migrations for a new app repo.
# Copy this script, set the variables below, and run on the server (or locally against a dev DB).

set -e

# --- Customize these ---
APP_NAME="myapp"                    # Used for DB name and log messages
REPO_DIR="/srv/ai/repos/myapp"      # Path to the cloned repo
PORT=3000                           # App port (for .env NEXTAUTH_URL etc.)

# --- Optional: override DB name ---
DB_NAME="${DB_NAME:-${APP_NAME}_dev}"

echo "=== Setting up: $APP_NAME (repo: $REPO_DIR, DB: $DB_NAME) ==="

# 0. Git pull (if repo exists)
if [[ -d "$REPO_DIR/.git" ]]; then
  echo "Pulling latest from git..."
  (cd "$REPO_DIR" && git pull)
else
  echo "Not a git repo or missing; skip git pull."
fi

# 1. Create PostgreSQL database (skip if exists)
if command -v psql &>/dev/null; then
  if psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "Database $DB_NAME already exists."
  else
    echo "Creating database: $DB_NAME"
    createdb "$DB_NAME" || true
  fi
else
  echo "psql not found; skip DB creation. Create manually: createdb $DB_NAME"
fi

# 2. .env from .env.example
if [[ -f "$REPO_DIR/.env.example" ]]; then
  if [[ ! -f "$REPO_DIR/.env" ]]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "Created .env from .env.example. Edit $REPO_DIR/.env and set DATABASE_URL and secrets."
  else
    echo ".env already exists; not overwriting."
  fi
else
  echo "No .env.example in $REPO_DIR; create .env manually."
fi

# 3. Install deps, Prisma, and build (if package.json present)
if [[ -f "$REPO_DIR/package.json" ]]; then
  (cd "$REPO_DIR" && npm install)
  if [[ -f "$REPO_DIR/prisma/schema.prisma" ]]; then
    (cd "$REPO_DIR" && npx prisma generate)
    echo "Run migrations when DATABASE_URL is set: cd $REPO_DIR && npx prisma migrate deploy"
    echo "Or for dev: npx prisma migrate dev --name init"
  fi
  if grep -q '"build"' "$REPO_DIR/package.json" 2>/dev/null; then
    echo "Running npm run build..."
    (cd "$REPO_DIR" && npm run build) || echo "Build failed (e.g. missing .env); fix and re-run build later."
  else
    echo "No 'build' script in package.json; skip npm run build."
  fi
fi

echo "=== Next steps ==="
echo "1. Edit $REPO_DIR/.env (DATABASE_URL, NEXTAUTH_SECRET, etc.)."
echo "2. Run migrations: cd $REPO_DIR && npx prisma migrate deploy"
echo "3. Optional seed: cd $REPO_DIR && npx prisma db seed"
echo "4. Start app (e.g. npm run dev or PM2) and add nginx (see ops/nginx/example-server-block.conf)."
