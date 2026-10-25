"""Opening-statement migration and rollout guard (spec D)."""

import json
import sys
from pathlib import Path

import pytest

import billing
import shared

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _seed(make_client, username, hours, payments=()):
    make_client(username, billing_log=[{"date": "2026-09-01", "hours": h, "note": "old"} for h in hours],
                hours_billed=round(sum(hours), 2),
                hours_paid=round(sum(payments) / 350.0, 2),     # as _apply_payment keeps it
                payments=[{"amount": a} for a in payments])


def test_migration_issues_silent_opening_statements(make_client, tmp_path, monkeypatch, sent_statement_emails):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _seed(make_client, "m1", (3.0, 4.0), payments=(350.0,))     # 7 hrs billed
    _seed(make_client, "m2", (0.0,))                             # notes only
    _seed(make_client, "m3", ())
    counts = mig.migrate(tmp_path / "bk", project_root=tmp_path / "project")
    assert counts == {"opening": 1, "baseline": 1, "covered": 1, "unreadable": 0, "skipped": 0}
    st = billing.load_ledger("m1")["statements"][0]
    assert (st["reason"], st["notice"]["status"], st["amount"]) == ("opening", "skipped", 2450.0)
    assert billing.load_ledger("m2")["covered_through"] == 1
    assert sent_statement_emails == []
    assert billing.is_migrated()
    c = shared.load_client("m1")
    due = billing.amount_due(c, billing.load_ledger("m1"))
    assert due == round(7.0 * 350.0, 2) - 350.0
    legacy = round(round(c["hours_billed"] - c["hours_paid"], 2) * 350.0, 2)
    assert abs(due - legacy) < 1.0
    assert mig.LAST_BACKUP is not None and mig.LAST_BACKUP.exists()
    assert mig.migrate(tmp_path / "bk", project_root=tmp_path / "project") ==         {"opening": 0, "baseline": 0, "covered": 3, "unreadable": 0, "skipped": 0}


def test_migration_refuses_backup_inside_project(make_client, tmp_path):
    import issue_opening_statements as mig
    project = tmp_path / "project"; project.mkdir()
    with pytest.raises(SystemExit):
        mig.migrate(project / "bk", project_root=project)


def test_startup_blocks_until_migrated(make_client, monkeypatch):
    import app as app_module
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(shared, "_fernet_cache", None)
    shared.save_client({"username": "sx"})
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    assert any("Opening statements" in p for p in app_module.check_startup_config())
    billing.mark_migrated()
    assert not any("Opening statements" in p for p in app_module.check_startup_config())


def test_fresh_install_auto_marks(monkeypatch):
    import app as app_module
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(shared, "_fernet_cache", None)
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    assert app_module.check_startup_config() == []
    assert billing.is_migrated()


def _tree(*dirs):
    snap = {}
    for d in dirs:
        for f in Path(d).rglob("*"):
            if f.is_file():
                snap[str(f)] = (f.stat().st_size, f.stat().st_mtime_ns, f.read_bytes())
    return snap


def test_corrupt_record_blocks_marking_but_migrates_others(make_client, tmp_path, monkeypatch):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _seed(make_client, "good", (2.0,))
    (shared.CLIENT_ACCOUNTS_DIR / "bad.json").write_bytes(b"\x00\xffgarbage")
    counts = mig.migrate(tmp_path / "bk", project_root=tmp_path / "project")
    assert counts["unreadable"] == 1 and counts["opening"] == 1
    assert not billing.is_migrated()
    assert len(billing.load_ledger("good")["statements"]) == 1


def test_unsafe_filename_counted_as_skipped(make_client, tmp_path, monkeypatch):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    (shared.CLIENT_ACCOUNTS_DIR / "bad name!.json").write_text("{}")
    counts = mig.migrate(tmp_path / "bk", project_root=tmp_path / "project")
    assert counts["skipped"] == 1 and not billing.is_migrated()
    assert any(r[0] == "bad name!" and r[4] == "skipped" for r in mig.LAST_REPORT)


def test_backup_includes_firm_settings(make_client, tmp_path):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "marker.json").write_text("{}")
    mig.migrate(tmp_path / "bk", project_root=tmp_path / "project")
    assert (mig.LAST_BACKUP / "firm-settings" / "marker.json").exists()
    assert (mig.LAST_BACKUP / "firm-settings" / "migrations.json").exists()


def test_nan_hours_not_issued_and_unreadable(make_client, tmp_path, monkeypatch, capsys):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    make_client("nanc", billing_log=[{"date": "2026-09-01", "hours": "nan", "note": "x"}])
    assert billing.issue_statement("nanc", reason="manual", issued_by="a", notify=False) is None
    assert "nanc" in capsys.readouterr().err
    counts = mig.migrate(tmp_path / "bk", project_root=tmp_path / "project")
    assert counts["unreadable"] == 1 and counts["opening"] == 0
    assert not billing.is_migrated()


def test_dry_run_changes_nothing_and_reports(make_client, tmp_path, monkeypatch):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _seed(make_client, "d1", (3.0, 4.0), payments=(350.0,))
    _seed(make_client, "d2", (0.0,))
    _seed(make_client, "d3", ())
    dirs = (shared.CLIENT_ACCOUNTS_DIR, shared.CLIENT_BILLING_DIR, shared.FIRM_SETTINGS_DIR)
    before = _tree(*dirs)
    counts = mig.migrate(None, dry_run=True)
    assert counts == {"opening": 1, "baseline": 1, "covered": 1, "unreadable": 0, "skipped": 0}
    assert _tree(*dirs) == before
    assert not billing.is_migrated() and mig.LAST_BACKUP is None
    rows = {r[0]: r for r in mig.LAST_REPORT}
    assert rows["d1"] == ("d1", 2100.0, 2100.0, 0.0, "opening")
    assert rows["d2"][4] == "baseline" and rows["d3"][4] == "covered"


def _run_main(mig, monkeypatch, capsys, *argv):
    monkeypatch.setattr(mig, "load_dotenv", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(sys, "argv", ["issue_opening_statements.py", *argv])
    code = mig.main()
    return code, capsys.readouterr().out


def test_main_exit_codes(make_client, tmp_path, monkeypatch, capsys):
    import issue_opening_statements as mig
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _seed(make_client, "ok1", (2.0,))
    code, out = _run_main(mig, monkeypatch, capsys, "--backup-dir", str(tmp_path / "bk1"))
    assert code == 0 and "Backup written to" in out

    (shared.CLIENT_ACCOUNTS_DIR / "bad.json").write_bytes(b"\x00garbage")
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    code, out = _run_main(mig, monkeypatch, capsys, "--backup-dir", str(tmp_path / "bk2"))
    assert code == 1 and "Migration NOT marked complete" in out
    assert not billing.is_migrated()

    def boom():
        raise RuntimeError("bad key")
    monkeypatch.setattr(shared, "_fernet", boom)
    code, out = _run_main(mig, monkeypatch, capsys, "--backup-dir", str(tmp_path / "bk3"))
    assert code == 2 and "bad key" in out


def test_main_dry_run_needs_no_backup_dir_and_flags_deltas(make_client, tmp_path, monkeypatch, capsys):
    import issue_opening_statements as mig
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    # legacy 3h*350=1050 owed; new = 3*350 - 0 = 1050 -> no flag. Add a payment mismatch:
    _seed(make_client, "f1", (3.0,))
    make_client("f2", billing_log=[{"date": "2026-09-01", "hours": 2.0, "note": "n"}],
                hours_billed=1.0, hours_paid=0, payments=[])   # legacy 350 vs new 700
    code, out = _run_main(mig, monkeypatch, capsys, "--dry-run")
    assert code == 0 and "<-- CHECK" in out and "f2" in out
    assert out.count("<-- CHECK") == 1
    assert mig.LAST_BACKUP is None


def test_attorney_client_list_shows_statement_amount_due(attorney_session, make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _seed(make_client, "lst", (2.0,))
    billing.issue_statement("lst", reason="manual", issued_by="a", notify=False)
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert "700.00" in html
