---
name: nextjs-fullstack-dev
description: Next.js 13+ full-stack development with App Router, Server Components, and modern React patterns. Use when building Next.js apps, working with App Router, Server Actions, or when the user mentions Next.js, React Server Components, or full-stack React development.
---

# Next.js Full-Stack Developer

## App Router Architecture

Follow Next.js 13+ App Router conventions:

### Directory Structure
```
app/
├── layout.tsx           # Root layout
├── page.tsx            # Home page
├── (auth)/             # Route groups (no URL segment)
│   ├── login/
│   └── register/
├── api/                # API routes
│   └── route.ts
└── [id]/               # Dynamic routes
    └── page.tsx
```

### Server vs Client Components

**Default to Server Components** - only use Client Components when necessary:

```typescript
// Server Component (default) - no 'use client'
export default async function Page() {
  const data = await fetch('https://api.example.com/data')
  return <div>{data}</div>
}

// Client Component - add 'use client' for:
// - useState, useEffect, event handlers
// - Browser APIs, interactivity
'use client'
export default function InteractiveButton() {
  const [count, setCount] = useState(0)
  return <button onClick={() => setCount(count + 1)}>{count}</button>
}
```

## Data Fetching Patterns

### Server Components (Recommended)
```typescript
// app/posts/page.tsx
async function getPosts() {
  const res = await fetch('https://api.example.com/posts', {
    cache: 'no-store', // Dynamic
    // OR cache: 'force-cache', // Static
    // OR next: { revalidate: 60 }, // ISR
  })
  return res.json()
}

export default async function PostsPage() {
  const posts = await getPosts()
  return <PostList posts={posts} />
}
```

### Client Components
```typescript
'use client'
import { useEffect, useState } from 'react'

export default function ClientData() {
  const [data, setData] = useState(null)
  
  useEffect(() => {
    fetch('/api/data').then(r => r.json()).then(setData)
  }, [])
  
  return <div>{data?.title}</div>
}
```

## Server Actions

Use for form submissions and mutations:

```typescript
// app/actions.ts
'use server'

export async function createPost(formData: FormData) {
  const title = formData.get('title')
  
  // Validate
  if (!title) {
    return { error: 'Title required' }
  }
  
  // Mutate
  await db.post.create({ data: { title } })
  
  // Revalidate cache
  revalidatePath('/posts')
  
  return { success: true }
}

// app/new/page.tsx
import { createPost } from '../actions'

export default function NewPost() {
  return (
    <form action={createPost}>
      <input name="title" required />
      <button type="submit">Create</button>
    </form>
  )
}
```

## API Routes

```typescript
// app/api/posts/route.ts
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const query = searchParams.get('query')
  
  const posts = await db.post.findMany({
    where: { title: { contains: query } }
  })
  
  return NextResponse.json(posts)
}

export async function POST(request: NextRequest) {
  const body = await request.json()
  const post = await db.post.create({ data: body })
  return NextResponse.json(post, { status: 201 })
}

// Dynamic routes: app/api/posts/[id]/route.ts
export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  const post = await db.post.findUnique({ where: { id: params.id } })
  if (!post) return NextResponse.json({ error: 'Not found' }, { status: 404 })
  return NextResponse.json(post)
}
```

## Authentication Patterns

### Middleware for Protected Routes
```typescript
// middleware.ts
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const token = request.cookies.get('auth-token')
  
  if (!token) {
    return NextResponse.redirect(new URL('/login', request.url))
  }
  
  return NextResponse.next()
}

export const config = {
  matcher: ['/dashboard/:path*', '/api/protected/:path*']
}
```

### Session Handling
```typescript
// lib/auth.ts
import { cookies } from 'next/headers'

export async function getSession() {
  const token = cookies().get('auth-token')?.value
  if (!token) return null
  return verifyToken(token)
}

// app/dashboard/page.tsx
import { getSession } from '@/lib/auth'
import { redirect } from 'next/navigation'

export default async function Dashboard() {
  const session = await getSession()
  if (!session) redirect('/login')
  
  return <div>Welcome {session.user.name}</div>
}
```

## Loading and Error States

```typescript
// app/posts/loading.tsx
export default function Loading() {
  return <div>Loading posts...</div>
}

// app/posts/error.tsx
'use client'
export default function Error({
  error,
  reset,
}: {
  error: Error
  reset: () => void
}) {
  return (
    <div>
      <h2>Something went wrong!</h2>
      <button onClick={reset}>Try again</button>
    </div>
  )
}
```

## Metadata and SEO

```typescript
// Static metadata
export const metadata = {
  title: 'My App',
  description: 'App description',
}

// Dynamic metadata
export async function generateMetadata({ params }) {
  const post = await getPost(params.id)
  return {
    title: post.title,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      description: post.excerpt,
      images: [{ url: post.image }],
    },
  }
}
```

## Environment Variables

```typescript
// Access in Server Components and API Routes
const apiKey = process.env.API_KEY

// For Client Components - prefix with NEXT_PUBLIC_
const publicKey = process.env.NEXT_PUBLIC_STRIPE_KEY
```

## Performance Best Practices

1. **Use Server Components by default** - faster initial load
2. **Parallel data fetching** - use Promise.all in Server Components
3. **Image optimization** - always use next/image
4. **Font optimization** - use next/font
5. **Code splitting** - dynamic imports for heavy components

```typescript
import dynamic from 'next/dynamic'

const HeavyChart = dynamic(() => import('@/components/Chart'), {
  loading: () => <p>Loading chart...</p>,
  ssr: false, // Disable SSR if needed
})
```

## Database Integration

### Prisma Pattern
```typescript
// lib/db.ts
import { PrismaClient } from '@prisma/client'

const globalForPrisma = global as unknown as { prisma: PrismaClient }

export const prisma = globalForPrisma.prisma || new PrismaClient()

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = prisma
```

## Testing Considerations

- Use Playwright for E2E testing (see qa-tester skill)
- Test Server Actions independently
- Mock fetch calls in Server Component tests
- Test API routes with supertest or similar

## Common Pitfalls

❌ **Don't:** Import 'use client' components into Server Components unnecessarily
✅ **Do:** Keep Client Components at the leaf level

❌ **Don't:** Use useEffect for data fetching in Server Components
✅ **Do:** Use async/await directly in Server Components

❌ **Don't:** Forget to revalidate after mutations
✅ **Do:** Use revalidatePath() or revalidateTag() in Server Actions

❌ **Don't:** Put sensitive data in NEXT_PUBLIC_ variables
✅ **Do:** Keep secrets in server-only environment variables
