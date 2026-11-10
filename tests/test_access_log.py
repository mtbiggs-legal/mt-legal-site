"""Access helpers and the attorney access log (spec A1, A2, A4)."""

from datetime import datetime, timedelta

import shared
from flask import session
from services import storage
from services import accounts
from conftest import access_log, flask_app


def _ctx(username="Endocide"):
    ctx = flask_app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.9"})
    ctx.push()
    session["role"] = "attorney"
    session["username"] = username
    return ctx


def test_can_access_client():
    c = {"assigned_attorney": "Endocide", "co_counsel": ["SophiaH"]}
    assert accounts.can_access_client("Endocide", c)
    assert accounts.can_access_client("SophiaH", c)
    assert not accounts.can_access_client("SophiaH", c, assigned_only=True)
    assert not accounts.can_access_client("Nobody", c)
    assert not accounts.can_access_client("", c)


def test_load_client_for_attorney(make_client):
    make_client("victim")
    ctx = _ctx("SophiaH")
    try:
        assert accounts.load_client_for_attorney("victim") is None
        assert accounts.load_client_for_attorney("missing") is None
    finally:
        ctx.pop()
    ctx = _ctx("Endocide")
    try:
        assert accounts.load_client_for_attorney("victim")["username"] == "victim"
    finally:
        ctx.pop()


def test_public_client_view_strips_private_fields():
    c = {"username": "u", "password": "$2b$x", "must_change_password": True,
         "access_log": [1], "conflict_checks": [2], "client_name": "N"}
    assert accounts.public_client_view(c) == {"username": "u", "client_name": "N"}


def test_log_access_appends_with_ip():
    ctx = _ctx()
    try:
        assert accounts._log_access({"username": "victim"}, "billing_entry", "1.0 hrs")
        (e,) = access_log("victim")
        assert (e["attorney"], e["action"], e["detail"], e["ip"]) ==                ("Endocide", "billing_entry", "1.0 hrs", "10.0.0.9")
    finally:
        ctx.pop()


def test_view_actions_deduplicated_within_10_minutes(monkeypatch):
    from services import audit
    ctx = _ctx()
    try:
        c = {"username": "victim"}
        assert accounts._log_access(c, "view_record")
        assert not accounts._log_access(c, "view_record")
        later = datetime.now() + timedelta(minutes=11)
        monkeypatch.setattr(audit, "datetime", type("D", (), {"now": staticmethod(lambda: later)}))
        assert accounts._log_access(c, "view_record")
    finally:
        ctx.pop()


def test_log_access_atomic_keeps_concurrent_changes(make_client):
    make_client("victim")
    ctx = _ctx()
    try:
        other = storage.load_client("victim")
        other["messages"].append({"from": "client", "text": "new"})
        storage.save_client(other)
        accounts.log_access_atomic("victim", "view_record")
        assert storage.load_client("victim")["messages"]
        assert access_log("victim")[-1]["action"] == "view_record"
    finally:
        ctx.pop()


def test_audit_log_is_append_only():
    import sqlite3
    import pytest
    from services import audit, db
    audit.record("x", client="victim", actor="a", role="attorney", ip="")
    with pytest.raises(sqlite3.DatabaseError):
        db.conn().execute("UPDATE audit_log SET action = 'y'")
    with pytest.raises(sqlite3.DatabaseError):
        db.conn().execute("DELETE FROM audit_log")


def test_audit_detail_is_encrypted():
    from services import audit, db
    audit.record("note", client="victim", detail="privileged detail", actor="a", role="attorney")
    raw = db.conn().execute("SELECT detail FROM audit_log").fetchone()[0]
    assert b"privileged" not in bytes(raw)
