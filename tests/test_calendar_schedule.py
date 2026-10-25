"""/calendar/schedule is public; only attorneys may tie it to a client (spec A1)."""

import pytest

import blueprints.calendar as cal
import shared


class _Events:
    def insert(self, **kw):
        return self

    def execute(self):
        return {"htmlLink": "https://calendar.example/x"}


class _Service:
    def events(self):
        return _Events()


@pytest.fixture(autouse=True)
def fake_gcal(monkeypatch):
    monkeypatch.setattr(cal, "get_calendar_service", lambda: _Service())


BODY = {"client_name": "Test Client", "date": "2026-11-02", "time": "10:00"}


def test_anonymous_cannot_touch_client(client, make_client):
    make_client("victim")
    assert client.post("/calendar/schedule", json=BODY).status_code == 200
    assert shared.load_client("victim")["activity_log"] == []


def test_attorney_logs_on_accessible_client(attorney_session, make_client):
    make_client("victim")
    attorney_session.post("/calendar/schedule", json=BODY)
    assert shared.load_client("victim")["activity_log"][-1]["action_type"] == "meeting_scheduled"


def test_attorney_cannot_log_on_inaccessible_client(other_attorney_session, make_client):
    make_client("victim")
    other_attorney_session.post("/calendar/schedule", json=BODY)
    assert shared.load_client("victim")["activity_log"] == []
