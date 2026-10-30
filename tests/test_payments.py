"""Billing summary, checkout creation, and payment webhooks."""

import hashlib
import hmac
import json
import types

import pytest

import shared
from services import storage


@pytest.fixture(autouse=True)
def rate(monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)


def test_load_client_adds_payment_defaults(make_client):
    """load_client injects hours_paid=0 and payments=[] when they are missing."""
    make_client(hours_billed=3.0)
    client = storage.load_client("testclient")
    assert client["hours_paid"] == 0
    assert client["payments"] == []


def test_billing_summary_returns_balance(client_session, make_client, issue_test_statement):
    make_client(payments=[{"amount": 350.0, "date": "2026-10-02", "method": "card"}])
    issue_test_statement("testclient", 3.0)
    resp = client_session.get("/portal/client/billing")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["billed_hours"] == 3.0
    assert data["amount_due"] == pytest.approx(700.0)      # $1,050 billed - $350 paid
    assert "hours_billed" not in data and "billing_log" not in data
    assert data["hourly_rate"] == 350.0
    assert len(data["payments"]) == 1


def test_billing_requires_login(client):
    resp = client.get("/portal/client/billing")
    assert resp.status_code in (302, 401)


def _stub_stripe_checkout(monkeypatch, url="https://checkout.stripe.com/pay/fake"):
    import stripe as _stripe
    fake_session = types.SimpleNamespace(url=url)
    monkeypatch.setattr(
        _stripe, "checkout",
        types.SimpleNamespace(
            Session=types.SimpleNamespace(create=lambda **kw: fake_session)
        ),
        raising=False,
    )


def test_stripe_checkout_returns_url(client_session, make_client, issue_test_statement, monkeypatch):
    make_client()
    issue_test_statement("testclient", 3.0)     # $1050 due
    monkeypatch.setattr(shared, "STRIPE_SECRET_KEY", "sk_test_fake")
    _stub_stripe_checkout(monkeypatch)

    resp = client_session.post("/portal/client/payment/stripe", json={})
    assert resp.status_code == 200
    assert resp.get_json()["checkout_url"] == "https://checkout.stripe.com/pay/fake"


def test_stripe_checkout_without_api_key_returns_503(client_session, make_client, monkeypatch):
    """An unconfigured Stripe key gives a clear message, not a 500."""
    make_client(hours_billed=3.0)
    monkeypatch.setattr(shared, "STRIPE_SECRET_KEY", "")

    resp = client_session.post("/portal/client/payment/stripe", json={})
    assert resp.status_code == 503
    assert "not set up" in resp.get_json()["error"]


def test_stripe_checkout_zero_balance_returns_400(client_session, make_client, issue_test_statement, monkeypatch):
    make_client(payments=[{"amount": 700.0}])
    issue_test_statement("testclient", 2.0)     # $700 billed, $700 paid
    monkeypatch.setattr(shared, "STRIPE_SECRET_KEY", "sk_test_fake")

    resp = client_session.post("/portal/client/payment/stripe", json={})
    assert resp.status_code == 400


def test_stripe_webhook_credits_hours(client, make_client, monkeypatch):
    make_client(hours_billed=3.0)
    monkeypatch.setattr(shared, "STRIPE_WEBHOOK_SECRET", "whsec_test")

    import stripe as _stripe
    fake_event = types.SimpleNamespace(
        type="checkout.session.completed",
        data=types.SimpleNamespace(object=types.SimpleNamespace(
            amount_total=105000,                       # $1050.00 in cents
            metadata={"client_username": "testclient"},
            id="cs_test_fake",
        )),
    )
    monkeypatch.setattr(
        _stripe, "Webhook",
        types.SimpleNamespace(construct_event=lambda payload, sig, secret: fake_event),
        raising=False,
    )

    resp = client.post("/webhooks/stripe", data=b"fake_payload",
                       headers={"Stripe-Signature": "t=fake,v1=fake"},
                       content_type="application/json")
    assert resp.status_code == 200

    credited = storage.load_client("testclient")
    assert credited["hours_paid"] == pytest.approx(3.0)   # 1050 / 350
    assert len(credited["payments"]) == 1
    assert credited["payments"][0]["method"] == "stripe"


def test_stripe_webhook_is_idempotent(client, make_client, monkeypatch):
    """Replaying the same checkout session must not credit twice."""
    make_client(hours_billed=3.0)
    monkeypatch.setattr(shared, "STRIPE_WEBHOOK_SECRET", "whsec_test")

    import stripe as _stripe
    fake_event = types.SimpleNamespace(
        type="checkout.session.completed",
        data=types.SimpleNamespace(object=types.SimpleNamespace(
            amount_total=105000,
            metadata={"client_username": "testclient"},
            id="cs_test_fake",
        )),
    )
    monkeypatch.setattr(
        _stripe, "Webhook",
        types.SimpleNamespace(construct_event=lambda payload, sig, secret: fake_event),
        raising=False,
    )

    for _ in range(2):
        client.post("/webhooks/stripe", data=b"fake_payload",
                    headers={"Stripe-Signature": "t=fake,v1=fake"},
                    content_type="application/json")

    credited = storage.load_client("testclient")
    assert len(credited["payments"]) == 1
    assert credited["hours_paid"] == pytest.approx(3.0)


def test_stripe_webhook_bad_signature_returns_400(client, monkeypatch):
    import stripe as _stripe

    def _raise(*a, **kw):
        raise Exception("Invalid signature")

    monkeypatch.setattr(shared, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(_stripe, "Webhook",
                        types.SimpleNamespace(construct_event=_raise), raising=False)

    resp = client.post("/webhooks/stripe", data=b"bad",
                       headers={"Stripe-Signature": "bad"})
    assert resp.status_code == 400


def test_stripe_webhook_without_secret_returns_503(client, monkeypatch):
    """Refuse webhooks entirely when no signing secret is configured."""
    monkeypatch.setattr(shared, "STRIPE_WEBHOOK_SECRET", "")
    resp = client.post("/webhooks/stripe", data=b"{}",
                       headers={"Stripe-Signature": "anything"})
    assert resp.status_code == 503


def test_coinbase_charge_returns_url(client_session, make_client, issue_test_statement, monkeypatch):
    make_client()
    issue_test_statement("testclient", 3.0)
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_API_KEY", "fake_key")

    fake_response = types.SimpleNamespace(
        ok=True,
        json=lambda: {"data": {"hosted_url": "https://commerce.coinbase.com/charges/TESTCODE"}},
    )
    import blueprints.portal_client as pc
    monkeypatch.setattr(pc, "_http",
                        types.SimpleNamespace(post=lambda *a, **kw: fake_response))

    resp = client_session.post("/portal/client/payment/coinbase", json={})
    assert resp.status_code == 200
    assert "commerce.coinbase.com" in resp.get_json()["hosted_url"]


def test_coinbase_charge_without_api_key_returns_503(client_session, make_client, monkeypatch):
    make_client(hours_billed=3.0)
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_API_KEY", "")
    resp = client_session.post("/portal/client/payment/coinbase", json={})
    assert resp.status_code == 503


def test_coinbase_webhook_credits_hours(client, make_client, monkeypatch):
    make_client(hours_billed=3.0)
    secret = "cb_webhook_secret"
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_WEBHOOK_SECRET", secret)

    payload = json.dumps({
        "event": {
            "type": "charge:confirmed",
            "data": {
                "code": "TESTCODE",
                "metadata": {"client_username": "testclient"},
                "pricing": {"local": {"amount": "1050.00", "currency": "USD"}},
            },
        }
    }).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    resp = client.post("/webhooks/coinbase", data=payload,
                       headers={"X-CC-Webhook-Signature": sig},
                       content_type="application/json")
    assert resp.status_code == 200

    credited = storage.load_client("testclient")
    assert credited["hours_paid"] == pytest.approx(3.0)
    assert len(credited["payments"]) == 1
    assert credited["payments"][0]["method"] == "coinbase"


def test_coinbase_webhook_bad_sig_returns_400(client, monkeypatch):
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_WEBHOOK_SECRET", "real_secret")
    resp = client.post("/webhooks/coinbase",
                       data=b'{"event":{"type":"charge:confirmed"}}',
                       headers={"X-CC-Webhook-Signature": "badsig"},
                       content_type="application/json")
    assert resp.status_code == 400


def test_coinbase_webhook_without_secret_returns_503(client, monkeypatch):
    """An empty secret makes the HMAC forgeable, so the route must refuse."""
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_WEBHOOK_SECRET", "")
    resp = client.post("/webhooks/coinbase",
                       data=b'{"event":{"type":"charge:confirmed"}}',
                       headers={"X-CC-Webhook-Signature": ""},
                       content_type="application/json")
    assert resp.status_code == 503


def test_concurrent_same_reference_credits_once(make_client):
    import threading
    make_client("payRace")
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(storage._apply_payment("payRace", 100.0, "stripe", "ref-1"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, True]
    assert len(storage.load_client("payRace")["payments"]) == 1
