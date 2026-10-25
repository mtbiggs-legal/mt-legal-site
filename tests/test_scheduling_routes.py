"""Scheduling-order routes (spec C2, C3)."""

import pytest

import blueprints.portal_attorney as pa
import scheduling_orders as so
import shared

EXTRACTED = {"dates": {k: {"date": None, "page": None, "evidence": "", "confidence": "low"}
                       for k in so.CASE_DATE_KINDS},
             "notes": "", "model": "m", "usage": None}


@pytest.fixture
def order(make_client, tmp_path):
    make_client("sc", client_name="Sam Client")
    d = tmp_path / "files" / "sc" / "documents" / "Scheduling Orders"
    d.mkdir(parents=True)
    (d / "order.pdf").write_bytes(b"%PDF")
    return d


@pytest.fixture
def gcal(monkeypatch):
    log = {"create": [], "update": [], "delete": [], "update_result": "ok", "delete_result": "ok",
           "create_id": "ev{}"}
    def create(summary, desc, date):
        log["create"].append((summary, date)); return log["create_id"].format(len(log["create"]))
    def update(eid, summary, desc, date):
        log["update"].append((eid, date)); return log["update_result"]
    def delete(eid):
        log["delete"].append(eid); return log["delete_result"]
    monkeypatch.setattr(pa, "gcal_create_all_day", create)
    monkeypatch.setattr(pa, "gcal_update_all_day", update)
    monkeypatch.setattr(pa, "gcal_delete_event", delete)
    monkeypatch.setattr(pa, "gcal_connected", lambda: True)
    return log


def _confirm(c, confirm_clear=True, **dates):
    full = {k: dates.get(k, "") for k in so.CASE_DATE_KINDS}
    full.update(dates)
    return c.post("/portal/attorney/scheduling-order/confirm",
                  json={"username": "sc", "filename": "order.pdf", "dates": full,
                        "confirm_clear": confirm_clear})


def test_extract_success_and_failure(attorney_session, order, monkeypatch):
    monkeypatch.setattr(pa, "extract_case_dates", lambda p: dict(EXTRACTED))
    d = attorney_session.post("/portal/attorney/scheduling-order/extract",
                              json={"username": "sc", "filename": "order.pdf"}).get_json()
    assert d["success"] and "usage" not in d["extraction"] and d["current"] == {}
    def boom(p): raise so.ExtractionError("nope")
    monkeypatch.setattr(pa, "extract_case_dates", boom)
    r = attorney_session.post("/portal/attorney/scheduling-order/extract",
                              json={"username": "sc", "filename": "order.pdf"})
    assert r.status_code == 200 and r.get_json() == {"success": False, "error": "nope", "current": {}}


def test_access(other_attorney_session, order, make_client):
    for url, body in (("/portal/attorney/scheduling-order/extract", {"username": "sc", "filename": "order.pdf"}),
                      ("/portal/attorney/scheduling-order/confirm", {"username": "sc", "filename": "order.pdf", "dates": {}})):
        assert other_attorney_session.post(url, json=body).status_code == 404


def test_confirm_validation(attorney_session, order):
    assert _confirm(attorney_session, bogus="2026-01-01").status_code == 400
    assert _confirm(attorney_session, trial="2026-02-30").status_code == 400
    r = attorney_session.post("/portal/attorney/scheduling-order/confirm",
                              json={"username": "sc", "filename": "missing.pdf",
                                    "dates": {k: "" for k in so.CASE_DATE_KINDS}})
    assert r.status_code == 404
    assert attorney_session.post("/portal/attorney/scheduling-order/confirm", json=[1]).status_code in (400, 404)


def test_confirm_saves_and_bills(attorney_session, order, gcal):
    r = _confirm(attorney_session, first_discussion="2026-11-04", trial="2027-03-01")
    d = r.get_json()
    assert r.status_code == 200 and d["success"]
    c = shared.load_client("sc")
    assert c["case_dates"]["trial"]["date"] == "2027-03-01"
    assert c["case_dates"]["trial"]["gcal_event_id"].startswith("ev")
    assert c["case_dates"]["trial"]["source"] == "order.pdf"
    assert c["case_dates"]["trial"]["confirmed_by"] == "Endocide"
    assert c["case_dates_history"] == []
    bill = c["billing_log"][-1]
    assert (bill["hours"], bill["type"]) == (0.2, "scheduling_order") and bill["date"]
    assert c["access_log"][-1]["action"] == "case_dates_confirmed"
    assert len(gcal["create"]) == 2


def test_identical_resave_is_noop(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01")
    n_bill = len(shared.load_client("sc")["billing_log"])
    d = _confirm(attorney_session, trial="2027-03-01").get_json()
    c = shared.load_client("sc")
    assert d["unchanged"] is True and len(c["billing_log"]) == n_bill and c["case_dates_history"] == []
    assert len(gcal["create"]) == 1


def test_amend_moves_events_and_keeps_history(attorney_session, order, gcal):
    _confirm(attorney_session, first_discussion="2026-11-04", trial="2027-03-01")
    first_conf = shared.load_client("sc")["case_dates"]["first_discussion"]["confirmed_at"]
    _confirm(attorney_session, first_discussion="2026-11-04", trial="2027-04-01")
    c = shared.load_client("sc")
    assert gcal["update"] == [("ev2", "2027-04-01")]
    assert c["case_dates"]["first_discussion"]["confirmed_at"] == first_conf     # unchanged kind kept
    assert c["case_dates_history"][-1]["previous"]["trial"]["date"] == "2027-03-01"
    _confirm(attorney_session, first_discussion="2026-11-04")                    # clear trial
    assert gcal["delete"] == ["ev2"] and "trial" not in shared.load_client("sc")["case_dates"]


def test_update_error_keeps_old_id_gone_recreates(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01")
    gcal["update_result"] = "error"
    d = _confirm(attorney_session, trial="2027-04-01").get_json()
    assert shared.load_client("sc")["case_dates"]["trial"]["gcal_event_id"] == "ev1"
    assert any("could not be moved" in w for w in d["warnings"])
    gcal["update_result"] = "gone"
    _confirm(attorney_session, trial="2027-05-01")
    assert shared.load_client("sc")["case_dates"]["trial"]["gcal_event_id"] == "ev2"


def test_not_connected_single_warning(attorney_session, order, gcal, monkeypatch):
    monkeypatch.setattr(pa, "gcal_connected", lambda: False)
    d = _confirm(attorney_session, first_discussion="2026-11-04", trial="2027-03-01").get_json()
    assert len(d["warnings"]) == 1 and "not connected" in d["warnings"][0]
    assert gcal["create"] == [] and shared.load_client("sc")["case_dates"]["trial"]["gcal_event_id"] is None


def test_history_cap(attorney_session, order, gcal):
    for i in range(23):
        _confirm(attorney_session, trial=f"2027-01-{i + 1:02d}")
    assert len(shared.load_client("sc")["case_dates_history"]) == 20


def test_concurrent_write_preserved_and_concurrent_confirm_409(attorney_session, order, gcal, monkeypatch):
    def create_with_side_write(summary, desc, date):
        c = shared.load_client("sc"); c["messages"].append({"from": "client", "text": "hi"})
        shared.save_client(c); return "evX"
    monkeypatch.setattr(pa, "gcal_create_all_day", create_with_side_write)
    _confirm(attorney_session, trial="2027-03-01")
    assert shared.load_client("sc")["messages"][-1]["text"] == "hi"

    def create_with_rival_confirm(summary, desc, date):
        c = shared.load_client("sc")
        c["case_dates"]["trial"] = {"date": "2030-01-01", "gcal_event_id": "rival"}
        shared.save_client(c); return "evMine"
    monkeypatch.setattr(pa, "gcal_create_all_day", create_with_rival_confirm)
    r = _confirm(attorney_session, trial="2027-03-01", motions="2027-01-15")
    assert r.status_code == 409
    assert "evMine" in gcal["delete"]
    assert "motions" not in shared.load_client("sc")["case_dates"]


def test_extract_unexpected_error_is_200_failure(attorney_session, order, monkeypatch):
    def boom(p): raise RuntimeError("kaboom")
    monkeypatch.setattr(pa, "extract_case_dates", boom)
    r = attorney_session.post("/portal/attorney/scheduling-order/extract",
                              json={"username": "sc", "filename": "order.pdf"})
    d = r.get_json()
    assert r.status_code == 200 and d["success"] is False and "unavailable" in d["error"]


def test_confirm_normalises_dates(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-1-5")
    assert shared.load_client("sc")["case_dates"]["trial"]["date"] == "2027-01-05"
    assert _confirm(attorney_session, trial="2027-01-05").get_json()["unchanged"] is True


def test_extra_body_fields_ignored(attorney_session, order, gcal):
    r = attorney_session.post("/portal/attorney/scheduling-order/confirm",
                              json={"username": "sc", "filename": "order.pdf",
                                    "dates": {**{k: "" for k in so.CASE_DATE_KINDS}, "trial": "2027-03-01"},
                                    "evil": {"x": 1}, "case_dates": {"a": 1}})
    assert r.status_code == 200
    assert list(shared.load_client("sc")["case_dates"]) == ["trial"]


def test_create_returns_none_warns(attorney_session, order, gcal, monkeypatch):
    monkeypatch.setattr(pa, "gcal_create_all_day", lambda s, d, dt: None)
    d = _confirm(attorney_session, trial="2027-03-01").get_json()
    assert any("could not be created" in w for w in d["warnings"])
    assert shared.load_client("sc")["case_dates"]["trial"]["gcal_event_id"] is None


def test_delete_error_warns_with_date(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01")
    gcal["delete_result"] = "error"
    d = _confirm(attorney_session).get_json()
    assert any("2027-03-01" in w and "left behind" in w for w in d["warnings"])


def test_gone_then_failed_create(attorney_session, order, gcal, monkeypatch):
    _confirm(attorney_session, trial="2027-03-01")
    gcal["update_result"] = "gone"
    monkeypatch.setattr(pa, "gcal_create_all_day", lambda s, d, dt: None)
    d = _confirm(attorney_session, trial="2027-04-01").get_json()
    assert any("could not be created" in w for w in d["warnings"])
    assert shared.load_client("sc")["case_dates"]["trial"]["gcal_event_id"] is None


def test_409_leaves_billing_and_history(attorney_session, order, gcal, monkeypatch):
    def rival(summary, desc, date):
        c = shared.load_client("sc")
        c["case_dates"]["trial"] = {"date": "2030-01-01", "gcal_event_id": "rival"}
        shared.save_client(c); return "evMine"
    monkeypatch.setattr(pa, "gcal_create_all_day", rival)
    before = shared.load_client("sc")
    n_bill, n_hist = len(before["billing_log"]), len(before["case_dates_history"])
    assert _confirm(attorney_session, trial="2027-03-01").status_code == 409
    after = shared.load_client("sc")
    assert len(after["billing_log"]) == n_bill and len(after["case_dates_history"]) == n_hist


def test_not_connected_warning_text(attorney_session, order, gcal, monkeypatch):
    monkeypatch.setattr(pa, "gcal_connected", lambda: False)
    d = _confirm(attorney_session, trial="2027-03-01").get_json()
    assert "update or remove any existing calendar events manually" in d["warnings"][0]


def _raw_confirm(c, dates, **extra):
    return c.post("/portal/attorney/scheduling-order/confirm",
                  json={"username": "sc", "filename": "order.pdf", "dates": dates, **extra})


def test_empty_or_partial_dates_rejected_and_nothing_changes(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01")
    before = shared.load_client("sc")
    r = _raw_confirm(attorney_session, {}, confirm_clear=True)
    assert r.status_code == 400 and r.get_json()["error"] == "All five dates must be sent."
    partial = {k: "" for k in so.CASE_DATE_KINDS if k != "motions"}
    assert _raw_confirm(attorney_session, partial, confirm_clear=True).status_code == 400
    after = shared.load_client("sc")
    assert after["case_dates"] == before["case_dates"] and gcal["delete"] == []


def test_clearing_requires_confirm_clear(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01")
    r = _confirm(attorney_session, confirm_clear=False)
    d = r.get_json()
    assert r.status_code == 400 and d["would_clear"] == ["trial"]
    assert "Confirm to remove them" in d["error"]
    assert shared.load_client("sc")["case_dates"]["trial"]["date"] == "2027-03-01"
    assert gcal["delete"] == []
    r = _confirm(attorney_session, confirm_clear=True)
    assert r.status_code == 200 and "trial" not in shared.load_client("sc")["case_dates"]


def test_confirm_returns_history(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01")
    d = _confirm(attorney_session, trial="2027-04-01").get_json()
    assert len(d["case_dates_history"]) == 1
    d = _confirm(attorney_session, trial="2027-04-01").get_json()
    assert d["unchanged"] is True and len(d["case_dates_history"]) == 1


def _sched_bills(c):
    return [b for b in c["billing_log"] if b.get("type") == "scheduling_order"]


def test_removal_only_is_not_billed(attorney_session, order, gcal):
    _confirm(attorney_session, trial="2027-03-01", motions="2027-01-15")
    assert len(_sched_bills(shared.load_client("sc"))) == 1
    _confirm(attorney_session, trial="2027-03-01")                    # removal only
    c = shared.load_client("sc")
    assert "motions" not in c["case_dates"] and len(_sched_bills(c)) == 1
    assert c["case_dates_history"] and c["access_log"][-1]["action"] == "case_dates_confirmed"
    _confirm(attorney_session, trial="2027-04-01")                    # change
    assert len(_sched_bills(shared.load_client("sc"))) == 2


def test_all_blank_on_fresh_client_is_unchanged(attorney_session, order, gcal):
    before = shared.load_client("sc")
    for flag in (False, True):
        r = _confirm(attorney_session, confirm_clear=flag)
        assert r.status_code == 200 and r.get_json()["unchanged"] is True
    after = shared.load_client("sc")
    assert after["billing_log"] == before["billing_log"]
    assert after["case_dates"] == before["case_dates"]
    assert not (gcal["create"] or gcal["update"] or gcal["delete"])
