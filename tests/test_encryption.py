"""Client account records are encrypted at rest (spec section C)."""

import json
import os
import re
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import shared
from conftest import access_log, get_record, put_raw
from services import storage
from services import accounts

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _accounts(tmp_path):
    return tmp_path / "accounts"


def test_save_client_writes_ciphertext(tmp_path):
    from services import db
    storage.save_client({"username": "encU", "client_name": "Secret Name"})
    raw = bytes(db.conn().execute("SELECT data FROM clients WHERE username='encU'").fetchone()[0])
    assert not raw.lstrip().startswith(b"{")
    assert b"Secret Name" not in raw


def test_round_trip(tmp_path):
    storage.save_client({"username": "encU", "client_name": "Ann", "billing_log": [{"hours": 1}]})
    loaded = storage.load_client("encU")
    assert loaded["client_name"] == "Ann"
    assert loaded["billing_log"] == [{"hours": 1}]


def test_plaintext_records_still_readable(make_client):
    make_client("plainU", client_name="Legacy Person")
    assert storage.load_client("plainU")["client_name"] == "Legacy Person"


def test_all_clients_reads_both_formats(make_client):
    make_client("plainU")
    storage.save_client({"username": "encU", "client_name": "Enc"})
    names = {c["username"] for c in storage.all_clients()}
    assert {"plainU", "encU"} <= names


def test_wrong_key_raises_record_decrypt_error(tmp_path):
    other = Fernet(Fernet.generate_key())
    put_raw("badU", other.encrypt(b'{"username": "badU"}'))
    with pytest.raises(storage.RecordDecryptError):
        storage.load_client("badU")


def test_all_clients_skips_undecryptable(tmp_path, capsys):
    other = Fernet(Fernet.generate_key())
    put_raw("badU", other.encrypt(b'{"username": "badU"}'))
    storage.save_client({"username": "goodU"})
    assert [c["username"] for c in storage.all_clients()] == ["goodU"]
    assert "badU" in capsys.readouterr().err


def test_load_client_defaults_new_fields(make_client):
    make_client("plainU")
    c = storage.load_client("plainU")
    for field in ("co_counsel", "access_log", "opposing_parties",
                  "related_parties", "conflict_checks"):
        assert c[field] == []


def test_no_direct_account_file_io():
    """Account files must only be touched through _read_record/_write_record."""
    root = Path(__file__).parent.parent
    files = [*root.glob("*.py"), *(root / "blueprints").glob("*.py"),
             *(root / "scripts").glob("*.py")]
    io_call = re.compile(r"\bopen\(|read_text\(|read_bytes\(|write_text\(|json\.load\(")
    offenders = []
    for py in files:
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "CLIENT_ACCOUNTS_DIR" in line and io_call.search(line):
                offenders.append(f"{py.name}:{n}: {line.strip()}")
    assert not offenders, "Direct account-file I/O:\n" + "\n".join(offenders)


def test_upgrade_all_plaintext_passwords(make_client):
    make_client("plainPw", password="password")
    make_client("hashedPw", password=accounts.hash_password("already-hashed"))
    make_client("noPw")

    assert accounts.upgrade_all_plaintext_passwords(apply=False) == ["plainPw"]
    assert storage.load_client("plainPw")["password"] == "password"  # dry run

    assert accounts.upgrade_all_plaintext_passwords() == ["plainPw"]
    c = storage.load_client("plainPw")
    assert c["password"].startswith("$2")
    assert accounts.check_password("password", c["password"])
    assert c["must_change_password"] is True
    assert accounts.upgrade_all_plaintext_passwords() == []


def _seed_plain(tmp_path, name, **fields):
    p = _accounts(tmp_path) / f"{name}.json"
    p.write_text(json.dumps({"username": name, **fields}), encoding="utf-8")
    return p








def test_scripts_compile():
    import py_compile
    for script in (Path(__file__).parent.parent / "scripts").glob("*.py"):
        py_compile.compile(str(script), doraise=True)


# ── review fixes ─────────────────────────────────────────────────────────────

def _seed_bom(tmp_path, name, **fields):
    p = _accounts(tmp_path) / f"{name}.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"username": name, **fields}).encode("utf-8"))
    return p


def test_migration_reads_bom_plaintext_and_encrypted_files(tmp_path):
    import migrate_to_db as mig
    _seed_bom(tmp_path, "bomU", client_name="Bom",
              access_log=[{"timestamp": "2026-01-02T03:04:05", "attorney": "Endocide",
                           "action": "view_record", "detail": "", "ip": "1.2.3.4"}])
    storage._write_record(_accounts(tmp_path) / "encU.json", {"username": "encU", "client_name": "E"})
    (_accounts(tmp_path) / "skip.json").write_text("{not json", encoding="utf-8")
    report = mig.migrate(apply=True, backup_dir=tmp_path / "bk")
    assert report["unreadable"] == ["skip.json"] and report["imported"] == 0   # nothing moved
    (_accounts(tmp_path) / "skip.json").unlink()
    report = mig.migrate(apply=True, backup_dir=tmp_path / "bk")
    assert report["imported"] == 2 and report["audit"] == 1
    assert storage.load_client("bomU")["client_name"] == "Bom"
    assert "access_log" not in get_record("bomU")
    assert access_log("bomU")[0]["ip"] == "1.2.3.4"
    assert not list(_accounts(tmp_path).glob("*.json"))                    # originals moved
    assert len(list(Path(report["backup"]).glob("*.json"))) == 2


def test_migration_refuses_backup_inside_project(tmp_path):
    import migrate_to_db as mig
    _seed_plain(tmp_path, "a1")
    with pytest.raises(SystemExit):
        mig.migrate(apply=True, backup_dir=shared.BASE_DIR / "backups")




def test_require_outside_dir(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(SystemExit):
        storage.require_outside_dir(project / "x", project)
    storage.require_outside_dir(tmp_path / "elsewhere", project)


def test_upgrade_reports_skipped(tmp_path):
    other = Fernet(Fernet.generate_key())
    put_raw("badU", other.encrypt(b'{"username": "badU"}'))
    skipped = []
    assert accounts.upgrade_all_plaintext_passwords(apply=False, skipped=skipped) == []
    assert skipped == ["badU"]




def test_malformed_key_raises_runtime_error(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "not-a-key")
    monkeypatch.setattr(storage, "_fernet_cache", None)
    with pytest.raises(RuntimeError, match="malformed"):
        storage._fernet()


def test_write_record_retries_permission_error(tmp_path, monkeypatch):
    real = os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("locked")
        return real(a, b)

    monkeypatch.setattr(storage.os, "replace", flaky)
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    path = _accounts(tmp_path) / "retryU.json"
    storage._write_record(path, {"username": "retryU"})
    assert storage._read_record(path)["username"] == "retryU"
    assert not list(_accounts(tmp_path).glob("*.tmp"))


def test_write_record_gives_up_and_cleans_tmp(tmp_path, monkeypatch):
    def always(a, b):
        raise PermissionError("locked")

    monkeypatch.setattr(storage.os, "replace", always)
    monkeypatch.setattr(storage.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        storage._write_record(_accounts(tmp_path) / "x.json", {"username": "x"})
    assert not list(_accounts(tmp_path).glob("*.tmp"))


def test_migration_stops_on_readback_mismatch(tmp_path, monkeypatch):
    import migrate_to_db as mig
    _seed_plain(tmp_path, "a1", client_name="A")
    monkeypatch.setattr(storage, "_db_get", lambda c, u: {"username": "different"})
    with pytest.raises(SystemExit):
        mig.migrate(apply=True, backup_dir=tmp_path / "bk")
    assert (_accounts(tmp_path) / "a1.json").exists()          # original kept


def test_upgrade_skips_malformed_record(tmp_path, make_client):
    make_client("goodPw", password="password")
    put_raw("broken", b"{not json")
    skipped = []
    assert accounts.upgrade_all_plaintext_passwords(skipped=skipped) == ["goodPw"]
    assert skipped == ["broken"]
    assert storage.load_client("goodPw")["password"].startswith("$2")


def test_concurrent_atomic_updates_lose_nothing(make_client):
    """Many threads appending to one record through update_client_atomic: the
    database transaction must keep every append."""
    import threading
    make_client("busy")
    errors = []

    def worker(i):
        try:
            for j in range(5):
                storage.update_client_atomic("busy", lambda c: c.setdefault("notes", []).append(f"{i}-{j}"))
        except Exception as exc:          # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(storage.load_client("busy")["notes"]) == 40


def test_migration_with_bad_backup_location_changes_nothing(tmp_path, monkeypatch):
    import migrate_to_db as mig
    _seed_plain(tmp_path, "a1", client_name="A")
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")                        # a file where the backup folder would go
    with pytest.raises(SystemExit):
        mig.migrate(apply=True, backup_dir=blocker / "backups")
    assert (_accounts(tmp_path) / "a1.json").exists()
    assert storage.all_usernames() == []          # nothing imported
