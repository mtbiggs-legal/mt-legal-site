# Payment System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a client-facing Billing tab to the client portal where clients can pay outstanding billable hours via Stripe Checkout (card) or Coinbase Commerce (BTC/ETH/SOL/USDC/USDT), with webhooks auto-confirming payment and updating client records.

**Architecture:** Stripe Checkout and Coinbase Commerce both use hosted pages (client briefly redirects out, then returns). Flask receives webhooks from each processor to auto-credit paid hours and log the payment. No card data ever touches the server — PCI compliance is inherited from Stripe's hosted page.

**Tech Stack:** Python/Flask, `stripe` pip package, `requests` (already available) for Coinbase Commerce API, Jinja2 templates, vanilla JS fetch.

**Design doc:** `docs/plans/2026-03-02-payment-system-design.md`

---

## Task 1: Install Stripe and update requirements.txt

**Files:**
- Modify: `requirements.txt`

**Step 1: Install stripe**

```bash
pip install stripe
```

Expected: `Successfully installed stripe-...`

**Step 2: Add to requirements.txt**

Add this line to `requirements.txt`:

```
stripe
```

(`requests` ships with Flask's dependencies; verify it's importable.)

**Step 3: Verify install**

```bash
python -c "import stripe; print(stripe.VERSION)"
```

Expected: prints a version like `7.x.x`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add stripe to requirements"
```

---

## Task 2: Add config vars to .env.example and app.py

**Files:**
- Modify: `.env.example`
- Modify: `app.py` (around line 80 where `ANTHROPIC_API_KEY` is loaded)

**Step 1: Update `.env.example`**

Add to the bottom of `.env.example`:

```
# Payment processing
HOURLY_RATE=350
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
COINBASE_COMMERCE_API_KEY=...
COINBASE_COMMERCE_WEBHOOK_SECRET=...
```

**Step 2: Add to app.py after `ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")` (line ~80)**

```python
HOURLY_RATE                      = float(os.getenv("HOURLY_RATE", "350"))
STRIPE_SECRET_KEY                = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY           = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET            = os.getenv("STRIPE_WEBHOOK_SECRET", "")
COINBASE_COMMERCE_API_KEY        = os.getenv("COINBASE_COMMERCE_API_KEY", "")
COINBASE_COMMERCE_WEBHOOK_SECRET = os.getenv("COINBASE_COMMERCE_WEBHOOK_SECRET", "")
```

**Step 3: Add imports at the top of app.py (after the existing imports on line ~10)**

```python
import stripe
import hmac
import hashlib
import requests as _http
```

**Step 4: Verify no startup error**

```bash
python -c "import app"
```

Expected: no errors

**Step 5: Commit**

```bash
git add app.py .env.example
git commit -m "feat(payments): add payment config vars and stripe import"
```

---

## Task 3: Add payment fields to client schema

**Files:**
- Modify: `app.py` — `load_client` function (line ~864)
- Test: `tests/test_payments.py` (create)

**Step 1: Write the failing test**

Create `tests/test_payments.py`:

```python
import json, sys, types, pytest, hmac, hashlib
from pathlib import Path

# Stub heavy deps (same pattern as other test files)
for mod in ("anthropic", "google.oauth2.credentials",
            "google_auth_oauthlib.flow", "googleapiclient.discovery",
            "mammoth", "pypdf", "fpdf", "stripe"):
    if mod not in sys.modules:
        parts = mod.split(".")
        for i in range(1, len(parts) + 1):
            name = ".".join(parts[:i])
            if name not in sys.modules:
                sys.modules[name] = types.ModuleType(name)

import app as _app_module

_app = _app_module.app
_app.config["TESTING"] = True
_app.config["SECRET_KEY"] = "test"


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "CLIENT_FILES_DIR",    tmp_path / "files")
    (tmp_path / "accounts").mkdir()
    (tmp_path / "files").mkdir()


@pytest.fixture
def flask_client(patch_dirs):
    with _app.test_client() as c:
        yield c


def make_client_json(tmp_path, username="testclient", extra=None):
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(exist_ok=True)
    record = {
        "username": username,
        "client_name": "Test Client",
        "hours_billed": 3.0,
        "billing_log": [],
    }
    if extra:
        record.update(extra)
    (accounts_dir / f"{username}.json").write_text(json.dumps(record))
    return record


def test_load_client_adds_payment_defaults(tmp_path, monkeypatch):
    """load_client should inject hours_paid=0 and payments=[] if missing."""
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    make_client_json(tmp_path)
    client = _app_module.load_client("testclient")
    assert client["hours_paid"] == 0
    assert client["payments"] == []
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_payments.py::test_load_client_adds_payment_defaults -v
```

Expected: `FAILED` — `KeyError: 'hours_paid'` or `AssertionError`

**Step 3: Implement — update `load_client` in app.py**

In `load_client` (line ~864), after loading the JSON, add defaults:

```python
def load_client(username):
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    # Payment fields added in v2 — backfill for existing records
    data.setdefault("hours_paid", 0)
    data.setdefault("payments", [])
    return data
```

**Step 4: Run to verify it passes**

```bash
pytest tests/test_payments.py::test_load_client_adds_payment_defaults -v
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add app.py tests/test_payments.py
git commit -m "feat(payments): backfill hours_paid and payments fields in load_client"
```

---

## Task 4: `GET /portal/client/billing` route

**Files:**
- Modify: `app.py` (add route after `/portal/client/message` route, around line 1018)
- Test: `tests/test_payments.py`

**Step 1: Write the failing test**

Append to `tests/test_payments.py`:

```python
def test_billing_summary_returns_balance(flask_client, tmp_path, monkeypatch):
    """Logged-in client gets hours, balance, and payment history."""
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "HOURLY_RATE", 350.0)
    make_client_json(tmp_path, extra={"hours_paid": 1.0,
                                      "payments": [{"amount": 350.0}]})
    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"] = "client"
    resp = flask_client.get("/portal/client/billing")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["hours_billed"] == 3.0
    assert data["hours_paid"] == 1.0
    assert data["balance_due"] == pytest.approx(700.0)   # 2.0 hrs * $350
    assert data["hourly_rate"] == 350.0
    assert len(data["payments"]) == 1


def test_billing_requires_login(flask_client):
    resp = flask_client.get("/portal/client/billing")
    assert resp.status_code in (302, 401)
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_payments.py::test_billing_summary_returns_balance tests/test_payments.py::test_billing_requires_login -v
```

Expected: both `FAILED` (route doesn't exist yet)

**Step 3: Implement the route in app.py**

Add after the `/portal/client/message` route (around line 1018):

```python
@app.route("/portal/client/billing")
@require_auth
def client_billing():
    if session.get("role") != "client":
        return jsonify({"error": "Unauthorized"}), 401
    client = load_client(session["username"])
    if not client:
        return jsonify({"error": "Client not found"}), 404
    hours_owed  = round(client["hours_billed"] - client["hours_paid"], 2)
    balance_due = round(hours_owed * HOURLY_RATE, 2)
    return jsonify({
        "hours_billed": client["hours_billed"],
        "hours_paid":   client["hours_paid"],
        "hours_owed":   hours_owed,
        "balance_due":  balance_due,
        "hourly_rate":  HOURLY_RATE,
        "payments":     list(reversed(client.get("payments", []))),
    })
```

**Step 4: Run to verify it passes**

```bash
pytest tests/test_payments.py::test_billing_summary_returns_balance tests/test_payments.py::test_billing_requires_login -v
```

Expected: both `PASSED`

**Step 5: Commit**

```bash
git add app.py tests/test_payments.py
git commit -m "feat(payments): add GET /portal/client/billing summary route"
```

---

## Task 5: `POST /portal/client/payment/stripe` — create Stripe Checkout session

**Files:**
- Modify: `app.py`
- Test: `tests/test_payments.py`

**Step 1: Write the failing test**

Append to `tests/test_payments.py`:

```python
def test_stripe_checkout_returns_url(flask_client, tmp_path, monkeypatch):
    """Route creates a Stripe Checkout session and returns its URL."""
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "HOURLY_RATE", 350.0)
    monkeypatch.setattr(_app_module, "STRIPE_SECRET_KEY", "sk_test_fake")
    make_client_json(tmp_path)  # 3.0 hrs billed, 0 paid -> $1050 due

    # Stub stripe.checkout.Session.create
    import stripe as _stripe
    fake_session = types.SimpleNamespace(url="https://checkout.stripe.com/pay/fake")
    checkout_ns = types.SimpleNamespace(
        Session=types.SimpleNamespace(create=lambda **kw: fake_session)
    )
    _stripe.checkout = checkout_ns

    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"] = "client"

    resp = flask_client.post("/portal/client/payment/stripe",
                             content_type="application/json", json={})
    assert resp.status_code == 200
    assert resp.get_json()["checkout_url"] == "https://checkout.stripe.com/pay/fake"


def test_stripe_checkout_zero_balance_returns_400(flask_client, tmp_path, monkeypatch):
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "HOURLY_RATE", 350.0)
    make_client_json(tmp_path, extra={"hours_billed": 2.0, "hours_paid": 2.0})
    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"] = "client"
    resp = flask_client.post("/portal/client/payment/stripe",
                             content_type="application/json", json={})
    assert resp.status_code == 400
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_payments.py::test_stripe_checkout_returns_url tests/test_payments.py::test_stripe_checkout_zero_balance_returns_400 -v
```

Expected: both `FAILED`

**Step 3: Implement the route in app.py**

Add after the `client_billing` route:

```python
@app.route("/portal/client/payment/stripe", methods=["POST"])
@require_auth
def client_payment_stripe():
    if session.get("role") != "client":
        return jsonify({"error": "Unauthorized"}), 401
    username = session["username"]
    client   = load_client(username)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    hours_owed  = round(client["hours_billed"] - client["hours_paid"], 2)
    balance_due = round(hours_owed * HOURLY_RATE, 2)
    if balance_due <= 0:
        return jsonify({"error": "No balance due"}), 400
    stripe.api_key = STRIPE_SECRET_KEY
    base = request.host_url.rstrip("/")
    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Legal Services — {hours_owed} hrs @ ${HOURLY_RATE:.0f}/hr",
                },
                "unit_amount": int(balance_due * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        metadata={"client_username": username},
        success_url=f"{base}/client-portal?tab=billing&paid=1",
        cancel_url=f"{base}/client-portal?tab=billing",
    )
    return jsonify({"checkout_url": checkout_session.url})
```

**Step 4: Run to verify it passes**

```bash
pytest tests/test_payments.py::test_stripe_checkout_returns_url tests/test_payments.py::test_stripe_checkout_zero_balance_returns_400 -v
```

Expected: both `PASSED`

**Step 5: Commit**

```bash
git add app.py tests/test_payments.py
git commit -m "feat(payments): add POST /portal/client/payment/stripe route"
```

---

## Task 6: `POST /webhooks/stripe` — handle payment confirmation

**Files:**
- Modify: `app.py`
- Test: `tests/test_payments.py`

**Step 1: Write the failing test**

Append to `tests/test_payments.py`:

```python
def test_stripe_webhook_credits_hours(flask_client, tmp_path, monkeypatch):
    """Stripe webhook marks hours as paid and logs the payment."""
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "HOURLY_RATE", 350.0)
    monkeypatch.setattr(_app_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    make_client_json(tmp_path)  # 3.0 hrs billed, 0 paid

    import stripe as _stripe
    fake_event = types.SimpleNamespace(
        type="checkout.session.completed",
        data=types.SimpleNamespace(
            object=types.SimpleNamespace(
                amount_total=105000,  # $1050.00 in cents
                metadata={"client_username": "testclient"},
                id="cs_test_fake",
            )
        )
    )
    _stripe.Webhook = types.SimpleNamespace(
        construct_event=lambda payload, sig, secret: fake_event
    )

    resp = flask_client.post(
        "/webhooks/stripe",
        data=b"fake_payload",
        headers={"Stripe-Signature": "t=fake,v1=fake"},
        content_type="application/json",
    )
    assert resp.status_code == 200

    client = _app_module.load_client("testclient")
    assert client["hours_paid"] == pytest.approx(3.0)   # 1050 / 350
    assert len(client["payments"]) == 1
    assert client["payments"][0]["method"] == "stripe"
    payment_entries = [e for e in client["billing_log"] if e.get("type") == "payment"]
    assert len(payment_entries) == 1


def test_stripe_webhook_bad_signature_returns_400(flask_client, monkeypatch):
    import stripe as _stripe
    def _raise(*a, **kw):
        raise Exception("Invalid signature")
    _stripe.Webhook = types.SimpleNamespace(construct_event=_raise)
    monkeypatch.setattr(_app_module, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    resp = flask_client.post("/webhooks/stripe", data=b"bad",
                             headers={"Stripe-Signature": "bad"})
    assert resp.status_code == 400
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_payments.py::test_stripe_webhook_credits_hours tests/test_payments.py::test_stripe_webhook_bad_signature_returns_400 -v
```

Expected: both `FAILED`

**Step 3: Implement routes in app.py**

Add after the Stripe checkout route:

```python
@app.route("/webhooks/stripe", methods=["POST"])
def webhook_stripe():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400
    if event.type == "checkout.session.completed":
        obj         = event.data.object
        username    = (obj.metadata or {}).get("client_username")
        amount_paid = round(obj.amount_total / 100, 2)  # cents -> dollars
        reference   = obj.id
        _apply_payment(username, amount_paid, "stripe", reference)
    return jsonify({"received": True})


def _apply_payment(username, amount_paid, method, reference):
    """Credit a confirmed payment to the client record (shared by Stripe and Coinbase)."""
    client = load_client(username)
    if not client:
        return
    hours_credited = round(amount_paid / HOURLY_RATE, 2)
    today          = date.today().isoformat()
    payment_entry  = {
        "date":           today,
        "amount":         amount_paid,
        "hours_credited": hours_credited,
        "method":         method,
        "reference":      reference,
        "note":           f"{method.title()} payment — {hours_credited} hrs @ ${HOURLY_RATE:.0f}/hr",
    }
    client["hours_paid"] = round(client.get("hours_paid", 0) + hours_credited, 2)
    client.setdefault("payments", []).append(payment_entry)
    client.setdefault("billing_log", []).append({
        "date":  today,
        "hours": 0,
        "note":  payment_entry["note"],
        "type":  "payment",
    })
    save_client(client)
```

**Step 4: Run to verify it passes**

```bash
pytest tests/test_payments.py::test_stripe_webhook_credits_hours tests/test_payments.py::test_stripe_webhook_bad_signature_returns_400 -v
```

Expected: both `PASSED`

**Step 5: Commit**

```bash
git add app.py tests/test_payments.py
git commit -m "feat(payments): add Stripe webhook and _apply_payment helper"
```

---

## Task 7: `POST /portal/client/payment/coinbase` — create Coinbase Commerce charge

**Files:**
- Modify: `app.py`
- Test: `tests/test_payments.py`

**Step 1: Write the failing test**

Append to `tests/test_payments.py`:

```python
def test_coinbase_charge_returns_url(flask_client, tmp_path, monkeypatch):
    """Route creates a Coinbase Commerce charge and returns its hosted URL."""
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "HOURLY_RATE", 350.0)
    monkeypatch.setattr(_app_module, "COINBASE_COMMERCE_API_KEY", "fake_key")
    make_client_json(tmp_path)

    fake_response = types.SimpleNamespace(
        ok=True,
        json=lambda: {"data": {"hosted_url": "https://commerce.coinbase.com/charges/TESTCODE"}},
    )
    monkeypatch.setattr(_app_module, "_http",
                        types.SimpleNamespace(post=lambda *a, **kw: fake_response))

    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"] = "client"

    resp = flask_client.post("/portal/client/payment/coinbase",
                             content_type="application/json", json={})
    assert resp.status_code == 200
    assert "commerce.coinbase.com" in resp.get_json()["hosted_url"]
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_payments.py::test_coinbase_charge_returns_url -v
```

Expected: `FAILED`

**Step 3: Implement the route in app.py**

Add after `_apply_payment`:

```python
@app.route("/portal/client/payment/coinbase", methods=["POST"])
@require_auth
def client_payment_coinbase():
    if session.get("role") != "client":
        return jsonify({"error": "Unauthorized"}), 401
    username = session["username"]
    client   = load_client(username)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    hours_owed  = round(client["hours_billed"] - client["hours_paid"], 2)
    balance_due = round(hours_owed * HOURLY_RATE, 2)
    if balance_due <= 0:
        return jsonify({"error": "No balance due"}), 400
    base = request.host_url.rstrip("/")
    resp = _http.post(
        "https://api.commerce.coinbase.com/charges",
        headers={
            "X-CC-Api-Key": COINBASE_COMMERCE_API_KEY,
            "X-CC-Version": "2018-03-22",
            "Content-Type": "application/json",
        },
        json={
            "name":         "Legal Services",
            "description":  f"{hours_owed} hrs @ ${HOURLY_RATE:.0f}/hr — {client['client_name']}",
            "pricing_type": "fixed_price",
            "local_price":  {"amount": f"{balance_due:.2f}", "currency": "USD"},
            "metadata":     {"client_username": username},
            "redirect_url": f"{base}/client-portal?tab=billing&paid=1",
            "cancel_url":   f"{base}/client-portal?tab=billing",
        },
    )
    if not resp.ok:
        return jsonify({"error": "Failed to create Coinbase charge"}), 502
    hosted_url = resp.json()["data"]["hosted_url"]
    return jsonify({"hosted_url": hosted_url})
```

**Step 4: Run to verify it passes**

```bash
pytest tests/test_payments.py::test_coinbase_charge_returns_url -v
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add app.py tests/test_payments.py
git commit -m "feat(payments): add POST /portal/client/payment/coinbase route"
```

---

## Task 8: `POST /webhooks/coinbase` — handle Coinbase payment confirmation

**Files:**
- Modify: `app.py`
- Test: `tests/test_payments.py`

**Step 1: Write the failing test**

Append to `tests/test_payments.py`:

```python
def test_coinbase_webhook_credits_hours(flask_client, tmp_path, monkeypatch):
    """Coinbase webhook credits hours when charge:confirmed fires."""
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "HOURLY_RATE", 350.0)
    secret = "cb_webhook_secret"
    monkeypatch.setattr(_app_module, "COINBASE_COMMERCE_WEBHOOK_SECRET", secret)
    make_client_json(tmp_path)

    payload = json.dumps({
        "event": {
            "type": "charge:confirmed",
            "data": {
                "code": "TESTCODE",
                "metadata": {"client_username": "testclient"},
                "pricing": {"local": {"amount": "1050.00", "currency": "USD"}},
            }
        }
    }).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    resp = flask_client.post(
        "/webhooks/coinbase",
        data=payload,
        headers={"X-CC-Webhook-Signature": sig},
        content_type="application/json",
    )
    assert resp.status_code == 200

    client = _app_module.load_client("testclient")
    assert client["hours_paid"] == pytest.approx(3.0)
    assert len(client["payments"]) == 1
    assert client["payments"][0]["method"] == "coinbase"


def test_coinbase_webhook_bad_sig_returns_400(flask_client, monkeypatch):
    monkeypatch.setattr(_app_module, "COINBASE_COMMERCE_WEBHOOK_SECRET", "real_secret")
    resp = flask_client.post(
        "/webhooks/coinbase",
        data=b'{"event":{"type":"charge:confirmed"}}',
        headers={"X-CC-Webhook-Signature": "badsig"},
        content_type="application/json",
    )
    assert resp.status_code == 400
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_payments.py::test_coinbase_webhook_credits_hours tests/test_payments.py::test_coinbase_webhook_bad_sig_returns_400 -v
```

Expected: both `FAILED`

**Step 3: Implement the webhook route in app.py**

Add after the Coinbase charge route:

```python
@app.route("/webhooks/coinbase", methods=["POST"])
def webhook_coinbase():
    payload  = request.get_data()
    sig      = request.headers.get("X-CC-Webhook-Signature", "")
    expected = hmac.new(
        COINBASE_COMMERCE_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "Invalid signature"}), 400
    body  = request.get_json(force=True, silent=True) or {}
    event = body.get("event", {})
    if event.get("type") == "charge:confirmed":
        data        = event.get("data", {})
        username    = (data.get("metadata") or {}).get("client_username")
        amount_paid = float((data.get("pricing", {}).get("local", {}).get("amount") or 0))
        reference   = data.get("code", "")
        _apply_payment(username, amount_paid, "coinbase", reference)
    return jsonify({"received": True})
```

**Step 4: Run all payment tests**

```bash
pytest tests/test_payments.py -v
```

Expected: all `PASSED`

**Step 5: Run full suite for regressions**

```bash
pytest tests/ -v
```

Expected: all `PASSED`

**Step 6: Commit**

```bash
git add app.py tests/test_payments.py
git commit -m "feat(payments): add Coinbase Commerce webhook route"
```

---

## Task 9: Add Billing tab to client_portal.html

**Files:**
- Modify: `templates/client_portal.html`

This is a frontend-only task — no new routes, no tests needed.

**Step 1: Add "Billing" button to the sidebar nav**

In `templates/client_portal.html`, find the `<nav>` block (line ~13) and add after the Messages button:

```html
<button class="portal-tab-btn" onclick="showTab('billing', this); loadBilling()">Billing</button>
```

**Step 2: Add the billing panel before `</div><!-- end main panels -->`**

Insert before the closing `</div><!-- end main panels -->` tag (line ~123):

```html
<!-- Billing tab -->
<div id="tab-billing" class="portal-panel">
  <div class="page-header" style="margin-bottom:1.25rem">
    <h1 style="font-size:1.5rem">Billing &amp; Payments</h1>
    <p style="font-size:.9rem">Pay your outstanding balance securely online.</p>
  </div>

  <!-- Balance summary -->
  <div class="portal-stats" id="billing-stats">
    <div class="portal-stat">
      <div class="portal-stat-label">Hours Billed</div>
      <div class="portal-stat-value" id="bill-hours-billed">&mdash;</div>
    </div>
    <div class="portal-stat">
      <div class="portal-stat-label">Hours Paid</div>
      <div class="portal-stat-value" id="bill-hours-paid">&mdash;</div>
    </div>
    <div class="portal-stat">
      <div class="portal-stat-label">Balance Due</div>
      <div class="portal-stat-value" id="bill-balance-due" style="color:var(--red)">&mdash;</div>
      <div class="portal-stat-sub" id="bill-balance-sub"></div>
    </div>
    <div class="portal-stat">
      <div class="portal-stat-label">Rate</div>
      <div class="portal-stat-value" id="bill-rate">&mdash;</div>
      <div class="portal-stat-sub">per hour</div>
    </div>
  </div>

  <!-- Pay Now card (hidden when balance = 0) -->
  <div class="card" id="billing-pay-card" style="margin-bottom:1.25rem;display:none">
    <div class="portal-section-title">Pay Now</div>
    <p id="billing-amount-label" style="font-family:Arial,sans-serif;font-size:1.1rem;font-weight:bold;color:var(--navy);margin-bottom:1rem"></p>
    <div style="display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:.75rem">
      <button class="btn btn-primary" id="btn-pay-card" onclick="payWithCard()">Pay with Card &rarr;</button>
      <button class="btn btn-secondary" id="btn-pay-crypto" onclick="payWithCrypto()">Pay with Crypto &rarr;</button>
    </div>
    <p style="font-family:Arial,sans-serif;font-size:.78rem;color:var(--gray-3)">
      Card: Visa &middot; Mastercard &middot; Amex &middot; ACH &nbsp;|&nbsp;
      Crypto: BTC &middot; ETH &middot; SOL &middot; USDC &middot; USDT
    </p>
    <div id="billing-pay-result"></div>
  </div>

  <!-- Zero balance message -->
  <div id="billing-paid-msg" style="display:none;margin-bottom:1.25rem" class="card">
    <p style="font-family:Arial,sans-serif;font-size:.95rem;color:var(--green);font-weight:bold">
      Your account is fully paid up. Thank you!
    </p>
  </div>

  <!-- Payment history -->
  <div class="card" id="billing-history-card" style="display:none">
    <div class="portal-section-title">Payment History</div>
    <table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:.88rem">
      <thead>
        <tr style="border-bottom:2px solid var(--gray-1)">
          <th style="text-align:left;padding:.4rem .5rem;color:var(--gray-3)">Date</th>
          <th style="text-align:left;padding:.4rem .5rem;color:var(--gray-3)">Method</th>
          <th style="text-align:right;padding:.4rem .5rem;color:var(--gray-3)">Hours</th>
          <th style="text-align:right;padding:.4rem .5rem;color:var(--gray-3)">Amount</th>
          <th style="text-align:left;padding:.4rem .5rem;color:var(--gray-3)">Reference</th>
        </tr>
      </thead>
      <tbody id="billing-history-body"></tbody>
    </table>
  </div>
</div>
```

**Step 3: Add billing JS to the `<script>` block (before closing `</script>`)**

Note: all dynamic content is built using `textContent` and DOM methods — no `innerHTML` — to prevent XSS.

```javascript
var _billingData = null;

function loadBilling() {
  if (_billingData) { renderBilling(); return; }
  fetch("/portal/client/billing")
    .then(function(r) { return r.json(); })
    .then(function(d) { _billingData = d; renderBilling(); })
    .catch(function() {
      var res = document.getElementById("billing-pay-result");
      if (res) res.textContent = "Unable to load billing data.";
    });
}

function renderBilling() {
  var d = _billingData;
  document.getElementById("bill-hours-billed").textContent = d.hours_billed;
  document.getElementById("bill-hours-paid").textContent   = d.hours_paid;
  document.getElementById("bill-rate").textContent         = "$" + d.hourly_rate.toFixed(0);
  if (d.balance_due > 0) {
    document.getElementById("bill-balance-due").textContent  = "$" + d.balance_due.toFixed(2);
    document.getElementById("bill-balance-sub").textContent  = d.hours_owed + " hrs unpaid";
    document.getElementById("billing-amount-label").textContent = "Amount Due: $" + d.balance_due.toFixed(2);
    document.getElementById("billing-pay-card").style.display  = "";
    document.getElementById("billing-paid-msg").style.display  = "none";
  } else {
    document.getElementById("bill-balance-due").textContent    = "$0.00";
    document.getElementById("bill-balance-due").style.color    = "var(--green)";
    document.getElementById("billing-pay-card").style.display  = "none";
    document.getElementById("billing-paid-msg").style.display  = "";
  }
  var payments = d.payments || [];
  if (payments.length) {
    document.getElementById("billing-history-card").style.display = "";
    var tbody = document.getElementById("billing-history-body");
    while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }
    payments.forEach(function(p) {
      var tr = document.createElement("tr");
      tr.style.borderBottom = "1px solid var(--gray-1)";

      function td(text, align) {
        var cell = document.createElement("td");
        cell.style.padding = ".4rem .5rem";
        if (align) cell.style.textAlign = align;
        cell.textContent = text || "\u2014";
        return cell;
      }

      var methodCell = td(p.method || "\u2014");
      methodCell.style.textTransform = "capitalize";

      tr.appendChild(td(p.date || "\u2014"));
      tr.appendChild(methodCell);
      tr.appendChild(td((p.hours_credited || 0) + " hrs", "right"));
      tr.appendChild(td("$" + (p.amount || 0).toFixed(2), "right"));

      var refCell = document.createElement("td");
      refCell.style.padding = ".4rem .5rem";
      refCell.style.color   = "var(--gray-3)";
      refCell.style.fontSize = ".78rem";
      refCell.textContent   = p.reference || "\u2014";
      tr.appendChild(refCell);

      tbody.appendChild(tr);
    });
  }
}

function payWithCard() {
  var btn = document.getElementById("btn-pay-card");
  var res = document.getElementById("billing-pay-result");
  btn.disabled = true;
  btn.textContent = "Redirecting\u2026";
  fetch("/portal/client/payment/stripe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.checkout_url) {
      window.location.href = d.checkout_url;
    } else {
      res.textContent = d.error || "An error occurred. Please try again.";
      btn.disabled = false;
      btn.textContent = "Pay with Card \u2192";
    }
  })
  .catch(function() {
    res.textContent = "Connection error. Please try again.";
    btn.disabled = false;
    btn.textContent = "Pay with Card \u2192";
  });
}

function payWithCrypto() {
  var btn = document.getElementById("btn-pay-crypto");
  var res = document.getElementById("billing-pay-result");
  btn.disabled = true;
  btn.textContent = "Redirecting\u2026";
  fetch("/portal/client/payment/coinbase", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.hosted_url) {
      window.location.href = d.hosted_url;
    } else {
      res.textContent = d.error || "An error occurred. Please try again.";
      btn.disabled = false;
      btn.textContent = "Pay with Crypto \u2192";
    }
  })
  .catch(function() {
    res.textContent = "Connection error. Please try again.";
    btn.disabled = false;
    btn.textContent = "Pay with Crypto \u2192";
  });
}
```

**Step 4: Commit**

```bash
git add templates/client_portal.html
git commit -m "feat(payments): add Billing tab UI with card and crypto pay buttons"
```

---

## Task 10: Success banner on return from payment

**Files:**
- Modify: `templates/client_portal.html`

**Step 1: Replace the existing `DOMContentLoaded` listener**

Find the existing listener (bottom of the script block):

```javascript
window.addEventListener("DOMContentLoaded", function() {
  const t = document.getElementById("message-thread");
  if (t) t.scrollTop = t.scrollHeight;
});
```

Replace it with:

```javascript
window.addEventListener("DOMContentLoaded", function() {
  var t = document.getElementById("message-thread");
  if (t) t.scrollTop = t.scrollHeight;

  // Auto-switch to billing tab and show success banner after payment redirect
  var params = new URLSearchParams(window.location.search);
  if (params.get("tab") === "billing") {
    var billingBtn = document.querySelector(".portal-tab-btn[onclick*='billing']");
    if (billingBtn) billingBtn.click();
    if (params.get("paid") === "1") {
      var panel = document.getElementById("tab-billing");
      if (panel) {
        var banner = document.createElement("div");
        banner.style.cssText = "background:var(--green);color:#fff;font-family:Arial,sans-serif;font-size:.95rem;padding:.75rem 1.25rem;border-radius:6px;margin-bottom:1rem;font-weight:bold";
        banner.textContent = "Payment received! Your account has been updated.";
        panel.insertBefore(banner, panel.firstChild);
        setTimeout(function() { banner.remove(); }, 6000);
        _billingData = null; // bust cache so fresh totals load
      }
    }
  }
});
```

**Step 2: Commit**

```bash
git add templates/client_portal.html
git commit -m "feat(payments): show success banner when returning from checkout"
```

---

## Task 11: Configure Stripe and Coinbase webhooks (manual steps)

This task is configuration — not code.

**Stripe:**
1. Go to https://dashboard.stripe.com/webhooks
2. Click "Add endpoint"
3. URL: `https://<your-ngrok-subdomain>.ngrok-free.dev/webhooks/stripe`
4. Event to listen for: `checkout.session.completed`
5. Copy the "Signing secret" → set as `STRIPE_WEBHOOK_SECRET` in `.env`
6. Copy Secret key → `STRIPE_SECRET_KEY` in `.env`
7. Copy Publishable key → `STRIPE_PUBLISHABLE_KEY` in `.env`

**Coinbase Commerce:**
1. Go to https://beta.commerce.coinbase.com/settings/security
2. Under "Webhook subscriptions", add: `https://<your-ngrok-subdomain>.ngrok-free.dev/webhooks/coinbase`
3. Copy the shared secret → `COINBASE_COMMERCE_WEBHOOK_SECRET` in `.env`
4. Settings → API Keys → copy key → `COINBASE_COMMERCE_API_KEY` in `.env`

**Optional — test Stripe locally with Stripe CLI:**
```bash
stripe listen --forward-to localhost:5000/webhooks/stripe
stripe trigger checkout.session.completed
```

**Note:** Ngrok's URL rotates on each restart unless you have a paid fixed subdomain. Update both webhook URLs in their dashboards after each ngrok restart.

---

## Task 12: Final test run and smoke test

**Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all `PASSED`

**Step 2: Smoke test in browser**

```bash
python app.py
```

- Log in as a test client
- Click "Billing" tab
- Verify balance, hours billed/paid, and rate show correctly
- Click "Pay with Card" — should redirect to Stripe's test checkout (use card `4242 4242 4242 4242`, any future date, any CVC)
- After payment, Stripe redirects back — banner should appear and billing tab should refresh

**Step 3: Final commit**

```bash
git add .
git commit -m "feat(payments): complete Stripe + Coinbase Commerce payment system"
```
