"""Session fixation, idle timeout, cookie flags (spec B2)."""

import pytest

import security
import shared
from conftest import flask_app


@pytest.fixture
def atty_pw(monkeypatch):
    monkeypatch.setitem(shared.ATTORNEYS["Endocide"], "password",
                        shared.hash_password("correct-horse"))


def test_login_resets_session_but_keeps_share_auth(client, atty_pw):
    with client.session_transaction() as s:
        s["planted"] = "attacker"
        s["share_authed"] = True
    client.post("/attorney-login", data={"username": "Endocide", "password": "correct-horse"})
    with client.session_transaction() as s:
        assert "planted" not in s
        assert s["share_authed"] is True
        assert s["role"] == "attorney" and "last_seen" in s


def test_login_cookie_flags(client, atty_pw):
    r = client.post("/attorney-login", data={"username": "Endocide", "password": "correct-horse"})
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_idle_session_json_gets_401(attorney_session):
    with attorney_session.session_transaction() as s:
        s["last_seen"] = security._now() - 31 * 60
    r = attorney_session.get("/portal/attorney/dashboard")
    assert r.status_code == 401
    assert r.headers["X-Session-Expired"] == "1"
    assert r.headers["X-Login-Url"].endswith("/attorney-login")
    with attorney_session.session_transaction() as s:
        assert "role" not in s


def test_idle_session_html_redirects(client_session):
    with client_session.session_transaction() as s:
        s["last_seen"] = security._now() - 31 * 60
    r = client_session.get("/client-portal", headers={"Accept": "text/html"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/client-login")


def test_active_session_refreshes_last_seen(attorney_session):
    with attorney_session.session_transaction() as s:
        s["last_seen"] = security._now() - 10 * 60
    attorney_session.get("/portal/attorney/token-usage")
    with attorney_session.session_transaction() as s:
        assert security._now() - s["last_seen"] < 5


def test_missing_last_seen_is_treated_as_fresh(attorney_session):
    assert attorney_session.get("/portal/attorney/token-usage").status_code == 200


def test_session_lifetime_configured():
    assert flask_app.permanent_session_lifetime.total_seconds() == 30 * 60


def test_login_rotates_csrf_token(client, atty_pw):
    with client.session_transaction() as s:
        s["_csrf"] = "before"
    client.post("/attorney-login", data={"username": "Endocide", "password": "correct-horse"})
    with client.session_transaction() as s:
        assert s.get("_csrf") != "before"
