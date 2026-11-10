"""Time the portal logs by itself is unbilled until the attorney approves it."""

import io

from services import billing, storage


def _upload(attorney_session):
    return attorney_session.post("/portal/attorney/upload-document", data={
        "username": "testclient", "category": "Other",
        "file": (io.BytesIO(b"%PDF"), "a.pdf")}, content_type="multipart/form-data")


def _pending(username="testclient"):
    return [e for e in storage.load_client(username)["billing_log"] if e.get("pending_review")]


def test_upload_entry_starts_unbilled(attorney_session, make_client):
    make_client()
    _upload(attorney_session)
    (e,) = _pending()
    assert e["billable"] is False and e["auto"] and e["hours"] == 0.1
    assert billing.is_private(e)


def test_approve_makes_it_billable(attorney_session, make_client):
    make_client()
    _upload(attorney_session)
    (e,) = _pending()
    d = attorney_session.post("/portal/attorney/time-entry/review",
                              json={"username": "testclient", "id": e["id"], "approve": True}).get_json()
    assert d["success"]
    saved = next(x for x in storage.load_client("testclient")["billing_log"] if x.get("id") == e["id"])
    assert "billable" not in saved and not saved["pending_review"] and saved["reviewed_by"] == "Endocide"
    assert not billing.is_private(saved)


def test_reject_keeps_it_unbilled(attorney_session, make_client):
    make_client()
    _upload(attorney_session)
    (e,) = _pending()
    attorney_session.post("/portal/attorney/time-entry/review",
                          json={"username": "testclient", "id": e["id"], "approve": False})
    saved = next(x for x in storage.load_client("testclient")["billing_log"] if x.get("id") == e["id"])
    assert saved["billable"] is False and saved["rejected"]
    # Already decided: a second review does nothing.
    r = attorney_session.post("/portal/attorney/time-entry/review",
                              json={"username": "testclient", "id": e["id"], "approve": True})
    assert r.status_code == 404


def test_approval_under_flat_fee_stays_unbilled(attorney_session, make_client):
    make_client(flat_fee={"amount": 1500, "from_entry": 0})
    _upload(attorney_session)
    (e,) = _pending()
    attorney_session.post("/portal/attorney/time-entry/review",
                          json={"username": "testclient", "id": e["id"], "approve": True})
    saved = next(x for x in storage.load_client("testclient")["billing_log"] if x.get("id") == e["id"])
    assert saved["billable"] is False


def test_client_ai_reply_is_pending(client_session, make_client, monkeypatch):
    make_client()

    class _Msg:
        content = [type("T", (), {"text": "reply"})()]

    class _AI:
        class messages:
            @staticmethod
            def create(**kw):
                return _Msg()
    import blueprints.portal_client as pc
    monkeypatch.setattr(pc, "get_anthropic_client", lambda: _AI())
    client_session.post("/portal/client/message", json={"text": "hello"})
    (e,) = _pending()
    assert e["type"] == "ai_message" and e["billable"] is False


def test_other_attorney_cannot_review(attorney_session, make_client):
    make_client()
    _upload(attorney_session)
    (e,) = _pending()
    with attorney_session.session_transaction() as s:
        s["username"] = "SophiaH"              # not assigned to testclient
    r = attorney_session.post("/portal/attorney/time-entry/review",
                              json={"username": "testclient", "id": e["id"], "approve": True})
    assert r.status_code == 404
