"""Statement issuing and the ledger (spec A1–A2, B1, B4)."""

from services import billing
import shared
from services import storage


def _entry(hours, date="2026-10-01", note="work"):
    return {"date": date, "hours": hours, "note": note, "category": "Other"}


def _client(make_client, username="bc", hours=(), **extra):
    log = [_entry(h) for h in hours]
    return make_client(username, billing_log=log,
                       hours_billed=round(sum(hours), 2), **extra)


def test_empty_ledger_for_new_client(make_client):
    _client(make_client)
    led = billing.load_ledger("bc")
    assert led == {"covered_through": 0, "covered_fingerprint": None, "statements": []}


def test_manual_issue_covers_all_unbilled(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _client(make_client, hours=(1.0, 0.0, 2.5))
    st = billing.issue_statement("bc", reason="manual", issued_by="Endocide", notify=False)
    assert (st["number"], st["id"], st["hours"], st["rate"], st["amount"]) == (1, "st_1", 3.5, 350.0, 1225.0)
    assert (st["entries_from"], st["entries_to"]) == (0, 3)
    assert st["notice"]["status"] == "skipped"
    led = billing.load_ledger("bc")
    assert led["covered_through"] == 3 and led["covered_fingerprint"][1] == 2.5


def test_no_statement_when_nothing_or_nonpositive(make_client):
    _client(make_client, hours=(0.0,))
    assert billing.issue_statement("bc", reason="manual", issued_by="x", notify=False) is None
    _client(make_client, "bc2", hours=(1.0, -1.0))
    assert billing.issue_statement("bc2", reason="manual", issued_by="x", notify=False) is None
    assert billing.load_ledger("bc2")["covered_through"] == 0


def test_threshold_only_issue(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 100.0)
    _client(make_client, hours=(19.99,))                       # $1,999
    assert billing.issue_statement("bc", reason="threshold", issued_by="system",
                                   notify=True, only_if_over_threshold=True) is None
    _client(make_client, "bc2", hours=(20.0,))                 # exactly $2,000
    st = billing.issue_statement("bc2", reason="threshold", issued_by="system",
                                 notify=True, only_if_over_threshold=True)
    assert st and st["notice"]["status"] == "pending"


def test_uses_assigned_attorneys_threshold(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 100.0)
    billing.set_threshold("SophiaH", 500)
    _client(make_client, hours=(6.0,), assigned_attorney="SophiaH")
    assert billing.issue_statement("bc", reason="threshold", issued_by="system",
                                   notify=False, only_if_over_threshold=True)


def test_numbering_and_second_statement(make_client):
    rec = _client(make_client, hours=(1.0,))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c = storage.load_client("bc")
    c["billing_log"].append(_entry(2.0, "2026-10-05"))
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "bc.json", c)   # avoid the save hook
    st2 = billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    assert (st2["number"], st2["entries_from"], st2["entries_to"], st2["billed_through"]) == (2, 1, 2, "2026-10-05")


def test_amount_due_never_negative(make_client):
    _client(make_client, hours=(1.0,), payments=[{"amount": 99999.0}])
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c, led = storage.load_client("bc"), billing.load_ledger("bc")
    assert billing.amount_due(c, led) == 0.0


def test_shortened_billing_log_does_not_crash(make_client):
    _client(make_client, hours=(1.0, 1.0))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c = storage.load_client("bc"); c["billing_log"] = c["billing_log"][:1]
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "bc.json", c)
    led = billing.load_ledger("bc")
    assert billing.unbilled_entries(c, led) == []
    assert billing.issue_statement("bc", reason="manual", issued_by="x", notify=False) is None


def test_stale_client_save_cannot_remove_statement(make_client):
    _client(make_client, hours=(1.0,))
    stale = storage.load_client("bc")
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    storage.save_client(stale)
    assert len(billing.load_ledger("bc")["statements"]) == 1


def test_ledger_is_encrypted(make_client):
    _client(make_client, hours=(1.0,))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    raw = (shared.CLIENT_BILLING_DIR / "bc.json").read_bytes()
    assert not storage._is_plaintext(raw)


def test_set_baseline(make_client):
    _client(make_client, hours=(0.0, 0.0))
    assert billing.set_baseline("bc") is True
    assert billing.load_ledger("bc")["covered_through"] == 2
    assert billing.set_baseline("bc") is False


def test_client_view_hides_unbilled(make_client):
    _client(make_client, hours=(1.0, 2.0))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c = storage.load_client("bc"); c["billing_log"].append(_entry(5.0, note="SECRET unbilled"))
    storage._write_record(shared.CLIENT_ACCOUNTS_DIR / "bc.json", c)
    view = billing.client_billing_view(storage.load_client("bc"), billing.load_ledger("bc"))
    blob = repr(view)
    assert "SECRET" not in blob and "threshold" not in blob and "notice" not in blob
    assert [e["statement_number"] for e in view["entries"]] == [1, 1]
    assert sorted(e["amount"] for e in view["entries"]) == [350.0, 700.0]
    assert view["billed_hours"] == 3.0 and view["latest_billed_through"] == "2026-10-01"


def test_has_new_statement(make_client):
    _client(make_client, hours=(1.0,), billing_seen_at="")
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c, led = storage.load_client("bc"), billing.load_ledger("bc")
    assert billing.client_billing_view(c, led)["has_new_statement"] is True
    c["billing_seen_at"] = "9999-12-31T00:00:00"
    assert billing.client_billing_view(c, led)["has_new_statement"] is False


def test_billing_summary_fields(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 100.0)
    _client(make_client, hours=(3.0,))
    s = billing.billing_summary(storage.load_client("bc"), billing.load_ledger("bc"))
    assert (s["unbilled_hours"], s["unbilled_amount"], s["threshold"], s["amount_due"]) == (3.0, 300.0, 2000.0, 0.0)
