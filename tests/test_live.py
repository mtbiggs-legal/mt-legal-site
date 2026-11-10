"""Live updates: change detection, access, client summary, and the idle timeout."""

import json
import os
import time

import pytest

import shared
from services import live, security, storage


def _touch(path):
    """Make a file's revision change even when tests run within one clock tick."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


@pytest.fixture
def two_clients(make_client):
    make_client("mine", client_name="Mine Client", next_court_date="2026-12-01")
    make_client("theirs", client_name="Their Client", assigned_attorney="SophiaH")


def test_client_rev_changes_on_record_ledger_and_documents(two_clients, tmp_path):
    r0 = live.client_rev("mine")
    c = storage.load_client("mine")
    c["hours_billed"] = 1.0
    storage.save_client(c)
    r1 = live.client_rev("mine")
    assert r1 != r0

    docs = shared.CLIENT_FILES_DIR / "mine" / "documents" / "Motions"
    docs.mkdir(parents=True)
    (docs / "motion.txt").write_text("x", encoding="utf-8")
    r2 = live.client_rev("mine")
    assert r2 != r1

    shared.CLIENT_BILLING_DIR.mkdir(parents=True, exist_ok=True)
    (shared.CLIENT_BILLING_DIR / "mine.json").write_text("{}", encoding="utf-8")
    assert live.client_rev("mine") != r2


def test_client_rev_rejects_unsafe_names():
    assert live.client_rev("../etc") == ""


def test_snapshot_only_lists_my_clients(two_clients):
    snap = live.attorney_snapshot("Endocide")
    assert set(snap["clients"]) == {"mine"}
    s = snap["clients"]["mine"]
    assert s["client_name"] == "Mine Client" and s["next_court_date"] == "2026-12-01"
    assert "assigned_attorney" not in s and "password" not in s


def test_attorney_live_route_reports_changes(attorney_session, two_clients):
    first = attorney_session.get("/portal/attorney/live").get_json()
    assert first["changed"] is True and "mine" in first["clients"]
    same = attorney_session.get("/portal/attorney/live?since=" + first["token"]).get_json()
    assert same == {"token": first["token"], "changed": False}

    c = storage.load_client("mine")
    c["last_communication"] = "2026-11-07"
    storage.save_client(c)
    after = attorney_session.get("/portal/attorney/live?since=" + first["token"]).get_json()
    assert after["changed"] is True
    assert after["clients"]["mine"]["last_communication"] == "2026-11-07"


def test_new_lead_changes_token(attorney_session, two_clients, tmp_path):
    t0 = attorney_session.get("/portal/attorney/live").get_json()["token"]
    (tmp_path / "leads" / "1_lead.json").write_text(json.dumps({"name": "L"}), encoding="utf-8")
    assert attorney_session.get("/portal/attorney/live?since=" + t0).get_json()["changed"] is True


def test_client_live_and_summary(client_session, make_client):
    make_client("testclient", client_name="Test Client", password="secret-hash",
                messages=[{"from": "attorney", "date": "2026-11-07 09:00", "text": "Hello"}],
                legal_issue="DUI", next_meeting="2026-11-10 10:00")
    first = client_session.get("/portal/client/live").get_json()
    assert first["changed"] is True
    assert client_session.get("/portal/client/live?since=" + first["token"]).get_json()["changed"] is False

    s = client_session.get("/portal/client/summary").get_json()
    assert s["messages"] == [{"from": "attorney", "date": "2026-11-07 09:00", "text": "Hello"}]
    assert s["next_meeting"] == "2026-11-10 10:00" and s["legal_issue"] == "DUI"
    assert "password" not in json.dumps(s) and "secret-hash" not in json.dumps(s)


def test_routes_are_role_gated(client, client_session, attorney_session):
    assert client.get("/portal/attorney/live").status_code == 302
    assert client_session.get("/portal/attorney/live").status_code == 302
    assert attorney_session.get("/portal/client/live").status_code == 302
    assert attorney_session.get("/portal/client/summary").status_code == 302


def test_routes_off_in_public_site_only(attorney_session, monkeypatch):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    assert attorney_session.get("/portal/attorney/live").status_code == 404


def test_live_poll_does_not_extend_idle_timeout(attorney_session, two_clients):
    start = time.time() - (security.IDLE_SECONDS - 60)      # 29 minutes idle
    with attorney_session.session_transaction() as s:
        s["last_seen"] = start
    assert attorney_session.get("/portal/attorney/live").status_code == 200
    with attorney_session.session_transaction() as s:
        assert s["last_seen"] == start                      # the poll didn't count as activity

    with attorney_session.session_transaction() as s:
        s["last_seen"] = time.time() - security.IDLE_SECONDS - 5
    r = attorney_session.get("/portal/attorney/live")
    assert r.status_code == 401 and r.headers.get("X-Session-Expired") == "1"


@pytest.mark.parametrize("path", ["/portal/attorney/client/mine", "/portal/attorney/documents/mine",
                                  "/portal/attorney/leads-list", "/portal/attorney/dashboard"])
def test_marked_background_refresh_does_not_extend_idle_timeout(attorney_session, two_clients, path):
    start = time.time() - 600
    with attorney_session.session_transaction() as s:
        s["last_seen"] = start
    assert attorney_session.get(path, headers={"X-Live-Refresh": "1"}).status_code == 200
    with attorney_session.session_transaction() as s:
        assert s["last_seen"] == start


def test_marked_refresh_cannot_revive_expired_session(attorney_session, two_clients):
    with attorney_session.session_transaction() as s:
        s["last_seen"] = time.time() - security.IDLE_SECONDS - 5
    r = attorney_session.get("/portal/attorney/client/mine", headers={"X-Live-Refresh": "1"})
    assert r.status_code == 401


def test_client_background_refresh_does_not_extend_idle_timeout(client_session, make_client):
    make_client("testclient")
    start = time.time() - 600
    with client_session.session_transaction() as s:
        s["last_seen"] = start
    for path in ("/portal/client/summary", "/portal/client/billing", "/portal/client/documents"):
        assert client_session.get(path, headers={"X-Live-Refresh": "1"}).status_code == 200
    with client_session.session_transaction() as s:
        assert s["last_seen"] == start


def test_normal_requests_still_extend_idle_timeout(attorney_session, two_clients):
    start = time.time() - 600
    with attorney_session.session_transaction() as s:
        s["last_seen"] = start
    attorney_session.get("/portal/attorney/clients")
    with attorney_session.session_transaction() as s:
        assert s["last_seen"] > start
