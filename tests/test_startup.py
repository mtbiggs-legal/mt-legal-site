"""Security headers, decrypt-error handling, and startup config checks (B2, B4, B5, C3)."""

from cryptography.fernet import Fernet

import app as app_module


def test_security_headers(client):
    r = client.get("/attorney-login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_undecryptable_client_returns_500(attorney_session, tmp_path):
    other = Fernet(Fernet.generate_key())
    (tmp_path / "accounts" / "badU.json").write_bytes(other.encrypt(b'{"username":"badU"}'))
    r = attorney_session.get("/portal/attorney/client/badU")
    assert r.status_code == 500
    assert r.get_json() == {"error": "Client record could not be decrypted."}


def test_startup_reports_missing_keys(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    problems = app_module.check_startup_config()
    assert any("SECRET_KEY" in p for p in problems)
    assert any("DATA_ENCRYPTION_KEY" in p for p in problems)


def test_startup_ok_when_keys_set(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert app_module.check_startup_config() == []


def test_startup_reports_plaintext_records(monkeypatch, make_client):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    make_client("plainOne")
    make_client("plainTwo")
    problems = app_module.check_startup_config()
    assert any("2 client record(s) are not yet encrypted" in p
               and "encrypt_existing_records.py" in p for p in problems)


def test_startup_ok_with_encrypted_records(monkeypatch, make_client):
    import shared
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    make_client("encOne")
    shared.save_client(shared.load_client("encOne"))
    assert app_module.check_startup_config() == []


def test_startup_reports_malformed_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "not-a-fernet-key")
    problems = app_module.check_startup_config()
    assert any("malformed" in p for p in problems)


def test_startup_warns_on_empty_attorney_hash(monkeypatch):
    import shared
    monkeypatch.setitem(shared.ATTORNEYS["Endocide"], "password", "")
    warnings = app_module.startup_warnings()
    assert any("ATTORNEY_ENDOCIDE_HASH is not set" in w and "Endocide" in w for w in warnings)
