"""Client documents: encrypted at rest, untrusted HTML never runs in the portal."""

import io

import shared
from services import client_files, storage
from services.html_sanitize import sanitize_html


def _upload(attorney_session, name, data, category="Other"):
    return attorney_session.post("/portal/attorney/upload-document", data={
        "username": "testclient", "category": category,
        "file": (io.BytesIO(data), name)}, content_type="multipart/form-data")


def test_upload_is_encrypted_and_downloads_decrypted(attorney_session, make_client):
    make_client()
    assert _upload(attorney_session, "note.pdf", b"%PDF-1.4 privileged").get_json()["success"]
    path = shared.CLIENT_FILES_DIR / "testclient" / "documents" / "Other" / "note.pdf"
    assert b"privileged" not in path.read_bytes()
    r = attorney_session.get("/portal/attorney/document/testclient/Other/note.pdf")
    assert r.data == b"%PDF-1.4 privileged"


def test_html_upload_refused(attorney_session, make_client):
    make_client()
    r = _upload(attorney_session, "x.html", b"<script>alert(1)</script>")
    assert r.status_code == 400


def test_html_preview_is_sandboxed(attorney_session, make_client):
    make_client()
    client_files.write("testclient", "Research", "memo.html", b"<script>alert(1)</script>")
    r = attorney_session.get("/portal/attorney/preview/testclient/Research/memo.html")
    csp = r.headers["Content-Security-Policy"]
    assert "sandbox" in csp and "allow-scripts" not in csp
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_pdf_preview_can_be_framed_by_the_portal_only(attorney_session, make_client):
    make_client()
    client_files.write("testclient", "Other", "a.pdf", b"%PDF")
    r = attorney_session.get("/portal/attorney/preview/testclient/Other/a.pdf")
    assert r.mimetype == "application/pdf"
    assert "frame-ancestors 'self'" in r.headers["Content-Security-Policy"]


def test_client_research_memo_is_sanitized(client_session, make_client):
    make_client()
    r = client_session.post("/portal/client/research-save", json={
        "question": "q", "memo": "<p onclick='x()'>ok</p><script>steal()</script>"})
    assert r.get_json()["success"]
    folder = shared.CLIENT_FILES_DIR / "testclient" / "documents" / "Research"
    (saved,) = list(folder.iterdir())
    html = client_files.read_text(saved)
    assert "<p>ok</p>" in html and "steal" not in html and "onclick" not in html


def test_legacy_plaintext_file_still_reads(make_client):
    make_client()
    folder = storage._client_docs_dir("testclient", "Other")
    (folder / "old.txt").write_bytes(b"legacy")
    assert client_files.read_bytes(folder / "old.txt") == b"legacy"


def test_plain_size_is_close():
    data = b"x" * 1000
    p = shared.CLIENT_FILES_DIR / "sz.bin"
    client_files.write_path(p, data)
    assert abs(client_files.plain_size(p) - 1000) <= 16


def test_lead_name_cannot_choose_the_path(client):
    r = client.post("/capture/lead", json={"name": "Eve ../../../escape", "email": ""})
    assert r.get_json()["success"]
    (lead,) = list(shared.LEADS_DIR.glob("*.json"))
    assert "escape" not in lead.name and lead.parent == shared.LEADS_DIR
    assert b"Eve" not in lead.read_bytes()            # encrypted
    assert storage.read_encrypted_json(lead)["name"] == "Eve ../../../escape"


def test_sanitizer_drops_active_content():
    out = sanitize_html('<a href="javascript:x">a</a><img src=x onerror=y><iframe>z</iframe><b>ok</b>')
    assert out == "<a>a</a><b>ok</b>"
