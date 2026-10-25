# Payment System Design
**Date:** 2026-03-02
**Status:** Approved

## Overview

Add a client-facing payment system to the client portal so clients can pay against their outstanding billable hours. Accepts card payments via Stripe Checkout and crypto (BTC, ETH, SOL, USDC, USDT) via Coinbase Commerce. Both processors use hosted checkout pages (client briefly redirected) with webhook callbacks to auto-confirm payment.

---

## Data Model

### App Config (`.env`)

```
HOURLY_RATE=350                      # Firm-wide dollars per billable hour
STRIPE_SECRET_KEY=sk_...
STRIPE_PUBLISHABLE_KEY=pk_...
STRIPE_WEBHOOK_SECRET=whsec_...
COINBASE_COMMERCE_API_KEY=...
COINBASE_COMMERCE_WEBHOOK_SECRET=...
```

### Client Account JSON — new fields

```json
{
  "hours_paid": 0,
  "payments": [
    {
      "date": "YYYY-MM-DD",
      "amount": 350.00,
      "hours_credited": 1.0,
      "method": "stripe",
      "reference": "cs_live_...",
      "note": "Card payment — 1.0 hrs @ $350/hr"
    }
  ]
}
```

`hours_billed` already exists. **Balance due = `(hours_billed - hours_paid) × HOURLY_RATE`.**

---

## Client Portal UI

New **"Billing"** tab in the sidebar nav.

### Balance Summary Card
Displays hours billed, hours paid, and balance due in a stat row matching the existing portal stat styling.

### Pay Now Card (shown only when balance > 0)
- Shows the dollar amount due
- Two buttons: **Pay with Card** and **Pay with Crypto**
- Footnote listing accepted methods: Visa, Mastercard, Amex, ACH · BTC, ETH, SOL, USDC, USDT

**Card flow:** JS calls `POST /portal/client/payment/stripe` → server returns Stripe Checkout URL → `window.location.href` redirects client → on success Stripe redirects to `/client-portal?tab=billing&paid=1` → portal shows a success banner.

**Crypto flow:** JS calls `POST /portal/client/payment/coinbase` → server returns Coinbase Commerce hosted URL → `window.location.href` redirects → on confirmation Coinbase redirects back → same success banner pattern.

### Payment History Table
Columns: Date · Method · Hours Credited · Amount · Reference ID
Rendered from `client.payments` array, newest first.

---

## Flask Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/portal/client/billing` | GET | `@login_required` | Return billing summary JSON |
| `/portal/client/payment/stripe` | POST | `@login_required` | Create Stripe Checkout session |
| `/portal/client/payment/coinbase` | POST | `@login_required` | Create Coinbase Commerce charge |
| `/webhooks/stripe` | POST | Signature only | Handle `checkout.session.completed` |
| `/webhooks/coinbase` | POST | Signature only | Handle `charge:confirmed` |

Webhook routes are **exempt from `@login_required`** — signature verification replaces session auth.

---

## Webhook Logic (both processors)

1. Verify signature (Stripe: `stripe.Webhook.construct_event`; Coinbase: HMAC-SHA256 over raw body)
2. Extract `client_username` from session metadata embedded at charge creation time
3. Calculate `hours_credited = round(amount_paid / HOURLY_RATE, 2)`
4. Update client record:
   - `client["hours_paid"] += hours_credited`
   - Append to `client["payments"]`
   - Append to `client["billing_log"]` with `type: "payment"`
5. `save_client(client)`
6. Return HTTP 200

---

## Security Notes

- Webhook endpoints skip session auth but verify cryptographic signatures — reject any request that fails signature check with HTTP 400
- `HOURLY_RATE` and all API keys stored in `.env`, never committed
- Stripe Checkout and Coinbase Commerce are PCI-compliant hosted pages — no card data touches the Flask server
- Ngrok URL rotates on restart: Stripe and Coinbase webhook URLs must be updated in their dashboards after each ngrok restart

---

## Dependencies to Add

```
stripe
coinbase-commerce
```

(`pip install stripe coinbase-commerce`, add to `requirements.txt`)
