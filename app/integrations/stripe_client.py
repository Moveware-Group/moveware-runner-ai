"""
Stripe integration for the AI orchestrator.

Provides Stripe account context, product/price validation, and documentation
retrieval for the LLM when implementing payment features. When a Jira story
involves Stripe, the executor fetches relevant account state (products, prices,
webhook endpoints) so Claude generates code that matches the actual Stripe setup.

Requires environment variables:
  STRIPE_SECRET_KEY - Stripe secret key (sk_test_xxx for dev, sk_live_xxx for prod)

Optional:
  STRIPE_WEBHOOK_SECRET - Webhook signing secret (whsec_xxx)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests


STRIPE_API_BASE = "https://api.stripe.com/v1"

STRIPE_KEYWORDS = [
    "stripe", "payment", "checkout", "subscription", "billing",
    "invoice", "price", "product", "customer portal",
    "webhook", "charge", "refund", "payout",
]


@dataclass
class StripeAccountContext:
    """Stripe account state relevant to code generation."""
    mode: str = ""  # "test" or "live"
    products: List[Dict[str, str]] = field(default_factory=list)
    prices: List[Dict[str, str]] = field(default_factory=list)
    webhook_endpoints: List[Dict[str, Any]] = field(default_factory=list)
    has_customer_portal: bool = False
    account_name: str = ""

    def to_prompt_context(self) -> str:
        """Format as context for injection into LLM prompts."""
        parts = [f"**Stripe Account Context ({self.mode} mode):**"]

        if self.account_name:
            parts.append(f"- Account: {self.account_name}")

        if self.products:
            parts.append("\n**Products:**")
            for p in self.products[:10]:
                parts.append(f"  - `{p['id']}`: {p['name']} ({p.get('status', 'active')})")

        if self.prices:
            parts.append("\n**Prices:**")
            for p in self.prices[:15]:
                amount = p.get("amount", "")
                currency = p.get("currency", "").upper()
                interval = p.get("interval", "one-time")
                product = p.get("product_name", "")
                parts.append(
                    f"  - `{p['id']}`: {amount} {currency}/{interval}"
                    + (f" ({product})" if product else "")
                )

        if self.webhook_endpoints:
            parts.append("\n**Webhook Endpoints:**")
            for wh in self.webhook_endpoints[:5]:
                status = wh.get("status", "")
                url = wh.get("url", "")
                events = ", ".join(wh.get("events", [])[:5])
                parts.append(f"  - {url} [{status}] → {events}")

        if self.has_customer_portal:
            parts.append("\n- Customer Portal: configured")

        parts.append(
            "\n**Use the exact product/price IDs above when implementing Stripe integration.**"
            "\n**Use `sk_test_` keys in code examples, never hardcode live keys.**"
        )

        return "\n".join(parts)


def _get_key() -> Optional[str]:
    return os.getenv("STRIPE_SECRET_KEY")


def _headers() -> dict:
    key = _get_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def is_configured() -> bool:
    """Check whether Stripe integration is configured."""
    return bool(_get_key())


def _get(endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
    """Make a GET request to the Stripe API."""
    key = _get_key()
    if not key:
        return None
    try:
        resp = requests.get(
            f"{STRIPE_API_BASE}/{endpoint}",
            headers=_headers(),
            params=params or {},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Stripe API error ({endpoint}): {e}")
        return None


def fetch_account_context() -> Optional[StripeAccountContext]:
    """
    Fetch current Stripe account state including products, prices,
    and webhook endpoints.
    """
    if not is_configured():
        print("Stripe integration skipped: STRIPE_SECRET_KEY not set")
        return None

    ctx = StripeAccountContext()
    key = _get_key() or ""
    ctx.mode = "test" if "test" in key else "live"

    # Fetch account info
    account = _get("account")
    if account:
        ctx.account_name = account.get("settings", {}).get("dashboard", {}).get("display_name", "")

    # Fetch active products
    products_data = _get("products", {"active": "true", "limit": "10"})
    if products_data:
        for p in products_data.get("data", []):
            ctx.products.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "status": "active" if p.get("active") else "inactive",
                "description": (p.get("description") or "")[:100],
            })

    # Fetch active prices
    prices_data = _get("prices", {"active": "true", "limit": "15", "expand[]": "data.product"})
    if prices_data:
        for p in prices_data.get("data", []):
            amount = p.get("unit_amount")
            if amount is not None:
                amount = f"${amount / 100:.2f}"
            else:
                amount = "custom"

            recurring = p.get("recurring") or {}
            interval = recurring.get("interval", "one-time")

            product = p.get("product", {})
            product_name = product.get("name", "") if isinstance(product, dict) else ""

            ctx.prices.append({
                "id": p.get("id", ""),
                "amount": str(amount),
                "currency": p.get("currency", "usd"),
                "interval": interval,
                "product_name": product_name,
            })

    # Fetch webhook endpoints
    webhooks_data = _get("webhook_endpoints", {"limit": "5"})
    if webhooks_data:
        for wh in webhooks_data.get("data", []):
            ctx.webhook_endpoints.append({
                "url": wh.get("url", ""),
                "status": wh.get("status", ""),
                "events": wh.get("enabled_events", []),
            })

    # Check for customer portal configuration
    try:
        portal_data = _get("billing_portal/configurations", {"limit": "1"})
        if portal_data and portal_data.get("data"):
            ctx.has_customer_portal = True
    except Exception:
        pass

    return ctx


def _is_stripe_task(text: str) -> bool:
    """Detect if a task involves Stripe payment functionality."""
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in STRIPE_KEYWORDS)


def get_stripe_context_for_issue(description: str, summary: str = "") -> str:
    """
    Fetch Stripe account context if the issue involves payment functionality.

    Auto-detects Stripe-related tasks by scanning for keywords like
    "payment", "checkout", "subscription", "stripe", etc.

    Returns formatted context string for LLM prompt injection,
    or empty string if not a Stripe task or API unavailable.
    """
    if not is_configured():
        return ""

    combined = f"{summary} {description}"
    if not _is_stripe_task(combined):
        return ""

    ctx = fetch_account_context()
    if not ctx:
        return ""

    return (
        "\n\n---\n\n"
        + ctx.to_prompt_context()
        + "\n"
    )
