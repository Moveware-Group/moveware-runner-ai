"""
Vercel Engineering best practices for the AI orchestrator.

Provides Next.js and React best-practice guidance from Vercel Engineering
as structured context for the LLM during code generation. This is injected
into the executor prompt for any Next.js/React project so Claude follows
modern patterns for performance, security, and code quality.

No API token required - this module is self-contained.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Dict


# Always available - no external credentials needed
def is_configured() -> bool:
    return True


BEST_PRACTICES = """
## Vercel Engineering — Next.js / React Best Practices

### App Router & Server Components (Next.js 13+)
- Default to Server Components; add "use client" only when the component needs
  browser APIs, event handlers, useState, or useEffect.
- Use `loading.tsx` for streaming / Suspense boundaries per route segment.
- Use `error.tsx` + `not-found.tsx` for graceful error and 404 handling.
- Co-locate related files: `page.tsx`, `layout.tsx`, `loading.tsx`, `error.tsx`
  inside each route folder.

### Data Fetching
- Fetch data in Server Components using `async/await` directly — no useEffect.
- Use `fetch()` with Next.js caching: `{ next: { revalidate: 60 } }` for ISR,
  `{ cache: "no-store" }` for dynamic data.
- For mutations use Server Actions (`"use server"`) instead of API routes
  when the caller is a Server Component or form.
- Deduplicate requests with `React.cache()` or Next.js automatic fetch dedup.

### Rendering Strategies
- **Static (SSG):** Default for pages with no dynamic data. Generates at build time.
- **ISR:** Use `revalidate` option for content that changes periodically.
- **Dynamic:** Use `export const dynamic = "force-dynamic"` or `cookies()`/`headers()`
  when every request must be unique.
- Prefer Partial Prerendering (PPR) where supported — static shell + streaming dynamic.

### Performance
- Use `next/image` for all images (automatic WebP/AVIF, lazy loading, sizing).
- Use `next/font` for fonts (zero layout shift, self-hosted, no external requests).
- Use `next/link` for client-side navigation (automatic prefetching).
- Use dynamic imports (`next/dynamic`) for heavy components below the fold.
- Minimize client-side JavaScript: keep "use client" boundaries as small as possible.
- Use `<Suspense>` boundaries to stream slow parts independently.
- Avoid barrel files (`index.ts` re-exports) that prevent tree-shaking.

### Metadata & SEO
- Use the Metadata API (`export const metadata` or `generateMetadata()`) in layouts/pages.
- Include `title`, `description`, `openGraph`, and `twitter` metadata.
- Add `robots.ts` and `sitemap.ts` at the app root for search engines.
- Use semantic HTML elements (`<main>`, `<article>`, `<nav>`, `<section>`).

### API Routes & Server Actions
- Place API routes under `app/api/` using Route Handlers (`route.ts`).
- Always validate input (use Zod or similar) in both API routes and Server Actions.
- Return proper HTTP status codes and structured error responses.
- Use `NextResponse.json()` for responses.
- For forms: prefer Server Actions with `useFormState` and `useFormStatus`
  over manual fetch to API routes.

### Authentication & Middleware
- Use `middleware.ts` at the project root for auth checks, redirects, and headers.
- Keep middleware lightweight — it runs on every matched request.
- Use `matcher` config to scope middleware to specific routes.
- Store sessions in HTTP-only cookies, not localStorage.

### Styling
- Use Tailwind CSS with the `tailwind.config.ts` file for theme customization.
- Use CSS Modules (`*.module.css`) for component-scoped styles when not using Tailwind.
- Avoid runtime CSS-in-JS (styled-components, Emotion) in Server Components.
- Use CSS variables for theming (dark mode, brand colors).

### TypeScript
- Enable strict mode in `tsconfig.json`.
- Type all props, API responses, and Server Action return values.
- Use `satisfies` operator for type-safe config objects.
- Use Zod schemas for runtime validation that generates TypeScript types.

### Error Handling
- Wrap data fetches in try/catch with meaningful error messages.
- Use `error.tsx` boundaries per route for graceful degradation.
- Log errors server-side; show user-friendly messages client-side.
- Use `notFound()` from `next/navigation` for missing resources (triggers `not-found.tsx`).

### Security
- Never expose secrets to the client — only `NEXT_PUBLIC_*` vars are bundled.
- Validate and sanitize all user input server-side.
- Use Content Security Policy headers via `next.config.js` or middleware.
- Use `HttpOnly`, `Secure`, `SameSite=Lax` for session cookies.
- Escape user content to prevent XSS (React does this by default, but watch
  `dangerouslySetInnerHTML`).

### Project Structure
```
app/
  (marketing)/        ← Route groups for shared layouts
    page.tsx
    about/page.tsx
  (dashboard)/
    layout.tsx        ← Dashboard-specific layout with sidebar
    page.tsx
    settings/page.tsx
  api/
    auth/route.ts
    webhooks/stripe/route.ts
  layout.tsx          ← Root layout (html, body, providers)
  not-found.tsx
  error.tsx
  loading.tsx
components/
  ui/                 ← Reusable UI primitives (Button, Card, Input)
  features/           ← Feature-specific components
lib/
  db.ts               ← Database client (Prisma singleton)
  auth.ts             ← Auth helpers
  utils.ts            ← Shared utilities
  validations.ts      ← Zod schemas
```

### Common Anti-Patterns to Avoid
- Using `useEffect` for data fetching (use Server Components or SWR/React Query).
- Putting "use client" at the top of every file.
- Using `<img>` instead of `next/image`.
- Using `<a>` instead of `next/link`.
- Fetching data in layouts then passing via props (use parallel data fetching).
- Large client bundles from importing entire libraries (use tree-shakeable imports).
- Hardcoding environment values instead of using `process.env`.
- Skipping error boundaries and loading states.
""".strip()


def _detect_nextjs_project(repo_path: Path) -> bool:
    """Check if the repo is a Next.js project."""
    indicators = [
        repo_path / "next.config.js",
        repo_path / "next.config.mjs",
        repo_path / "next.config.ts",
        repo_path / "app" / "layout.tsx",
        repo_path / "app" / "layout.jsx",
        repo_path / "app" / "page.tsx",
        repo_path / "pages" / "_app.tsx",
    ]
    return any(p.exists() for p in indicators)


def _detect_react_project(repo_path: Path) -> bool:
    """Check if the repo is a React project (non-Next.js)."""
    pkg_path = repo_path / "package.json"
    if not pkg_path.exists():
        return False
    try:
        import json
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        return "react" in deps
    except Exception:
        return False


def get_vercel_context_for_issue(
    description: str,
    summary: str = "",
    repo_name: str = "",
    repo_path: Optional[str] = None,
    skills: Optional[List[str]] = None,
) -> str:
    """
    Return Vercel Engineering best practices if the project is Next.js/React.

    Detection is based on:
    1. Skills list containing "nextjs-fullstack-dev"
    2. Next.js config files in the repo
    3. React in package.json dependencies

    No API token required — this is a self-contained best-practice reference.

    Returns formatted context string for LLM prompt injection,
    or empty string if the project isn't Next.js/React.
    """
    # Quick check via skills list (fastest path)
    if skills and "nextjs-fullstack-dev" in skills:
        return _format_context()

    # Check via repo filesystem
    if repo_path:
        path = Path(repo_path)
        if _detect_nextjs_project(path) or _detect_react_project(path):
            return _format_context()

    # Check via task content keywords
    combined = f"{summary} {description}".lower()
    nextjs_keywords = [
        "next.js", "nextjs", "next js", "app router", "server component",
        "server action", "react server", "use client", "use server",
    ]
    if any(kw in combined for kw in nextjs_keywords):
        return _format_context()

    return ""


def _format_context() -> str:
    return (
        "\n\n---\n\n"
        + BEST_PRACTICES
        + "\n\n**Follow the Vercel Engineering best practices above for all "
        "Next.js/React code in this task.**\n"
    )
