---
name: stripe-payments
description: Stripe payment gateway integration using best practices for checkout, subscriptions, webhooks, and PCI compliance. Use when implementing payments, subscriptions, billing, or when Stripe is mentioned.
---

# Stripe Payments Integration

## Overview

Stripe provides payment processing infrastructure for internet businesses. This skill covers implementation patterns for checkout, subscriptions, webhooks, and PCI-compliant payment flows. The Stripe MCP server in Cursor provides direct access to Stripe APIs and documentation.

## MCP Server (Cursor IDE)

The Stripe MCP server is configured at `.cursor/mcp.json` using Stripe's hosted endpoint. On first use, Cursor will prompt OAuth login to your Stripe account.

**Available MCP tools:**
- Create and manage customers, products, prices, and subscriptions
- Process payments and refunds
- Access Stripe documentation and integration guides
- Query payment data and analytics
- Manage webhooks and events

## Checkout (Stripe Checkout)

### Server-Side Session Creation

```typescript
// app/api/checkout/route.ts
import Stripe from "stripe"
import { NextResponse } from "next/server"

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)

export async function POST(req: Request) {
  const { priceId, customerId } = await req.json()

  const session = await stripe.checkout.sessions.create({
    customer: customerId,
    mode: "subscription", // or "payment" for one-time
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${process.env.NEXT_PUBLIC_URL}/checkout/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.NEXT_PUBLIC_URL}/pricing`,
    allow_promotion_codes: true,
    billing_address_collection: "auto",
    tax_id_collection: { enabled: true },
  })

  return NextResponse.json({ url: session.url })
}
```

### Client-Side Redirect

```tsx
"use client"
import { useState } from "react"

export function CheckoutButton({ priceId }: { priceId: string }) {
  const [loading, setLoading] = useState(false)

  const handleCheckout = async () => {
    setLoading(true)
    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priceId }),
    })
    const { url } = await res.json()
    window.location.href = url
  }

  return (
    <button onClick={handleCheckout} disabled={loading}>
      {loading ? "Redirecting..." : "Subscribe"}
    </button>
  )
}
```

## Webhook Handling

### Webhook Endpoint

```typescript
// app/api/webhooks/stripe/route.ts
import Stripe from "stripe"
import { headers } from "next/headers"

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)

export async function POST(req: Request) {
  const body = await req.text()
  const sig = (await headers()).get("stripe-signature")!

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(
      body,
      sig,
      process.env.STRIPE_WEBHOOK_SECRET!
    )
  } catch (err) {
    return new Response(`Webhook Error: ${(err as Error).message}`, { status: 400 })
  }

  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session
      await handleCheckoutComplete(session)
      break
    }
    case "customer.subscription.updated": {
      const subscription = event.data.object as Stripe.Subscription
      await handleSubscriptionUpdate(subscription)
      break
    }
    case "customer.subscription.deleted": {
      const subscription = event.data.object as Stripe.Subscription
      await handleSubscriptionCanceled(subscription)
      break
    }
    case "invoice.payment_failed": {
      const invoice = event.data.object as Stripe.Invoice
      await handlePaymentFailed(invoice)
      break
    }
  }

  return new Response("OK", { status: 200 })
}

async function handleCheckoutComplete(session: Stripe.Checkout.Session) {
  const customerId = session.customer as string
  const subscriptionId = session.subscription as string

  // Update your database
  await prisma.user.update({
    where: { stripeCustomerId: customerId },
    data: {
      subscriptionId,
      subscriptionStatus: "active",
      plan: "pro",
    },
  })
}

async function handleSubscriptionUpdate(subscription: Stripe.Subscription) {
  await prisma.user.update({
    where: { stripeCustomerId: subscription.customer as string },
    data: {
      subscriptionStatus: subscription.status,
    },
  })
}

async function handleSubscriptionCanceled(subscription: Stripe.Subscription) {
  await prisma.user.update({
    where: { stripeCustomerId: subscription.customer as string },
    data: {
      subscriptionStatus: "canceled",
      plan: "free",
    },
  })
}

async function handlePaymentFailed(invoice: Stripe.Invoice) {
  // Notify the user, send dunning email, etc.
}
```

## Customer Portal

```typescript
// app/api/portal/route.ts
import Stripe from "stripe"

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)

export async function POST(req: Request) {
  const { customerId } = await req.json()

  const session = await stripe.billingPortal.sessions.create({
    customer: customerId,
    return_url: `${process.env.NEXT_PUBLIC_URL}/settings/billing`,
  })

  return Response.json({ url: session.url })
}
```

## Subscription Management

### Creating Products and Prices

```typescript
const product = await stripe.products.create({
  name: "Pro Plan",
  description: "Full access to all features",
})

const monthlyPrice = await stripe.prices.create({
  product: product.id,
  unit_amount: 2900, // $29.00
  currency: "usd",
  recurring: { interval: "month" },
})

const yearlyPrice = await stripe.prices.create({
  product: product.id,
  unit_amount: 29000, // $290.00 (save ~17%)
  currency: "usd",
  recurring: { interval: "year" },
})
```

### Subscription Status Check Middleware

```typescript
// middleware.ts or lib/auth.ts
export async function requireActiveSubscription(userId: string) {
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { subscriptionStatus: true, plan: true },
  })

  if (!user || user.subscriptionStatus !== "active") {
    throw new Error("Active subscription required")
  }

  return user
}
```

## Environment Variables

```
STRIPE_SECRET_KEY=sk_live_xxx        # or sk_test_xxx for development
STRIPE_PUBLISHABLE_KEY=pk_live_xxx   # or pk_test_xxx for development
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

## Testing

```bash
# Install Stripe CLI
brew install stripe/stripe-cli/stripe   # macOS
# or download from https://stripe.com/docs/stripe-cli

# Login
stripe login

# Forward webhooks to local server
stripe listen --forward-to localhost:3000/api/webhooks/stripe

# Trigger test events
stripe trigger checkout.session.completed
stripe trigger customer.subscription.updated
stripe trigger invoice.payment_failed
```

## Best Practices

1. **Always verify webhooks** - Use `stripe.webhooks.constructEvent()` with the signing secret
2. **Idempotent handlers** - Stripe may send the same event multiple times; handle gracefully
3. **Use test mode** - All development with `sk_test_` keys; never use live keys locally
4. **Customer portal** - Let Stripe handle subscription management UI when possible
5. **Price IDs, not amounts** - Reference `price_xxx` IDs, not hardcoded dollar amounts
6. **Metadata** - Store your internal IDs in Stripe metadata for easy cross-referencing
7. **Error handling** - Catch `Stripe.errors.StripeError` for API-specific error handling
8. **PCI compliance** - Never handle raw card numbers; use Stripe Checkout or Elements
9. **Tax collection** - Enable Stripe Tax for automatic tax calculation
10. **Dunning** - Configure Smart Retries and email reminders for failed payments
