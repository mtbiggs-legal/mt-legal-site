"""Clients and matters: several matters per client, one current."""

from services import matters, storage


def test_existing_client_gets_one_matter(attorney_session, make_client):
    make_client(case_type="Criminal Defense", case_no="24-CR-1")
    d = attorney_session.get("/portal/attorney/matters/testclient").get_json()
    (m,) = d["matters"]
    assert m["current"] and m["case_no"] == "24-CR-1" and m["status"] == "open"
    assert storage.load_client("testclient")["current_matter"] == m["id"]


def test_open_switch_close(attorney_session, make_client):
    make_client(case_type="Criminal Defense", case_no="24-CR-1")
    first = matters.list_for("testclient")[0]["id"]
    d = attorney_session.post("/portal/attorney/matters/open", json={
        "username": "testclient", "title": "Estate plan", "case_type": "Estate Planning",
        "opposing_parties": []}).get_json()
    assert d["success"]
    rec = storage.load_client("testclient")
    assert rec["case_type"] == "Estate Planning" and rec["case_no"] == ""
    # The old matter kept its details.
    old = next(m for m in matters.list_for("testclient") if m["id"] == first)
    assert old["case_no"] == "24-CR-1" and not old["current"]
    # Switch back: the record shows the old matter again.
    attorney_session.post("/portal/attorney/matters/switch", json={"username": "testclient", "id": first})
    assert storage.load_client("testclient")["case_no"] == "24-CR-1"
    d = attorney_session.post("/portal/attorney/matters/close",
                              json={"username": "testclient", "id": d["matter"]["id"]}).get_json()
    assert [m["status"] for m in d["matters"]] == ["open", "closed"]


def test_new_matter_runs_conflict_check(attorney_session, make_client):
    make_client()
    make_client("other", client_name="Acme Roofing")
    d = attorney_session.post("/portal/attorney/matters/open", json={
        "username": "testclient", "title": "Contract", "opposing_parties": ["Acme Roofing"]}).get_json()
    assert d["conflict_hits"]
    assert storage.load_client("testclient")["conflict_checks"][-1]["trigger"] == "new_matter"


def test_matter_details_encrypted(make_client):
    from services import db
    make_client(case_no="SECRET-CASE-9")
    matters.list_for("testclient")
    raw = bytes(db.conn().execute("SELECT data FROM matters").fetchone()[0])
    assert b"SECRET-CASE-9" not in raw


def test_other_attorney_cannot_see_matters(attorney_session, make_client):
    make_client()
    with attorney_session.session_transaction() as s:
        s["username"] = "SophiaH"
    assert attorney_session.get("/portal/attorney/matters/testclient").status_code == 404
