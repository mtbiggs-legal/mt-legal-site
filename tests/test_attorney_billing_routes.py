"""Attorney billing routes (spec C3)."""

from services import billing
from services import storage


def _client(make_client, hours=1.0, **kw):
    return make_client("ab", billing_log=[{"date": "2026-10-01", "hours": hours, "note": "x"}],
                       hours_billed=hours, email="ab@example.com", **kw)


def test_client_get_includes_billing_summary(attorney_session, make_client):
    _client(make_client)
    s = attorney_session.get("/portal/attorney/client/ab").get_json()["billing_summary"]
    assert s["unbilled_hours"] == 1.0 and s["threshold"] == 2000.0


def test_issue_statement(attorney_session, make_client, sent_statement_emails):
    _client(make_client)
    r = attorney_session.post("/portal/attorney/issue-statement", json={"username": "ab"})
    d = r.get_json()
    assert r.status_code == 200 and d["statement"]["reason"] == "manual"
    assert d["billing_summary"]["unbilled_hours"] == 0.0
    assert len(sent_statement_emails) == 1
    assert storage.load_client("ab")["access_log"][-1]["action"] == "statement_issued"
    r2 = attorney_session.post("/portal/attorney/issue-statement", json={"username": "ab"})
    assert r2.status_code == 400 and r2.get_json()["error"] == "No unbilled time to bill."


def test_issue_statement_access(other_attorney_session, make_client):
    _client(make_client)
    assert other_attorney_session.post("/portal/attorney/issue-statement",
                                       json={"username": "ab"}).status_code == 404
    _client(make_client, co_counsel=["SophiaH"])
    assert other_attorney_session.post("/portal/attorney/issue-statement",
                                       json={"username": "ab"}).status_code == 200


def test_statement_notice_resend(attorney_session, make_client, monkeypatch):
    import blueprints.email_service as es
    _client(make_client)
    monkeypatch.setattr(es, "send_statement_email", lambda *a: "failed")
    attorney_session.post("/portal/attorney/issue-statement", json={"username": "ab"})
    monkeypatch.setattr(es, "send_statement_email", lambda *a: "sent")
    r = attorney_session.post("/portal/attorney/statement-notice",
                              json={"username": "ab", "statement_id": "st_1"})
    assert r.status_code == 200
    assert billing.load_ledger("ab")["statements"][0]["notice"]["status"] == "sent"
    assert r.get_json()["billing_summary"]["statements"][0]["notice"]["status"] == "sent"
    r = attorney_session.post("/portal/attorney/statement-notice",
                              json={"username": "ab", "statement_id": "st_1"})
    assert r.status_code == 400


def test_billing_settings(attorney_session):
    assert attorney_session.get("/portal/attorney/billing-settings").get_json() == {
        "threshold": 2000.0, "default": 2000.0}
    r = attorney_session.post("/portal/attorney/billing-settings", json={"threshold": 50})
    assert r.status_code == 400
    assert attorney_session.post("/portal/attorney/billing-settings",
                                 json={"threshold": 1200}).get_json()["threshold"] == 1200.0
    assert billing.get_threshold("Endocide") == 1200.0 and billing.get_threshold("SophiaH") == 2000.0


def test_billing_entry_returns_summary(attorney_session, make_client, sent_statement_emails):
    make_client("ab", email="ab@example.com")
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "ab", "note": "small", "hours": 1})
    s = r.get_json()["billing_summary"]
    assert s["unbilled_hours"] == 1.0 and s["statements"] == []
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "ab", "note": "big", "hours": 6})
    s = r.get_json()["billing_summary"]
    assert len(s["statements"]) == 1 and s["unbilled_hours"] == 0.0


def test_bad_bodies(attorney_session):
    for url in ("issue-statement", "statement-notice"):
        assert attorney_session.post("/portal/attorney/" + url, json=[1]).status_code == 404
        assert attorney_session.post("/portal/attorney/" + url).status_code == 404
    assert attorney_session.post("/portal/attorney/billing-settings", json=[1]).status_code == 400
    assert attorney_session.post("/portal/attorney/billing-settings").status_code == 400


def test_billing_settings_missing_or_bad_threshold(attorney_session):
    assert attorney_session.post("/portal/attorney/billing-settings", json={}).status_code == 400
    assert attorney_session.post("/portal/attorney/billing-settings",
                                 json={"threshold": "abc"}).status_code == 400


def test_issue_statement_404_leaves_no_log(other_attorney_session, make_client):
    _client(make_client)
    assert other_attorney_session.post("/portal/attorney/issue-statement",
                                       json={"username": "ab"}).status_code == 404
    assert storage.load_client("ab").get("access_log", []) == []
