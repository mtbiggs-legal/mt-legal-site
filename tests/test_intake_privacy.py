"""Public intake never reveals other clients (spec D3.1)."""

import shared


def test_intake_returns_no_conflict_data(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    r = client.post("/intake/submit", json={
        "full_name": "Bob Smith", "case_type": "Civil Litigation",
        "email": "bob@example.com", "phone": "615-555-0100",
        "matter_description": "Fence dispute", "opposing_party": "Acme Roofing"})
    d = r.get_json()
    assert r.status_code == 200
    assert "conflict_warnings" not in d and "conflict_hits" not in d
    assert "Robert Smith" not in r.get_data(as_text=True)
    rec = shared.load_client(d["portal_account"]["username"])
    assert rec["opposing_parties"] == ["Acme Roofing"]
    chk = rec["conflict_checks"][0]
    assert chk["trigger"] == "intake" and chk["hits"][0]["matched_name"] == "Robert Smith"


def test_self_register_records_check(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    d = client.post("/client-register", json={"full_name": "Bob Smith",
                                               "password": "long-enough-1"}).get_json()
    assert "conflict" not in str(d).lower()
    assert shared.load_client(d["username"])["conflict_checks"][0]["trigger"] == "self_register"


def test_claim_document_new_account_records_check(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    d = client.post("/drafting/claim-document", json={
        "full_name": "Bob Smith", "password": "long-enough-1",
        "draft_content": "<p>x</p>"}).get_json()
    assert "conflict" not in str(d).lower()
    assert shared.load_client(d["username"])["conflict_checks"][0]["trigger"] == "claim"


def _intake(client, **overrides):
    payload = {"full_name": "Dana Cole", "email": "dana@example.com", "phone": "615-555-0101",
               "matter_description": "Question about a crypto will"}
    payload.update(overrides)
    return client.post("/intake/submit", json=payload)


def test_intake_requires_email_and_phone(client):
    for missing in ("email", "phone"):
        r = _intake(client, **{missing: ""})
        assert r.status_code == 400, missing


def test_intake_case_type_is_optional_and_defaults_to_other(client):
    r = _intake(client)
    assert r.status_code == 200
    rec = shared.load_client(r.get_json()["portal_account"]["username"])
    assert rec["case_type"] == "Other"


def test_intake_does_not_bill_the_prospective_client(client):
    r = _intake(client, case_type="Estate Planning")
    rec = shared.load_client(r.get_json()["portal_account"]["username"])
    # The intake is logged as a zero-hour note; nothing is charged.
    assert all(float(e.get("hours", 0)) == 0 for e in rec.get("billing_log", []))
    assert not rec.get("hours_billed")


def test_intake_page_marks_optional_fields_and_drops_fee_notice():
    html = open("templates/intake.html", encoding="utf-8").read()
    assert "0.2 billable" not in html
    assert '<label for="case_type">Case Type <span class="field-optional">(optional)</span></label>' in html
    assert 'id="email" name="email" placeholder="client@example.com" required' in html
    assert 'id="phone" name="phone" placeholder="(555) 000-0000" required' in html
