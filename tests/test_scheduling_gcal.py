"""Google Calendar helpers with three-way outcomes (spec C4)."""

import types

import shared


class _Req:
    def __init__(self, fn): self.fn = fn
    def execute(self): return self.fn()


class _HttpError(Exception):
    def __init__(self, status):
        self.resp = types.SimpleNamespace(status=status)


class _Events:
    def __init__(self, store, fail=None):
        self.store, self.fail = store, fail
    def insert(self, calendarId, body):
        def run():
            if self.fail == "insert": raise RuntimeError("boom")
            self.store["e1"] = body; return {"id": "e1"}
        return _Req(run)
    def patch(self, calendarId, eventId, body):
        def run():
            if self.fail == "gone": raise _HttpError(404)
            if self.fail == "error": raise _HttpError(500)
            self.store[eventId] = body; return {"id": eventId}
        return _Req(run)
    def delete(self, calendarId, eventId):
        def run():
            if self.fail == "gone": raise _HttpError(410)
            if self.fail == "error": raise RuntimeError("down")
            self.store.pop(eventId, None); return {}
        return _Req(run)


def _connect(monkeypatch, fail=None):
    store = {}
    svc = types.SimpleNamespace(events=lambda: _Events(store, fail))
    monkeypatch.setattr(shared, "GOOGLE_LIBS", True)
    monkeypatch.setattr(shared, "TOKEN_FILE", types.SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(shared, "get_calendar_service", lambda: svc)
    return store


def test_not_connected(monkeypatch):
    monkeypatch.setattr(shared, "GOOGLE_LIBS", False)
    assert shared.gcal_create_all_day("S", "D", "2026-11-04") is None
    assert shared.gcal_update_all_day("x", "S", "D", "2026-11-04") == "error"
    assert shared.gcal_delete_event("x") == "error"


def test_create_update_delete_ok(monkeypatch):
    store = _connect(monkeypatch)
    assert shared.gcal_create_all_day("Trial: A", "desc", "2026-11-04") == "e1"
    assert store["e1"]["start"] == {"date": "2026-11-04"} and store["e1"]["end"] == {"date": "2026-11-05"}
    assert shared.gcal_update_all_day("e1", "Trial: A", "desc", "2026-12-01") == "ok"
    assert store["e1"]["start"] == {"date": "2026-12-01"}
    assert shared.gcal_delete_event("e1") == "ok" and "e1" not in store


def test_gone_vs_error(monkeypatch):
    _connect(monkeypatch, fail="gone")
    assert shared.gcal_update_all_day("e1", "S", "D", "2026-11-04") == "gone"
    assert shared.gcal_delete_event("e1") == "gone"
    _connect(monkeypatch, fail="error")
    assert shared.gcal_update_all_day("e1", "S", "D", "2026-11-04") == "error"
    assert shared.gcal_delete_event("e1") == "error"


def test_create_failure_and_bad_date(monkeypatch):
    _connect(monkeypatch, fail="insert")
    assert shared.gcal_create_all_day("S", "D", "2026-11-04") is None
    _connect(monkeypatch)
    assert shared.gcal_create_all_day("S", "D", "not-a-date") is None


def test_defaults_and_category(make_client):
    make_client("cd1")
    c = shared.load_client("cd1")
    assert c["case_dates"] == {} and c["case_dates_history"] == []
    cats = shared.DOCS_CATEGORIES
    assert "Scheduling Orders" in cats and cats.index("Scheduling Orders") == cats.index("Court Orders") + 1
