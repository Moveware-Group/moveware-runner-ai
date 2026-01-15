#!/usr/bin/env bash
set -euo pipefail

# NOTE: This is a reference installer. Review before running.

APP_USER="moveware-ai"
APP_GROUP="moveware-ai"
BASE_DIR="/srv/ai/app"
STATE_DIR="/srv/ai/state"
WORK_DIR="/srv/ai/work"

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip git nginx jq

# GitHub CLI
type gh >/dev/null 2>&1 || {
  sudo apt-get install -y curl
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
  sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y gh
}

# Create service user
if ! id "$APP_USER" >/dev/null 2>&1; then
  sudo useradd -m -s /bin/bash "$APP_USER"
fi

sudo mkdir -p "$BASE_DIR" "$STATE_DIR" "$WORK_DIR"
sudo chown -R "$APP_USER":"$APP_GROUP" /srv/ai || true

# Copy repo to /srv/ai/app (assumes you have cloned this repo locally)
# sudo rsync -a --delete ./ "$BASE_DIR"/

# venv + deps
sudo -u "$APP_USER" python3 -m venv "$BASE_DIR/.venv"
sudo -u "$APP_USER" "$BASE_DIR/.venv/bin/pip" install -r "$BASE_DIR/requirements.txt"

# systemd units are in scripts/systemd
sudo cp scripts/systemd/moveware-ai-orchestrator.service /etc/systemd/system/
sudo cp scripts/systemd/moveware-ai-worker.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now moveware-ai-orchestrator
sudo systemctl enable --now moveware-ai-worker

# nginx config is in scripts/nginx
sudo cp scripts/nginx/moveware-ai-runner.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/moveware-ai-runner.conf /etc/nginx/sites-enabled/moveware-ai-runner.conf
sudo nginx -t
sudo systemctl restart nginx
