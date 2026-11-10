"""Firm admin deadlines: reminder steps, records, editing, emails, assistant."""

from datetime import date

import pytest

import shared
from services import firm_admin, firm_admin_scheduler
from services import assistant_tools as tools


@pytest.fixture
def fixed_today(monkeypatch):
    def set_today(d):
        monkeypatch.setattr(firm_admin, "_today", lambda: d)
    set_today(date(2026, 1, 1))
    return set_today


def _item(oid, today=None):
    return next(o for o in firm_admin.overview(today)["obligations"] if o["id"] == oid)


def test_seeded_items_and_statuses(fixed_today):
    obs = {o["id"]: o for o in firm_admin.overview(date(2026, 1, 1))["obligations"]}
    assert {"bpr", "iolta", "cle", "privilege_tax", "estimated_tax", "pllc_report", "malpractice"} <= set(obs)
    assert obs["bpr"]["status"] == "needs_date" and obs["malpractice"]["status"] == "needs_date"
    assert obs["pllc_report"]["status"] == "off"
    assert obs["estimated_tax"]["next_due"] == "2026-01-15"
    assert (obs["estimated_tax"]["status"], obs["estimated_tax"]["stage"]) == ("due_soon", 15)
    assert obs["privilege_tax"]["status"] == "ok" and obs["privilege_tax"]["next_due"] == "2026-06-01"
    assert (shared.FIRM_SETTINGS_DIR / "firm-admin.json").exists()


@pytest.mark.parametrize("days,expected", [
    (61, None), (60, 60), (46, 60), (45, 45), (31, 45), (30, 30), (16, 30), (15, 15),
    (11, 15), (10, 10), (6, 10), (5, 5), (0, 5), (-1, "overdue"),
])
def test_reminder_steps(days, expected):
    assert firm_admin.stage(days) == expected


def test_marking_done_stops_reminders_and_keeps_record(fixed_today):
    firm_admin.overview()
    rec = firm_admin.complete("estimated_tax", "2026-01-15", "Endocide", "$3,000", "IRS-123", "Q4")
    assert rec["title"].startswith("Quarterly estimated taxes")
    o = _item("estimated_tax", date(2026, 1, 1))
    assert o["next_due"] == "2026-04-15" and o["stage"] is None and o["status"] == "ok"
    assert o["last_record"]["confirmation"] == "IRS-123"
    assert "estimated_tax" not in [r["id"] for r in firm_admin.reminders(date(2026, 1, 1))]
    records = firm_admin.overview()["records"]
    assert records[0]["amount"] == "$3,000" and records[0]["by"] == "Endocide"
    with pytest.raises(firm_admin.AdminError):
        firm_admin.complete("estimated_tax", "2026-01-15", "Endocide")
    firm_admin.delete_record(records[0]["id"])
    assert _item("estimated_tax", date(2026, 1, 1))["next_due"] == "2026-01-15"


def test_overdue_until_done(fixed_today):
    firm_admin.overview()
    o = _item("estimated_tax", date(2026, 1, 20))
    assert (o["status"], o["next_due"], o["days_left"]) == ("overdue", "2026-01-15", -5)
    assert firm_admin.reminders(date(2026, 1, 20))[0]["text"] == "Overdue since 2026-01-15"


def test_add_edit_and_remove_items(fixed_today):
    ob = firm_admin.save_obligation({"title": "Davidson County business license", "category": "Business entity",
                                     "repeat": "yearly", "dates": "03-01", "link": "https://example.com"})
    assert _item(ob["id"], date(2026, 1, 15))["stage"] == 45
    firm_admin.save_obligation({"id": "bpr", "title": "BPR annual registration and fee", "repeat": "yearly",
                                "dates": ["02-01"]})
    assert _item("bpr", date(2026, 1, 1))["next_due"] == "2026-02-01"
    once = firm_admin.save_obligation({"title": "File PLLC articles", "repeat": "once", "date": "2026-01-10"})
    assert _item(once["id"], date(2026, 1, 1))["stage"] == 10
    firm_admin.delete_obligation(once["id"])
    assert once["id"] not in [o["id"] for o in firm_admin.overview()["obligations"]]
    for bad in ({"title": ""}, {"title": "x", "dates": "6/1"}, {"title": "x", "repeat": "once", "date": "soon"},
                {"title": "x", "dates": "06-01", "link": "javascript:alert(1)"}, {"title": "x", "repeat": "weekly"}):
        with pytest.raises(firm_admin.AdminError):
            firm_admin.save_obligation(bad)


def test_damaged_file_is_never_overwritten(fixed_today):
    path = shared.FIRM_SETTINGS_DIR / "firm-admin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(firm_admin.AdminError):
        firm_admin.overview()
    assert path.read_text(encoding="utf-8") == "{not json"


def test_each_email_step_goes_out_once(fixed_today):
    firm_admin.save_obligation({"id": "bpr", "title": "BPR", "dates": "03-01"})
    firm_admin.overview()

    def bpr(day):
        return [i for i in firm_admin.claim_email_reminders(day) if i["title"] == "BPR"]
    assert len(bpr(date(2026, 1, 10))) == 1          # 50 days out: the 60-day step
    assert bpr(date(2026, 1, 11)) == []
    assert len(bpr(date(2026, 1, 15))) == 1          # 45
    # App off for weeks: only the current step is sent, not every missed one.
    assert len(bpr(date(2026, 2, 25))) == 1          # 5
    assert bpr(date(2026, 2, 26)) == []
    assert len(bpr(date(2026, 3, 2))) == 1           # overdue
    assert bpr(date(2026, 3, 9)) == []


def test_scheduler_waits_for_sendgrid(fixed_today, monkeypatch):
    from blueprints import email_service
    sent = []
    monkeypatch.setattr(email_service, "_send_firm_alert", lambda *a: sent.append(a))
    monkeypatch.setattr(email_service, "_api_key", lambda: "")
    firm_admin_scheduler.tick()
    assert sent == []
    assert not (firm_admin._load()["reminders_sent"])                # no step used up
    monkeypatch.setattr(email_service, "_api_key", lambda: "SG.test")
    firm_admin_scheduler.tick()
    assert len(sent) == 1 and "Quarterly estimated taxes" in sent[0][0]


# ── Routes ───────────────────────────────────────────────────────────────────

def test_routes(attorney_session, fixed_today):
    d = attorney_session.get("/portal/attorney/firm-admin").get_json()
    assert any(o["id"] == "cle" for o in d["obligations"])
    items = attorney_session.get("/portal/attorney/dashboard").get_json()["action_items"]
    assert any(i.get("kind") == "admin" and "estimated" in i["client_name"].lower() for i in items)
    r = attorney_session.post("/portal/attorney/firm-admin/complete", json={
        "id": "estimated_tax", "due": "2026-01-15", "amount": "$2,500", "confirmation": "EFTPS 9"})
    assert r.get_json()["success"] and r.get_json()["records"][0]["confirmation"] == "EFTPS 9"
    r = attorney_session.post("/portal/attorney/firm-admin/item", json={"title": "Bad", "dates": "13-40"})
    assert r.status_code == 400
    r = attorney_session.post("/portal/attorney/firm-admin/complete", json={"id": "nope", "due": "2026-01-15"})
    assert r.status_code == 400


def test_routes_need_an_attorney(client_session):
    assert client_session.get("/portal/attorney/firm-admin").status_code in (302, 401, 403)


# ── Assistant ────────────────────────────────────────────────────────────────

def test_assistant_tools(fixed_today):
    assert '"estimated_tax"' in tools.get_firm_admin("Endocide")
    o, summary = tools._prep_admin_done("Endocide", {"item": "estimated", "amount": "$2,000"})
    assert o["id"] == "estimated_tax" and "2026-01-15" in summary and "$2,000" in summary
    out = tools._run_admin_done("Endocide", {"item": "estimated_tax", "confirmation": "X1"})
    assert "Recorded" in out and "2026-01-15" in out
    with pytest.raises(tools.ToolError):
        tools._prep_admin_done("Endocide", {"item": "bpr"})          # no due date set yet
    with pytest.raises(tools.ToolError):
        tools._prep_admin_done("Endocide", {"item": "zzz"})
    assert "firm_admin_due" in tools.get_attention_items("Endocide")
