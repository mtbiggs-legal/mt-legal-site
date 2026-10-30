"""Access helpers and the attorney access log (spec A1, A2, A4)."""

from datetime import datetime, timedelta

import shared
from services import storage
from services import accounts
from conftest import flask_app


def _ctx(username="Endocide"):
    ctx = flask_app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.9"})
    ctx.push()
    shared.session["role"] = "attorney"
    shared.session["username"] = username
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
        c = {}
        assert accounts._log_access(c, "billing_entry", "1.0 hrs")
        e = c["access_log"][0]
        assert (e["attorney"], e["action"], e["detail"], e["ip"]) == \
               ("Endocide", "billing_entry", "1.0 hrs", "10.0.0.9")
    finally:
        ctx.pop()


def test_view_actions_deduplicated_within_10_minutes():
    ctx = _ctx()
    try:
        c = {}
        assert accounts._log_access(c, "view_record")
        assert not accounts._log_access(c, "view_record")
        c["access_log"][0]["timestamp"] = (
            datetime.now() - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%S")
        assert accounts._log_access(c, "view_record")
        assert len(c["access_log"]) == 2
    finally:
        ctx.pop()


def test_log_access_atomic_keeps_concurrent_changes(make_client):
    make_client("victim")
    ctx = _ctx()
    try:
        storage.load_client("victim")                      # stale copy, never saved
        other = storage.load_client("victim")              # concurrent writer
        other["messages"].append({"from": "client", "text": "new"})
        storage.save_client(other)
        accounts.log_access_atomic("victim", "view_record")
        rec = storage.load_client("victim")
        assert rec["messages"] and rec["access_log"][-1]["action"] == "view_record"
    finally:
        ctx.pop()


def test_access_log_capped():
    ctx = _ctx()
    try:
        c = {"access_log": [{"timestamp": "2020-01-01T00:00:00", "attorney": "x",
                             "action": "edit_record", "detail": "", "ip": ""}] * 1000}
        accounts._log_access(c, "edit_record")
        assert len(c["access_log"]) == 1000
        assert c["access_log"][-1]["attorney"] == "Endocide"
    finally:
        ctx.pop()
