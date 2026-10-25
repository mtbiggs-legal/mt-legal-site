"""Claiming a generated document must not let a stranger into an existing file."""

import pytest

import shared


DRAFT = "<p>IN THE CIRCUIT COURT ...</p>"


def _claim(client, **overrides):
    payload = {
        "full_name":     "John Smith",
        "password":      "correct-horse",
        "email":         "john@example.com",
        "phone":         "555-0100",
        "case_type":     "Civil Litigation",
        "template_type": "Demand Letter",
        "draft_content": DRAFT,
    }
    payload.update(overrides)
    return client.post("/drafting/claim-document", json=payload)


def test_claim_creates_account_and_saves_document(client, tmp_path):
    resp = _claim(client)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["username"] == "jsmith"

    saved = (tmp_path / "files" / "jsmith" / "documents" /
             "Generated Documents" / data["doc_filename"])
    assert saved.exists()
    assert "CIRCUIT COURT" in saved.read_text(encoding="utf-8")


def test_claim_logs_activity(client):
    """The activity entry used to be wiped by a later save."""
    _claim(client)
    record = shared.load_client("jsmith")
    kinds = [e["action_type"] for e in record["activity_log"]]
    assert "document_generated" in kinds


def test_claim_with_wrong_password_is_refused(client):
    """A second person with the same name cannot write into the first one's file."""
    first = _claim(client)
    assert first.status_code == 200

    resp = _claim(client, password="not-the-password", draft_content="<p>intruder</p>")
    assert resp.status_code == 403
    assert "already exists" in resp.get_json()["error"]

    # Nothing extra was written or billed to the existing account.
    record = shared.load_client("jsmith")
    docs = list((shared.CLIENT_FILES_DIR / "jsmith" / "documents" /
                 "Generated Documents").iterdir())
    assert len(docs) == 1
    assert record["hours_billed"] == pytest.approx(0.7)   # 0.2 intake + 0.5 doc


def test_claim_with_correct_password_adds_to_existing_account(client):
    _claim(client)
    resp = _claim(client, template_type="Rental Agreement")
    assert resp.status_code == 200
    assert resp.get_json()["username"] == "jsmith"

    record = shared.load_client("jsmith")
    # 0.2 intake + 0.5 + 0.5 for the two documents
    assert record["hours_billed"] == pytest.approx(1.2)
    assert record["hours_billed"] == pytest.approx(
        sum(e["hours"] for e in record["billing_log"]))


def test_claim_rejects_short_password(client):
    resp = _claim(client, password="abc")
    assert resp.status_code == 400
    assert "at least" in resp.get_json()["error"]


def test_claim_requires_draft_content(client):
    resp = _claim(client, draft_content="")
    assert resp.status_code == 400


def test_claim_escapes_client_name_in_saved_html(client, tmp_path):
    """A name is untrusted text — it must not become markup in the saved file."""
    resp = _claim(client, full_name="John <script>alert(1)</script> Smith")
    assert resp.status_code == 200
    data = resp.get_json()
    saved = (tmp_path / "files" / data["username"] / "documents" /
             "Generated Documents" / data["doc_filename"]).read_text(encoding="utf-8")
    assert "<script>" not in saved
    assert "&lt;script&gt;" in saved
