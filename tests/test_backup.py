"""scripts/backup_data.py: encrypted round trip, refuses unsafe targets."""

import importlib.util
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import shared

_spec = importlib.util.spec_from_file_location(
    "backup_data", Path(__file__).parent.parent / "scripts" / "backup_data.py")
backup_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup_data)


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    root = tmp_path / "data"
    (root / "client-accounts").mkdir(parents=True)
    (root / "client-accounts" / "c1.json").write_bytes(b"record")
    monkeypatch.setattr(shared, "DATA_ROOT", root)
    monkeypatch.setattr(shared, "DB_PATH", root / "db" / "mt-legal.db")
    from conftest import put_record
    put_record({"username": "dbclient", "client_name": "In The DB"})
    bak = backup_data.create(tmp_path / "out")
    assert b"record" not in bak.read_bytes()
    n = backup_data.restore(bak, tmp_path / "restored")
    assert n == 2 and (tmp_path / "restored" / "client-accounts" / "c1.json").read_bytes() == b"record"
    import sqlite3
    rows = sqlite3.connect(str(tmp_path / "restored" / "db" / "mt-legal.db")).execute(
        "SELECT username FROM clients").fetchall()
    assert rows == [("dbclient",)]


def test_backup_must_live_outside_project(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(SystemExit):
        backup_data.create(shared.BASE_DIR / "backups")


def test_needs_its_own_key(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    with pytest.raises(SystemExit):
        backup_data.create(tmp_path / "out")
