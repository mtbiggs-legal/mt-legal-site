"""5 failures in 15 minutes locks a username+IP for 15 minutes (spec B1)."""

import pytest

import security
import shared


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1_000_000.0}
    monkeypatch.setattr(security, "_now", lambda: t["now"])
    return t


@pytest.fixture
def atty_pw(monkeypatch):
    monkeypatch.setitem(shared.ATTORNEYS["Endocide"], "password",
                        shared.hash_password("correct-horse"))


def _login(c, pw):
    return c.post("/attorney-login", data={"username": "Endocide", "password": pw})


def test_unit_lock_after_five(clock):
    for _ in range(4):
        security.record_login_failure("client", "Bob", "1.1.1.1")
    assert security.login_locked("client", "bob", "1.1.1.1") == 0
    security.record_login_failure("client", "Bob", "1.1.1.1")
    assert security.login_locked("client", "bob", "1.1.1.1") > 0
    assert security.login_locked("client", "bob", "2.2.2.2") == 0
    clock["now"] += 15 * 60 + 1
    assert security.login_locked("client", "bob", "1.1.1.1") == 0


def test_failures_outside_window_do_not_count(clock):
    for _ in range(4):
        security.record_login_failure("client", "bob", "ip")
    clock["now"] += 16 * 60
    security.record_login_failure("client", "bob", "ip")
    assert security.login_locked("client", "bob", "ip") == 0


def test_attorney_login_locks_and_rejects_correct_password(client, clock, atty_pw):
    for _ in range(5):
        assert _login(client, "wrong").status_code == 200
    r = _login(client, "correct-horse")
    assert r.status_code == 429
    assert b"Too many failed attempts" in r.data


def test_success_clears_failures(client, clock, atty_pw):
    for _ in range(4):
        _login(client, "wrong")
    assert _login(client, "correct-horse").status_code == 302
    for _ in range(4):
        _login(client, "wrong")
    assert _login(client, "correct-horse").status_code == 302


def test_client_login_throttled(client, clock, make_client):
    make_client("jdoe", password=shared.hash_password("right-pass"))
    for _ in range(5):
        client.post("/client-login", data={"username": "jdoe", "password": "nope"})
    r = client.post("/client-login", data={"username": "jdoe", "password": "right-pass"})
    assert r.status_code == 429


def test_claim_document_throttled(client, clock, make_client):
    make_client("tclient", client_name="Test Client", password=shared.hash_password("right-pass"))
    body = {"full_name": "Test Client", "password": "wrong-pass", "draft_content": "<p>x</p>"}
    for _ in range(5):
        assert client.post("/drafting/claim-document", json=body).status_code == 403
    body["password"] = "right-pass"
    assert client.post("/drafting/claim-document", json=body).status_code == 429


def test_corrupt_state_file_is_treated_as_empty(clock):
    security._failures_path().parent.mkdir(parents=True, exist_ok=True)
    security._failures_path().write_text("{not json")
    assert security.login_locked("client", "bob", "ip") == 0
    security.record_login_failure("client", "bob", "ip")
