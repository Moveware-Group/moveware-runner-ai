#!/bin/bash
#
# GitHub App Setup Helper Script
#
# Makes it easy to install GitHub App authentication on the server
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}GitHub App Setup for AI Runner${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Usage: sudo ./scripts/setup-github-app.sh"
    exit 1
fi

# Prompt for GitHub App credentials
echo -e "${YELLOW}Please provide your GitHub App credentials:${NC}"
echo ""

read -p "GitHub App ID: " APP_ID
if [ -z "$APP_ID" ]; then
    echo -e "${RED}Error: App ID is required${NC}"
    exit 1
fi

read -p "Installation ID (leave blank to auto-detect): " INSTALLATION_ID

read -p "Path to private key .pem file: " PEM_FILE
if [ ! -f "$PEM_FILE" ]; then
    echo -e "${RED}Error: Private key file not found: $PEM_FILE${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Credentials collected${NC}"
echo ""

# Create .ssh directory if it doesn't exist
echo "Creating .ssh directory..."
mkdir -p /srv/ai/.ssh
chown moveware-ai:moveware-ai /srv/ai/.ssh
chmod 700 /srv/ai/.ssh

# Copy private key
echo "Installing private key..."
cp "$PEM_FILE" /srv/ai/.ssh/github-app-private-key.pem
chown moveware-ai:moveware-ai /srv/ai/.ssh/github-app-private-key.pem
chmod 600 /srv/ai/.ssh/github-app-private-key.pem

echo -e "${GREEN}✓ Private key installed${NC}"
echo ""

# Update environment file
echo "Updating environment configuration..."

# Check if environment file exists
if [ ! -f /etc/moveware-ai.env ]; then
    echo -e "${RED}Error: /etc/moveware-ai.env not found${NC}"
    exit 1
fi

# Backup environment file
cp /etc/moveware-ai.env /etc/moveware-ai.env.backup-$(date +%Y%m%d-%H%M%S)

# Add GitHub App configuration
echo "" >> /etc/moveware-ai.env
echo "# ---- GitHub App Configuration ----" >> /etc/moveware-ai.env
echo "GITHUB_APP_ID=$APP_ID" >> /etc/moveware-ai.env

if [ -n "$INSTALLATION_ID" ]; then
    echo "GITHUB_APP_INSTALLATION_ID=$INSTALLATION_ID" >> /etc/moveware-ai.env
fi

echo "GITHUB_APP_PRIVATE_KEY_PATH=/srv/ai/.ssh/github-app-private-key.pem" >> /etc/moveware-ai.env

echo -e "${GREEN}✓ Environment updated${NC}"
echo ""

# Install dependencies
echo "Installing Python dependencies..."
cd /srv/ai/app
sudo -u moveware-ai .venv/bin/pip install -q PyGithub==2.1.1 PyJWT==2.8.0 cryptography==41.0.7

echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Restart services
echo "Restarting services..."
systemctl restart moveware-ai-worker
systemctl restart moveware-ai-orchestrator

echo -e "${GREEN}✓ Services restarted${NC}"
echo ""

# Verify setup
echo "Verifying setup..."
sleep 2

if journalctl -u moveware-ai-worker -n 20 | grep -q "GitHub App authentication initialized"; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ SUCCESS!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "GitHub App authentication is now active!"
    echo ""
    echo "Configuration:"
    echo "  App ID: $APP_ID"
    if [ -n "$INSTALLATION_ID" ]; then
        echo "  Installation ID: $INSTALLATION_ID"
    else
        echo "  Installation ID: Auto-detected"
    fi
    echo "  Private Key: /srv/ai/.ssh/github-app-private-key.pem"
    echo ""
    echo "View logs:"
    echo "  sudo journalctl -u moveware-ai-worker -f"
else
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}⚠ WARNING${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "GitHub App may not be initialized correctly."
    echo "Check logs for errors:"
    echo "  sudo journalctl -u moveware-ai-worker -n 50"
    echo ""
    echo "The system will fall back to PAT (GH_TOKEN) if GitHub App fails."
fi

echo ""
echo "Backup of old environment: /etc/moveware-ai.env.backup-*"
echo ""
