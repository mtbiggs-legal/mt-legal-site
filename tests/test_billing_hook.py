"""after_client_save issues threshold statements on every save path (spec B2)."""

import billing
import shared


def _over(make_client, username="hk", **kw):
    # 6 hrs * $350 = $2,100 >= $2,000
    return make_client(username, billing_log=[{"date": "2026-10-01", "hours": 6.0, "note": "x"}],
                       hours_billed=6.0, **kw)


def test_save_issues_statement_when_over(make_client, sent_statement_emails, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    shared.save_client(_over(make_client, email="hk@example.com"))
    led = billing.load_ledger("hk")
    assert len(led["statements"]) == 1 and led["statements"][0]["reason"] == "threshold"
    assert led["statements"][0]["notice"]["status"] == "sent"
    assert len(sent_statement_emails) == 1


def test_save_without_email_marks_no_email(make_client, sent_statement_emails, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    shared.save_client(_over(make_client))
    assert billing.load_ledger("hk")["statements"][0]["notice"]["status"] == "no_email"
    assert sent_statement_emails == []


def test_no_statement_under_threshold(make_client):
    rec = make_client("hk", billing_log=[{"date": "d", "hours": 1.0, "note": "x"}], hours_billed=1.0)
    shared.save_client(rec)
    assert billing.load_ledger("hk")["statements"] == []


def test_inert_until_migrated(make_client):
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    shared.save_client(_over(make_client))
    assert billing.load_ledger("hk")["statements"] == []


def test_hook_errors_never_fail_save(make_client, monkeypatch, capsys):
    monkeypatch.setattr(billing, "issue_statement",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    shared.save_client(_over(make_client))          # must not raise
    assert "boom" in capsys.readouterr().err


def test_attorney_billing_entry_path(attorney_session, make_client):
    make_client("hk")
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "hk", "note": "trial prep", "hours": 6})
    assert r.status_code == 200
    assert len(billing.load_ledger("hk")["statements"]) == 1


def test_create_client_path_builds_log_inline(attorney_session):
    # create-client builds billing_log inline (no recalc_hours); still hooked via save_client.
    r = attorney_session.post("/portal/attorney/create-client",
                              json={"username": "newc", "client_name": "New C"})
    assert r.status_code == 200 and shared.load_client("newc") is not None
    assert billing.load_ledger("newc")["statements"] == []   # 0.2 hrs: under threshold, no crash


def test_fingerprint_mismatch_warns(make_client, capsys):
    rec = make_client("hk", billing_log=[{"date": "d", "hours": 1.0, "note": "a"}], hours_billed=1.0)
    billing.issue_statement("hk", reason="manual", issued_by="x", notify=False)
    rec["billing_log"] = [{"date": "d", "hours": 9.0, "note": "different"}]
    shared.save_client(rec)
    assert "fingerprint" in capsys.readouterr().err


def test_update_client_field_atomic(make_client):
    make_client("hk")
    path = shared.CLIENT_ACCOUNTS_DIR / "hk.json"
    # A concurrent writer changes another field first; the atomic update keeps it.
    rec = shared._read_record(path)
    rec["client_name"] = "Changed Elsewhere"
    shared._write_record(path, rec)
    shared.update_client_field_atomic("hk", "billing_seen_at", "2026-10-02T00:00:00")
    got = shared._read_record(path)
    assert got["billing_seen_at"] == "2026-10-02T00:00:00"
    assert got["client_name"] == "Changed Elsewhere"


def test_update_client_field_atomic_unsafe_or_missing(make_client):
    shared.update_client_field_atomic("../evil", "x", 1)       # no-op, no raise
    shared.update_client_field_atomic("", "x", 1)
    shared.update_client_field_atomic("nobody", "x", 1)
    assert not (shared.CLIENT_ACCOUNTS_DIR / "nobody.json").exists()
