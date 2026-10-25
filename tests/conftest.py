"""Shared pytest setup for the law office app.

Two things every test module needs and used to duplicate:

1. Stubs for the optional heavy dependencies, so `import app` works in a bare
   environment (and so tests never make a real API call).
2. Fixtures that redirect all client file I/O into a tmp_path.

Since the blueprint refactor the data directories and config live in
`shared`, not `app` — patch `shared.<NAME>` and every blueprint sees it,
because blueprints call the helper functions defined there.
"""

import json
import os
import sys
import types
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# Every test run gets its own throwaway encryption key. Assigned (not
# setdefault) so a developer's real .env key is never used by tests.
os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

# Make the app package importable no matter where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub optional deps before `app` is imported.
for _mod in ("anthropic", "google.oauth2.credentials",
             "google_auth_oauthlib.flow", "google.auth.transport.requests",
             "googleapiclient.discovery", "mammoth", "pypdf", "fpdf",
             "stripe", "bcrypt", "sendgrid"):
    parts = _mod.split(".")
    for _i in range(1, len(parts) + 1):
        _name = ".".join(parts[:_i])
        if _name not in sys.modules:
            sys.modules[_name] = types.ModuleType(_name)

# anthropic.AuthenticationError / APIError are referenced in `except` clauses,
# which requires them to be real exception classes.
_anthropic = sys.modules["anthropic"]
for _exc in ("AuthenticationError", "APIError"):
    if not isinstance(getattr(_anthropic, _exc, None), type):
        setattr(_anthropic, _exc, type(_exc, (Exception,), {}))

# The real bcrypt is stubbed out, so provide hashing that behaves correctly
# enough for tests: a recognisable "$2" prefix and a working round-trip.
_bcrypt = sys.modules["bcrypt"]
if not hasattr(_bcrypt, "hashpw"):
    _bcrypt.gensalt = lambda *a, **kw: b"$2b$test$salt"
    _bcrypt.hashpw  = lambda pw, salt: b"$2b$test$" + pw
    _bcrypt.checkpw = lambda pw, hashed: hashed == b"$2b$test$" + pw

import shared          # noqa: E402
import blueprints.email_service as _email_real  # noqa: E402
REAL_SEND_STATEMENT_EMAIL = getattr(_email_real, "send_statement_email", None)
import app as _app_module  # noqa: E402

# --- Guard: tests must never touch the real data folders --------------------
import threading  # noqa: E402

_REAL_BASE = Path(shared.BASE_DIR)          # captured before any monkeypatching
_REAL_DATA_DIRS = ("client-accounts", "client-billing", "client-files", "client-data",
                   "leads", "firm-settings", "security-state", "draft-history",
                   "research-history", "case-searches", "token-usage")


def _snapshot_real_data():
    snap = {}
    for name in _REAL_DATA_DIRS:
        d = _REAL_BASE / name
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file():
                st = f.stat()
                snap[f.relative_to(_REAL_BASE).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


@pytest.fixture(scope="session", autouse=True)
def _real_data_untouched():
    before = _snapshot_real_data()
    yield
    for t in threading.enumerate():
        if t is not threading.current_thread() and t is not threading.main_thread():
            t.join(5)
    after = _snapshot_real_data()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        pytest.fail("Tests touched the REAL data folders: " + ", ".join(changed), pytrace=False)


flask_app = _app_module.app
flask_app.config["TESTING"] = True
flask_app.config["SECRET_KEY"] = "test"
# The CSRF check is exercised explicitly in test_csrf.py; everywhere else the
# existing .post() calls would all need a token.
flask_app.config["CSRF_ENABLED"] = False


@pytest.fixture
def sent_statement_emails():
    return []


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch, sent_statement_emails):
    """Point every client data directory at a fresh tmp_path.

    Blueprints do `from shared import X` for the directory constants, which
    binds them at import time — so each one has to be patched in the module
    that uses it as well as in `shared`.
    """
    accounts = tmp_path / "accounts"
    files    = tmp_path / "files"
    tokens   = tmp_path / "tokens"
    leads    = tmp_path / "leads"
    security = tmp_path / "security"
    data     = tmp_path / "data"
    billing_dir  = tmp_path / "billing"
    settings_dir = tmp_path / "settings"
    for d in (accounts, files, tokens, leads, security, data, billing_dir, settings_dir):
        d.mkdir(exist_ok=True)

    monkeypatch.setattr(shared, "CLIENT_ACCOUNTS_DIR", accounts)
    monkeypatch.setattr(shared, "CLIENT_FILES_DIR",    files)
    monkeypatch.setattr(shared, "TOKEN_USAGE_DIR",     tokens)
    monkeypatch.setattr(shared, "LEADS_DIR",           leads)
    monkeypatch.setattr(shared, "SECURITY_STATE_DIR", security, raising=False)
    monkeypatch.setattr(shared, "CLIENT_BILLING_DIR", billing_dir, raising=False)
    monkeypatch.setattr(shared, "FIRM_SETTINGS_DIR",  settings_dir, raising=False)
    # Billing: treat the opening-statement migration as done, send notices
    # inline, and never call SendGrid. Tests that need otherwise override these.
    (settings_dir / "migrations.json").write_text('{"opening_statements": "test"}')
    import billing as _billing
    monkeypatch.setattr(_billing, "NOTICE_ASYNC", False, raising=False)
    import blueprints.email_service as _email
    monkeypatch.setattr(_email, "send_statement_email",
                        lambda *a, **k: (sent_statement_emails.append((a, k)) or "sent"),
                        raising=False)
    # Pin the rate so threshold arithmetic in tests never depends on the shell env.
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)

    import blueprints.portal_attorney as _pa
    import blueprints.portal_client as _pc
    import blueprints.public as _pub
    import blueprints.intake as _intake
    for mod, name, value in (
        (_pa,  "CLIENT_FILES_DIR",    files),
        (_pa,  "CLIENT_ACCOUNTS_DIR", accounts),
        (_pa,  "TOKEN_USAGE_DIR",     tokens),
        (_pa,  "LEADS_DIR",           leads),
        (_pc,  "CLIENT_FILES_DIR",    files),
        (_pub, "LEADS_DIR",           leads),
        (_intake, "CLIENT_DATA_DIR",  data),
        (_intake, "CLIENT_FILES_DIR", files),
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)

    # Tests must not depend on whether the developer's .env sets a share
    # password; the gate itself is covered explicitly in test_share_password.
    monkeypatch.delenv("SHARE_PASSWORD", raising=False)
    return tmp_path


@pytest.fixture
def client(patch_dirs):
    """Anonymous test client."""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def client_session(patch_dirs):
    """Test client logged in as the client 'testclient'."""
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "testclient"
            sess["role"]     = "client"
        yield c


@pytest.fixture
def attorney_session(patch_dirs):
    """Test client logged in as an attorney."""
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "Endocide"
            sess["role"]     = "attorney"
        yield c


@pytest.fixture
def other_attorney_session(patch_dirs):
    """Test client logged in as an attorney who is NOT assigned to make_client's default client."""
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "SophiaH"
            sess["role"]     = "attorney"
        yield c


@pytest.fixture
def issue_test_statement():
    """Give a client billed, statement-issued hours: appends a log entry and
    issues a manual statement (no notice)."""
    import billing
    def _issue(username, hours, date="2026-10-01"):
        c = shared.load_client(username)
        c.setdefault("billing_log", []).append(
            {"date": date, "hours": hours, "note": "test work", "category": "Other"})
        c["hours_billed"] = round(sum(float(e.get("hours", 0)) for e in c["billing_log"]), 2)
        shared._write_record(shared.CLIENT_ACCOUNTS_DIR / f"{username}.json", c)
        return billing.issue_statement(username, reason="manual", issued_by="test", notify=False)
    return _issue


@pytest.fixture
def make_client(tmp_path):
    """Factory writing a client account JSON into the patched accounts dir."""
    def _make(username="testclient", **extra):
        record = {
            "username":          username,
            "client_name":       "Test Client",
            "case_type":         "Criminal Defense",
            "legal_issue":       "DUI charge",
            "assigned_attorney": "Endocide",
            "hours_billed":      0,
            "billing_log":       [],
            "activity_log":      [],
            "messages":          [],
        }
        record.update(extra)
        (tmp_path / "accounts" / f"{username}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
        return record
    return _make
