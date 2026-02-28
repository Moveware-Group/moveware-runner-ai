---
name: prisma-database
description: Prisma ORM for database schema design, migrations, querying, and automated database management. Use when working with databases, schema design, migrations, or when Prisma is mentioned.
---

# Prisma Database Management

## Overview

Prisma is a next-generation ORM for Node.js and TypeScript that provides type-safe database access, schema migrations, and a visual database browser (Prisma Studio). This skill covers schema design, migration workflows, and best practices for use with the Prisma MCP server.

## MCP Server (Cursor IDE)

The Prisma MCP server is configured at `.cursor/mcp.json` and runs locally via `npx prisma mcp`.

**Available MCP tools:**
- Introspect database schemas in real-time
- Execute SQL queries directly
- Run and manage migrations
- Create and manage database backups
- Browse data via Prisma Studio
- Manage connection strings and recovery

## Schema Design

### Project Setup

```bash
npm install prisma @prisma/client
npx prisma init
```

### Schema Conventions

```prisma
// prisma/schema.prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String?
  role      Role     @default(USER)
  posts     Post[]
  profile   Profile?
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt @map("updated_at")

  @@map("users")
  @@index([email])
}

model Post {
  id          String     @id @default(cuid())
  title       String
  content     String?
  published   Boolean    @default(false)
  author      User       @relation(fields: [authorId], references: [id], onDelete: Cascade)
  authorId    String     @map("author_id")
  categories  Category[]
  createdAt   DateTime   @default(now()) @map("created_at")
  updatedAt   DateTime   @updatedAt @map("updated_at")

  @@map("posts")
  @@index([authorId])
  @@index([published, createdAt])
}

model Profile {
  id     String @id @default(cuid())
  bio    String?
  avatar String?
  user   User   @relation(fields: [userId], references: [id], onDelete: Cascade)
  userId String @unique @map("user_id")

  @@map("profiles")
}

model Category {
  id    String @id @default(cuid())
  name  String @unique
  slug  String @unique
  posts Post[]

  @@map("categories")
}

enum Role {
  USER
  ADMIN
  MODERATOR
}
```

### Schema Design Rules

1. **Use `cuid()` or `uuid()` for IDs** - Avoid auto-increment for distributed systems
2. **Always add `createdAt`/`updatedAt`** - Track record lifecycle
3. **Use `@@map()` for table names** - Keep SQL snake_case, TypeScript camelCase
4. **Define indexes explicitly** - On foreign keys and frequently queried columns
5. **Set `onDelete` behavior** - `Cascade`, `SetNull`, or `Restrict` on relations
6. **Use enums** - For fixed sets of values (roles, statuses, types)

## Migration Workflow

```bash
# Create migration from schema changes
npx prisma migrate dev --name add_user_role

# Apply migrations in production
npx prisma migrate deploy

# Reset database (dev only)
npx prisma migrate reset

# Check migration status
npx prisma migrate status
```

### Migration Best Practices

- **Never edit applied migrations** - Create new ones instead
- **Review generated SQL** - Check `prisma/migrations/*/migration.sql` before applying
- **Seed data** - Use `prisma/seed.ts` for development data
- **Test migrations** - Run against a staging DB before production

## Querying Patterns

### CRUD Operations

```typescript
import { PrismaClient } from "@prisma/client"

const prisma = new PrismaClient()

// Create with relations
const user = await prisma.user.create({
  data: {
    email: "jane@example.com",
    name: "Jane",
    profile: {
      create: { bio: "Developer" },
    },
  },
  include: { profile: true },
})

// Find with filtering and pagination
const posts = await prisma.post.findMany({
  where: {
    published: true,
    author: { role: "ADMIN" },
  },
  include: {
    author: { select: { name: true, email: true } },
    categories: true,
  },
  orderBy: { createdAt: "desc" },
  take: 20,
  skip: 0,
})

// Update
const updated = await prisma.user.update({
  where: { id: userId },
  data: { role: "ADMIN" },
})

// Upsert
const upserted = await prisma.user.upsert({
  where: { email: "jane@example.com" },
  update: { name: "Jane Updated" },
  create: { email: "jane@example.com", name: "Jane" },
})

// Delete with cascade
await prisma.user.delete({ where: { id: userId } })
```

### Transactions

```typescript
const [user, post] = await prisma.$transaction([
  prisma.user.create({ data: { email: "new@example.com", name: "New" } }),
  prisma.post.create({ data: { title: "First Post", authorId: "..." } }),
])

// Interactive transaction for complex logic
await prisma.$transaction(async (tx) => {
  const sender = await tx.user.update({
    where: { id: senderId },
    data: { balance: { decrement: amount } },
  })
  if (sender.balance < 0) throw new Error("Insufficient funds")

  await tx.user.update({
    where: { id: recipientId },
    data: { balance: { increment: amount } },
  })
})
```

## Singleton Pattern (Next.js)

```typescript
// lib/prisma.ts
import { PrismaClient } from "@prisma/client"

const globalForPrisma = globalThis as unknown as { prisma: PrismaClient }

export const prisma = globalForPrisma.prisma ?? new PrismaClient()

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma
```

## Seeding

```typescript
// prisma/seed.ts
import { PrismaClient } from "@prisma/client"

const prisma = new PrismaClient()

async function main() {
  await prisma.user.upsert({
    where: { email: "admin@example.com" },
    update: {},
    create: {
      email: "admin@example.com",
      name: "Admin",
      role: "ADMIN",
    },
  })
}

main()
  .then(() => prisma.$disconnect())
  .catch(async (e) => {
    console.error(e)
    await prisma.$disconnect()
    process.exit(1)
  })
```

```json
// package.json
{
  "prisma": {
    "seed": "ts-node --compiler-options {\"module\":\"CommonJS\"} prisma/seed.ts"
  }
}
```

## Best Practices

1. **Use Prisma Client extensions** for reusable query logic (soft delete, audit logs)
2. **Enable query logging in dev** - `new PrismaClient({ log: ["query"] })`
3. **Use `select` over `include`** when you only need specific fields
4. **Batch operations** - Use `createMany`, `updateMany`, `deleteMany` for bulk ops
5. **Connection pooling** - Use Prisma Accelerate or PgBouncer in production
6. **Type-safe queries** - Let TypeScript catch schema mismatches at compile time
