# Design References for AI Runner

Guide for providing design references to the AI Runner so it creates production-quality UIs.

## Problem

The AI Runner creates functional code but may produce minimal UIs without proper styling or complete user experiences.

## Solution

Provide design references in Jira tickets to guide the AI Runner.

## Methods to Provide Design References

### 1. Reference URLs in Description

Add reference URLs to the Jira ticket description:

```
Create the quote submission page.

Design reference: https://tailwindui.com/components/application-ui/forms/form-layouts

Style: Modern, clean interface with card-based layout
Colors: Use Moveware brand colors (blue primary, gray secondary)
Layout: Full-width form on desktop, stacked on mobile
```

The AI Runner will see this in the description and use it as guidance.

### 2. Attach Screenshots

Attach design mockups or reference screenshots to the Jira ticket:
- Click "Attach" in Jira
- Upload PNG/JPG of desired design
- Add description: "Target design for homepage"

**Note:** The AI Runner currently reads ticket descriptions and comments, but not attachments. Attachments should be supplemented with descriptive text.

### 3. Link to Design System

Reference an existing design system or component library:

```
Use Tailwind UI patterns: https://tailwindui.com/components
Component style: Application UI > Data Display > Tables
Responsive: Mobile-first, 2-column grid on tablet+
```

### 4. Describe Visual Requirements

Be specific about visual elements:

```
**Visual Requirements:**
- Hero section with gradient background (blue to purple)
- Large heading (text-4xl font-bold)
- Three-column feature grid
- Each card has icon, title, description
- Rounded corners (rounded-lg)
- Shadow on hover (hover:shadow-xl transition)
- Mobile: Single column stack
- Desktop: Three columns with gap-6
```

## Example: Well-Defined UI Task

### Bad (Vague)

```
Summary: Create homepage
Description: Build the landing page for the app
```

Result: Minimal page with "Welcome" text ❌

### Good (Detailed)

```
Summary: Create marketing landing page with hero and features
Description: 
Build a modern, responsive landing page for the Moveware Online Docs platform.

**Layout:**
1. Hero Section
   - Full-width gradient background (bg-gradient-to-r from-blue-600 to-blue-800)
   - Large heading: "Transform Your Document Workflow"
   - Subheading explaining the value proposition
   - CTA button (primary blue, rounded-lg, shadow-lg)
   - Hero image/illustration on right side

2. Features Section
   - Three-column grid (grid-cols-1 md:grid-cols-3 gap-8)
   - Each feature card:
     * Icon at top (using lucide-react or heroicons)
     * Bold title
     * Description paragraph
     * "Learn more" link
   - White background with subtle border

3. CTA Section
   - Centered text with button
   - Contrasting background (bg-gray-50)

**Design Reference:** 
Similar to https://tailwindui.com/templates/saas-marketing
Style: Modern SaaS landing page

**Branding:**
- Primary: Blue (#2563eb)
- Use Inter font family
- Rounded corners throughout
- Smooth transitions on interactive elements
```

Result: Complete, polished landing page ✅

## Providing Design Systems

### Create a Reference Design File

Create a `DESIGN.md` in the repository root:

```markdown
# Moveware Design System

## Colors
- Primary Blue: #2563eb (bg-blue-600)
- Primary Hover: #1d4ed8 (bg-blue-700)
- Secondary Gray: #6b7280 (text-gray-600)
- Success Green: #10b981 (bg-green-500)
- Error Red: #ef4444 (bg-red-500)

## Typography
- Font Family: Inter
- Headings: font-bold text-gray-900
- Body: font-normal text-gray-600
- Code: font-mono text-sm

## Spacing
- Container: max-w-7xl mx-auto px-4 sm:px-6 lg:px-8
- Section padding: py-12 sm:py-16 lg:py-20
- Card padding: p-6

## Components

### Button Primary
```tsx
<button className="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg shadow-md hover:shadow-lg transition duration-200">
  Click Me
</button>
```

### Card
```tsx
<div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition duration-200">
  {/* Content */}
</div>
```

## Layouts

### Page Container
```tsx
<div className="min-h-screen bg-gray-50">
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
    {/* Page content */}
  </div>
</div>
```
```

The AI Runner will see this file in repository context and follow these patterns.

## Reference Sites for Common Patterns

### Landing Pages
- **Tailwind UI**: https://tailwindui.com/templates
- **Vercel**: https://vercel.com (Next.js examples)
- **Stripe**: https://stripe.com (Clean, modern SaaS design)

### Forms
- **Tailwind UI Forms**: https://tailwindui.com/components/application-ui/forms
- Use validation, error states, help text
- Include loading states for submissions

### Dashboards
- **Tailwind UI Dashboards**: https://tailwindui.com/components/application-ui/application-shells
- Sidebar navigation, header, main content area
- Cards for metrics, tables for data

### Data Tables
- **TanStack Table**: https://tanstack.com/table/latest
- Sortable columns, pagination, search
- Loading skeletons, empty states

## Task Labels for Design Emphasis

Add labels to Jira tickets to signal design importance:

- `ui-polish` - Needs production-quality UI
- `design-reference` - Has design reference attached/linked
- `mobile-first` - Must be mobile-responsive
- `accessibility` - Requires WCAG compliance

When these labels are present, the AI Runner should pay extra attention to visual quality.

## Workflow: Iterative Design Refinement

1. **AI creates initial implementation**
   - Functional but may need visual polish

2. **Human reviews and provides feedback**
   - "The cards need more spacing"
   - "Use a gradient background instead of solid"
   - "Add icons to the feature list"

3. **Reassign to AI with specific design feedback**
   - AI Runner reads comments and refines the design

4. **Repeat until satisfied**

## Best Practices

### DO
✅ Provide specific visual requirements in tickets
✅ Link to reference designs or component libraries
✅ Use descriptive language (colors, spacing, layout)
✅ Reference existing design systems
✅ Create DESIGN.md in repository for consistency
✅ Use Tailwind utility classes for specificity

### DON'T
❌ Write vague descriptions like "make it look nice"
❌ Assume AI knows your brand colors/style
❌ Expect pixel-perfect recreation of complex designs
❌ Skip responsive design requirements
❌ Forget to specify interactive states (hover, focus, loading)

## Future Enhancements

Planned features to improve design quality:

1. **Attachment reading** - AI Runner can view attached screenshots
2. **Design system validation** - Automatically check compliance with DESIGN.md
3. **Visual diff checking** - Compare screenshots before/after
4. **Component library integration** - Pre-built components the AI can reference
5. **Brand asset management** - Automatic access to logos, colors, fonts

## Example: Creating a Complete Dashboard

```
Epic: Build admin dashboard

Story: Create dashboard layout and navigation

Sub-task 1: Implement dashboard shell with sidebar navigation
Description:
Create the main dashboard layout using Next.js App Router.

**Layout Structure:**
- Left sidebar (fixed, w-64, bg-gray-900 text-white)
  * Logo at top
  * Navigation menu with icons (lucide-react)
  * User profile at bottom
- Main content area (flex-1)
  * Top header bar with breadcrumbs and user menu
  * Content section (bg-gray-50)

**Navigation Items:**
- Dashboard (LayoutDashboard icon)
- Quotes (FileText icon)
- Reviews (BarChart icon)
- Settings (Settings icon)

**Interactive States:**
- Active nav item: bg-blue-600 rounded-lg
- Hover: bg-gray-800
- Mobile: Collapsible sidebar with hamburger menu

**Reference:**
Similar to: https://tailwindui.com/components/application-ui/application-shells/sidebar

Sub-task 2: Add dashboard metrics cards
Description:
Create metric cards showing key statistics.

**Design:**
- Grid layout (grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6)
- Each card:
  * White background, rounded-lg, shadow-sm
  * Icon in colored circle (top left)
  * Metric value (text-3xl font-bold)
  * Label (text-sm text-gray-600)
  * Trend indicator (green arrow up/red arrow down)

**Metrics to display:**
- Total Quotes (FileText icon, blue)
- Pending Reviews (Clock icon, orange)
- Completed (CheckCircle icon, green)
- Revenue (DollarSign icon, purple)

**Reference:**
https://tailwindui.com/components/application-ui/data-display/stats
```

This level of detail ensures the AI creates a production-ready dashboard, not just placeholder code.

## Related Documentation

- [Story Workflow](./story-workflow.md) - How AI Runner processes tickets
- [Jira Fields and Conventions](./jira-fields-and-conventions.md) - Ticket formatting
