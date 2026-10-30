"""Attorney conflict endpoints (spec D3, D4)."""

import json

import shared
from services import storage


def test_create_client_records_and_returns_redacted(other_attorney_session, make_client):
    make_client("rsmith", client_name="Robert Smith")        # Endocide's client
    d = other_attorney_session.post("/portal/attorney/create-client", json={
        "username": "bsmith", "client_name": "Bob Smith", "case_type": "Civil Litigation",
        "opposing_parties": ["Zed Corp"],
        "related_parties": [{"name": "Kim Smith", "relationship": "Spouse"}]}).get_json()
    assert d["conflict_warnings"] and "username" not in d["conflict_hits"][0]
    rec = storage.load_client("bsmith")
    assert rec["opposing_parties"] == ["Zed Corp"]
    assert rec["related_parties"] == [{"name": "Kim Smith", "relationship": "Spouse"}]
    assert rec["conflict_checks"][0]["trigger"] == "create"


def test_manual_check_unattached_goes_to_firm_log(attorney_session, make_client, tmp_path):
    make_client("c1", client_name="Robert Smith")
    d = attorney_session.post("/portal/attorney/conflict-check",
                              json={"names": ["Bob Smith"]}).get_json()
    assert d["check"]["hits"][0]["matched_name"] == "Robert Smith"
    log = json.loads((tmp_path / "security" / "conflict-checks.json").read_text())
    assert log[0]["names"] == ["Bob Smith"]


def test_manual_check_attached(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    attorney_session.post("/portal/attorney/conflict-check",
                          json={"names": ["Bob Smith"], "username": "c2"})
    c2 = storage.load_client("c2")
    assert c2["conflict_checks"][0]["trigger"] == "manual"
    assert c2["access_log"][-1]["action"] == "conflict_check"


def test_manual_check_validation(attorney_session, other_attorney_session, make_client):
    make_client("c1")
    assert attorney_session.post("/portal/attorney/conflict-check",
                                 json={"names": ["  "]}).status_code == 400
    assert other_attorney_session.post("/portal/attorney/conflict-check",
                                       json={"names": ["x"], "username": "c1"}).status_code == 404


def test_decision_flow(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    chk = attorney_session.post("/portal/attorney/conflict-check",
                                json={"names": ["Bob Smith"], "username": "c2"}).get_json()["check"]
    url = "/portal/attorney/conflict-decision"
    assert attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                            "decision": "maybe"}).status_code == 400
    assert attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                            "decision": "waiver_obtained"}).status_code == 400
    assert attorney_session.post(url, json={"username": "c2", "check_id": "nope",
                                            "decision": "cleared"}).status_code == 404
    r = attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                         "decision": "waiver_obtained",
                                         "note": "Signed waiver 10/1"})
    assert r.status_code == 200
    saved = storage.load_client("c2")["conflict_checks"][0]
    assert saved["decision"] == "waiver_obtained" and saved["decided_by"] == "Endocide"


def test_update_client_rechecks_new_parties_only(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person", opposing_parties=["Robert Smith"])
    r = attorney_session.post("/portal/attorney/update-client", json={
        "username": "c2", "opposing_parties": ["Robert Smith"], "related_parties": []})
    assert r.get_json()["conflict_hits"] == []          # nothing new
    r = attorney_session.post("/portal/attorney/update-client", json={
        "username": "c2", "related_parties": [{"name": "Bob Smith", "relationship": "Witness"}]})
    assert r.get_json()["conflict_hits"][0]["matched_name"] == "Robert Smith"
    assert storage.load_client("c2")["conflict_checks"][-1]["trigger"] == "edit"


def test_client_get_includes_redacted_checks_and_sidebar_badge(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    attorney_session.post("/portal/attorney/conflict-check",
                          json={"names": ["Bob Smith"], "username": "c2"})
    d = attorney_session.get("/portal/attorney/client/c2").get_json()
    assert len(d["conflict_checks"]) == 1 and "access_log" not in d
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert 'title="Unresolved conflict check"' in html   # the badge element, not the CSS rule


def test_old_checker_removed():
    assert not hasattr(shared, "check_conflict_of_interest")


def test_update_client_rename_rechecks(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    r = attorney_session.post("/portal/attorney/update-client",
                              json={"username": "c2", "client_name": "Bob Smith"})
    assert r.get_json()["conflict_hits"][0]["matched_name"] == "Robert Smith"


def test_decision_history_kept(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    chk = attorney_session.post("/portal/attorney/conflict-check",
                                json={"names": ["Bob Smith"], "username": "c2"}).get_json()["check"]
    url = "/portal/attorney/conflict-decision"
    attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                     "decision": "declined", "note": "first"})
    attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                     "decision": "cleared", "note": "second"})
    saved = storage.load_client("c2")["conflict_checks"][0]
    assert saved["decision"] == "cleared"
    assert saved["decision_history"][0]["decision"] == "declined"
    assert saved["decision_history"][0]["decision_note"] == "first"


def test_client_get_hits_redacted_to_public_fields(other_attorney_session, make_client,
                                                  monkeypatch):
    from services.conflicts import PUBLIC_HIT_FIELDS
    # The firm is solo, so every case type routes to the managing partner.
    # Route this one to the second account to keep covering cross-attorney redaction.
    monkeypatch.setitem(shared.CASE_ATTORNEY_MAP, "Civil Litigation", "SophiaH")
    make_client("rsmith", client_name="Robert Smith")          # Endocide's client
    d = other_attorney_session.post("/portal/attorney/create-client", json={
        "username": "bsmith", "client_name": "Bob Smith",
        "case_type": "Civil Litigation"}).get_json()
    assert all("rsmith" not in w for w in d["conflict_warnings"])
    got = other_attorney_session.get("/portal/attorney/client/bsmith").get_json()
    hits = got["conflict_checks"][0]["hits"]
    assert hits and all(set(h) == set(PUBLIC_HIT_FIELDS) for h in hits)
