# Automatic Design System Integration

The AI Runner automatically includes and enforces design systems in all projects, ensuring consistent, branded UIs across all generated code.

## How It Works

### 1. Automatic Detection

When the AI Runner processes any UI-related task, it:

```
1. Checks if DESIGN.md exists in the project repo
   ├─ YES → Includes full design system in context
   └─ NO  → Includes design template from runner repo
2. Passes design system to Claude with explicit instructions
3. Claude generates UI code following the design patterns
```

### 2. UI Task Detection

Tasks are identified as UI-related if they contain keywords like:
- `ui`, `page`, `component`, `layout`, `form`, `button`
- `style`, `design`, `interface`, `frontend`
- `react`, `next.js`, `tailwind`

### 3. Design System Enforcement

The AI Runner's system prompt now includes:

> **CRITICAL:** If a Design System (DESIGN.md) is provided, YOU MUST follow it exactly
> - Use the exact color classes, spacing, and component patterns
> - Copy button styles, card styles, and layout patterns
> - Match the typography scale and font weights

This ensures Claude doesn't deviate from your brand guidelines.

## Setup for New Projects

### Automatic (Recommended)

When creating a new Next.js project, the AI Runner will:

1. Detect it's a project initialization task
2. Include DESIGN.md in the files to create
3. Populate it with the design template
4. Customize it based on any branding info in the ticket

**Example ticket:**

```
Summary: Initialize Next.js app with Acme branding

Description:
Create Next.js 14 project with App Router.

Branding:
- Primary color: Green (#10b981)
- Font: Poppins
- Logo: Acme Corp
```

Result: DESIGN.md created with green primary color and Poppins font.

### Manual Addition to Existing Projects

Use the helper script:

```bash
cd /srv/ai/app

# Add to specific project
./scripts/add_design_system.sh /srv/ai/repos/online-docs "Moveware Online Docs"

# Review and customize
vi /srv/ai/repos/online-docs/DESIGN.md

# Commit
cd /srv/ai/repos/online-docs
git add DESIGN.md
git commit -m "Add design system documentation"
git push origin main
```

## Design System Template

Located at: `docs/DESIGN-TEMPLATE.md`

Includes:
- ✅ Brand colors (primary, secondary, semantic)
- ✅ Typography scales and font weights
- ✅ Layout patterns (containers, spacing, breakpoints)
- ✅ Component patterns (buttons, cards, forms, alerts)
- ✅ Common UI patterns (hero, feature grid, stats, navigation)
- ✅ Accessibility guidelines
- ✅ Animation/transition standards

## Customization

### Per-Project Branding

Edit `DESIGN.md` in each project repo:

```markdown
# MyApp Design System

## Brand Colors
- Primary Blue: #1e40af (Tailwind: bg-blue-800)  ← Change this
- Primary Hover: #1e3a8a
...
```

### Global Template Updates

Update `docs/DESIGN-TEMPLATE.md` in the runner repo:

```bash
cd /srv/ai/app
vi docs/DESIGN-TEMPLATE.md

# Make changes, then commit
git add docs/DESIGN-TEMPLATE.md
git commit -m "Update design system template"
git push

# Restart worker to use new template
sudo systemctl restart moveware-ai-worker
```

All **new** projects will use the updated template.

## Benefits

### Consistency
- ✅ All UIs use the same colors, fonts, spacing
- ✅ Components look and feel consistent
- ✅ No "creative interpretation" by AI

### Speed
- ✅ No need to specify styling in every ticket
- ✅ AI knows exactly what "primary button" means
- ✅ Fewer revision cycles

### Maintainability
- ✅ Single source of truth for design decisions
- ✅ Easy to update brand colors globally
- ✅ New developers see the design patterns immediately

## Example: Before vs After

### Before (No Design System)

**Ticket:**
```
Create quote submission page
```

**Result:**
- Plain HTML form
- Minimal styling
- Inconsistent with rest of app
- Needs multiple revisions

### After (With Design System)

**Ticket:**
```
Create quote submission page
```

**Result:**
- Branded card layout (from design system)
- Primary button styling (exact colors/shadow)
- Form inputs with focus states (from design system)
- Consistent spacing and typography
- Perfect on first try ✅

## Advanced Usage

### Task-Specific Overrides

You can override design system defaults in specific tickets:

```
Create admin dashboard with dark theme

**Design Override:**
Use dark mode colors instead of standard:
- Background: bg-gray-900
- Surface: bg-gray-800
- Text: text-gray-100

Still follow the design system for:
- Component structure
- Spacing scale
- Typography scale
- Button patterns (but dark variants)
```

### Multiple Design Systems

For projects with multiple themes (e.g., client portal vs admin):

```
DESIGN.md           ← Main design system
DESIGN-ADMIN.md     ← Admin theme variant
DESIGN-MOBILE.md    ← Mobile app theme
```

Reference specific system in tickets:

```
Create admin user list page

**Note:** Use patterns from DESIGN-ADMIN.md (dark theme)
```

### Component Library Integration

If using a component library (shadcn/ui, Radix, etc.):

Add to DESIGN.md:

```markdown
## Component Library

This project uses [shadcn/ui](https://ui.shadcn.com/)

**Installed Components:**
- Button: `components/ui/button.tsx`
- Card: `components/ui/card.tsx`
- Form: `components/ui/form.tsx`

**When creating new UI:**
1. Check if component exists in `components/ui/`
2. Use existing component if available
3. Create new component only if needed
4. Follow the same pattern as existing components
```

## Troubleshooting

### AI Not Following Design System

**Problem:** Generated UI doesn't match DESIGN.md

**Solutions:**

1. **Verify DESIGN.md exists:**
   ```bash
   ls -la /srv/ai/repos/[project]/DESIGN.md
   ```

2. **Check file size (should be visible in logs):**
   ```bash
   sudo journalctl -u moveware-ai-worker -f | grep "Design System"
   ```

3. **Add explicit instruction to ticket:**
   ```
   **IMPORTANT:** Follow DESIGN.md exactly
   - Use bg-blue-600 for primary buttons (not other shades)
   - Use rounded-xl for all cards (not rounded-lg)
   ```

4. **Restart worker after template changes:**
   ```bash
   sudo systemctl restart moveware-ai-worker
   ```

### Design System Not Loaded

**Problem:** Context doesn't include design system

**Check:**
```bash
# Verify template exists
ls -la /srv/ai/app/docs/DESIGN-TEMPLATE.md

# Verify executor can read it
sudo -u moveware-ai python3 << EOF
from pathlib import Path
template = Path('/srv/ai/app/docs/DESIGN-TEMPLATE.md')
print(f"Exists: {template.exists()}")
print(f"Readable: {template.is_file()}")
EOF
```

### Inconsistent Styling Across Tasks

**Problem:** Different subtasks use different styles

**Solution:** Ensure DESIGN.md committed before starting subtasks:

```bash
cd /srv/ai/repos/[project]

# Add design system first
git add DESIGN.md
git commit -m "Add design system"
git push origin main

# Then start UI tasks
# AI will see DESIGN.md in all subsequent tasks
```

## Best Practices

### 1. Design System First

For new projects:
```
Epic: Build Admin Dashboard
  Story 1: Setup project and design system  ← Do this first
    Sub-task: Initialize Next.js
    Sub-task: Add DESIGN.md with branding
  Story 2: Build dashboard UI               ← Then build features
    Sub-task: Create layout
    Sub-task: Add metrics cards
```

### 2. Keep It Updated

When design changes:
```bash
# Update DESIGN.md
vi DESIGN.md

# Commit
git add DESIGN.md
git commit -m "Update primary color to match new branding"
git push

# Create tickets to update existing components
```

### 3. Document Deviations

If a component needs to deviate from the design system:

```markdown
## Exceptions

### Admin Dashboard
**Why:** Admin needs dark theme for extended use
**Pattern:** Uses inverted colors (light text on dark bg)
**Components:** Dashboard layout, admin nav, admin cards
```

### 4. Review Design System in PRs

Add design system compliance to your PR checklist:

```markdown
## PR Checklist
- [ ] Code follows design system (DESIGN.md)
- [ ] Colors match brand palette
- [ ] Spacing uses design system scale
- [ ] Typography follows style guide
- [ ] Interactive states implemented (hover, focus)
```

## Related Documentation

- [Design References](./design-references.md) - How to provide mockups/references
- [DESIGN-TEMPLATE.md](./DESIGN-TEMPLATE.md) - Full template content
- [Story Workflow](./story-workflow.md) - How AI Runner processes tickets
