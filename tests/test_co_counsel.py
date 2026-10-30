"""Co-counsel management (spec A3)."""

from services import storage


def _post(c, **body):
    return c.post("/portal/attorney/co-counsel", json={"username": "victim", **body})


def test_assigned_attorney_adds_and_removes(attorney_session, make_client):
    make_client("victim")
    r = _post(attorney_session, action="add", attorney="SophiaH")
    assert r.status_code == 200 and r.get_json()["co_counsel"] == ["SophiaH"]
    log = storage.load_client("victim")["access_log"]
    assert log[-1]["action"] == "co_counsel_change"
    r = _post(attorney_session, action="remove", attorney="SophiaH")
    assert r.get_json()["co_counsel"] == []


def test_adding_twice_is_idempotent(attorney_session, make_client):
    make_client("victim")
    _post(attorney_session, action="add", attorney="SophiaH")
    assert _post(attorney_session, action="add", attorney="SophiaH").get_json()["co_counsel"] == ["SophiaH"]


def test_cannot_add_self_or_unknown(attorney_session, make_client):
    make_client("victim")
    assert _post(attorney_session, action="add", attorney="Endocide").status_code == 400
    assert _post(attorney_session, action="add", attorney="Ghost").status_code == 400
    assert _post(attorney_session, action="promote", attorney="SophiaH").status_code == 400


def test_co_counsel_cannot_change_list(other_attorney_session, make_client):
    make_client("victim", co_counsel=["SophiaH"])
    assert _post(other_attorney_session, action="remove", attorney="SophiaH").status_code == 404
