"""Client-facing billing never shows unbilled time (spec C1, C2)."""

import re
import types

import pytest

from services import billing
import shared
from services import storage


@pytest.fixture(autouse=True)
def _rate(monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)


def test_billing_route_view_and_seen(client_session, make_client, issue_test_statement):
    make_client(email="t@example.com")
    issue_test_statement("testclient", 1.0)
    c = storage.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 4.0, "note": "UNBILLED-SECRET"})
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    r = client_session.get("/portal/client/billing")
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "UNBILLED-SECRET" not in body and "threshold" not in body and "notice" not in body
    d = r.get_json()
    assert d["has_new_statement"] is True and d["billed_hours"] == 1.0
    assert storage.load_client("testclient")["billing_seen_at"] != ""
    assert client_session.get("/portal/client/billing").get_json()["has_new_statement"] is False


def test_stripe_charges_statement_amount_only(client_session, make_client, issue_test_statement, monkeypatch):
    import stripe
    captured = {}
    monkeypatch.setattr(shared, "STRIPE_SECRET_KEY", "sk_test_x")

    def _create(**kw):
        captured.update(kw)
        return types.SimpleNamespace(url="https://stripe.example/x", id="cs_1")

    monkeypatch.setattr(
        stripe, "checkout",
        types.SimpleNamespace(Session=types.SimpleNamespace(create=_create)),
        raising=False,
    )
    make_client()
    issue_test_statement("testclient", 2.0)                      # $700
    c = storage.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 3.0, "note": "unbilled"})
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    resp = client_session.post("/portal/client/payment/stripe", json={})
    assert resp.status_code == 200
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 70000


def test_overview_shows_billed_hours(client_session, make_client, issue_test_statement):
    make_client()
    issue_test_statement("testclient", 1.5)
    c = storage.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 4.0, "note": "unbilled"})
    c["hours_billed"] = 5.5                                       # live total must not show
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    html = client_session.get("/client-portal").get_data(as_text=True)
    values = re.findall(r'portal-stat-value[^>]*>\s*([^<]*?)\s*<', html)
    assert "1.5" in values and "5.5" not in values
    assert "5.5" not in html


def test_new_badge_renders_when_statement_unseen(client_session, make_client, issue_test_statement):
    make_client()
    issue_test_statement("testclient", 1.0)
    html = client_session.get("/client-portal").get_data(as_text=True)
    assert 'class="new-badge"' in html
    client_session.get("/portal/client/billing")
    html = client_session.get("/client-portal").get_data(as_text=True)
    assert 'class="new-badge"' not in html


def test_new_statement_after_view_is_flagged(client_session, make_client, issue_test_statement, monkeypatch):
    make_client()
    monkeypatch.setattr(billing, "_now", lambda: "2026-10-02T10:00:00")
    issue_test_statement("testclient", 1.0)
    assert client_session.get("/portal/client/billing").get_json()["has_new_statement"] is True
    monkeypatch.setattr(billing, "_now", lambda: "2026-10-02T10:00:05")
    issue_test_statement("testclient", 1.0, date="2026-10-02")
    assert client_session.get("/portal/client/billing").get_json()["has_new_statement"] is True
    assert client_session.get("/portal/client/billing").get_json()["has_new_statement"] is False


def test_view_without_new_statement_leaves_seen_at(client_session, make_client, issue_test_statement):
    make_client()
    issue_test_statement("testclient", 1.0)
    client_session.get("/portal/client/billing")
    seen = storage.load_client("testclient")["billing_seen_at"]
    assert seen
    client_session.get("/portal/client/billing")
    assert storage.load_client("testclient")["billing_seen_at"] == seen
    c = storage.load_client("testclient")
    assert seen == billing.load_ledger("testclient")["statements"][-1]["issued_at"]


def test_client_research_save_returns_billed_hours(client_session, make_client):
    make_client()
    d = client_session.post("/portal/client/research-save",
                            json={"memo": "<p>memo</p>", "question": "Is X legal?"}).get_json()
    assert d["success"] and "total_hours" not in d
    assert d["billed_hours"] == 0.0            # the 0.2 hrs just logged stays unbilled


def test_coinbase_charges_statement_amount_only(client_session, make_client, issue_test_statement, monkeypatch):
    make_client()
    issue_test_statement("testclient", 2.0)                      # $700
    c = storage.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 3.0, "note": "unbilled"})
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_API_KEY", "fake_key")

    captured = {}
    fake_response = types.SimpleNamespace(
        ok=True,
        json=lambda: {"data": {"hosted_url": "https://commerce.coinbase.com/charges/TESTCODE"}},
    )

    def _post(*a, **kw):
        captured.update(kw)
        return fake_response

    import blueprints.portal_client as pc
    monkeypatch.setattr(pc, "_http", types.SimpleNamespace(post=_post))

    resp = client_session.post("/portal/client/payment/coinbase", json={})
    assert resp.status_code == 200
    assert captured["json"]["local_price"]["amount"] == "700.00"


def test_claim_document_returns_billed_hours(client):
    d = client.post("/drafting/claim-document", json={
        "full_name": "Cal Claimant", "password": "long-enough-1",
        "draft_content": "<p>x</p>"}).get_json()
    assert d["billed_hours"] == 0 and "hours_billed" not in d
    assert d["success"] is True


def test_checkout_names_hide_client_details(client_session, make_client, issue_test_statement, monkeypatch):
    make_client()
    issue_test_statement("testclient", 2.0)
    monkeypatch.setattr(shared, "COINBASE_COMMERCE_API_KEY", "fake_key")
    captured = {}

    def _post(*a, **kw):
        captured.update(kw)
        return types.SimpleNamespace(ok=True, json=lambda: {"data": {"hosted_url": "https://x"}})

    import blueprints.portal_client as pc
    monkeypatch.setattr(pc, "_http", types.SimpleNamespace(post=_post))
    client_session.post("/portal/client/payment/coinbase", json={})
    blob = repr(captured["json"])
    assert "Test Client" not in blob and "hrs" not in blob
    assert captured["json"]["description"] == "Legal Services \u2014 Statement balance"
