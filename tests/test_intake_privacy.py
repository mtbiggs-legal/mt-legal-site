"""Public intake never reveals other clients (spec D3.1)."""

import shared


def test_intake_returns_no_conflict_data(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    r = client.post("/intake/submit", json={
        "full_name": "Bob Smith", "case_type": "Civil Litigation",
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
