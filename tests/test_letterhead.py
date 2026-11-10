"""Firm letterhead on letters, the flat-fee engagement letter, and Word downloads."""

import io
import types
import zipfile

import pytest

import shared
import blueprints.drafting as drafting
from services import docx_writer

LETTER = "[Date]\nVIA E-MAIL\nJane Smith\nRe: Engagement\nDear Jane Smith:\nThank you.\nSincerely,\n/s/ Madison T. Biggs"
FILING = "IN THE CIRCUIT COURT FOR DAVIDSON COUNTY, TENNESSEE\nCase No. 1\nMOTION TO CONTINUE\nText."
WILL = "LAST WILL AND TESTAMENT OF JANE SMITH\nI, Jane Smith, declare this to be my will."


def _parts(text, **kw):
    z = zipfile.ZipFile(io.BytesIO(docx_writer.text_to_docx("t", text, **kw)))
    return z.namelist(), z.read("word/document.xml").decode("utf-8")


@pytest.fixture
def firm(monkeypatch):
    monkeypatch.setattr(shared, "FIRM_ADDRESS", "611 Commerce Street, Suite 2611; Nashville, TN 37203")
    monkeypatch.setattr(shared, "ATTORNEY_BPR", "039446")


def test_letters_get_the_letterhead(firm):
    names, xml = _parts(LETTER)
    assert "word/media/letterhead-logo.png" in names
    assert 'r:embed="rId3"' in xml
    assert "611 Commerce Street, Suite 2611 · Nashville, TN 37203" in xml
    assert "615-606-2603" in xml and "midtennlegal.com" in xml
    assert xml.index("611 Commerce") < xml.index("Dear Jane Smith")


def test_letter_top_is_flush_left_and_acceptance_stays_with_signature():
    rows = docx_writer._letter_rows(docx_writer.layout(LETTER.replace("[Date]", "[Date]\nVIA E-MAIL")
                                                       + "\nACCEPTED AND AGREED. I have read this.\n____\nJane"))
    assert dict(rows)["VIA E-MAIL"] == "address"
    assert dict(rows)["ACCEPTED AND AGREED. I have read this."] == "accept"
    assert dict(rows)["Sincerely,"] == "letter-keep"


@pytest.mark.parametrize("text", [FILING, WILL])
def test_filings_and_wills_never_do(firm, text):
    names, xml = _parts(text)
    assert "word/media/letterhead-logo.png" not in names
    assert "611 Commerce" not in xml


def test_letterhead_can_be_forced_either_way(firm):
    assert "word/media/letterhead-logo.png" in _parts(WILL, letterhead=True)[0]
    assert "611 Commerce" not in _parts(LETTER, letterhead=False)[1]


def test_without_an_address_the_city_shows(monkeypatch):
    monkeypatch.setattr(shared, "FIRM_ADDRESS", "")
    assert docx_writer.letterhead_lines()[0] == shared.FIRM_CITY


def test_bpr_reads_either_env_name():
    from config import Settings
    assert Settings(env={"ATTORNEY_BPR_NUMBER": "039446"}).ATTORNEY_BPR == "039446"
    assert Settings(env={"ATTORNEY_BPR": "111111", "ATTORNEY_BPR_NUMBER": "039446"}).ATTORNEY_BPR == "111111"


# ── Flat-fee engagement letter template ─────────────────────────────────────

def test_flat_fee_letter_prompt(attorney_session, monkeypatch, firm):
    seen = {}

    def create(**kw):
        seen.update(kw)
        return types.SimpleNamespace(content=[types.SimpleNamespace(text="Dear Jane:")])

    monkeypatch.setattr(drafting, "get_anthropic_client",
                        lambda: types.SimpleNamespace(messages=types.SimpleNamespace(create=create)))
    r = attorney_session.post("/drafting/generate", json={
        "template_type": "Flat-Fee Engagement Letter (Criminal)",
        "variables": {"client_name": "Jane Smith", "charges": "DUI", "flat_fee_full": "$3,000",
                      "flat_fee_split": "$3,500: $1,750 now, $1,750 later"}})
    assert r.get_json()["success"]
    prompt = seen["messages"][0]["content"]
    for text in ("Jane Smith", "DUI", "$3,000", "$1,750 now", "BPR No. 039446",
                 "is nonrefundable and is earned by MT Legal when paid",
                 "Rule 1.5(f) of the Tennessee Rules of Professional Conduct",
                 "you may be entitled to a refund of any part of the fee"):
        assert text in prompt, text


# ── Word download ───────────────────────────────────────────────────────────

def test_word_download(attorney_session, firm):
    r = attorney_session.post("/drafting/docx", json={"title": "Flat-Fee Engagement Letter (Criminal)",
                                                      "content": LETTER})
    assert r.status_code == 200
    assert 'filename="Flat_Fee_Engagement_Letter__Criminal_' in r.headers["Content-Disposition"]
    assert "word/media/letterhead-logo.png" in zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert attorney_session.post("/drafting/docx", json={"content": ""}).status_code == 400


def test_word_download_needs_an_attorney(client_session):
    r = client_session.post("/drafting/docx", json={"title": "x", "content": "y"})
    assert r.status_code in (302, 401, 403)
