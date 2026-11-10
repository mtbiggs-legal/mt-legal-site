"""Flat-fee billing: the fee is owed instead of hours, time logged under it is
tracked privately and never billed, and payments count toward it."""

import pytest

from services import billing, storage
from services import assistant_tools as tools


def _entry(hours, note="work", date="2026-11-01"):
    return {"date": date, "hours": hours, "note": note, "category": "Other"}


def _log_time(username, hours, note="flat work"):
    def mutate(c):
        c["billing_log"].append(_entry(hours, note))
        storage.recalc_hours(c)
    return storage.update_client_atomic(username, mutate)


def _summary(username):
    return billing.billing_summary(storage.load_client(username), billing.load_ledger(username))


def test_flat_fee_is_owed_and_reported(make_client):
    make_client("ff")
    billing.set_flat_fee("ff", 2500, "full", "2026-12-01", "DUI 1st", set_by="Endocide")
    s = _summary("ff")
    f = s["flat_fee"]
    assert s["amount_due"] == 2500.0
    assert (f["amount"], f["plan"], f["paid"], f["remaining"], f["status"]) == (2500.0, "full", 0, 2500.0, "unpaid")
    assert f["due_date"] == "2026-12-01" and f["description"] == "DUI 1st"
    assert f["tracked_hours"] == 0 and f["effective_rate"] is None


def test_time_under_flat_fee_is_private_and_never_billed(make_client):
    make_client("ff", billing_log=[_entry(1.0, "before")], hours_billed=1.0)
    assert billing.issue_statement("ff", reason="manual", issued_by="x", notify=False)["hours"] == 1.0
    billing.set_flat_fee("ff", 1500, "full")
    _log_time("ff", 2.0)
    log = storage.load_client("ff")["billing_log"]
    assert "billable" not in log[0]                  # already-billed time stays billed
    assert log[1]["billable"] is False
    assert billing.issue_statement("ff", reason="manual", issued_by="x", notify=False) is None
    f = _summary("ff")["flat_fee"]
    assert f["tracked_hours"] == 2.0 and f["effective_rate"] == 750.0
    # The client never sees private time.
    view = billing.client_billing_view(storage.load_client("ff"), billing.load_ledger("ff"))
    assert [e["note"] for e in view["entries"]] == ["before"]
    assert "tracked_hours" not in view["flat_fee"] and "effective_rate" not in view["flat_fee"]


def test_unbilled_time_is_folded_into_the_flat_fee(make_client):
    make_client("ff", billing_log=[_entry(1.0, "billed"), _entry(0.5, "billed too")], hours_billed=1.5)
    billing.issue_statement("ff", reason="manual", issued_by="x", notify=False)
    storage.update_client_atomic("ff", lambda c: c["billing_log"].append(_entry(0.5, "unbilled")))
    billing.set_flat_fee("ff", 1000, "full")
    log = storage.load_client("ff")["billing_log"]
    assert [e.get("billable") for e in log] == [None, None, False]
    s = _summary("ff")
    assert s["unbilled_hours"] == 0 and s["flat_fee"]["tracked_hours"] == 0.5


def test_threshold_statement_ignores_private_time(make_client, monkeypatch):
    monkeypatch.setattr(billing, "get_threshold", lambda _a: 100.0)
    make_client("ff")
    billing.set_flat_fee("ff", 1500, "full")
    _log_time("ff", 5.0)                             # $1,750 of time, but private
    assert billing.load_ledger("ff")["statements"] == []


def test_half_plan_payments_and_overdue(make_client):
    make_client("ff")
    billing.set_flat_fee("ff", 3000, "half", "2026-01-15")
    storage._apply_payment("ff", 1500.0, "check", "1001")
    f = billing.flat_fee_status(storage.load_client("ff"), billing.load_ledger("ff"), today="2026-01-10")
    assert (f["first_payment"], f["paid"], f["remaining"], f["status"], f["overdue"]) == (1500.0, 1500.0, 1500.0, "half_paid", False)
    f = billing.flat_fee_status(storage.load_client("ff"), billing.load_ledger("ff"), today="2026-02-01")
    assert f["overdue"] is True
    storage._apply_payment("ff", 1500.0, "cash", "cash-1")
    f = billing.flat_fee_status(storage.load_client("ff"), billing.load_ledger("ff"))
    assert (f["status"], f["remaining"], f["overdue"]) == ("paid", 0, False)
    assert _summary("ff")["amount_due"] == 0


def test_payments_go_to_statements_first(make_client):
    make_client("ff", billing_log=[_entry(2.0)], hours_billed=2.0)    # $700 at the test rate
    billing.issue_statement("ff", reason="manual", issued_by="x", notify=False)
    billing.set_flat_fee("ff", 1000, "full")
    storage._apply_payment("ff", 900.0, "check", "1")
    f = _summary("ff")["flat_fee"]
    assert (f["paid"], f["remaining"]) == (200.0, 800.0)
    assert _summary("ff")["amount_due"] == 800.0


def test_back_to_hourly_keeps_private_time_private(make_client):
    make_client("ff")
    billing.set_flat_fee("ff", 1000, "full")
    _log_time("ff", 1.0, "flat")
    billing.clear_flat_fee("ff")
    _log_time("ff", 2.0, "hourly")
    log = storage.load_client("ff")["billing_log"]
    assert log[0]["billable"] is False and "billable" not in log[1]
    assert _summary("ff")["flat_fee"] is None
    assert billing.issue_statement("ff", reason="manual", issued_by="x", notify=False)["hours"] == 2.0


def test_changing_the_fee_keeps_its_start(make_client):
    make_client("ff", billing_log=[_entry(1.0)])
    billing.issue_statement("ff", reason="manual", issued_by="x", notify=False)
    billing.set_flat_fee("ff", 1000, "full")
    billing.set_flat_fee("ff", 1200, "half", "2026-12-01")
    fee = storage.load_client("ff")["flat_fee"]
    assert (fee["amount"], fee["plan"], fee["from_entry"]) == (1200.0, "half", 1)


@pytest.mark.parametrize("amount,plan,due", [
    (0, "full", ""), (-5, "full", ""), ("abc", "full", ""), (float("nan"), "full", ""),
    (200_000, "full", ""), (500, "monthly", ""), (500, "full", "12/01/2026"),
])
def test_set_flat_fee_rejects_bad_input(make_client, amount, plan, due):
    make_client("ff")
    with pytest.raises(ValueError):
        billing.set_flat_fee("ff", amount, plan, due)


# ── Routes ───────────────────────────────────────────────────────────────────

def test_flat_fee_route_set_and_remove(attorney_session, make_client):
    make_client("testclient")
    r = attorney_session.post("/portal/attorney/flat-fee", json={
        "username": "testclient", "amount": 2000, "plan": "half", "due_date": "2026-12-15"})
    d = r.get_json()
    assert r.status_code == 200 and d["success"]
    assert d["billing_summary"]["flat_fee"]["first_payment"] == 1000.0
    r = attorney_session.post("/portal/attorney/flat-fee", json={"username": "testclient", "amount": -1, "plan": "full"})
    assert r.status_code == 400 and "error" in r.get_json()
    r = attorney_session.post("/portal/attorney/flat-fee", json={"username": "testclient", "action": "remove"})
    assert r.get_json()["billing_summary"]["flat_fee"] is None


def test_flat_fee_route_denies_unassigned_attorney(other_attorney_session, make_client):
    make_client("testclient")
    r = other_attorney_session.post("/portal/attorney/flat-fee", json={
        "username": "testclient", "amount": 2000, "plan": "full"})
    assert r.status_code == 404
    assert "flat_fee" not in storage.load_client("testclient")


def test_record_payment_route(attorney_session, make_client):
    make_client("testclient")
    billing.set_flat_fee("testclient", 1000, "full")
    r = attorney_session.post("/portal/attorney/record-payment", json={
        "username": "testclient", "amount": 400, "method": "check", "reference": "1042"})
    d = r.get_json()
    assert d["success"] and d["billing_summary"]["flat_fee"]["remaining"] == 600.0
    # Same reference twice is refused; bad amount and method are refused.
    r = attorney_session.post("/portal/attorney/record-payment", json={
        "username": "testclient", "amount": 400, "method": "check", "reference": "1042"})
    assert r.status_code == 400
    for body in ({"amount": 0}, {"amount": "x"}, {"amount": 10, "method": "bitcoin"}):
        r = attorney_session.post("/portal/attorney/record-payment", json={"username": "testclient", **body})
        assert r.status_code == 400


def test_client_portal_shows_flat_fee_not_private_time(client_session, make_client):
    make_client("testclient")
    billing.set_flat_fee("testclient", 1500, "full", description="Simple possession")
    _log_time("testclient", 3.0, "secret prep")
    d = client_session.get("/portal/client/billing").get_json()
    assert d["flat_fee"]["remaining"] == 1500.0 and d["amount_due"] == 1500.0
    assert d["entries"] == []
    html = client_session.get("/client-portal").get_data(as_text=True)
    assert "Fee Balance" in html and "$1500.00" in html
    assert "billed at 0.1 hrs per message" not in html
    assert "secret prep" not in html
    s = client_session.get("/portal/client/summary").get_json()
    assert s["flat_fee"]["remaining"] == 1500.0


# ── Assistant ────────────────────────────────────────────────────────────────

def test_assistant_set_flat_fee_tool(make_client):
    make_client("testclient", client_name="Test Client")
    _, _, summary = tools._prep_flat_fee("Endocide", {"client": "testclient", "amount": 2500, "plan": "half",
                                                      "due_date": "2026-12-01"})
    assert "$2,500.00 flat fee" in summary and "half up front" in summary
    out = tools._run_flat_fee("Endocide", {"client": "testclient", "amount": 2500, "plan": "half",
                                           "due_date": "2026-12-01"})
    assert "flat fee" in out
    assert storage.load_client("testclient")["flat_fee"]["amount"] == 2500.0
    with pytest.raises(tools.ToolError):
        tools._prep_flat_fee("Endocide", {"client": "testclient", "amount": 100, "plan": "weekly"})
    tools._run_flat_fee("Endocide", {"client": "testclient", "remove": True})
    assert "flat_fee" not in storage.load_client("testclient")
