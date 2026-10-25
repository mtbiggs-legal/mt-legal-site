"""CSRF token required on state-changing requests (spec B3)."""

import pytest

from conftest import flask_app


@pytest.fixture(autouse=True)
def csrf_on(monkeypatch):
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", True)


def _set_token(c, tok="tok123"):
    with c.session_transaction() as s:
        s["_csrf"] = tok
    return tok


def test_post_without_token_rejected(attorney_session, make_client):
    make_client("victim")
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "victim", "note": "x", "hours": 1})
    assert r.status_code == 400
    assert r.get_json() == {"error": "Invalid or missing CSRF token."}
    assert r.headers["X-CSRF-Failed"] == "1"


def test_post_with_header_accepted(attorney_session, make_client):
    make_client("victim")
    tok = _set_token(attorney_session)
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "victim", "note": "x", "hours": 1},
                              headers={"X-CSRF-Token": tok})
    assert r.status_code == 200


def test_wrong_token_rejected(attorney_session, make_client):
    make_client("victim")
    _set_token(attorney_session)
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "victim", "note": "x", "hours": 1},
                              headers={"X-CSRF-Token": "nope"})
    assert r.status_code == 400


def test_login_form_field_accepted(client):
    tok = _set_token(client)
    r = client.post("/attorney-login", data={"username": "x", "password": "y", "csrf_token": tok})
    assert r.status_code == 200  # wrong password, but not a CSRF failure


# /api/track-visit is also exempt but is left out here: posting to it writes
# the real page-visits.json, which conftest does not redirect.
@pytest.mark.parametrize("path", ["/webhooks/stripe", "/webhooks/coinbase", "/intake/submit",
                                  "/client-register", "/chat/message", "/capture/lead",
                                  "/follow-up/schedule"])
def test_exempt_paths(client, path):
    assert any(rule.rule == path for rule in flask_app.url_map.iter_rules()), path
    r = client.post(path, json={})
    assert r.headers.get("X-CSRF-Failed") is None


def test_get_never_checked(attorney_session):
    assert attorney_session.get("/portal/attorney/token-usage").status_code == 200


def test_pages_render_token_and_shim(client):
    html = client.get("/attorney-login").get_data(as_text=True)
    assert 'name="csrf-token"' in html
    assert 'name="csrf_token"' in html
    head = html.split("</head>")[0]
    assert "window.fetch = window.apiFetch" in head
    # The shim must run before any page script that could call fetch().
    assert head.index("window.fetch = window.apiFetch") < html.index("js/app.js")
