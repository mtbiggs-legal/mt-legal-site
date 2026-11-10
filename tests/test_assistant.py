"""Portal assistant: data tools, access control, and confirm-before-change."""

from services import client_files
import copy
import json
import types
from datetime import date, timedelta

import pytest

import shared
from services import assistant, assistant_tools as tools, billing, storage

TODAY = date.today()
D = lambda n: (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def _fresh_conversations():
    assistant._conversations.clear()
    yield
    assistant._conversations.clear()


@pytest.fixture
def clients(make_client):
    make_client("tgreer", client_name="Travis L. Greer", case_type="Criminal Defense",
                county="Davidson", court="General Sessions", next_court_date=D(2),
                last_communication=D(-1), billing_log=[{"date": D(-1), "hours": 2.0, "note": "Review"}],
                messages=[{"from": "client", "date": "2026-11-01 09:00", "text": "Any news?"}])
    make_client("dokonkwo", client_name="Danielle R. Okonkwo", case_type="Family Law — Child Custody",
                county="Rutherford", court="Circuit Court", next_court_date=D(5),
                last_communication=D(-45), billing_log=[{"date": D(-2), "hours": 1.5, "note": "Draft"}])
    make_client("other", client_name="Not Mine", assigned_attorney="SophiaH",
                county="Shelby", next_court_date=D(1))


# ── Data tools ───────────────────────────────────────────────────────────────

def test_schedule_lists_only_my_dates_in_range(clients):
    out = json.loads(tools.get_schedule("Endocide", D(0), D(6)))
    names = [e["client"] for e in out["events"]]
    assert names == ["Travis L. Greer", "Danielle R. Okonkwo"]
    assert {e["county"] for e in out["events"]} == {"Davidson", "Rutherford"}
    assert "Not Mine" not in json.dumps(out)


def test_schedule_rejects_bad_dates(clients):
    with pytest.raises(tools.ToolError):
        tools.get_schedule("Endocide", "next week", D(3))
    with pytest.raises(tools.ToolError):
        tools.get_schedule("Endocide", D(5), D(1))


def test_resolve_client_by_partial_name_and_access(clients):
    assert tools.resolve_client("Endocide", "greer")["username"] == "tgreer"
    with pytest.raises(tools.ToolError, match="No client"):
        tools.resolve_client("Endocide", "Not Mine")          # another attorney's client


def test_resolve_client_ambiguous(make_client):
    make_client("jsmith", client_name="Jane Smith")
    make_client("jsmith2", client_name="John Smith")
    with pytest.raises(tools.ToolError, match="Several clients"):
        tools.resolve_client("Endocide", "smith")


def test_billing_status_shows_payment_and_balance(clients):
    billing.issue_statement("tgreer", reason="test", issued_by="Endocide", notify=False)
    storage._apply_payment("tgreer", 200.0, "check", "chk-1")
    out = json.loads(tools.get_billing_status("Endocide", "Travis"))
    assert out["total_billed"] == 700.0                       # 2 hrs at the pinned $350
    assert out["total_paid"] == 200.0
    assert out["amount_due"] == 500.0
    assert out["payments"][0]["method"] == "check"


def test_billing_report_for_month(clients):
    out = json.loads(tools.get_billing_report("Endocide", TODAY.strftime("%Y-%m")))
    expected = sum(h for d, h in ((D(-1), 2.0), (D(-2), 1.5)) if d[:7] == TODAY.strftime("%Y-%m"))
    assert out["hours_logged"] == expected
    assert all(r["client"] != "Not Mine" for r in out["by_client"])
    with pytest.raises(tools.ToolError):
        tools.get_billing_report("Endocide", "November")


def test_attention_items(clients, tmp_path):
    (tmp_path / "leads" / "1_lead.json").write_text(json.dumps(
        {"name": "Lead One", "assigned_attorney": "Endocide"}), encoding="utf-8")
    out = json.loads(tools.get_attention_items("Endocide"))
    assert [x["client"] for x in out["court_within_7_days"]] == ["Travis L. Greer", "Danielle R. Okonkwo"]
    assert out["need_follow_up"][0]["client"] == "Danielle R. Okonkwo"
    assert out["unanswered_client_messages"][0]["client"] == "Travis L. Greer"
    assert out["open_leads"] == 1


def test_every_tool_has_a_definition():
    names = [t["name"] for t in tools.tool_definitions()]
    assert set(names) == set(tools.DATA_TOOLS) | set(tools.ACTION_TOOLS)
    for t in tools.tool_definitions():
        assert t["input_schema"]["type"] == "object"


# ── The loop, through the routes ─────────────────────────────────────────────

class _Block(dict):
    def to_dict(self):
        return dict(self)


def _resp(*blocks, stop="end_turn"):
    return types.SimpleNamespace(content=[_Block(b) for b in blocks], stop_reason=stop,
                                 usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))


def _script(monkeypatch, *responses):
    """Make the model return these responses in order; record each request."""
    calls, queue = [], list(responses)

    def create(**kw):
        calls.append(copy.deepcopy(kw))
        return queue.pop(0)

    fake = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=create)))
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: fake)
    return calls


def _tool(name, inp, tid="tu_1"):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def test_question_runs_data_tool_and_answers(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("get_schedule", {"start_date": D(0), "end_date": D(6)}), stop="tool_use"),
                    _resp({"type": "text", "text": "You have court in Davidson and Rutherford."}))
    r = attorney_session.post("/portal/attorney/assistant/message", json={"text": "Where do I have court?"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["reply"] == "You have court in Davidson and Rutherford."
    assert data["pending"] == []
    result = calls[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "Rutherford" in result["content"]
    assert "Today is" in calls[0]["messages"][0]["content"][0]["text"]


def test_action_waits_for_confirmation_then_runs(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp({"type": "text", "text": "I'll log that."},
                          _tool("log_time", {"client": "greer", "hours": 1.25, "note": "Called DA"}),
                          stop="tool_use"),
                    _resp({"type": "text", "text": "Done."}))
    r = attorney_session.post("/portal/attorney/assistant/message", json={"text": "Log 1.25 hrs for Greer"})
    data = r.get_json()
    assert len(data["pending"]) == 1 and "1.25 hr" in data["pending"][0]["summary"]
    assert len(storage.load_client("tgreer")["billing_log"]) == 1          # nothing written yet

    r = attorney_session.post("/portal/attorney/assistant/confirm",
                              json={"decisions": {data["pending"][0]["id"]: True}})
    assert r.get_json()["reply"] == "Done."
    log = storage.load_client("tgreer")["billing_log"]
    assert log[-1]["hours"] == 1.25 and log[-1]["note"] == "Called DA"
    assert "Logged 1.25 hr" in calls[1]["messages"][-1]["content"][0]["content"]


def test_declined_action_does_not_run(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("send_client_message", {"client": "tgreer", "text": "Hello"}), stop="tool_use"),
                    _resp({"type": "text", "text": "Okay, not sent."}))
    pend = attorney_session.post("/portal/attorney/assistant/message",
                                 json={"text": "Message Travis"}).get_json()["pending"]
    attorney_session.post("/portal/attorney/assistant/confirm", json={"decisions": {pend[0]["id"]: False}})
    assert storage.load_client("tgreer")["messages"][-1]["from"] == "client"
    assert "declined" in calls[1]["messages"][-1]["content"][0]["content"]


def test_new_message_declines_pending(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("record_payment", {"client": "tgreer", "amount": 100}), stop="tool_use"),
                    _resp({"type": "text", "text": "Sure."}))
    attorney_session.post("/portal/attorney/assistant/message", json={"text": "Record $100"})
    attorney_session.post("/portal/attorney/assistant/message", json={"text": "Never mind"})
    assert storage.load_client("tgreer").get("payments") in ([], None)
    first = calls[1]["messages"][-1]["content"]
    assert first[0]["type"] == "tool_result" and "declined" in first[0]["content"]
    assert first[1]["type"] == "text" and "Never mind" in first[1]["text"]


def test_invalid_action_input_goes_back_as_error(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("log_time", {"client": "greer", "hours": 99, "note": "x"}), stop="tool_use"),
                    _resp({"type": "text", "text": "That's too many hours."}))
    data = attorney_session.post("/portal/attorney/assistant/message", json={"text": "log 99"}).get_json()
    assert data["pending"] == []
    err = calls[1]["messages"][-1]["content"][0]
    assert err["is_error"] is True


def test_action_cannot_touch_another_attorneys_client(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("update_case_info", {"client": "other", "changes": {"county": "Knox"}}),
                          stop="tool_use"),
                    _resp({"type": "text", "text": "I can't find that client."}))
    data = attorney_session.post("/portal/attorney/assistant/message", json={"text": "x"}).get_json()
    assert data["pending"] == []
    assert storage.load_client("other")["county"] == "Shelby"


def test_routes_require_attorney(client, client_session):
    for c in (client, client_session):
        r = c.post("/portal/attorney/assistant/message", json={"text": "hi"})
        assert r.status_code == 401


def test_routes_off_in_public_site_only(attorney_session, monkeypatch):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    assert attorney_session.post("/portal/attorney/assistant/message", json={"text": "hi"}).status_code == 404


def test_confirm_with_nothing_pending(attorney_session):
    r = attorney_session.post("/portal/attorney/assistant/confirm", json={"decisions": {}})
    assert r.status_code == 400


def test_history_and_reset(attorney_session, clients, monkeypatch):
    _script(monkeypatch, _resp({"type": "text", "text": "Hello."}))
    attorney_session.post("/portal/attorney/assistant/message", json={"text": "Hi there"})
    h = attorney_session.get("/portal/attorney/assistant/history").get_json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant"]
    assert h["messages"][0]["text"] == "Hi there"
    attorney_session.post("/portal/attorney/assistant/reset")
    assert attorney_session.get("/portal/attorney/assistant/history").get_json()["messages"] == []


DRAFT = ("IN THE GENERAL SESSIONS COURT FOR DAVIDSON COUNTY, TENNESSEE\n\nSTATE OF TENNESSEE v. TRAVIS L. GREER\n\n"
         "MOTION TO SUPPRESS\n\n1. Defendant moves the Court to suppress all evidence obtained after the stop.")


def test_draft_is_saved_as_word_document(attorney_session, clients, monkeypatch):
    import io
    import zipfile
    calls = _script(monkeypatch,
                    _resp(_tool("save_draft_document", {"client": "greer", "title": "Motion to Suppress",
                                                        "content": DRAFT}), stop="tool_use"),
                    _resp({"type": "text", "text": "I drafted the motion and saved it to Motions."}))
    d = attorney_session.post("/portal/attorney/assistant/message", json={"text": "Draft a motion to suppress for Greer"}).get_json()
    assert d["reply"].startswith("I drafted") and "MOTION TO SUPPRESS" not in d["reply"]
    doc = d["documents"][0]
    assert doc["category"] == "Drafts" and doc["filename"].startswith("DRAFT_Motion_to_Suppress_")
    assert doc["filename"].endswith(".docx") and doc["username"] == "tgreer"
    path = shared.CLIENT_FILES_DIR / "tgreer" / "documents" / "Drafts" / doc["filename"]
    xml = zipfile.ZipFile(io.BytesIO(client_files.read_bytes(path))).read("word/document.xml").decode()
    assert "MOTION TO SUPPRESS" in xml and "suppress all evidence" in xml
    acts = [e["action_type"] for e in storage.load_client("tgreer")["activity_log"]]
    assert "document_generated" in acts


def test_draft_needs_full_content_and_my_client(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("save_draft_document", {"client": "greer", "title": "X", "content": "too short"}, "t1"),
                          _tool("save_draft_document", {"client": "Not Mine", "title": "X", "content": DRAFT}, "t2"),
                          stop="tool_use"),
                    _resp({"type": "text", "text": "Couldn't save."}))
    d = attorney_session.post("/portal/attorney/assistant/message", json={"text": "draft"}).get_json()
    assert d["documents"] == []
    errs = calls[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in errs)
    assert not (shared.CLIENT_FILES_DIR / "other" / "documents").exists()


def test_cut_off_tool_call_is_not_run(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp(_tool("save_draft_document", {"client": "greer", "title": "Long", "content": DRAFT}),
                          stop="max_tokens"),
                    _resp({"type": "text", "text": "I'll split it."}))
    d = attorney_session.post("/portal/attorney/assistant/message", json={"text": "draft a long brief"}).get_json()
    assert d["documents"] == [] and d["reply"] == "I'll split it."
    assert "length limit" in calls[1]["messages"][-1]["content"][0]["content"]
    assert not (shared.CLIENT_FILES_DIR / "tgreer" / "documents" / "Generated Documents").exists()


def test_system_prompt_has_signature_block(monkeypatch):
    monkeypatch.setattr(shared, "ATTORNEY_BPR", "012345")
    monkeypatch.setenv("FIRM_PHONE", "(615) 555-0100")
    p = assistant.system_prompt()
    assert "Madison T. Biggs, Esq." in p and "BPR No. 012345" in p and "(615) 555-0100" in p
    assert "{signature_block}" not in p


def test_court_filing_layout():
    from services.docx_writer import layout
    text = ("IN THE CIRCUIT COURT FOR DAVIDSON COUNTY, TENNESSEE\n\nJANE DOE,\nv.\nACME CORP.,\nCase No. 26C1\n\n"
            "MOTION TO DISMISS\n\nDefendant moves to dismiss.\n\nARGUMENT\n\n1. The claim fails.\n\n"
            "Respectfully submitted,\n____________\nMadison T. Biggs, Esq.\n\nCERTIFICATE OF SERVICE\n\n"
            "I hereby certify service.")
    kinds = [k for _, k in layout(text)]
    assert kinds == ["caption"] * 5 + ["title", "body", "heading", "body"] + ["signature"] * 3 + ["heading", "cert"]


def test_court_filing_formatting_in_word():
    import io
    import zipfile
    from services.docx_writer import text_to_docx
    xml = zipfile.ZipFile(io.BytesIO(text_to_docx("t", "IN THE CIRCUIT COURT FOR DAVIDSON COUNTY\nCase No. 1\n"
                                                       "MOTION TO DISMISS\nBody paragraph.\nARGUMENT"))).read("word/document.xml").decode()
    body = xml.split("Body paragraph")[0].rsplit("<w:p>", 1)[1]
    assert 'w:jc w:val="both"' in body and 'w:line="480"' in body and 'w:firstLine="720"' in body
    title = xml.split("MOTION TO DISMISS")[0].rsplit("<w:p>", 1)[1]
    assert 'w:jc w:val="center"' in title and "<w:b/>" in title and "<w:keepNext/>" in title


def test_letters_are_single_spaced():
    from services.docx_writer import layout
    assert {k for _, k in layout("Dear Mr. Smith:\nThank you for meeting with me.\nSincerely,")} == {"letter"}


def test_placeholder_paragraphs_are_not_bold():
    import io
    import zipfile
    from services.docx_writer import text_to_docx
    xml = zipfile.ZipFile(io.BytesIO(text_to_docx("t", "MOTION TO CONTINUE\n8. [POSITION OF THE STATE]"))
                          ).read("word/document.xml").decode()
    heading, numbered = xml.split("MOTION TO CONTINUE")[0], xml.split("MOTION TO CONTINUE")[1]
    assert "<w:b/>" in heading and "<w:b/>" not in numbered


LONG_DOC = ("IN THE GENERAL SESSIONS COURT OF DAVIDSON COUNTY, TENNESSEE\nCase No. 26-GS-41907\n\n"
            "MOTION TO DISMISS\n\nComes now the Defendant... " + "Argument. " * 150 +
            "\n\nWHEREFORE, Defendant prays...\n\nRespectfully submitted,\n\nCERTIFICATE OF SERVICE")


def test_draft_written_in_chat_is_saved_instead(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch,
                    _resp({"type": "text", "text": "Here's a draft.\n\n" + LONG_DOC}),
                    _resp(_tool("save_draft_document", {"client": "greer", "title": "Motion to Dismiss",
                                                        "content": LONG_DOC}), stop="tool_use"),
                    _resp({"type": "text", "text": "Saved the motion to Greer's Drafts."}))
    d = attorney_session.post("/portal/attorney/assistant/message", json={"text": "draft a motion to dismiss"}).get_json()
    assert d["reply"] == "Saved the motion to Greer's Drafts."             # the document text isn't shown
    assert d["documents"][0]["category"] == "Drafts"
    assert calls[1]["messages"][-1]["content"][0]["text"].startswith("[Portal note")
    h = attorney_session.get("/portal/attorney/assistant/history").get_json()["messages"]
    assert [m["role"] for m in h] == ["user", "assistant"] and "COMES NOW" not in json.dumps(h).upper()


def test_short_answers_are_not_treated_as_documents(attorney_session, clients, monkeypatch):
    calls = _script(monkeypatch, _resp({"type": "text", "text": "A motion to dismiss usually comes after..."}))
    d = attorney_session.post("/portal/attorney/assistant/message", json={"text": "what is a motion to dismiss"}).get_json()
    assert d["reply"].startswith("A motion to dismiss") and len(calls) == 1


def test_conversation_belongs_to_one_attorney(clients):
    conv = assistant.get_conversation("", "Endocide")
    assert assistant.get_conversation(conv["id"], "SophiaH")["id"] != conv["id"]


def test_client_portal_never_shows_drafts(client_session, make_client):
    make_client("testclient")
    d = shared.CLIENT_FILES_DIR / "testclient" / "documents" / "Drafts"
    d.mkdir(parents=True)
    (d / "DRAFT_x.docx").write_bytes(b"x")
    listing = client_session.get("/portal/client/documents").get_json()
    assert "Drafts" not in listing["categories"] and "Drafts" not in listing["files"]
    assert client_session.get("/portal/client/document/Drafts/DRAFT_x.docx").status_code == 400
