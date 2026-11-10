"""Felony case checklist and the automatic Request for Discovery."""

from services import client_files
import io
import zipfile

import pytest

import shared
from services import felony, storage
from services import assistant_tools as tools

FELONY = dict(client_name="Evan R. Mercer", charge_level="Felony", county="Davidson",
              charges="Possession with intent, T.C.A. 39-17-417")


def _drafts(username):
    folder = shared.CLIENT_FILES_DIR / username / "documents" / "Drafts"
    return sorted(p.name for p in folder.glob("*.docx")) if folder.exists() else []


def _docx_text(username, name):
    data = client_files.read_bytes(shared.CLIENT_FILES_DIR / username / "documents" / "Drafts" / name)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _update(username, **fields):
    return storage.update_client_atomic(username, lambda c: c.update(fields))


def test_no_draft_while_in_general_sessions(make_client):
    make_client("fel", court="Davidson County General Sessions Court", case_no="26-GS-1", **FELONY)
    _update("fel", next_meeting="x")
    assert _drafts("fel") == [] and "discovery_draft" not in storage.load_client("fel")


def test_draft_when_case_reaches_criminal_court(make_client):
    make_client("fel", court="Davidson County General Sessions Court", **FELONY)
    _update("fel", court="Davidson County Criminal Court", case_no="2026-C-1234")
    names = _drafts("fel")
    assert len(names) == 1 and names[0].startswith("DRAFT_Request_for_Discovery_")
    d = storage.load_client("fel")["discovery_draft"]
    assert (d["status"], d["category"], d["filename"], d["reviewed"]) == ("ready", "Drafts", names[0], False)
    xml = _docx_text("fel", names[0])
    for text in ("IN THE CRIMINAL COURT FOR DAVIDSON COUNTY, TENNESSEE", "EVAN R. MERCER",
                 "Case No. 2026-C-1234", "REQUEST FOR DISCOVERY", "Rule 16", "body-worn camera",
                 "Brady v. Maryland", "39-17-417", "CERTIFICATE OF SERVICE"):
        assert text in xml, text


def test_only_one_draft_per_case(make_client):
    make_client("fel", court="Davidson County Criminal Court", case_no="2026-C-1", **FELONY)
    _update("fel", next_meeting="a")
    _update("fel", next_meeting="b")
    felony.set_item("fel", felony.ARRAIGNMENT, True, "Endocide")
    assert len(_drafts("fel")) == 1


def test_arraignment_check_drafts_without_court_info(make_client):
    make_client("fel", **FELONY)
    felony.set_item("fel", felony.ARRAIGNMENT, True, "Endocide")
    assert len(_drafts("fel")) == 1
    item = felony.checklist_view(storage.load_client("fel"))[0]
    assert item["done"] and item["by"] == "Endocide" and item["at"]


def test_misdemeanors_get_no_checklist_or_draft(make_client):
    make_client("mis", charge_level="Misdemeanor", court="Davidson County Criminal Court", case_no="1")
    _update("mis", next_meeting="x")
    assert _drafts("mis") == [] and felony.checklist_view(storage.load_client("mis")) == []
    with pytest.raises(ValueError):
        felony.set_item("mis", "bodycam", True, "Endocide")


def test_circuit_court_counts_as_trial_court(make_client):
    make_client("fel", court="Maury County Circuit Court", case_no="2026-CR-9", **{**FELONY, "county": "Maury"})
    _update("fel", next_meeting="x")
    names = _drafts("fel")
    assert names and "IN THE CIRCUIT COURT FOR MAURY COUNTY, TENNESSEE" in _docx_text("fel", names[0])


def test_drafts_never_reach_the_client_portal(client_session, make_client):
    make_client("testclient", court="Davidson County Criminal Court", case_no="2026-C-7", **FELONY)
    _update("testclient", next_meeting="x")
    assert _drafts("testclient")
    docs = client_session.get("/portal/client/documents").get_json()
    assert "Request_for_Discovery" not in str(docs)


# ── Routes ───────────────────────────────────────────────────────────────────

def test_checklist_route_and_dashboard(attorney_session, make_client):
    make_client("testclient", **FELONY)
    view = attorney_session.get("/portal/attorney/client/testclient").get_json()
    assert [i["key"] for i in view["felony_checklist"]][:2] == ["arraignment", "discovery_filed"]
    d = attorney_session.post("/portal/attorney/felony-checklist",
                              json={"username": "testclient", "key": "arraignment", "done": True}).get_json()
    assert d["success"] and d["felony_checklist"][0]["done"]
    assert d["discovery_draft"]["status"] == "ready"
    def drafts():
        items = attorney_session.get("/portal/attorney/dashboard").get_json()["action_items"]
        return [i["username"] for i in items if i.get("kind") == "discovery_draft"]
    assert drafts() == ["testclient"]
    attorney_session.post("/portal/attorney/discovery-reviewed", json={"username": "testclient"})
    assert drafts() == []
    r = attorney_session.post("/portal/attorney/felony-checklist",
                              json={"username": "testclient", "key": "nope", "done": True})
    assert r.status_code == 400


def test_checklist_route_denies_unassigned_attorney(other_attorney_session, make_client):
    make_client("testclient", **FELONY)
    r = other_attorney_session.post("/portal/attorney/felony-checklist",
                                    json={"username": "testclient", "key": "bodycam", "done": True})
    assert r.status_code == 404
    assert "felony_checklist" not in storage.load_client("testclient")


# ── Assistant ────────────────────────────────────────────────────────────────

def test_assistant_checklist_tool(make_client):
    make_client("testclient", **FELONY)
    _, _, _, summary = tools._prep_checklist("Endocide", {"client": "testclient", "item": "arraignment"})
    assert "drafts the Request for Discovery" in summary
    out = tools._run_checklist("Endocide", {"client": "testclient", "item": "arraignment"})
    assert "Request for Discovery drafted" in out
    tools._run_checklist("Endocide", {"client": "testclient", "item": "bodycam", "done": True})
    details = tools.get_client_details("Endocide", "testclient")
    assert '"bodycam"' in details and "Request_for_Discovery" in details
    assert "Request_for_Discovery" in tools.get_attention_items("Endocide")
    with pytest.raises(tools.ToolError):
        tools._prep_checklist("Endocide", {"client": "testclient", "item": "made_up"})
