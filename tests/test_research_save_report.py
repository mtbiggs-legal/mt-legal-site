"""Saving AI research output into a client's document folder + billing."""

from datetime import datetime

import pytest

import shared


def test_save_report_analysis_creates_file_and_bills(attorney_session, make_client, tmp_path):
    """An 'analysis' report is written as .txt and bills AI + review time."""
    make_client()
    resp = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis",
              "text": "ISSUE 1: Fourth Amendment violation."})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["filename"].startswith("legal_issues_")
    assert data["filename"].endswith(".txt")
    assert data["category"] == "Litigation Drafts"

    # Two entries: AI research + attorney review, 0.2 hrs each.
    assert data["billing_entry"]["hours"] == 0.2
    assert data["billing_entry2"]["hours"] == 0.2
    assert "legal issues analysis" in data["billing_entry"]["note"].lower()
    assert data["total_hours"] == pytest.approx(0.4)

    saved = (tmp_path / "files" / "testclient" / "documents" /
             "Litigation Drafts" / data["filename"])
    assert saved.exists()
    assert "Fourth Amendment" in saved.read_text(encoding="utf-8")


def test_save_report_authority_creates_file_and_bills(attorney_session, make_client):
    make_client()
    resp = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "authority",
              "text": "Terry v. Ohio, 392 U.S. 1 (1968)."})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["filename"].startswith("legal_authority_")
    assert "authority memo" in data["billing_entry"]["note"].lower()


def test_save_report_hours_match_billing_log(attorney_session, make_client):
    """hours_billed is recomputed from the log rather than incremented."""
    make_client()
    attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis", "text": "x"})

    client = shared.load_client("testclient")
    assert client["hours_billed"] == pytest.approx(
        sum(e["hours"] for e in client["billing_log"])
    )


def test_save_report_missing_params_returns_400(attorney_session):
    resp = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"report_type": "analysis", "text": "some text"})
    assert resp.status_code == 400

    resp2 = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis"})
    assert resp2.status_code == 400


def test_save_report_invalid_type_returns_400(attorney_session):
    resp = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "bogus", "text": "some text"})
    assert resp.status_code == 400


def test_save_report_deduplicates_filename(attorney_session, make_client, tmp_path):
    make_client()
    dest_dir = tmp_path / "files" / "testclient" / "documents" / "Litigation Drafts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    (dest_dir / f"legal_issues_{ts}.txt").write_text("existing", encoding="utf-8")

    resp = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis", "text": "new content"})
    assert resp.status_code == 200
    assert "_2" in resp.get_json()["filename"]


def test_save_report_unknown_client_returns_404(attorney_session, tmp_path):
    resp = attorney_session.post(
        "/portal/attorney/research/save-report",
        json={"username": "nobody", "report_type": "analysis", "text": "some analysis text"})
    assert resp.status_code == 404
    orphaned = list((tmp_path / "files").rglob("*.txt"))
    assert orphaned == [], f"Unexpected files on disk: {orphaned}"


def test_save_report_requires_attorney(client, make_client):
    make_client()
    resp = client.post(
        "/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis", "text": "x"})
    assert resp.status_code in (302, 401)
