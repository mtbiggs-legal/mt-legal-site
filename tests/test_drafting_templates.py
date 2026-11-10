"""Document generator templates, and saving drafts as Google Docs."""

import re
import string
import types
from pathlib import Path

import pytest

import blueprints.drafting as drafting
from services import gcal, storage

TEMPLATE_HTML = (Path(__file__).resolve().parent.parent / "templates" / "drafting.html").read_text(encoding="utf-8")


def _fields_id(name):
    """Python twin of templateFieldsId() in static/js/app.js."""
    return "fields-" + re.sub(r"\s+", "-", re.sub(r"[()]", "", name.lower()).strip())


def _block(name):
    m = re.search(r'<div id="%s"(.*?)\n    </div>' % re.escape(_fields_id(name)), TEMPLATE_HTML, re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("name", sorted(drafting.TEMPLATE_PROMPTS))
def test_every_template_formats_and_has_a_form(name):
    prompt = drafting.TEMPLATE_PROMPTS[name]
    placeholders = {f for _, f, _, _ in string.Formatter().parse(prompt) if f}
    assert placeholders <= set(drafting._ALL_VARS), placeholders - set(drafting._ALL_VARS)

    assert f'<option value="{name}">' in TEMPLATE_HTML
    block = _block(name)
    assert block is not None, f"no fields block {_fields_id(name)}"
    names = set(re.findall(r'name="([a-z_]+)"', block))
    assert names, "the form block has no fields"
    # Every field the form sends is used by the prompt, so nothing typed is dropped.
    assert names <= placeholders, names - placeholders


@pytest.mark.parametrize("name", ["Answer to Complaint", "Civil Complaint", "Discovery Requests",
                                  "Petition to Modify Parenting Plan", "Petition for Civil Contempt",
                                  "Notice of Intent to Relocate", "Answer and Counter-Complaint for Divorce"])
def test_basic_civil_and_family_templates_exist(name):
    assert name in drafting.TEMPLATE_PROMPTS


def test_generate_answer_passes_fields_to_claude(attorney_session, monkeypatch):
    seen = {}

    def create(**kw):
        seen.update(kw)
        return types.SimpleNamespace(content=[types.SimpleNamespace(text="ANSWER OF DEFENDANT")])

    fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    monkeypatch.setattr(drafting, "get_anthropic_client", lambda: fake)
    resp = attorney_session.post("/drafting/generate", json={
        "template_type": "Answer to Complaint",
        "variables": {"plaintiff_name": "ACME Corp.", "affirmative_defenses": "Statute of limitations"},
    })
    assert resp.status_code == 200
    assert resp.get_json()["draft"] == "ANSWER OF DEFENDANT"
    prompt = seen["messages"][0]["content"]
    assert "ACME Corp." in prompt and "Statute of limitations" in prompt
    assert "Certificate of Service" in seen["system"]


# ── Google Docs ──────────────────────────────────────────────────────────────

URL = "https://docs.google.com/document/d/abc123/edit"


def _fake_doc(monkeypatch, url=URL, exc=None):
    calls = []

    def create(title, text):
        calls.append((title, text))
        if exc:
            raise exc
        return {"id": "abc123", "url": url}

    monkeypatch.setattr(gcal, "create_google_doc", create)
    return calls


def test_google_doc_returns_link(attorney_session, monkeypatch):
    calls = _fake_doc(monkeypatch)
    resp = attorney_session.post("/drafting/google-doc", json={"title": "Answer to Complaint", "content": "TEXT"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["url"] == URL
    assert calls[0][1] == "TEXT"
    assert calls[0][0].startswith("Answer to Complaint (")


def test_google_doc_for_client_names_and_logs_it(attorney_session, make_client, monkeypatch):
    make_client("testclient", client_name="Test Client")
    calls = _fake_doc(monkeypatch)
    resp = attorney_session.post("/drafting/google-doc",
                                 json={"title": "Motion to Compel Discovery", "content": "TEXT",
                                       "username": "testclient"})
    assert resp.status_code == 200
    assert "Test Client" in calls[0][0]
    kinds = [e["action_type"] for e in storage.load_client("testclient")["activity_log"]]
    assert "google_doc_created" in kinds


def test_google_doc_refuses_another_attorneys_client(other_attorney_session, make_client, monkeypatch):
    make_client("testclient")
    calls = _fake_doc(monkeypatch)
    resp = other_attorney_session.post("/drafting/google-doc",
                                       json={"title": "T", "content": "TEXT", "username": "testclient"})
    assert resp.status_code == 404
    assert calls == []


def test_google_doc_not_authorized_message(attorney_session, monkeypatch):
    _fake_doc(monkeypatch, exc=ValueError("Google Drive not authorized."))
    resp = attorney_session.post("/drafting/google-doc", json={"title": "T", "content": "TEXT"})
    assert resp.status_code == 400
    assert "not authorized" in resp.get_json()["error"]


def test_google_doc_rejects_non_google_link(attorney_session, monkeypatch):
    _fake_doc(monkeypatch, url="https://evil.example/doc")
    resp = attorney_session.post("/drafting/google-doc", json={"title": "T", "content": "TEXT"})
    assert resp.status_code == 502


def test_google_doc_needs_content(attorney_session, monkeypatch):
    calls = _fake_doc(monkeypatch)
    resp = attorney_session.post("/drafting/google-doc", json={"title": "T", "content": "  "})
    assert resp.status_code == 400
    assert calls == []


def test_google_doc_requires_attorney(client, client_session, monkeypatch):
    calls = _fake_doc(monkeypatch)
    for c in (client, client_session):
        resp = c.post("/drafting/google-doc", json={"title": "T", "content": "TEXT"})
        assert resp.status_code == 401
    assert calls == []


def test_doc_html_escapes_and_keeps_paragraphs():
    out = gcal.text_to_doc_html("A <b>", "Line one\nline two\n\n<script>x</script>")
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "<p>Line one<br>line two</p>" in out
    assert "<title>A &lt;b&gt;</title>" in out


BANK = ["Marital Dissolution Agreement", "Final Decree of Divorce", "Petition to Establish Parentage",
        "Petition to Modify Child Support", "Motion for Pendente Lite Support", "Petition for Grandparent Visitation",
        "Petition for Name Change", "Durable Power of Attorney (Financial)", "Health Care Power of Attorney",
        "Living Will (Advance Directive)", "HIPAA Authorization", "Petition to Probate Will", "Small Estate Affidavit",
        "Notice of Appearance", "Motion to Continue", "Motion for Extension of Time", "Motion to Compel Discovery",
        "Motion for Default Judgment", "Motion to Withdraw as Counsel", "Agreed Order", "Notice of Hearing"]


@pytest.mark.parametrize("name", BANK)
def test_motions_bank_templates_exist(name):
    assert name in drafting.TEMPLATE_PROMPTS


def test_drafting_page_groups_estate_and_pleadings(attorney_session):
    html = attorney_session.get("/drafting").get_data(as_text=True)
    assert "Estate Planning" in html and "Basic Pleadings" in html
    assert html.count('<option value="Last Will and Testament">') == 1
