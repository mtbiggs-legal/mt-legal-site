"""Public intake only queues a submission: no account, no client data back."""

from pathlib import Path

import shared
from services import intake_queue, security, storage


def _intake(client, **overrides):
    payload = {"full_name": "Dana Cole", "email": "dana@example.com", "phone": "615-555-0101",
               "matter_description": "Question about a crypto will"}
    payload.update(overrides)
    return client.post("/intake/submit", json=payload)


def test_intake_queues_and_opens_no_account(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    before = set(storage.all_usernames())
    r = _intake(client, full_name="Bob Smith", opposing_party="Acme Roofing")
    d = r.get_json()
    assert r.status_code == 200 and d["success"]
    assert set(d) == {"success", "urgent_dates", "email_sent"}
    assert "Robert Smith" not in r.get_data(as_text=True)
    assert set(storage.all_usernames()) == before
    (entry,) = intake_queue.list_pending("Endocide")
    assert entry["fields"]["full_name"] == "Bob Smith"


def test_queued_intake_is_encrypted_at_rest(client):
    _intake(client, matter_description="secret matter text")
    (path,) = list(shared.PENDING_INTAKE_DIR.glob("*.json"))
    assert b"secret matter text" not in path.read_bytes()


def test_intake_requires_email_and_phone(client):
    for missing in ("email", "phone"):
        assert _intake(client, **{missing: ""}).status_code == 400, missing


def test_intake_is_rate_limited(client):
    client.application.config["RATE_LIMITS_ENABLED"] = True
    try:
        codes = [_intake(client).status_code for _ in range(6)]
    finally:
        client.application.config["RATE_LIMITS_ENABLED"] = False
        security._rate_hits.clear()
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_approve_opens_account_with_random_name_and_invite(client, attorney_session, make_client):
    make_client("rsmith", client_name="Robert Smith")
    _intake(client, full_name="Bob Smith", case_type="", opposing_party="Acme Roofing")
    (entry,) = intake_queue.list_pending("Endocide")
    d = attorney_session.post("/portal/attorney/intakes/approve", json={"id": entry["id"]}).get_json()
    assert d["success"]
    rec = storage.load_client(d["username"])
    assert d["username"].startswith("c") and "smith" not in d["username"]
    assert rec["case_type"] == "Other"
    assert rec["password"] == "" and rec["invite"]["digest"]
    assert rec["opposing_parties"] == ["Acme Roofing"]
    assert rec["conflict_checks"][0]["hits"][0]["matched_name"] == "Robert Smith"
    assert d["conflict_hits"] == 1
    assert all(float(e.get("hours", 0)) == 0 for e in rec["billing_log"])
    assert intake_queue.list_pending("Endocide") == []
    # A second approval of the same intake does nothing.
    assert attorney_session.post("/portal/attorney/intakes/approve",
                                 json={"id": entry["id"]}).status_code == 404


def test_intake_review_requires_attorney(client, client_session):
    for c in (client, client_session):
        r = c.get("/portal/attorney/intakes", headers={"Accept": "application/json"})
        assert r.status_code == 401
        assert c.post("/portal/attorney/intakes/approve", json={"id": "x"}).status_code == 401


def test_decline_takes_no_action(client, attorney_session):
    _intake(client)
    (entry,) = intake_queue.list_pending("Endocide")
    assert attorney_session.post("/portal/attorney/intakes/decline",
                                 json={"id": entry["id"]}).get_json()["success"]
    assert intake_queue.list_pending("Endocide") == []
    assert storage.all_usernames() == []


def test_self_registration_is_gone(client):
    assert client.post("/client-register", json={}).status_code in (404, 405)
    assert client.post("/drafting/claim-document", json={}).status_code in (404, 405)


def test_intake_page_marks_optional_fields_and_drops_fee_notice():
    html = Path("templates/intake.html").read_text(encoding="utf-8")
    assert "0.2 billable" not in html
    assert '<label for="case_type">Case Type <span class="field-optional">(optional)</span></label>' in html
    assert 'id="email" name="email" placeholder="client@example.com" required' in html
    assert 'id="phone" name="phone" placeholder="(555) 000-0000" required' in html
