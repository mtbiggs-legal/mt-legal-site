"""Throttle hardening: race, state-file bounds/atomicity, per-IP limit, static, no-store."""

import json
import threading

import pytest

from services import security, storage


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1_000_000.0}
    monkeypatch.setattr(security, "_now", lambda: t["now"])
    return t


def test_begin_attempt_is_atomic_under_parallel_requests(clock):
    results = []
    barrier = threading.Barrier(6)

    def worker():
        barrier.wait()
        results.append(security.begin_login_attempt("client", "bob", "1.1.1.1"))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(0) <= 5
    assert security.login_locked("client", "bob", "1.1.1.1") > 0


def test_begin_attempt_returns_remaining_when_locked(clock):
    for _ in range(5):
        assert security.begin_login_attempt("client", "bob", "ip") == 0
    assert security.begin_login_attempt("client", "bob", "ip") > 0


def test_state_file_is_capped(clock, monkeypatch):
    monkeypatch.setattr(security, "MAX_TRACKED_KEYS", 3)
    for i in range(5):
        clock["now"] += 1
        security.record_login_failure("client", f"u{i}", "ip")
    data = json.loads(security._failures_path().read_text())
    assert len(data) == 3
    assert set(data) == {f"client:u{i}:ip" for i in (2, 3, 4)}


def test_cap_evicts_unlocked_before_locked(clock, monkeypatch):
    monkeypatch.setattr(security, "MAX_TRACKED_KEYS", 2)
    for _ in range(5):                       # oldest entry becomes locked
        security.record_login_failure("client", "locked", "ip")
    for i in range(3):
        clock["now"] += 1
        security.record_login_failure("client", f"u{i}", "ip")
    data = json.loads(security._failures_path().read_text())
    assert "client:locked:ip" in data
    assert len(data) == 2


def test_save_failure_does_not_raise(clock, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("locked")
    # The failures file is written through storage.write_json.
    monkeypatch.setattr(storage.os, "replace", boom)
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    security.record_login_failure("client", "bob", "ip")   # must not raise


def test_ip_spray_limit(clock):
    for i in range(20):
        assert security.begin_login_attempt("client", f"user{i}", "9.9.9.9") == 0
    assert security.begin_login_attempt("client", "user-new", "9.9.9.9") > 0
    assert security.begin_login_attempt("client", "user-new", "8.8.8.8") == 0


def test_successful_logins_never_lock_shared_ip(clock):
    for i in range(30):
        clock["now"] += 1
        assert security.begin_login_attempt("client", f"user{i}", "9.9.9.9") == 0
        security.clear_login_failures("client", f"user{i}", "9.9.9.9")
    assert security.begin_login_attempt("client", "another", "9.9.9.9") == 0


def test_success_does_not_undo_an_existing_ip_lock(clock):
    for i in range(20):
        security.begin_login_attempt("client", f"user{i}", "9.9.9.9")
    security.clear_login_failures("client", "user0", "9.9.9.9")
    assert security.begin_login_attempt("client", "new", "9.9.9.9") > 0


def test_static_requests_do_not_refresh_idle_session(attorney_session):
    with attorney_session.session_transaction() as s:
        s["last_seen"] = security._now() - 31 * 60
    assert attorney_session.get("/static/css/tokens.css").status_code == 200
    r = attorney_session.get("/portal/attorney/dashboard")
    assert r.status_code == 401


def test_no_store_on_dynamic_not_static(attorney_session):
    r = attorney_session.get("/portal/attorney/token-usage")
    assert "no-store" in r.headers.get("Cache-Control", "")
    r = attorney_session.get("/static/css/tokens.css")
    assert "no-store" not in r.headers.get("Cache-Control", "")
