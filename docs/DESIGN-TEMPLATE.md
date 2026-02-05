# Design System Template

Copy this to your Next.js repository as `DESIGN.md` to provide consistent design guidance for the AI Runner.

---

# [Your App Name] Design System

## Brand Identity

### Colors

**Primary Palette:**
- Primary Blue: `#2563eb` (Tailwind: `bg-blue-600`)
- Primary Hover: `#1d4ed8` (Tailwind: `bg-blue-700`)
- Primary Light: `#60a5fa` (Tailwind: `bg-blue-400`)

**Neutral Palette:**
- Background: `#f9fafb` (Tailwind: `bg-gray-50`)
- Surface: `#ffffff` (Tailwind: `bg-white`)
- Border: `#e5e7eb` (Tailwind: `border-gray-200`)
- Text Primary: `#111827` (Tailwind: `text-gray-900`)
- Text Secondary: `#6b7280` (Tailwind: `text-gray-600`)
- Text Muted: `#9ca3af` (Tailwind: `text-gray-400`)

**Semantic Colors:**
- Success: `#10b981` (Tailwind: `bg-green-500`)
- Warning: `#f59e0b` (Tailwind: `bg-amber-500`)
- Error: `#ef4444` (Tailwind: `bg-red-500`)
- Info: `#3b82f6` (Tailwind: `bg-blue-500`)

### Typography

**Font Family:**
- Primary: `Inter` (Google Fonts or next/font)
- Monospace: `'Fira Code', monospace`

**Font Scales:**
```tsx
// Headings
text-4xl font-bold  // Hero heading (36px)
text-3xl font-bold  // Page heading (30px)
text-2xl font-bold  // Section heading (24px)
text-xl font-semibold  // Subsection heading (20px)
text-lg font-semibold  // Card heading (18px)

// Body
text-base font-normal  // Body text (16px)
text-sm font-normal    // Small text (14px)
text-xs font-normal    // Caption (12px)
```

**Font Weights:**
- Regular: `font-normal` (400)
- Medium: `font-medium` (500)
- Semibold: `font-semibold` (600)
- Bold: `font-bold` (700)

## Layout

### Container

```tsx
<div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
  {/* Content */}
</div>
```

**Breakpoints:**
- Mobile: `< 640px`
- Tablet: `>= 640px` (sm:)
- Desktop: `>= 1024px` (lg:)
- Wide: `>= 1280px` (xl:)

### Spacing Scale

```tsx
// Padding/Margin
p-2   // 8px
p-4   // 16px
p-6   // 24px
p-8   // 32px
p-12  // 48px
p-16  // 64px
p-20  // 80px

// Component-specific
py-12 sm:py-16 lg:py-20  // Section vertical padding
space-y-6                 // Stack spacing
gap-6                     // Grid gap
```

### Page Structure

```tsx
<div className="min-h-screen bg-gray-50">
  {/* Header */}
  <header className="bg-white shadow-sm">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      {/* Navigation */}
    </div>
  </header>

  {/* Main Content */}
  <main className="py-12">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      {/* Page content */}
    </div>
  </main>

  {/* Footer */}
  <footer className="bg-white border-t border-gray-200">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Footer content */}
    </div>
  </footer>
</div>
```

## Components

### Button

**Primary Button:**
```tsx
<button className="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-6 rounded-lg shadow-md hover:shadow-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed">
  Button Text
</button>
```

**Secondary Button:**
```tsx
<button className="bg-white hover:bg-gray-50 text-gray-700 font-semibold py-3 px-6 rounded-lg border border-gray-300 shadow-sm hover:shadow-md transition-all duration-200">
  Button Text
</button>
```

**Ghost Button:**
```tsx
<button className="text-blue-600 hover:text-blue-700 hover:bg-blue-50 font-semibold py-2 px-4 rounded-lg transition-all duration-200">
  Button Text
</button>
```

### Card

**Standard Card:**
```tsx
<div className="bg-white rounded-xl shadow-md p-6 hover:shadow-lg transition-shadow duration-200">
  {/* Card content */}
</div>
```

**Interactive Card (clickable):**
```tsx
<div className="bg-white rounded-xl shadow-md p-6 hover:shadow-xl hover:scale-[1.02] transition-all duration-200 cursor-pointer">
  {/* Card content */}
</div>
```

### Form Input

**Text Input:**
```tsx
<div className="space-y-2">
  <label htmlFor="email" className="block text-sm font-medium text-gray-700">
    Email Address
  </label>
  <input
    type="email"
    id="email"
    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
    placeholder="you@example.com"
  />
</div>
```

**Input with Error:**
```tsx
<div className="space-y-2">
  <label htmlFor="email" className="block text-sm font-medium text-gray-700">
    Email Address
  </label>
  <input
    type="email"
    id="email"
    className="w-full px-4 py-3 border border-red-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
    placeholder="you@example.com"
  />
  <p className="text-sm text-red-600">Please enter a valid email address</p>
</div>
```

### Badge

```tsx
// Status badges
<span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
  Active
</span>

<span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-yellow-100 text-yellow-800">
  Pending
</span>

<span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-800">
  Inactive
</span>
```

### Alert

**Success Alert:**
```tsx
<div className="bg-green-50 border border-green-200 rounded-lg p-4">
  <div className="flex items-start">
    <CheckCircle className="h-5 w-5 text-green-500 mt-0.5" />
    <div className="ml-3">
      <h3 className="text-sm font-medium text-green-800">Success</h3>
      <p className="text-sm text-green-700 mt-1">Your changes have been saved.</p>
    </div>
  </div>
</div>
```

**Error Alert:**
```tsx
<div className="bg-red-50 border border-red-200 rounded-lg p-4">
  <div className="flex items-start">
    <AlertCircle className="h-5 w-5 text-red-500 mt-0.5" />
    <div className="ml-3">
      <h3 className="text-sm font-medium text-red-800">Error</h3>
      <p className="text-sm text-red-700 mt-1">Something went wrong. Please try again.</p>
    </div>
  </div>
</div>
```

### Loading Spinner

```tsx
<div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-blue-600 border-r-transparent"></div>
```

### Navigation

**Header Navigation:**
```tsx
<nav className="flex items-center space-x-8">
  <a href="/" className="text-gray-700 hover:text-blue-600 font-medium transition-colors">
    Home
  </a>
  <a href="/quotes" className="text-gray-700 hover:text-blue-600 font-medium transition-colors">
    Quotes
  </a>
  <a href="/performance" className="text-gray-700 hover:text-blue-600 font-medium transition-colors">
    Performance
  </a>
</nav>
```

## Common Patterns

### Hero Section

```tsx
<section className="bg-gradient-to-r from-blue-600 to-blue-800 text-white">
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 sm:py-24 lg:py-32">
    <div className="max-w-3xl">
      <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6">
        Welcome to [Your App]
      </h1>
      <p className="text-xl sm:text-2xl text-blue-100 mb-8">
        Transform your workflow with our modern platform
      </p>
      <div className="flex flex-col sm:flex-row gap-4">
        <button className="bg-white text-blue-600 hover:bg-blue-50 font-semibold py-3 px-8 rounded-lg shadow-lg transition-all duration-200">
          Get Started
        </button>
        <button className="bg-blue-700 hover:bg-blue-600 text-white font-semibold py-3 px-8 rounded-lg border-2 border-blue-400 transition-all duration-200">
          Learn More
        </button>
      </div>
    </div>
  </div>
</section>
```

### Feature Grid

```tsx
<section className="py-20">
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div className="text-center mb-12">
      <h2 className="text-3xl font-bold text-gray-900 mb-4">Features</h2>
      <p className="text-xl text-gray-600">Everything you need in one place</p>
    </div>
    
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
      {/* Feature Card */}
      <div className="bg-white rounded-xl shadow-md p-8 hover:shadow-lg transition-shadow duration-200">
        <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mb-4">
          <Icon className="w-6 h-6 text-blue-600" />
        </div>
        <h3 className="text-xl font-bold text-gray-900 mb-2">Feature Title</h3>
        <p className="text-gray-600">Feature description goes here</p>
      </div>
      {/* Repeat for other features */}
    </div>
  </div>
</section>
```

### Stats/Metrics

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
  <div className="bg-white rounded-xl shadow-md p-6">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-gray-600">Total Users</p>
        <p className="text-3xl font-bold text-gray-900 mt-2">1,234</p>
      </div>
      <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
        <Users className="w-6 h-6 text-blue-600" />
      </div>
    </div>
    <div className="flex items-center mt-4 text-sm">
      <TrendingUp className="w-4 h-4 text-green-500 mr-1" />
      <span className="text-green-600 font-medium">12%</span>
      <span className="text-gray-600 ml-2">vs last month</span>
    </div>
  </div>
  {/* Repeat for other metrics */}
</div>
```

## Icons

**Recommended Library:** [Lucide React](https://lucide.dev/guide/packages/lucide-react)

```bash
npm install lucide-react
```

```tsx
import { Home, User, Settings, ChevronRight } from 'lucide-react'

<Home className="w-5 h-5" />
```

## Animations

**Preferred Transitions:**
```tsx
transition-all duration-200      // Fast interaction
transition-all duration-300      // Standard
transition-all duration-500      // Slow/smooth
```

**Hover Effects:**
```tsx
hover:scale-105          // Slight grow
hover:scale-[1.02]       // Subtle grow
hover:-translate-y-1     // Lift up
hover:shadow-lg          // Shadow increase
```

## Accessibility

**Always Include:**
- Semantic HTML (`<button>`, `<nav>`, `<main>`, `<header>`)
- ARIA labels for icon-only buttons
- Keyboard navigation (focus states)
- Sufficient color contrast (WCAG AA minimum)
- Alt text for images
- Form labels for inputs

**Focus States:**
```tsx
focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
```

## References

**Inspiration:**
- [Tailwind UI](https://tailwindui.com/components) - Component patterns
- [Vercel](https://vercel.com) - Clean, modern SaaS design
- [Stripe](https://stripe.com) - Professional interface design

**Tools:**
- [Tailwind CSS](https://tailwindcss.com/docs) - Utility classes
- [Lucide Icons](https://lucide.dev) - Icon library
- [Headless UI](https://headlessui.com) - Unstyled components
