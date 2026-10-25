"""Client account records are encrypted at rest (spec section C)."""

import json
import re
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import shared

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _accounts(tmp_path):
    return tmp_path / "accounts"


def test_save_client_writes_ciphertext(tmp_path):
    shared.save_client({"username": "encU", "client_name": "Secret Name"})
    raw = (_accounts(tmp_path) / "encU.json").read_bytes()
    assert not raw.lstrip().startswith(b"{")
    assert b"Secret Name" not in raw


def test_round_trip(tmp_path):
    shared.save_client({"username": "encU", "client_name": "Ann", "billing_log": [{"hours": 1}]})
    loaded = shared.load_client("encU")
    assert loaded["client_name"] == "Ann"
    assert loaded["billing_log"] == [{"hours": 1}]


def test_plaintext_records_still_readable(make_client):
    make_client("plainU", client_name="Legacy Person")
    assert shared.load_client("plainU")["client_name"] == "Legacy Person"


def test_all_clients_reads_both_formats(make_client):
    make_client("plainU")
    shared.save_client({"username": "encU", "client_name": "Enc"})
    names = {c["username"] for c in shared.all_clients()}
    assert {"plainU", "encU"} <= names


def test_wrong_key_raises_record_decrypt_error(tmp_path):
    other = Fernet(Fernet.generate_key())
    (_accounts(tmp_path) / "badU.json").write_bytes(other.encrypt(b'{"username": "badU"}'))
    with pytest.raises(shared.RecordDecryptError):
        shared.load_client("badU")


def test_all_clients_skips_undecryptable(tmp_path, capsys):
    other = Fernet(Fernet.generate_key())
    (_accounts(tmp_path) / "badU.json").write_bytes(other.encrypt(b'{"username": "badU"}'))
    shared.save_client({"username": "goodU"})
    assert [c["username"] for c in shared.all_clients()] == ["goodU"]
    assert "badU" in capsys.readouterr().err


def test_load_client_defaults_new_fields(make_client):
    make_client("plainU")
    c = shared.load_client("plainU")
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
    make_client("hashedPw", password=shared.hash_password("already-hashed"))
    make_client("noPw")

    assert shared.upgrade_all_plaintext_passwords(apply=False) == ["plainPw"]
    assert shared.load_client("plainPw")["password"] == "password"  # dry run

    assert shared.upgrade_all_plaintext_passwords() == ["plainPw"]
    c = shared.load_client("plainPw")
    assert c["password"].startswith("$2")
    assert shared.check_password("password", c["password"])
    assert c["must_change_password"] is True
    assert shared.upgrade_all_plaintext_passwords() == []


def _seed_plain(tmp_path, name, **fields):
    p = _accounts(tmp_path) / f"{name}.json"
    p.write_text(json.dumps({"username": name, **fields}), encoding="utf-8")
    return p


def test_encrypt_all_backs_up_and_encrypts(tmp_path):
    import encrypt_existing_records as mig
    _seed_plain(tmp_path, "a1", client_name="A")
    shared.save_client({"username": "a2"})                 # already encrypted
    counts, backup = mig.encrypt_all(_accounts(tmp_path), tmp_path / "bk",
                                     project_root=tmp_path / "project")
    assert counts == {"encrypted": 1, "already": 1, "failed": 0}
    assert (backup / "a1.json").read_text().startswith("{")
    assert not (_accounts(tmp_path) / "a1.json").read_bytes().startswith(b"{")
    assert shared.load_client("a1")["client_name"] == "A"


def test_encrypt_all_is_idempotent(tmp_path):
    import encrypt_existing_records as mig
    _seed_plain(tmp_path, "a1")
    mig.encrypt_all(_accounts(tmp_path), tmp_path / "bk", project_root=tmp_path / "project")
    counts, _ = mig.encrypt_all(_accounts(tmp_path), tmp_path / "bk",
                                project_root=tmp_path / "project")
    assert counts == {"encrypted": 0, "already": 1, "failed": 0}


def test_encrypt_all_refuses_backup_inside_project(tmp_path):
    import encrypt_existing_records as mig
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(SystemExit):
        mig.encrypt_all(_accounts(tmp_path), project / "backups", project_root=project)


def test_scripts_compile():
    import py_compile
    for script in (Path(__file__).parent.parent / "scripts").glob("*.py"):
        py_compile.compile(str(script), doraise=True)


# ── review fixes ─────────────────────────────────────────────────────────────

def _seed_bom(tmp_path, name, **fields):
    p = _accounts(tmp_path) / f"{name}.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"username": name, **fields}).encode("utf-8"))
    return p


def test_bom_plaintext_loads(tmp_path):
    _seed_bom(tmp_path, "bomU", client_name="Bom")
    assert shared.load_client("bomU")["client_name"] == "Bom"


def test_encrypt_all_encrypts_bom_plaintext(tmp_path):
    import encrypt_existing_records as mig
    _seed_bom(tmp_path, "bomU", client_name="Bom")
    counts, _ = mig.encrypt_all(_accounts(tmp_path), tmp_path / "bk",
                                project_root=tmp_path / "project")
    assert counts == {"encrypted": 1, "already": 0, "failed": 0}
    assert shared.load_client("bomU")["client_name"] == "Bom"


def test_require_outside_dir(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(SystemExit):
        shared.require_outside_dir(project / "x", project)
    shared.require_outside_dir(tmp_path / "elsewhere", project)


def test_upgrade_reports_skipped(tmp_path):
    other = Fernet(Fernet.generate_key())
    (_accounts(tmp_path) / "badU.json").write_bytes(other.encrypt(b'{"username": "badU"}'))
    skipped = []
    assert shared.upgrade_all_plaintext_passwords(apply=False, skipped=skipped) == []
    assert skipped == ["badU"]


def test_encrypt_all_continues_after_bad_record(tmp_path):
    import encrypt_existing_records as mig
    _seed_plain(tmp_path, "a1", client_name="A")
    (_accounts(tmp_path) / "a0.json").write_text("{not json", encoding="utf-8")
    counts, _ = mig.encrypt_all(_accounts(tmp_path), tmp_path / "bk",
                                project_root=tmp_path / "project")
    assert counts == {"encrypted": 1, "already": 0, "failed": 1}
    assert (_accounts(tmp_path) / "a0.json").read_text() == "{not json"
    assert shared.load_client("a1")["client_name"] == "A"


def test_malformed_key_raises_runtime_error(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "not-a-key")
    monkeypatch.setattr(shared, "_fernet_cache", None)
    with pytest.raises(RuntimeError, match="malformed"):
        shared._fernet()


def test_write_record_retries_permission_error(tmp_path, monkeypatch):
    real = shared.os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("locked")
        return real(a, b)

    monkeypatch.setattr(shared.os, "replace", flaky)
    monkeypatch.setattr(shared.time, "sleep", lambda s: None)
    path = _accounts(tmp_path) / "retryU.json"
    shared._write_record(path, {"username": "retryU"})
    assert shared._read_record(path)["username"] == "retryU"
    assert not list(_accounts(tmp_path).glob("*.tmp"))


def test_write_record_gives_up_and_cleans_tmp(tmp_path, monkeypatch):
    def always(a, b):
        raise PermissionError("locked")

    monkeypatch.setattr(shared.os, "replace", always)
    monkeypatch.setattr(shared.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        shared._write_record(_accounts(tmp_path) / "x.json", {"username": "x"})
    assert not list(_accounts(tmp_path).glob("*.tmp"))


def test_encrypt_all_restores_on_roundtrip_mismatch(tmp_path, monkeypatch):
    import encrypt_existing_records as mig
    _seed_plain(tmp_path, "a1", client_name="A")
    monkeypatch.setattr(shared, "_read_record", lambda p: {"username": "different"})
    counts, backup = mig.encrypt_all(_accounts(tmp_path), tmp_path / "bk",
                                     project_root=tmp_path / "project")
    assert counts == {"encrypted": 0, "already": 0, "failed": 1}
    assert (_accounts(tmp_path) / "a1.json").read_bytes().startswith(b"{")


def test_upgrade_skips_malformed_record(tmp_path, make_client):
    make_client("goodPw", password="password")
    (_accounts(tmp_path) / "broken.json").write_text("{not json", encoding="utf-8")
    skipped = []
    assert shared.upgrade_all_plaintext_passwords(skipped=skipped) == ["goodPw"]
    assert skipped == ["broken"]
    assert shared.load_client("goodPw")["password"].startswith("$2")
