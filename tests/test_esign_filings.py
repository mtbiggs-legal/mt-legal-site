"""E-signatures (Dropbox Sign, faked) and court filing packages."""

from services import client_files
import hashlib
import hmac
import io
import json
import time
import types

import pytest

import shared
from services import assistant, assistant_tools as tools, esign, filings, storage

KEY = "test-dropbox-key"


@pytest.fixture
def greer(make_client, tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "DROPBOX_SIGN_API_KEY", KEY)
    monkeypatch.setattr(shared, "DROPBOX_SIGN_TEST_MODE", True)
    make_client("tgreer", client_name="Travis L. Greer", email="travis@example.com",
                case_type="Criminal Defense", county="Davidson", court="General Sessions Court",
                case_no="26-GS-41907", opposing_parties=["State of Tennessee"])
    docs = shared.CLIENT_FILES_DIR / "tgreer" / "documents"
    (docs / "Generated Documents").mkdir(parents=True)
    (docs / "Generated Documents" / "Engagement_Letter.pdf").write_bytes(b"%PDF-1.4 fake")
    (docs / "Motions").mkdir(parents=True)
    (docs / "Motions" / "Motion_to_Suppress.txt").write_text("COMES NOW the Defendant...", encoding="utf-8")
    return "tgreer"


class FakeSign:
    """Stands in for Dropbox Sign's HTTP API."""

    def __init__(self, monkeypatch):
        self.sent, self.reminded, self.status = [], [], {}
        monkeypatch.setattr(esign, "_send_api", self.send)
        monkeypatch.setattr(esign, "_get_api", lambda rid: self.status[rid])
        monkeypatch.setattr(esign, "_download_api", lambda rid: b"%PDF signed")
        monkeypatch.setattr(esign, "_remind_api", lambda rid, email: self.reminded.append((rid, email)))

    def send(self, title, subject, message, signers, filename, content, metadata):
        rid = f"sr_{len(self.sent) + 1}"
        self.sent.append({"title": title, "signers": signers, "filename": filename, "metadata": metadata})
        api = {"signature_request_id": rid, "metadata": metadata, "is_complete": False,
               "signatures": [{"signer_email_address": s["email"], "status_code": "awaiting_signature"}
                              for s in signers]}
        self.status[rid] = api
        return api

    def sign_all(self, rid):
        api = self.status[rid]
        api["is_complete"] = True
        for s in api["signatures"]:
            s["status_code"], s["signed_at"] = "signed", 1794000000
        return api


# ── E-sign ───────────────────────────────────────────────────────────────────

def test_send_records_request_and_defaults_to_client(attorney_session, greer, monkeypatch):
    fake = FakeSign(monkeypatch)
    r = attorney_session.post("/portal/attorney/esign/send", json={
        "username": "tgreer", "category": "Generated Documents", "filename": "Engagement_Letter.pdf",
        "signers": [{"name": "Travis L. Greer", "email": "travis@example.com"}]})
    assert r.status_code == 200, r.get_json()
    assert fake.sent[0]["metadata"]["client"] == "tgreer"
    reqs = storage.load_client("tgreer")["esign_requests"]
    assert reqs[0]["status"] == "sent" and reqs[0]["test_mode"] is True


def test_send_rejects_bad_signers_and_missing_documents(attorney_session, greer, monkeypatch):
    FakeSign(monkeypatch)
    bad = attorney_session.post("/portal/attorney/esign/send", json={
        "username": "tgreer", "category": "Generated Documents", "filename": "Engagement_Letter.pdf",
        "signers": [{"name": "X", "email": "not-an-email"}]})
    assert bad.status_code == 400
    missing = attorney_session.post("/portal/attorney/esign/send", json={
        "username": "tgreer", "category": "Generated Documents", "filename": "../../secret.pdf",
        "signers": [{"name": "X", "email": "x@example.com"}]})
    assert missing.status_code == 400


def test_not_configured_message(attorney_session, greer, monkeypatch):
    monkeypatch.setattr(shared, "DROPBOX_SIGN_API_KEY", "")
    r = attorney_session.post("/portal/attorney/esign/send", json={
        "username": "tgreer", "category": "Generated Documents", "filename": "Engagement_Letter.pdf",
        "signers": [{"name": "T", "email": "t@example.com"}]})
    assert r.status_code == 400 and "DROPBOX_SIGN_API_KEY" in r.get_json()["error"]


def test_refresh_saves_signed_copy_once(attorney_session, greer, monkeypatch):
    fake = FakeSign(monkeypatch)
    entry = esign.send("tgreer", "Generated Documents", "Engagement_Letter.pdf",
                       [{"name": "T", "email": "t@example.com"}], "", "", "Endocide")
    fake.sign_all(entry["id"])
    reqs = attorney_session.get("/portal/attorney/esign/tgreer?refresh=1").get_json()["requests"]
    assert reqs[0]["status"] == "signed"
    assert reqs[0]["signed_file"] == "Signed Documents/Engagement_Letter_signed.pdf"
    saved = shared.CLIENT_FILES_DIR / "tgreer" / "documents" / "Signed Documents" / "Engagement_Letter_signed.pdf"
    assert client_files.read_bytes(saved) == b"%PDF signed"
    attorney_session.get("/portal/attorney/esign/tgreer?refresh=1")
    assert len(list(saved.parent.iterdir())) == 1                       # not downloaded twice


@pytest.fixture(autouse=True)
def _fresh_callbacks():
    esign._seen_events.clear()


def _event(event_type, request, t=None):
    t = str(int(time.time()) if t is None else t)
    h = hmac.new(KEY.encode(), (t + event_type).encode(), hashlib.sha256).hexdigest()
    return {"json": json.dumps({"event": {"event_time": t, "event_type": event_type, "event_hash": h},
                                "signature_request": request})}


def test_callback_verifies_and_applies(client, greer, monkeypatch):
    fake = FakeSign(monkeypatch)
    entry = esign.send("tgreer", "Generated Documents", "Engagement_Letter.pdf",
                       [{"name": "T", "email": "t@example.com"}], "", "", "Endocide")
    api = fake.sign_all(entry["id"])
    r = client.post("/webhooks/dropbox-sign", data=_event("signature_request_all_signed", api))
    assert r.status_code == 200 and r.get_data(as_text=True) == esign.CALLBACK_REPLY
    assert storage.load_client("tgreer")["esign_requests"][0]["status"] == "signed"


def test_callback_body_is_not_trusted(client, greer, monkeypatch):
    """A validly hashed event with a forged body: status comes from Dropbox Sign, not the post."""
    FakeSign(monkeypatch)
    entry = esign.send("tgreer", "Generated Documents", "Engagement_Letter.pdf",
                       [{"name": "T", "email": "t@example.com"}], "", "", "Endocide")
    forged = {"signature_request_id": entry["id"], "metadata": {"client": "tgreer"}, "is_complete": True,
              "signatures": [{"signer_email_address": "t@example.com", "status_code": "signed"}]}
    client.post("/webhooks/dropbox-sign", data=_event("signature_request_all_signed", forged))
    rec = storage.load_client("tgreer")["esign_requests"][0]
    assert rec["status"] == "sent" and not rec["signed_file"]       # the real API still says waiting


def test_stale_and_replayed_callbacks_are_ignored(client, greer, monkeypatch):
    fake = FakeSign(monkeypatch)
    calls = []
    monkeypatch.setattr(esign, "_get_api", lambda rid: calls.append(rid) or fake.status[rid])
    entry = esign.send("tgreer", "Generated Documents", "Engagement_Letter.pdf",
                       [{"name": "T", "email": "t@example.com"}], "", "", "Endocide")
    req = {"signature_request_id": entry["id"], "metadata": {"client": "tgreer"}}
    old = _event("signature_request_viewed", req, t=int(time.time()) - 10 * 24 * 3600)
    assert client.post("/webhooks/dropbox-sign", data=old).status_code == 200
    assert calls == []
    fresh = _event("signature_request_viewed", req)
    client.post("/webhooks/dropbox-sign", data=fresh)
    client.post("/webhooks/dropbox-sign", data=fresh)                 # replayed
    assert calls == [entry["id"]]


def test_callback_ignores_requests_we_did_not_send(client, greer, monkeypatch):
    FakeSign(monkeypatch)
    calls = []
    monkeypatch.setattr(esign, "_get_api", lambda rid: calls.append(rid))
    client.post("/webhooks/dropbox-sign", data=_event(
        "signature_request_all_signed", {"signature_request_id": "sr_unknown", "metadata": {"client": "tgreer"}}))
    assert calls == []


def test_callback_rejects_bad_hash(client, greer, monkeypatch):
    FakeSign(monkeypatch)
    payload = json.loads(_event("signature_request_all_signed", {})["json"])
    payload["event"]["event_hash"] = "0" * 64
    r = client.post("/webhooks/dropbox-sign", data={"json": json.dumps(payload)})
    assert r.status_code == 400


def test_callback_test_event_is_acknowledged(client, greer):
    r = client.post("/webhooks/dropbox-sign", data=_event("callback_test", {}))
    assert r.get_data(as_text=True) == esign.CALLBACK_REPLY


def test_remind_only_waiting_signers(attorney_session, greer, monkeypatch):
    fake = FakeSign(monkeypatch)
    entry = esign.send("tgreer", "Generated Documents", "Engagement_Letter.pdf",
                       [{"name": "T", "email": "t@example.com"}], "", "", "Endocide")
    r = attorney_session.post("/portal/attorney/esign/remind", json={"username": "tgreer", "request_id": entry["id"]})
    assert r.get_json()["reminded"] == ["T"] and fake.reminded == [(entry["id"], "t@example.com")]


def test_esign_routes_require_attorney(client_session, greer):
    assert client_session.get("/portal/attorney/esign/tgreer").status_code == 302
    assert client_session.post("/portal/attorney/esign/send", json={}).status_code == 401


def test_other_attorney_cannot_send(other_attorney_session, greer, monkeypatch):
    FakeSign(monkeypatch)
    r = other_attorney_session.post("/portal/attorney/esign/send", json={
        "username": "tgreer", "category": "Generated Documents", "filename": "Engagement_Letter.pdf",
        "signers": [{"name": "T", "email": "t@example.com"}]})
    assert r.status_code == 404


def test_assistant_send_for_signature_prefills_client(attorney_session, greer, monkeypatch):
    fake = FakeSign(monkeypatch)
    assistant._conversations.clear()

    class B(dict):
        def to_dict(self):
            return dict(self)

    responses = [types.SimpleNamespace(content=[B(type="tool_use", id="t1", name="send_for_signature",
                                                  input={"client": "greer", "document": "engagement"})],
                                       stop_reason="tool_use", usage=None),
                 types.SimpleNamespace(content=[B(type="text", text="Sent.")], stop_reason="end_turn", usage=None)]
    fake_client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(
        create=lambda **kw: responses.pop(0))))
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: fake_client)
    d = attorney_session.post("/portal/attorney/assistant/message", json={"text": "send the engagement letter"}).get_json()
    assert "travis@example.com" in d["pending"][0]["summary"] and not fake.sent
    attorney_session.post("/portal/attorney/assistant/confirm", json={"decisions": {"t1": True}})
    assert fake.sent[0]["signers"][0]["email"] == "travis@example.com"


# ── Filing packages ──────────────────────────────────────────────────────────

def test_prefill_uses_client_file(greer):
    p = filings.prefill(storage.load_client("tgreer"))
    f = p["fields"]
    assert (f["court"], f["county"], f["case_no"], f["client_role"]) == \
        ("General Sessions Court", "Davidson", "26-GS-41907", "Defendant")
    assert f["service"][0]["name"].startswith("Office of the District Attorney General, Davidson")
    assert p["missing"] == ["service addresses"]                      # the only thing the file lacks


def test_prefill_reports_missing(make_client):
    make_client("new", client_name="New Client", case_type="Civil Litigation")
    p = filings.prefill(storage.load_client("new"))
    assert set(p["missing"]) >= {"court", "county", "case_no", "client_role", "service"}


def _form(**over):
    data = {"username": "tgreer", "category": "Motions", "filename": "Motion_to_Suppress.txt",
            "court": "General Sessions Court", "county": "Davidson", "case_no": "26-GS-41907",
            "client_role": "Defendant", "title": "Motion to Suppress",
            "service": [{"name": "Office of the District Attorney General", "address": "da@example.gov",
                         "method": "email"}], "approve_signature": True}
    data.update(over)
    return data


def test_prepare_builds_package_and_saves_answers(attorney_session, greer, monkeypatch):
    seen = {}

    def render(path, f, approved):
        seen.update(f=f, approved=approved, cert=filings.certificate_of_service(f, approved))
        return b"%PDF package"

    monkeypatch.setattr(filings, "render_package", render)
    r = attorney_session.post("/portal/attorney/filing/prepare", json=_form())
    assert r.status_code == 200, r.get_json()
    entry = r.get_json()["filing"]
    assert entry["package"] == "Filing Packages/Motion_to_Suppress_filing_package.pdf"
    assert any("proposed order" in c for c in entry["checklist"])
    assert "/s/ Madison T. Biggs" in seen["cert"]
    c = storage.load_client("tgreer")
    assert c["service_list"][0]["address"] == "da@example.gov"       # remembered for next time
    assert filings.prefill(c)["missing"] == []


def test_signature_stays_blank_without_approval(greer):
    f = filings.clean_fields(_form(approve_signature=False))
    cert = filings.certificate_of_service(f, approved=False)
    assert not any(line.startswith("/s/") for line in cert)


def test_prepare_requires_missing_fields(attorney_session, greer, monkeypatch):
    monkeypatch.setattr(filings, "render_package", lambda *a: b"%PDF")
    r = attorney_session.post("/portal/attorney/filing/prepare", json=_form(case_no="", service=[]))
    assert r.status_code == 400 and "case number" in r.get_json()["error"]


def test_prepare_refuses_word_documents(attorney_session, greer):
    (shared.CLIENT_FILES_DIR / "tgreer" / "documents" / "Motions" / "Draft.docx").write_bytes(b"x")
    r = attorney_session.post("/portal/attorney/filing/prepare", json=_form(filename="Draft.docx"))
    assert r.status_code == 400 and "PDF" in r.get_json()["error"]


def test_mark_filed_saves_copy_and_hearing(attorney_session, greer, monkeypatch):
    monkeypatch.setattr(filings, "render_package", lambda *a: b"%PDF")
    entry = attorney_session.post("/portal/attorney/filing/prepare", json=_form()).get_json()["filing"]
    r = attorney_session.post("/portal/attorney/filing/mark-filed", data={
        "username": "tgreer", "filing_id": entry["id"], "category": "Motions",
        "hearing_date": "2099-01-15", "hearing_label": "Suppression hearing",
        "file": (io.BytesIO(b"%PDF stamped"), "stamped.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    f = r.get_json()["filing"]
    assert f["status"] == "filed" and f["stamped_file"] == "Motions/FILED_stamped.pdf"
    assert f["hearing_date"] == "2099-01-15"
    assert storage.load_client("tgreer")["next_court_date"] == "2099-01-15"   # no court date was set


def test_mark_filed_keeps_earlier_court_date(attorney_session, greer, monkeypatch):
    monkeypatch.setattr(filings, "render_package", lambda *a: b"%PDF")
    c = storage.load_client("tgreer")
    c["next_court_date"] = "2098-06-01"
    storage.save_client(c)
    entry = attorney_session.post("/portal/attorney/filing/prepare", json=_form()).get_json()["filing"]
    attorney_session.post("/portal/attorney/filing/mark-filed", data={
        "username": "tgreer", "filing_id": entry["id"], "hearing_date": "2099-01-15"},
        content_type="multipart/form-data")
    assert storage.load_client("tgreer")["next_court_date"] == "2098-06-01"


def test_filing_routes_require_attorney(client_session, greer):
    assert client_session.get("/portal/attorney/filing/tgreer").status_code == 302
