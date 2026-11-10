"""Gaps found in the follow-up review of the hardening work."""

import json
from pathlib import Path

import app as app_module
import shared
from services import accounts, intake_queue, security, storage


def test_production_startup_moves_record_files_into_database(monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "IS_PRODUCTION", True)
    monkeypatch.setattr(shared, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    shared.CLIENT_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    (shared.CLIENT_ACCOUNTS_DIR / "old1.json").write_text(
        json.dumps({"username": "old1", "client_name": "Old One"}), encoding="utf-8")
    app_module._auto_migrate_records()
    assert storage.load_client("old1")["client_name"] == "Old One"
    assert not list(shared.CLIENT_ACCOUNTS_DIR.glob("*.json"))
    assert list((tmp_path / "migration-backup").glob("client-accounts-*/old1.json"))
    assert not any("migrate_to_db" in p for p in app_module.check_startup_config())


def test_local_startup_does_not_auto_migrate(monkeypatch):
    monkeypatch.setattr(shared, "IS_PRODUCTION", False)
    (shared.CLIENT_ACCOUNTS_DIR / "old2.json").write_text('{"username": "old2"}', encoding="utf-8")
    app_module._auto_migrate_records()
    assert not storage.client_exists("old2")


def test_invite_link_uses_portal_host_when_set(monkeypatch):
    monkeypatch.setattr(shared, "SITE_URL", "https://www.example.test")
    assert accounts.invite_url("u.tok") == "https://www.example.test/client-portal/invite/u.tok"
    monkeypatch.setattr(shared, "PORTAL_URL", "https://portal.example.test")
    assert accounts.invite_url("u.tok") == "https://portal.example.test/client-portal/invite/u.tok"


def test_lead_form_is_rate_limited(client):
    client.application.config["RATE_LIMITS_ENABLED"] = True
    try:
        codes = [client.post("/capture/lead", json={"name": "A B"}).status_code for _ in range(6)]
    finally:
        client.application.config["RATE_LIMITS_ENABLED"] = False
        security._rate_hits.clear()
    assert codes == [200] * 5 + [429]


def test_visit_counter_rejects_odd_page_names(client):
    client.post("/api/track-visit", json={"page": "home"})
    client.post("/api/track-visit", json={"page": "x" * 500})
    client.post("/api/track-visit", json={"page": {"a": 1}})
    assert storage._load_page_visits() == {"home": 1}


def test_intake_keeps_the_esignature_consent(client, attorney_session):
    client.post("/intake/submit", json={
        "full_name": "Dana Cole", "email": "dana@example.com", "phone": "615-555-0101",
        "matter_description": "x",
        "esignature": {"signed": True, "signer": "Dana Cole", "timestamp": "2026-11-09T12:00:00Z",
                       "junk": "<script>"}})
    (entry,) = intake_queue.list_pending("Endocide")
    assert entry["esignature"]["signed"] is True and "junk" not in entry["esignature"]
    d = attorney_session.post("/portal/attorney/intakes/approve", json={"id": entry["id"]}).get_json()
    assert storage.load_client(d["username"])["esignature"]["signer"] == "Dana Cole"


def test_standalone_pages_load_the_click_dispatcher():
    for p in Path("templates").glob("*.html"):
        s = p.read_text(encoding="utf-8")
        if "data-on-" in s and "{% extends" not in s:
            assert "js/events.js" in s, p.name
