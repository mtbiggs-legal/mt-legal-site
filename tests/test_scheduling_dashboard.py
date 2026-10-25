"""Case dates on the dashboard (spec C5)."""

from datetime import date, timedelta

import blueprints.portal_attorney as pa


def _d(days):
    return (date.today() + timedelta(days=days)).isoformat()


def test_case_dates_on_calendar_and_deadlines(attorney_session, make_client, monkeypatch):
    make_client("dc", client_name="Dana C", case_dates={
        "trial":   {"date": _d(30), "gcal_event_id": "g-trial"},
        "motions": {"date": _d(200), "gcal_event_id": None}})
    monkeypatch.setattr(pa, "_fetch_gcal_events", lambda days_ahead=180: [
        {"summary": "Trial: Dana C (court)", "start_date": _d(30), "start_datetime": "", "gcal_id": "g-trial"},
        {"summary": "Court hearing other", "start_date": _d(10), "start_datetime": "", "gcal_id": "g-other"}])
    d = attorney_session.get("/portal/attorney/dashboard").get_json()
    cal = [e for e in d["calendar"] if e.get("username") == "dc"]
    assert {(e["type"], e["matter"]) for e in cal} == {("Court Date", "Trial"), ("Court Date", "Motions Deadline")}
    assert not any(e.get("matter", "").startswith("Trial: Dana") for e in d["calendar"])   # deduped
    dl = [x for x in d["deadlines"] if x.get("username") == "dc"]
    assert [x["charges"] for x in dl] == ["Trial"]                                          # 200 days out excluded
    assert any("hearing other" in x["client_name"] for x in d["deadlines"])                 # other Google event kept


def test_malformed_case_dates_do_not_break_dashboard(attorney_session, make_client, monkeypatch):
    make_client("m1", client_name="Bad One", case_dates=[1])
    make_client("m2", client_name="Bad Two", case_dates={"trial": "x", "motions": None})
    make_client("m3", client_name="Good", case_dates={"trial": {"date": _d(20), "gcal_event_id": None}})
    monkeypatch.setattr(pa, "_fetch_gcal_events", lambda days_ahead=180: [])
    r = attorney_session.get("/portal/attorney/dashboard")
    assert r.status_code == 200
    d = r.get_json()
    assert any(e.get("username") == "m3" for e in d["calendar"])
    assert not any(e.get("username") in ("m1", "m2") for e in d["calendar"])
