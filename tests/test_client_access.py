"""Every attorney route that touches a client enforces assignment (spec A1)."""

import inspect
import re

import pytest

import shared
from services import storage
from conftest import flask_app


@pytest.fixture(autouse=True)
def victim(make_client, tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "ANTHROPIC_API_KEY", None)   # AI routes fail fast, never 404
    make_client("victim", client_name="Victor Im", password="$2b$test$pw",
                legal_issue="Theft charge")
    d = tmp_path / "files" / "victim" / "documents" / "Motions"
    d.mkdir(parents=True)
    (d / "a.txt").write_text("motion text")


OK, AI = {200}, {500, 503}
ROUTES = [
    ("get",  "/portal/attorney/client/victim", None, OK),
    ("post", "/portal/attorney/update-client", {"username": "victim", "phone": "1"}, OK),
    ("post", "/portal/attorney/generate-summary", {"username": "victim"}, AI),
    ("post", "/portal/attorney/billing-entry", {"username": "victim", "note": "x", "hours": 0.1}, OK),
    ("post", "/portal/attorney/reply", {"username": "victim", "text": "hi"}, OK),
    ("get",  "/portal/attorney/documents/victim", None, OK),
    ("get",  "/portal/attorney/document/victim/Motions/a.txt", None, OK),
    ("get",  "/portal/attorney/preview/victim/Motions/a.txt", None, OK),
    ("get",  "/portal/attorney/docx-preview/victim/Motions/a.txt", None, AI),
    ("post", "/portal/attorney/research/issue-spot",
     {"username": "victim", "category": "Motions", "filename": "a.txt"}, AI),
    ("post", "/portal/attorney/research/draft", {"username": "victim", "issues": "x"}, AI),
    ("post", "/portal/attorney/research/save-draft",
     {"username": "victim", "draft": "x", "filename": "d"}, OK),
    ("post", "/portal/attorney/research/save-report",
     {"username": "victim", "report_type": "analysis", "text": "x"}, OK),
    ("get",  "/portal/attorney/access-log/victim", None, OK),
    ("post", "/portal/attorney/issue-statement", {"username": "victim"}, {200, 400}),
    ("post", "/portal/attorney/statement-notice",
     {"username": "victim", "statement_id": "st_1"}, {200, 400}),
]
ASSIGNED_ONLY = [
    ("post", "/portal/attorney/archive-client", {"username": "victim"}, OK),
    ("post", "/portal/attorney/unarchive-client", {"username": "victim"}, OK),
    ("post", "/portal/attorney/delete-document",
     {"username": "victim", "category": "Motions", "filename": "a.txt"}, OK),
]


def _call(c, method, url, payload):
    return c.get(url) if method == "get" else c.post(url, json=payload)


@pytest.mark.parametrize("method,url,payload,expected", ROUTES + ASSIGNED_ONLY)
def test_unassigned_attorney_gets_404(other_attorney_session, method, url, payload, expected):
    resp = _call(other_attorney_session, method, url, payload)
    assert resp.status_code == 404
    assert storage.load_client("victim")["access_log"] == []


@pytest.mark.parametrize("method,url,payload,expected", ROUTES + ASSIGNED_ONLY)
def test_assigned_attorney_allowed(attorney_session, method, url, payload, expected):
    assert _call(attorney_session, method, url, payload).status_code in expected


@pytest.mark.parametrize("method,url,payload,expected", ROUTES)
def test_co_counsel_allowed(other_attorney_session, method, url, payload, expected):
    c = storage.load_client("victim")
    c["co_counsel"] = ["SophiaH"]
    storage.save_client(c)
    assert _call(other_attorney_session, method, url, payload).status_code in expected


@pytest.mark.parametrize("method,url,payload,expected", ASSIGNED_ONLY)
def test_co_counsel_denied_assigned_only_routes(other_attorney_session, method, url, payload, expected):
    c = storage.load_client("victim")
    c["co_counsel"] = ["SophiaH"]
    storage.save_client(c)
    assert _call(other_attorney_session, method, url, payload).status_code == 404


def test_denied_update_does_not_change_record(other_attorney_session):
    other_attorney_session.post("/portal/attorney/update-client",
                                json={"username": "victim", "phone": "555"})
    assert not storage.load_client("victim").get("phone")


def test_denied_delete_keeps_file(other_attorney_session, tmp_path):
    other_attorney_session.post("/portal/attorney/delete-document", json={
        "username": "victim", "category": "Motions", "filename": "a.txt"})
    assert (tmp_path / "files" / "victim" / "documents" / "Motions" / "a.txt").exists()


def test_repeated_previews_logged_once(attorney_session):
    for _ in range(2):
        attorney_session.get("/portal/attorney/preview/victim/Motions/a.txt")
    log = storage.load_client("victim")["access_log"]
    assert [e["action"] for e in log] == ["view_document_preview"]


def test_upload_rejected_before_file_is_written(other_attorney_session, tmp_path):
    import io
    resp = other_attorney_session.post(
        "/portal/attorney/upload-document",
        data={"username": "victim", "category": "Other",
              "file": (io.BytesIO(b"x"), "evil.txt")},
        content_type="multipart/form-data")
    assert resp.status_code == 404
    assert not (tmp_path / "files" / "victim" / "documents" / "Other" / "evil.txt").exists()


def test_clients_list_only_accessible(other_attorney_session, make_client):
    make_client("mine", assigned_attorney="SophiaH")
    names = [c["username"] for c in other_attorney_session.get("/portal/attorney/clients").get_json()]
    assert names == ["mine"]


def test_archive_lead_requires_assignment(other_attorney_session, tmp_path):
    import json
    (tmp_path / "leads" / "l1.json").write_text(json.dumps(
        {"name": "Lead", "assigned_attorney": "Endocide"}))
    resp = other_attorney_session.post("/portal/attorney/archive-lead", json={"filename": "l1.json"})
    assert resp.status_code == 404


# Routes that read a username but legitimately do not load an existing client.
NO_CLIENT_ROUTES = {
    "attorney_portal", "portal_attorney_dashboard", "portal_create_client",
    "portal_leads_list", "attorney_token_usage", "insights_export_tax",
    "portal_conflict_check",
}


def test_every_client_route_is_guarded():
    """Sweep: a new portal route that reads a client username must use
    load_client_for_attorney, or this test fails."""
    offenders = []
    for rule in flask_app.url_map.iter_rules():
        # Attorney routes live in several blueprints (research, insights), so
        # match on the URL as well as the portal_attorney blueprint.
        if not (rule.endpoint.startswith("portal_attorney.")
                or rule.rule.startswith("/portal/attorney/")):
            continue
        name = rule.endpoint.split(".", 1)[1]
        fn   = inspect.unwrap(flask_app.view_functions[rule.endpoint])
        src  = inspect.getsource(fn)
        src  = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        src  = src.replace('session["username"]', "").replace('session.get("username"', "")
        reads_username = "<username>" in rule.rule or re.search(
            r'''get\(\s*["']username["']|\[\s*["']username["']\s*\]''', src)
        if reads_username and name not in NO_CLIENT_ROUTES \
                and "load_client_for_attorney" not in src:
            offenders.append(f"{name} ({rule.rule})")
    assert not offenders, "Unguarded client routes: " + ", ".join(offenders)
