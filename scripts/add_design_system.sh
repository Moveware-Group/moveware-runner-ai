#!/bin/bash
#
# Add Design System to Existing Project
# Usage: ./add_design_system.sh [project_directory] [project_name]
#
# This script adds DESIGN.md to an existing project repository
#

set -e

PROJECT_DIR="${1:-/srv/ai/repos/online-docs}"
PROJECT_NAME="${2:-Moveware Online Documents}"

echo "=================================================="
echo "Adding Design System to Project"
echo "=================================================="
echo ""
echo "Project Directory: $PROJECT_DIR"
echo "Project Name: $PROJECT_NAME"
echo ""

# Check if directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: Directory $PROJECT_DIR does not exist"
    exit 1
fi

# Check if DESIGN.md already exists
if [ -f "$PROJECT_DIR/DESIGN.md" ]; then
    echo "⚠️  DESIGN.md already exists in $PROJECT_DIR"
    read -p "Overwrite? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# Get the script directory to find the template
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_PATH="$SCRIPT_DIR/../docs/DESIGN-TEMPLATE.md"

if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "ERROR: Design template not found at $TEMPLATE_PATH"
    exit 1
fi

# Copy template to project
echo "📝 Copying design system template..."
cp "$TEMPLATE_PATH" "$PROJECT_DIR/DESIGN.md"

# Customize the template with project name
echo "✏️  Customizing for $PROJECT_NAME..."
sed -i "s/\[Your App Name\]/$PROJECT_NAME/g" "$PROJECT_DIR/DESIGN.md"

# Add note about this being auto-generated
cat > "$PROJECT_DIR/DESIGN.md.tmp" << EOF
# $PROJECT_NAME Design System

> **Note:** This design system was auto-generated. Customize the colors, typography, and components to match your brand.

EOF

# Append the rest of the template (skip the first line which has the placeholder)
tail -n +2 "$PROJECT_DIR/DESIGN.md" >> "$PROJECT_DIR/DESIGN.md.tmp"
mv "$PROJECT_DIR/DESIGN.md.tmp" "$PROJECT_DIR/DESIGN.md"

echo ""
echo "✅ Design system added to $PROJECT_DIR/DESIGN.md"
echo ""
echo "Next steps:"
echo "1. Review and customize DESIGN.md with your brand colors and fonts"
echo "2. Commit the file:"
echo "   cd $PROJECT_DIR"
echo "   git add DESIGN.md"
echo "   git commit -m 'Add design system documentation'"
echo "   git push origin main"
echo ""
echo "3. Future UI tasks will automatically reference this design system"
echo ""
