"""Engagement and non-engagement letters: wording, auto-draft, redraft, intake decline, assistant."""

import io
import zipfile

import pytest

import shared
from services import client_files, engagement, intake_queue, storage
from services import assistant_tools as tools

CRIMINAL = dict(client_name="Jane Smith", email="jane@example.com", case_type="Criminal Defense",
                charges="DUI, first offense", court="Davidson County General Sessions Court", case_no="GS123")


@pytest.fixture(autouse=True)
def firm(monkeypatch):
    monkeypatch.setattr(shared, "ATTORNEY_BPR", "039446")
    monkeypatch.setattr(shared, "FIRM_ADDRESS", "611 Commerce Street, Suite 2611; Nashville, TN 37203")


def _drafts(username):
    folder = shared.CLIENT_FILES_DIR / username / "documents" / "Drafts"
    return sorted(p.name for p in folder.glob("*.docx")) if folder.exists() else []


def _xml(data):
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")


# ── Wording ──────────────────────────────────────────────────────────────────

def test_flat_fee_letter_is_filled_from_the_client():
    terms = engagement.clean_terms({"flat_full": "3000", "flat_split_total": "$3,500", "flat_first": "1750",
                                    "flat_second": "1750", "second_due": "December 15, 2026"})
    text = engagement.letter_text("flat_fee", CRIMINAL, terms)
    for s in ("Dear Jane Smith:", "jane@example.com", "DUI, first offense",
              "Davidson County General Sessions Court, GS123", "A flat fee of $3,000, paid in full",
              "A flat fee of $3,500, paid in two installments: $1,750 before work begins, and $1,750 due on or "
              "before December 15, 2026", "BPR No. 039446", *engagement.NONREFUNDABLE):
        assert s in text, s


def test_blank_amounts_stay_blank():
    text = engagement.letter_text("flat_fee", CRIMINAL, {})
    assert "A flat fee of [_____], paid in full" in text


@pytest.mark.parametrize("kind", ["hourly", "evergreen", "limited"])
def test_hourly_letters_hold_the_retainer_in_trust(kind):
    text = engagement.letter_text(kind, {"client_name": "Al", "case_type": "Estate Planning"},
                                  {"hourly_rate": "350", "retainer": "2500"})
    assert "$350" in text and "$2,500" in text and "IOLTA" in text
    assert "Re: " in text and "Estate Planning matter" in text


def test_limited_scope_shows_only_the_chosen_fee():
    flat = engagement.letter_text("limited", {"client_name": "Al"}, {"flat_full": "900"})
    assert "Flat fee: You agree to pay a flat fee of $900" in flat and "Hourly:" not in flat
    both = engagement.letter_text("limited", {"client_name": "Al"}, {})
    assert "____ Hourly:" in both and "____ Flat fee:" in both


def test_non_engagement_letter():
    text = engagement.letter_text("non_engagement", engagement.intake_client(
        {"full_name": "Bob Lee", "email": "bob@example.com", "case_type": "Personal Injury"}))
    for s in ("Dear Bob Lee:", "Re: Non-Engagement: Personal Injury matter", "has decided not to represent you",
              "No attorney-client relationship has been formed", "statutes of limitations",
              "consult another attorney right away", "No fee is owed", "BPR No. 039446"):
        assert s in text, s
    assert "ACCEPTED" not in text


@pytest.mark.parametrize("bad", [{"flat_full": "abc"}, {"retainer": "-5"}, {"hourly_rate": "0"},
                                 {"flat_full": "99999999"}])
def test_bad_amounts_are_refused(bad):
    with pytest.raises(engagement.LetterError):
        engagement.clean_terms(bad)


def test_letters_print_on_the_letterhead():
    xml = _xml(engagement.letter_docx("flat_fee", CRIMINAL, {}))
    assert "611 Commerce Street, Suite 2611" in xml and 'r:embed="rId3"' in xml


# ── Drafted when the file is opened ─────────────────────────────────────────

def test_create_client_drafts_the_letter(attorney_session):
    r = attorney_session.post("/portal/attorney/create-client",
                              json={"username": "newc", "client_name": "New C", "case_type": "Criminal Defense"})
    assert r.status_code == 200
    rec = storage.load_client("newc")["engagement_letter"]
    assert rec["kind"] == "flat_fee" and rec["by"] == "auto" and _drafts("newc") == [rec["filename"]]
    view = attorney_session.get("/portal/attorney/client/newc").get_json()["engagement"]
    assert view["draft"]["filename"] == rec["filename"] and view["kind"] == "flat_fee"
    assert view["defaults"]["hourly"]["hourly_rate"]


def test_civil_clients_get_the_hourly_letter(attorney_session):
    attorney_session.post("/portal/attorney/create-client",
                          json={"username": "civ", "client_name": "Civ", "case_type": "Civil Litigation"})
    rec = storage.load_client("civ")["engagement_letter"]
    assert rec["kind"] == "hourly" and rec["terms"]["hourly_rate"]


def test_approved_intake_drafts_the_letter(client, attorney_session):
    client.post("/intake/submit", json={"full_name": "Dana Cole", "email": "dana@example.com",
                                        "phone": "615-555-0101", "case_type": "Criminal Defense",
                                        "matter_description": "DUI arrest"})
    (entry,) = intake_queue.list_pending("Endocide")
    d = attorney_session.post("/portal/attorney/intakes/approve", json={"id": entry["id"]}).get_json()
    assert storage.load_client(d["username"])["engagement_letter"]["kind"] == "flat_fee"
    assert len(_drafts(d["username"])) == 1


def test_existing_clients_are_not_drafted_on_save(make_client):
    make_client("old", **CRIMINAL)
    storage.update_client_atomic("old", lambda c: c.update(next_meeting="x"))
    assert "engagement_letter" not in storage.load_client("old") and _drafts("old") == []


# ── Redraft with new amounts ─────────────────────────────────────────────────

def test_redraft_replaces_the_previous_draft(attorney_session, make_client):
    make_client("testclient", **CRIMINAL)
    engagement.draft("testclient")
    first = _drafts("testclient")
    d = attorney_session.post("/portal/attorney/engagement-letter", json={
        "username": "testclient", "kind": "flat_fee",
        "terms": {"flat_full": "2,500", "flat_split_total": "3000", "flat_first": "1500", "flat_second": "1500"}}
    ).get_json()
    assert d["success"] and d["engagement"]["terms"]["flat_full"] == "2500"
    assert d["engagement"]["draft"]["by"] == "Endocide"
    names = _drafts("testclient")
    assert len(names) == 1 and names != first
    data = client_files.read_bytes(shared.CLIENT_FILES_DIR / "testclient" / "documents" / "Drafts" / names[0])
    assert "A flat fee of $2,500, paid in full" in _xml(data)


def test_redraft_route_checks_input_and_access(attorney_session, other_attorney_session, make_client):
    make_client("testclient", **CRIMINAL)
    bad = attorney_session.post("/portal/attorney/engagement-letter",
                                json={"username": "testclient", "kind": "flat_fee", "terms": {"flat_full": "x"}})
    assert bad.status_code == 400
    assert attorney_session.post("/portal/attorney/engagement-letter",
                                 json={"username": "testclient", "kind": "nope"}).status_code == 400
    assert other_attorney_session.post("/portal/attorney/engagement-letter",
                                       json={"username": "testclient", "kind": "hourly"}).status_code == 404
    assert _drafts("testclient") == []


def test_letters_never_reach_the_client_portal(client_session, make_client):
    make_client("testclient", **CRIMINAL)
    engagement.draft("testclient")
    assert "Engagement" not in str(client_session.get("/portal/client/documents").get_json())


# ── Declined intakes ─────────────────────────────────────────────────────────

def test_declined_intake_non_engagement_letter(client, attorney_session):
    client.post("/intake/submit", json={"full_name": "Bob Lee", "email": "bob@example.com",
                                        "phone": "615-555-0102", "case_type": "Personal Injury",
                                        "matter_description": "Slip and fall"})
    (entry,) = intake_queue.list_pending("Endocide")
    url = f"/portal/attorney/intakes/{entry['id']}/non-engagement-letter"
    assert attorney_session.get(url).status_code == 404            # still pending
    attorney_session.post("/portal/attorney/intakes/decline", json={"id": entry["id"]})
    r = attorney_session.get(url)
    assert r.status_code == 200 and "Non_Engagement_Letter_Bob_Lee" in r.headers["Content-Disposition"]
    assert "Dear Bob Lee:" in _xml(r.data)
    assert attorney_session.get("/portal/attorney/intakes/zz/non-engagement-letter").status_code == 404


def test_declined_intake_letter_is_only_for_its_attorney(make_client):
    entry = intake_queue.submit(intake_queue.clean_submission({"full_name": "Bob Lee"}))
    intake_queue.decline(entry["id"], entry["assigned_attorney"])
    assert intake_queue.declined_entry(entry["id"], entry["assigned_attorney"])
    assert intake_queue.declined_entry(entry["id"], "SomeoneElse") is None


# ── Assistant ────────────────────────────────────────────────────────────────

def test_assistant_letter_tool(make_client):
    make_client("testclient", **CRIMINAL)
    _, kind, terms, summary = tools._prep_letter("Endocide", {"client": "testclient", "flat_full": 3000})
    assert kind == "flat_fee" and "$3,000" in summary and "Draft the Flat-Fee" in summary
    out = tools._run_letter("Endocide", {"client": "testclient", "flat_full": 3000, "flat_split_total": 3500})
    assert "drafted" in out and "Drafts/" in out
    # A later change keeps the other amounts.
    tools._run_letter("Endocide", {"client": "testclient", "flat_full": 2800})
    rec = storage.load_client("testclient")["engagement_letter"]
    assert rec["terms"]["flat_full"] == "2800" and rec["terms"]["flat_split_total"] == "3500"
    assert len(_drafts("testclient")) == 1
    assert "engagement_letter" in tools.get_client_details("Endocide", "testclient")
    _, kind, _, _ = tools._prep_letter("Endocide", {"client": "testclient", "kind": "non_engagement"})
    assert kind == "non_engagement"
    with pytest.raises(tools.ToolError):
        tools._prep_letter("Endocide", {"client": "testclient", "kind": "bogus"})
    with pytest.raises(tools.ToolError):
        tools._prep_letter("Endocide", {"client": "testclient", "retainer": -1})
