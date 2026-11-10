"""Attorney two-step sign-in, session revocation, password change, logout."""

import pytest

import shared
from services import accounts, security, storage, two_factor


@pytest.fixture
def atty(monkeypatch):
    monkeypatch.setitem(shared.ATTORNEYS["Endocide"], "password",
                        accounts.hash_password("correct-horse"))
    monkeypatch.setattr(shared, "ATTORNEY_2FA_REQUIRED", True)


def _login(c):
    return c.post("/attorney-login", data={"username": "Endocide", "password": "correct-horse"})


def _enroll(c):
    _login(c)
    secret = two_factor.pending_secret("Endocide")
    codes = two_factor.confirm_setup("Endocide", two_factor.code_at(secret, int(two_factor._now() // 30)))
    return secret, codes


def test_password_alone_does_not_sign_in(client, atty):
    r = _login(client)
    assert r.headers["Location"].endswith("/attorney-login/setup")
    with client.session_transaction() as s:
        assert "role" not in s and s["mfa_user"] == "Endocide"
    assert client.get("/attorney-portal").status_code == 302


def test_setup_then_code_signs_in(client, atty, monkeypatch):
    _login(client)
    page = client.get("/attorney-login/setup").get_data(as_text=True)
    secret = two_factor.pending_secret("Endocide")
    assert secret in page
    code = two_factor.code_at(secret, int(two_factor._now() // 30))
    r = client.post("/attorney-login/setup", data={"code": code})
    assert r.status_code == 200 and b"Recovery" in r.data
    with client.session_transaction() as s:
        assert s["role"] == "attorney"
    assert two_factor.is_enabled("Endocide") and two_factor.recovery_left("Endocide") == 10


def test_enrolled_attorney_needs_code(client, atty, monkeypatch):
    secret, _ = _enroll(client)
    client.post("/logout")
    r = _login(client)
    assert r.headers["Location"].endswith("/attorney-login/verify")
    assert client.post("/attorney-login/verify", data={"code": "000000"}).status_code == 200
    with client.session_transaction() as s:
        assert "role" not in s
    monkeypatch.setattr(two_factor, "_now", lambda: two_factor.time.time() + 30)
    code = two_factor.code_at(secret, int(two_factor._now() // 30))
    r = client.post("/attorney-login/verify", data={"code": code})
    assert r.headers["Location"].endswith("/attorney-portal")


def test_code_cannot_be_replayed(client, atty):
    secret, _ = _enroll(client)                   # the setup code is now used
    used = two_factor.code_at(secret, int(two_factor._now() // 30))
    assert not two_factor.verify("Endocide", used)


def test_recovery_code_works_once(client, atty):
    _, codes = _enroll(client)
    assert two_factor.verify("Endocide", codes[0])
    assert not two_factor.verify("Endocide", codes[0])
    assert two_factor.recovery_left("Endocide") == 9


def test_mfa_step_expires(client, atty, monkeypatch):
    _enroll(client)
    client.post("/logout")
    _login(client)
    with client.session_transaction() as s:
        s["mfa_at"] = security._now() - 600
    assert client.get("/attorney-login/verify").headers["Location"].endswith("/attorney-login")


def test_state_is_encrypted(client, atty):
    secret, _ = _enroll(client)
    raw = (shared.SECURITY_STATE_DIR / "attorney-2fa.json").read_bytes()
    assert secret.encode() not in raw


# ── Sessions ──────────────────────────────────────────────────────────────────

def test_bumping_version_ends_old_sessions(attorney_session):
    assert attorney_session.get("/portal/attorney/token-usage").status_code == 200
    security.bump_session_version("attorney", "Endocide")
    r = attorney_session.get("/portal/attorney/token-usage", headers={"Accept": "application/json"})
    assert r.status_code == 401


def test_session_for_removed_attorney_ends(client):
    with client.session_transaction() as s:
        s["role"], s["username"] = "attorney", "Nobody"
    r = client.get("/portal/attorney/token-usage", headers={"Accept": "application/json"})
    assert r.status_code == 401


def test_logout_is_post_only(attorney_session):
    assert attorney_session.get("/logout").status_code == 405
    assert attorney_session.post("/logout").status_code == 302
    with attorney_session.session_transaction() as s:
        assert "role" not in s


# ── Password change ───────────────────────────────────────────────────────────

def _pw_client(make_client, client_session):
    make_client(password=accounts.hash_password("Old-Pass-123"))
    return client_session


def test_change_password_needs_current(make_client, client_session):
    c = _pw_client(make_client, client_session)
    r = c.post("/client-portal/change-password", data={
        "current_password": "wrong", "new_password": "New-Pass-456", "confirm_password": "New-Pass-456"})
    assert r.status_code == 200 and b"not correct" in r.data
    assert accounts.check_password("Old-Pass-123", storage.load_client("testclient")["password"])


def test_change_password_rejects_weak(make_client, client_session):
    c = _pw_client(make_client, client_session)
    r = c.post("/client-portal/change-password", data={
        "current_password": "Old-Pass-123", "new_password": "password", "confirm_password": "password"})
    assert r.status_code == 200
    assert accounts.check_password("Old-Pass-123", storage.load_client("testclient")["password"])


def test_change_password_signs_out_other_sessions(make_client, client_session, patch_dirs):
    from conftest import flask_app
    c = _pw_client(make_client, client_session)
    with flask_app.test_client() as other:
        with other.session_transaction() as s:
            s["role"], s["username"] = "client", "testclient"
        r = c.post("/client-portal/change-password", data={
            "current_password": "Old-Pass-123", "new_password": "New-Pass-456",
            "confirm_password": "New-Pass-456"})
        assert r.status_code == 302
        assert c.get("/portal/client/billing").status_code == 200       # this session continues
        assert other.get("/portal/client/billing",
                         headers={"Accept": "application/json"}).status_code == 401


def test_plaintext_password_never_matches():
    assert not accounts.check_password("secret", "secret")


# ── Lockout across IPs ────────────────────────────────────────────────────────

def test_account_locks_across_ips(monkeypatch):
    for i in range(security.ACCOUNT_MAX_FAILURES):
        assert security.begin_login_attempt("client", "victim", f"10.0.0.{i}") == 0
    assert security.begin_login_attempt("client", "victim", "10.0.9.9") > 0


def test_sign_in_events_are_audited(client, atty):
    from services import audit
    _login(client)                                       # password ok -> setup step
    client.post("/attorney-login", data={"username": "Endocide", "password": "wrong"})
    actions = [e["action"] for e in audit.recent(10)]
    assert "login_password_ok" in actions and "login_failed" in actions


def test_sign_in_activity_route(attorney_session):
    from services import audit
    audit.record("login_failed", actor="someone", role="", detail="client someone")
    d = attorney_session.get("/portal/attorney/sign-in-activity").get_json()
    assert d["events"][0]["action"] == "login_failed"
