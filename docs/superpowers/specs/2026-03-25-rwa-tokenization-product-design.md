# RWA Tokenization Service Product — Design Spec

**Date:** 2026-03-25
**Status:** Approved
**Approach:** Integrated — public page + client portal card + attorney asset valuation

---

## Overview

Add a full-service RWA (Real World Asset) Tokenization product as a one-time service offering. Includes a public marketing page, client portal payment flow (deposit + remainder), attorney-side asset valuation, and fee schedule update.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Service scope | Full-service (legal + token deployment coordination) | User decision |
| Pricing model | Tiered by asset value | Industry standard, scales with deal size |
| Tiers | <$500K=5%, $500K-$2M=3%, $2M-$10M=1.5%, $10M+=Custom | User approved |
| Payment flow | $2,500 deposit upfront, remainder after attorney sets asset value | Attorney controls valuation |
| Deposit amount | $2,500 | User decision |
| Visibility | Public page + client portal | Marketing + payment in one |

---

## Section 1: Public Tokenization Page

### New Route

`GET /tokenization` — serves `templates/tokenization.html`

No auth required (public-facing).

### Page Content

- **Hero section:** Headline "Real World Asset Tokenization", brief description of full-service offering
- **What's included:**
  - Securities exemption analysis (Reg D, Reg A+, Reg S, Reg CF)
  - Private Placement Memorandum (PPM) drafting
  - Smart contract legal review
  - Token deployment coordination
  - Investor onboarding documentation
  - Ongoing compliance support
- **Tiered fee table:**

| Asset Value | Fee |
|---|---|
| Under $500K | 5% |
| $500K – $2M | 3% |
| $2M – $10M | 1.5% |
| $10M+ | Custom / negotiated |

- **Deposit note:** "$2,500 retainer deposit to begin"
- **CTA button:** Links to `/intake`
- **Disclaimers:**
  - This is legal information, not legal advice, until a formal engagement letter is signed
  - DeFi law is rapidly evolving — always verify current SEC/CFTC guidance
  - Smart contract code review by a qualified Solidity auditor is recommended alongside legal review
  - Tax advice requires a CPA or tax attorney — this firm can refer

### Styling

Uses `base.html` layout, matches existing page styles (same CSS, same nav).

---

## Section 2: Client Portal — Tokenization Service Card

### Location

`templates/client_portal.html` billing tab. New card visible only when `case_type == "DeFi / Crypto Law"`.

### Card Content

- **Title:** "Tokenization Service"
- **Tier table:** Same fee breakpoints as public page
- **Deposit status:**
  - If no `tokenization_deposit` payment exists: "Pay $2,500 Deposit" button → Stripe checkout
  - If deposit paid: Green "Deposit received" with date
- **Remainder section:**
  - If `asset_value` not set on client record: "Your attorney will provide a valuation and final fee after consultation."
  - If `tokenization_tier == "Custom"`: "Your asset is valued at $X. Due to the size of this engagement, your attorney will provide a custom fee proposal."
  - If calculated remainder <= 0: "Your deposit covers the full fee. No additional payment required."
  - If `asset_value` set and remainder > 0 and not paid: Show calculated fee, minus deposit, with "Pay Remainder" button → Stripe checkout
  - If remainder paid: Green "Paid in full" with date

### Conditional Display

Card rendered server-side via Jinja (`{% if client.case_type == "DeFi / Crypto Law" %}`) using the `client` object already passed to the template at render time. Deposit/remainder status checked by scanning `client.payments` in Jinja for entries with matching `type` values. Other case types see the billing tab as-is.

### Success Banners

The existing JS checks `params.get("paid") === "1"` for the payment success banner. Add handling for `?paid=deposit` ("Tokenization deposit received — thank you!") and `?paid=remainder` ("Tokenization payment complete — thank you!").

---

## Section 3: Attorney Portal — Set Asset Value

### Location

`templates/attorney_portal.html` — client info panel, visible when viewing a DeFi / Crypto Law client.

### UI

- "Asset Valuation" label with a number input field
- On save, shows calculated tier percentage and total fee as read-only
- Attorney can verify before committing

### New Route

`POST /portal/attorney/client/asset-value`

- **Input:** `{ "username": "...", "asset_value": 750000 }`
- **Logic:**
  - Calculates tier: <$500K → "5%", $500K-$2M → "3%", $2M-$10M → "1.5%", $10M+ → "Custom"
  - Calculates fee: `asset_value * tier_percentage` (for Custom tier, fee is `null` — attorney must negotiate separately)
  - Validates: `asset_value` must be a positive number
  - Saves `asset_value` and `tokenization_tier` on client record
- **Output:** `{ "success": true, "asset_value": 750000, "tier": "3%", "fee": 22500 }`
- **Output (Custom tier):** `{ "success": true, "asset_value": 15000000, "tier": "Custom", "fee": null }`
- **Auth:** `@require_attorney`

---

## Section 4: Stripe Checkout — Deposit & Remainder

### Deposit Route

`POST /portal/client/payment/tokenization-deposit`

- **Auth:** `@require_auth` + manual role check (`session.get("role") != "client"` → 401), matching existing payment routes
- **Guards:**
  - Returns error if deposit already paid (checks `payments[]` for `type: "tokenization_deposit"`)
  - Idempotency: also checks if Stripe session reference already exists in `payments[]`
- **Stripe Checkout Session:**
  - Mode: `"payment"`
  - Amount: 250000 cents ($2,500)
  - Product name: `"RWA Tokenization — Retainer Deposit"`
  - Metadata: `{ "client_username": "...", "payment_type": "tokenization_deposit" }`
  - Success URL: `/client-portal?tab=billing&paid=deposit`
  - Cancel URL: `/client-portal?tab=billing`
- **Returns:** `{ "checkout_url": "https://checkout.stripe.com/..." }`

### Remainder Route

`POST /portal/client/payment/tokenization-remainder`

- **Auth:** `@require_auth` + manual role check, matching existing payment routes
- **Guards:**
  - Returns error if `asset_value` not set on client record
  - Returns error if deposit not paid
  - Returns error if remainder already paid
  - Returns error if `tokenization_tier == "Custom"` (Custom tier requires manual invoicing)
  - Returns error if calculated remainder <= 0 (deposit fully covers fee)
- **Calculation:** `fee = asset_value * tier_percentage`, `remainder = fee - 2500`
- **Guard:** If `remainder <= 0`, return `{ "error": "Deposit covers the full fee. No additional payment required." }`
- **Stripe Checkout Session:**
  - Mode: `"payment"`
  - Amount: `int(remainder * 100)` cents
  - Product name: `"RWA Tokenization — Remainder ({tier} of ${asset_value:,.0f})"`
  - Metadata: `{ "client_username": "...", "payment_type": "tokenization_remainder" }`
  - Success URL: `/client-portal?tab=billing&paid=remainder`
  - Cancel URL: `/client-portal?tab=billing`
- **Returns:** `{ "checkout_url": "https://checkout.stripe.com/..." }`

### Webhook Update

Existing webhook handler at `/webhooks/stripe` processes `checkout.session.completed`.

**Changes to webhook handler:**
1. Extract `payment_type` from `obj.metadata.get("payment_type", "payment")` (defaults to `"payment"` for existing hourly flows)
2. Check for duplicate delivery: if `reference` (session ID) already exists in client's `payments[]`, skip processing
3. Pass `payment_type` to `_apply_payment()`

**Changes to `_apply_payment()`:**
Add a `payment_type` parameter (default `"payment"`). Branch behavior:

- **If `payment_type` is `"payment"` (existing hourly):** Current behavior unchanged — calculate `hours_credited`, update `hours_paid`, standard note
- **If `payment_type` is `"tokenization_deposit"` or `"tokenization_remainder"`:** Do NOT credit hours. Set `hours_credited: 0`. Do NOT modify `hours_paid`. Use descriptive note (e.g., "RWA Tokenization — Retainer Deposit" or "RWA Tokenization — Remainder"). Store `type` as the `payment_type` value instead of `"payment"`

---

## Section 5: Fee Schedule Update

### Location

`templates/client_portal.html` — existing fee schedule modal.

### Addition

The existing fee schedule is rendered via JavaScript with `toFixed(2)` on the cost column, so a string value would break. Instead, add the tokenization entry as a separate HTML block below the existing table (outside the JS-rendered rows):

- A horizontal rule or section divider
- Text: **"RWA Tokenization (Full-Service)"**
- Tier table inline (same as public page)
- Note: "$2,500 retainer deposit required to begin."

---

## New Client Record Fields

Two new fields on the client JSON object (both default to `null`):

- `asset_value` — number, set by attorney via `/portal/attorney/client/asset-value`
- `tokenization_tier` — string, auto-calculated ("5%", "3%", "1.5%", or "Custom")

---

## Files Modified

| File | Changes |
|------|---------|
| `app.py` | Add `/tokenization` route, `/portal/client/payment/tokenization-deposit` route, `/portal/client/payment/tokenization-remainder` route, `/portal/attorney/client/asset-value` route, update `_apply_payment()` to store payment_type |
| `templates/tokenization.html` | New file — public tokenization service page |
| `templates/client_portal.html` | Add tokenization service card to billing tab, update fee schedule modal |
| `templates/attorney_portal.html` | Add asset valuation section to client info panel |

## Files NOT Modified

- `static/js/app.js` — new JS can be inline in templates following existing patterns
- `static/css/style.css` — existing styles sufficient
- `templates/base.html` — no nav link added; `/tokenization` page is discoverable via homepage or direct link, not primary nav (keeping nav clean)

## Deferred (v1 acceptable as-is)

- **Coinbase payment for tokenization** — Only Stripe checkout is supported for deposit and remainder in v1. Coinbase Commerce could be added later with equivalent routes.
- **Attorney dashboard tokenization status** — No quick indicator on the client list cards. Attorney must open client info to see deposit/valuation status. Can be added later.

---

## Testing

- [ ] `/tokenization` page loads publicly with tier table, service list, disclaimers, and CTA
- [ ] Client portal billing tab shows tokenization card only for DeFi / Crypto Law clients
- [ ] Non-DeFi clients do NOT see the tokenization card
- [ ] "Pay $2,500 Deposit" button creates Stripe checkout for correct amount
- [ ] Deposit payment recorded with `type: "tokenization_deposit"` after webhook
- [ ] After deposit, card shows "Deposit received" instead of pay button
- [ ] Duplicate deposit attempts are blocked
- [ ] Attorney can set asset value, tier auto-calculates correctly
- [ ] After asset value set, client sees calculated remainder and "Pay Remainder" button
- [ ] Remainder payment blocked if deposit not paid
- [ ] Remainder payment blocked if asset_value not set
- [ ] Remainder amount is correct: `(asset_value * tier%) - $2,500`
- [ ] Remainder blocked for Custom tier ($10M+) — shows "attorney will provide custom fee"
- [ ] Remainder blocked when calculated fee <= $2,500 — shows "deposit covers full fee"
- [ ] Duplicate Stripe webhook delivery does not double-record payment
- [ ] Tokenization payments do NOT credit hours or modify hours_paid
- [ ] Success banners show for `?paid=deposit` and `?paid=remainder`
- [ ] Fee schedule modal includes tokenization section with tier table
- [ ] Existing hourly billing and payment flows unchanged — no regression
