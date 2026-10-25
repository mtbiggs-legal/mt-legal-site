# Security Hardening & Conflict Checker Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock every client file to its assigned attorney plus co-counsel. Encrypt client records at rest. Harden login, session and CSRF handling. Replace the exact-match conflict checker with a fuzzy, recorded one.

**Spec:** `docs/superpowers/specs/2026-10-01-security-hardening-conflict-checker-design.md`. Read it first: it explains *why* behind each rule below.

**Architecture:** Three focused units sit alongside the existing `shared.py`:
- **`shared.py`** grows the encrypted record I/O and the access helpers. All client-record I/O already lives there.
- **`security.py`** (new) owns login throttling, session reset and idle timeout, CSRF, and security headers. It is wired into Flask through `security.init_app(app)`.
- **`conflicts.py`** (new) owns name normalisation, fuzzy matching, check records, and redaction.

Routes in `blueprints/` call these units, and the attorney-portal UI for the new features lives in a new `static/js/attorney_security.js` rather than growing the 3,700-line template.

**Tech Stack:** Flask, `cryptography` (Fernet), stdlib `difflib`, pytest.

**Run tests with:** `python -m pytest tests -q` from the repo root. Note the `tests` argument: a bare `pytest` also collects the root-level `test_email.py` and crashes. The baseline is **88 passed**.

### Deviations from the spec (deliberate, small)

1. **CSRF client side:** `base.html` defines `apiFetch` and then sets `window.fetch = apiFetch` in `<head>`. The spec instead asked for each of the ~47 `fetch(` call sites to be rewritten. The shim gives the same guarantee (every same-origin POST carries the token) with no per-call edits. The "no raw POST fetch" grep test becomes a test that the shim is in `<head>` before any other script.
2. **`_log_access_and_save` is dropped.** Every route that logs access already holds the loaded record, so it calls `_log_access(...)` and then `save_client(...)`.
3. **The access log is served by its own endpoint** (`GET /portal/attorney/access-log/<username>`). Embedding it in the client JSON would contradict spec A4, which strips it from `public_client_view`.
4. **Single-token names are capped at 0.75, not 0.69.** An exact single-token match (for example "Acme LLC" vs "Acme Inc", both of which normalise to `acme`) then shows as *possible* instead of being silently dropped. A bare surname against a full name still scores below 0.70 and is ignored. Over-inclusion is the safer failure for conflict checks.
5. **Redacted hits keep `searched_role` and `adverse`** beyond the field list in spec D2. Both describe the *search*, not the other client, and the UI needs them to show the "potentially adverse" flag.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `shared.py` | modify | Encrypted `_read_record`/`_write_record`, `RecordDecryptError`, `SECURITY_STATE_DIR`, access helpers (`can_access_client`, `load_client_for_attorney`, `public_client_view`, `_log_access`), `acceptable_password`, `upgrade_all_plaintext_passwords`; remove `check_conflict_of_interest` and fcntl |
| `security.py` | create | Throttle, session reset, idle timeout, CSRF, headers, `init_app` |
| `conflicts.py` | create | Normalise, similarity, `run_conflict_check`, `record_check`, `redact_hits`, firm log |
| `app.py` | modify | Session config, `security.init_app`, decrypt error handler, `check_startup_config` |
| `blueprints/auth.py` | modify | Throttle and session start on both logins; conflict check on `/client-register` |
| `blueprints/portal_attorney.py` | modify | Access checks, access logging, co-counsel, access-log, conflict endpoints, create-client password fix |
| `blueprints/intake.py` | modify | New checker, no public conflict data, save `opposing_parties` |
| `blueprints/drafting.py` | modify | Throttle `claim-document`; conflict check on account creation |
| `blueprints/calendar.py` | modify | Public route no longer touches client records |
| `templates/base.html` | modify | CSRF meta tag and fetch shim |
| `templates/attorney_login.html`, `client_login.html`, `change_password.html` | modify | Hidden `csrf_token` field |
| `templates/attorney_portal.html` | modify | Password field fix, sidebar badges, two new panels, nav buttons, script include |
| `static/js/app.js` | modify | Remove public conflict banner |
| `static/js/attorney_security.js` | create | Parties, co-counsel, conflicts, access history and Conflict Check tab UI |
| `scripts/generate_data_key.py` | create | Print a new Fernet key |
| `scripts/encrypt_existing_records.py` | create | Back up, encrypt and verify |
| `scripts/hash_existing_passwords.py` | modify | Delegate to `shared.upgrade_all_plaintext_passwords` |
| `requirements.txt`, `.gitignore` | modify | `cryptography`; `security-state/` |
| `tests/conftest.py` | modify | Test key, `CSRF_ENABLED=False`, `SECURITY_STATE_DIR`, `other_attorney_session` |
| `tests/test_activity_log.py` | modify | Read via `_read_record` |
| `tests/test_encryption.py`, `test_client_access.py`, `test_co_counsel.py`, `test_access_log.py`, `test_no_hash_leak.py`, `test_calendar_schedule.py`, `test_login_throttle.py`, `test_session.py`, `test_csrf.py`, `test_startup.py`, `test_conflicts.py`, `test_conflict_routes.py`, `test_intake_privacy.py` | create | See tasks |

---

## Chunk 1: Encryption at rest

### Task 1: Test harness prep

**Files:**
- Modify: `tests/conftest.py`
- Modify: `requirements.txt`, `.gitignore`

- [ ] **Step 1: Add the dependency and ignore rule**

Append `cryptography` to `requirements.txt` (on its own line, after `bcrypt`). Append to `.gitignore` under the client-data block:

```
security-state/
```

Run: `python -c "import cryptography; print(cryptography.__version__)"`
Expected: a version string (46.x is installed on the dev machine). If it errors, run `python -m pip install cryptography`.

- [ ] **Step 2: Update `tests/conftest.py`**

Directly after the `import pytest` line, add:

```python
import os

from cryptography.fernet import Fernet

# Every test run gets its own throwaway encryption key. Assigned (not
# setdefault) so a developer's real .env key is never used by tests.
os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
```

After `flask_app.config["SECRET_KEY"] = "test"`, add:

```python
# The CSRF check is exercised explicitly in test_csrf.py; everywhere else the
# existing .post() calls would all need a token.
flask_app.config["CSRF_ENABLED"] = False
```

In `patch_dirs`, add `security = tmp_path / "security"` to the directory list and the `mkdir` loop, then add this beside the other `monkeypatch.setattr(shared, ...)` lines:

```python
    monkeypatch.setattr(shared, "SECURITY_STATE_DIR", security, raising=False)
```

(`raising=False` is only needed until Task 2 creates the attribute; leave it in, it is harmless.)

`blueprints/intake.py` binds `CLIENT_DATA_DIR` and `CLIENT_FILES_DIR` at import, and today no fixture redirects them. A test that posts to `/intake/submit` would therefore write into the **real** `client-data/` and `client-files/` folders. Add `data = tmp_path / "data"` to the directory list and `mkdir` loop. Then add `import blueprints.intake as _intake` beside the other blueprint imports in `patch_dirs`, and add these two entries to its `(mod, name, value)` tuple:

```python
        (_intake, "CLIENT_DATA_DIR",  data),
        (_intake, "CLIENT_FILES_DIR", files),
```

After the `attorney_session` fixture, add:

```python
@pytest.fixture
def other_attorney_session(patch_dirs):
    """Test client logged in as an attorney who is NOT assigned to make_client's default client."""
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "SophiaH"
            sess["role"]     = "attorney"
        yield c
```

- [ ] **Step 3: Run the suite**

Run: `python -m pytest tests -q`
Expected: `88 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py requirements.txt .gitignore
git commit -m "test: conftest prep for encryption, CSRF flag, and security state"
```

### Task 2: Encrypted record I/O

**Files:**
- Modify: `shared.py` (imports at top; directories block ~line 96; `load_client`/`save_client`/`all_clients` ~lines 220–284)
- Modify: `tests/test_activity_log.py`
- Create: `tests/test_encryption.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_encryption.py`:

```python
"""Client account records are encrypted at rest (spec section C)."""

import json
import re
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import shared


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
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python -m pytest tests/test_encryption.py -q`
Expected: most tests FAIL. `test_save_client_writes_ciphertext` fails because the file starts with `{`, and `RecordDecryptError` doesn't exist yet. `test_no_direct_account_file_io` may already pass.

- [ ] **Step 3: Implement in `shared.py`**

1. **Imports.** Delete the `# fcntl is Unix-only…` comment and the `fcntl` try/except block below it (lines 16–21). Records are now written with an atomic replace, and the threading lock stays. Add `import sys` and `import time` beside the other stdlib imports, and add this after the `from flask import ...` line:

```python
from cryptography.fernet import Fernet, InvalidToken
```

2. **Directories.** In the data directories block, add `SECURITY_STATE_DIR = BASE_DIR / "security-state"` after `TOKEN_USAGE_DIR`, and add `SECURITY_STATE_DIR` to the `for _d in (...)` mkdir tuple.

3. **Record I/O.** Replace the body of the `# Client file I/O helpers` section from `def load_client` through the end of `all_clients` with:

```python
class RecordDecryptError(Exception):
    """A client record exists but cannot be decrypted with DATA_ENCRYPTION_KEY."""


_fernet_cache = None


def _fernet() -> Fernet:
    """Return the Fernet cipher for client records. Loaded lazily so a missing
    key is reported by check_startup_config(), not as an import traceback."""
    global _fernet_cache
    if _fernet_cache is None:
        key = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "DATA_ENCRYPTION_KEY is not set. Run: python scripts/generate_data_key.py"
            )
        _fernet_cache = Fernet(key.encode())
    return _fernet_cache


def _read_record(path: Path) -> dict:
    """Read a client account file. Plaintext JSON (legacy) and Fernet tokens
    are both accepted so records can be migrated gradually."""
    raw = path.read_bytes()
    if raw.lstrip().startswith(b"{"):
        return json.loads(raw.decode("utf-8"))
    try:
        return json.loads(_fernet().decrypt(raw).decode("utf-8"))
    except InvalidToken as exc:
        raise RecordDecryptError(path.stem) from exc


def _write_record(path: Path, data: dict) -> None:
    """Encrypt and write a client account file atomically.

    On Windows os.replace fails with PermissionError while another handle
    (OneDrive sync, antivirus, a concurrent all_clients() read) has the target
    open, so retry briefly before giving up."""
    token = _fernet().encrypt(json.dumps(data, indent=2).encode("utf-8"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(token)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


_CLIENT_LIST_DEFAULTS = ("co_counsel", "access_log", "opposing_parties",
                         "related_parties", "conflict_checks")


def load_client(username: str):
    # Reject anything that isn't a plain account name so a crafted username
    # cannot read a file from outside CLIENT_ACCOUNTS_DIR.
    if not username or safe_username(username) != username:
        return None
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    if not path.exists():
        return None
    with _get_client_lock(username):
        data = _read_record(path)
    data.setdefault("hours_paid", 0)
    data.setdefault("payments", [])
    data.setdefault("legal_issue_summary", "")
    data.setdefault("activity_log", [])
    data.setdefault("billing_log", [])
    data.setdefault("esignature", None)
    for field in _CLIENT_LIST_DEFAULTS:
        data.setdefault(field, [])
    return data


def save_client(data: dict):
    username = data["username"]
    if not username or safe_username(username) != username:
        raise ValueError(f"Refusing to save client with unsafe username: {username!r}")
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        _write_record(path, data)


def all_clients():
    clients = []
    for p in sorted(CLIENT_ACCOUNTS_DIR.glob("*.json")):
        try:
            clients.append(_read_record(p))
        except RecordDecryptError:
            print(f"[warn] could not decrypt client record: {p.stem}", file=sys.stderr)
        except Exception:
            pass
    return clients
```

4. Check that `check_conflict_of_interest` in `shared.py` still opens files with `open(path)`. It is deleted in Task 18, but until then it must not break. Change its loop body's read to `existing = _read_record(path)`, keeping the surrounding `try/except Exception: continue`.

- [ ] **Step 4: Update `tests/test_activity_log.py`**

Replace both occurrences of:

```python
    updated = json.loads((tmp_path / "accounts" / "testU.json").read_text())
```

(and the `testU2` one) with:

```python
    updated = shared._read_record(tmp_path / "accounts" / "testU.json")
```

(using `testU2.json` in the second one).

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests -q`
Expected: all pass, about 96 tests.

- [ ] **Step 6: Commit**

```bash
git add shared.py tests/test_encryption.py tests/test_activity_log.py
git commit -m "feat(security): encrypt client account records at rest"
```

### Task 3: Plaintext-password cleanup function

**Files:**
- Modify: `shared.py` (password helpers section)
- Modify: `scripts/hash_existing_passwords.py`
- Test: `tests/test_encryption.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_encryption.py`)

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_encryption.py::test_upgrade_all_plaintext_passwords -q`
Expected: FAIL with `AttributeError: ... upgrade_all_plaintext_passwords`.

- [ ] **Step 3: Implement** — add to `shared.py` after `upgrade_password_if_needed`:

```python
def upgrade_all_plaintext_passwords(apply: bool = True) -> list:
    """Hash every client password still stored in plaintext and force a change
    on next login. Returns the usernames upgraded (or, with apply=False, the
    ones that would be)."""
    upgraded = []
    for path in sorted(CLIENT_ACCOUNTS_DIR.glob("*.json")):
        try:
            client = load_client(path.stem)
        except RecordDecryptError:
            continue
        pw = (client or {}).get("password", "")
        if not pw or pw.startswith("$2"):
            continue
        upgraded.append(client["username"])
        if apply:
            client["password"]             = hash_password(pw)
            client["must_change_password"] = True
            save_client(client)
    return upgraded
```

- [ ] **Step 4: Rewrite `scripts/hash_existing_passwords.py` to delegate.** Replace everything from `import argparse` to the end with:

```python
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import shared  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually rewrite the files (default is a dry run)")
    args = parser.parse_args()

    pending = shared.upgrade_all_plaintext_passwords(apply=False)
    print(f"Plaintext passwords: {len(pending)}")
    for name in pending:
        print(f"    {name}")
    if not pending:
        print("\nNothing to migrate.")
        return 0
    if not args.apply:
        print("\nDry run — nothing was changed. Re-run with --apply.")
        return 0

    stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = shared.CLIENT_ACCOUNTS_DIR.parent / f"client-accounts-backup-{stamp}"
    shutil.copytree(shared.CLIENT_ACCOUNTS_DIR, backup)
    print(f"\nBackup written to: {backup}")
    done = shared.upgrade_all_plaintext_passwords()
    print(f"Done — {len(done)} password(s) hashed; those clients must set a new "
          "password at next login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Also update the module docstring's last paragraph: replace "Clients keep their existing passwords; only the stored form changes." with "Affected clients are required to choose a new password at next login."

- [ ] **Step 5: Run tests** — `python -m pytest tests -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add shared.py scripts/hash_existing_passwords.py tests/test_encryption.py
git commit -m "feat(security): shared plaintext-password upgrade, forces change on next login"
```

### Task 4: Key generation and migration scripts

**Files:**
- Create: `scripts/generate_data_key.py`, `scripts/encrypt_existing_records.py`
- Test: `tests/test_encryption.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
import sys as _sys

_sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


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
```

- [ ] **Step 2: Run them to verify they fail** — `ModuleNotFoundError: encrypt_existing_records`.

- [ ] **Step 3: Create `scripts/generate_data_key.py`**

```python
"""Print a new DATA_ENCRYPTION_KEY for .env.

Usage:
    python scripts/generate_data_key.py

Put the printed line in .env AND store a copy somewhere outside this folder
(password manager, printed in the office safe). If the key is lost, encrypted
client records cannot be recovered.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(f"DATA_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print("\nAdd the line above to .env and back the key up OUTSIDE this folder.")
```

- [ ] **Step 4: Create `scripts/encrypt_existing_records.py`**

```python
"""Encrypt every plaintext client account record in place.

Usage:
    python scripts/encrypt_existing_records.py --backup-dir D:\\law-office-backups

1. Copies client-accounts/ to a timestamped folder under --backup-dir
   (refused if that folder is inside this OneDrive-synced project).
2. Encrypts each plaintext record, re-reads it, and restores it from the
   backup if the round trip does not match.
Safe to re-run: already-encrypted records are skipped.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import shared  # noqa: E402


def encrypt_all(accounts_dir: Path, backup_root: Path, project_root: Path = ROOT):
    backup_root  = Path(backup_root).resolve()
    project_root = Path(project_root).resolve()
    if backup_root == project_root or project_root in backup_root.parents:
        raise SystemExit("Refusing: --backup-dir is inside the project folder, "
                         "which OneDrive syncs. Choose a folder outside it.")
    # Microseconds keep two runs in the same second from colliding.
    backup = backup_root / f"client-accounts-{datetime.now():%Y%m%d_%H%M%S_%f}"
    shutil.copytree(accounts_dir, backup)

    counts = {"encrypted": 0, "already": 0, "failed": 0}
    for path in sorted(Path(accounts_dir).glob("*.json")):
        raw = path.read_bytes()
        if not raw.lstrip().startswith(b"{"):
            counts["already"] += 1
            continue
        original = json.loads(raw.decode("utf-8"))
        shared._write_record(path, original)
        if shared._read_record(path) == original:
            counts["encrypted"] += 1
        else:
            shutil.copy2(backup / path.name, path)
            counts["failed"] += 1
    return counts, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()
    try:
        shared._fernet()
    except RuntimeError as exc:
        print(exc)
        return 2
    counts, backup = encrypt_all(shared.CLIENT_ACCOUNTS_DIR, Path(args.backup_dir))
    print(f"Backup:            {backup}")
    print(f"Encrypted:         {counts['encrypted']}")
    print(f"Already encrypted: {counts['already']}")
    print(f"Failed (restored): {counts['failed']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests** — `python -m pytest tests -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_data_key.py scripts/encrypt_existing_records.py tests/test_encryption.py
git commit -m "feat(security): data-key generator and record encryption migration"
```

---

## Chunk 2: Access control

### Task 5: Access helpers

**Files:**
- Modify: `shared.py` (new section after the "Username / activity helpers" section)
- Create: `tests/test_access_log.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_access_log.py`:

```python
"""Access helpers and the attorney access log (spec A1, A2, A4)."""

from datetime import datetime, timedelta

import shared
from conftest import flask_app


def _ctx(username="Endocide"):
    ctx = flask_app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.9"})
    ctx.push()
    shared.session["role"] = "attorney"
    shared.session["username"] = username
    return ctx


def test_can_access_client():
    c = {"assigned_attorney": "Endocide", "co_counsel": ["SophiaH"]}
    assert shared.can_access_client("Endocide", c)
    assert shared.can_access_client("SophiaH", c)
    assert not shared.can_access_client("SophiaH", c, assigned_only=True)
    assert not shared.can_access_client("Nobody", c)
    assert not shared.can_access_client("", c)


def test_load_client_for_attorney(make_client):
    make_client("victim")
    ctx = _ctx("SophiaH")
    try:
        assert shared.load_client_for_attorney("victim") is None
        assert shared.load_client_for_attorney("missing") is None
    finally:
        ctx.pop()
    ctx = _ctx("Endocide")
    try:
        assert shared.load_client_for_attorney("victim")["username"] == "victim"
    finally:
        ctx.pop()


def test_public_client_view_strips_private_fields():
    c = {"username": "u", "password": "$2b$x", "must_change_password": True,
         "access_log": [1], "conflict_checks": [2], "client_name": "N"}
    assert shared.public_client_view(c) == {"username": "u", "client_name": "N"}


def test_log_access_appends_with_ip():
    ctx = _ctx()
    try:
        c = {}
        assert shared._log_access(c, "billing_entry", "1.0 hrs")
        e = c["access_log"][0]
        assert (e["attorney"], e["action"], e["detail"], e["ip"]) == \
               ("Endocide", "billing_entry", "1.0 hrs", "10.0.0.9")
    finally:
        ctx.pop()


def test_view_actions_deduplicated_within_10_minutes():
    ctx = _ctx()
    try:
        c = {}
        assert shared._log_access(c, "view_record")
        assert not shared._log_access(c, "view_record")
        c["access_log"][0]["timestamp"] = (
            datetime.now() - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%S")
        assert shared._log_access(c, "view_record")
        assert len(c["access_log"]) == 2
    finally:
        ctx.pop()


def test_access_log_capped():
    ctx = _ctx()
    try:
        c = {"access_log": [{"timestamp": "2020-01-01T00:00:00", "attorney": "x",
                             "action": "edit_record", "detail": "", "ip": ""}] * 1000}
        shared._log_access(c, "edit_record")
        assert len(c["access_log"]) == 1000
        assert c["access_log"][-1]["attorney"] == "Endocide"
    finally:
        ctx.pop()
```

- [ ] **Step 2: Run them to verify they fail** — `AttributeError` on `can_access_client`.

- [ ] **Step 3: Implement.** `shared.py` already imports `request` and `session` from flask; confirm. Add a new section:

```python
# ═════════════════════════════════════════════════════════════════════════════
# Attorney access control & access log
# ═════════════════════════════════════════════════════════════════════════════

_PRIVATE_CLIENT_FIELDS = frozenset({"password", "must_change_password",
                                    "access_log", "conflict_checks"})
_ACCESS_LOG_MAX = 1000
_VIEW_DEDUP     = timedelta(minutes=10)


def can_access_client(attorney_username: str, client: dict, assigned_only: bool = False) -> bool:
    if not attorney_username or not client:
        return False
    if client.get("assigned_attorney") == attorney_username:
        return True
    return (not assigned_only) and attorney_username in (client.get("co_counsel") or [])


def load_client_for_attorney(username: str, assigned_only: bool = False):
    """load_client + access check for the logged-in attorney. Returns None —
    caller sends 404 — when the client does not exist OR the attorney may not
    see it; the two cases are deliberately indistinguishable."""
    if session.get("role") != "attorney":
        return None
    client = load_client((username or "").strip())
    if client and can_access_client(session.get("username", ""), client, assigned_only):
        return client
    return None


def public_client_view(client: dict) -> dict:
    """Copy of a client record that is safe to send to the browser."""
    return {k: v for k, v in client.items() if k not in _PRIVATE_CLIENT_FIELDS}


def _log_access(client: dict, action: str, detail: str = "") -> bool:
    """Append an attorney access entry to client['access_log'] (in memory —
    the caller saves). view_* actions repeated by the same attorney within 10
    minutes are skipped. Returns True if an entry was appended."""
    attorney = session.get("username", "")
    now      = datetime.now()
    log      = client.setdefault("access_log", [])
    if action.startswith("view_"):
        for entry in reversed(log):
            try:
                ts = datetime.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%S")
            except (KeyError, ValueError):
                continue
            if now - ts > _VIEW_DEDUP:
                break
            if entry.get("attorney") == attorney and entry.get("action") == action:
                return False
    log.append({
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "attorney":  attorney,
        "action":    action,
        "detail":    (detail or "")[:200],
        "ip":        request.remote_addr or "",
    })
    del log[:-_ACCESS_LOG_MAX]
    return True
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_access_log.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add shared.py tests/test_access_log.py
git commit -m "feat(security): attorney access helpers and access log"
```

### Task 6: Guard the client-record routes

**Files:**
- Modify: `blueprints/portal_attorney.py`: imports (line 14), `portal_clients_list`/`portal_client_get` (~787–799), archive/unarchive (~802–825), `portal_update_client` (~951), `portal_generate_summary` (~1021), `portal_billing_entry` (~1057), `portal_attorney_reply` (~1123)
- Create: `tests/test_client_access.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_client_access.py`:

```python
"""Every attorney route that touches a client enforces assignment (spec A1)."""

import inspect
import re

import pytest

import shared
from conftest import flask_app


@pytest.fixture(autouse=True)
def victim(make_client, tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "ANTHROPIC_API_KEY", None)   # AI routes fail fast, never 404
    make_client("victim", client_name="Victor Im", password="$2b$test$pw",
                legal_issue="Theft charge")
    d = tmp_path / "files" / "victim" / "documents" / "Motions"
    d.mkdir(parents=True)
    (d / "a.txt").write_text("motion text")


ROUTES = [
    ("get",  "/portal/attorney/client/victim", None),
    ("post", "/portal/attorney/update-client", {"username": "victim", "phone": "1"}),
    ("post", "/portal/attorney/generate-summary", {"username": "victim"}),
    ("post", "/portal/attorney/billing-entry", {"username": "victim", "note": "x", "hours": 0.1}),
    ("post", "/portal/attorney/reply", {"username": "victim", "text": "hi"}),
    ("get",  "/portal/attorney/documents/victim", None),
    ("get",  "/portal/attorney/document/victim/Motions/a.txt", None),
    ("get",  "/portal/attorney/preview/victim/Motions/a.txt", None),
    ("get",  "/portal/attorney/docx-preview/victim/Motions/a.txt", None),
    ("post", "/portal/attorney/research/issue-spot",
     {"username": "victim", "category": "Motions", "filename": "a.txt"}),
    ("post", "/portal/attorney/research/draft", {"username": "victim", "issues": "x"}),
    ("post", "/portal/attorney/research/save-draft",
     {"username": "victim", "draft": "x", "filename": "d"}),
    ("post", "/portal/attorney/research/save-report",
     {"username": "victim", "report_type": "analysis", "text": "x"}),
    ("get",  "/portal/attorney/access-log/victim", None),
]
ASSIGNED_ONLY = [
    ("post", "/portal/attorney/archive-client", {"username": "victim"}),
    ("post", "/portal/attorney/unarchive-client", {"username": "victim"}),
    ("post", "/portal/attorney/delete-document",
     {"username": "victim", "category": "Motions", "filename": "a.txt"}),
]


def _call(c, method, url, payload):
    return c.get(url) if method == "get" else c.post(url, json=payload)


@pytest.mark.parametrize("method,url,payload", ROUTES + ASSIGNED_ONLY)
def test_unassigned_attorney_gets_404(other_attorney_session, method, url, payload):
    resp = _call(other_attorney_session, method, url, payload)
    assert resp.status_code == 404
    assert shared.load_client("victim")["access_log"] == []


@pytest.mark.parametrize("method,url,payload", ROUTES + ASSIGNED_ONLY)
def test_assigned_attorney_allowed(attorney_session, method, url, payload):
    assert _call(attorney_session, method, url, payload).status_code != 404


@pytest.mark.parametrize("method,url,payload", ROUTES)
def test_co_counsel_allowed(other_attorney_session, method, url, payload):
    c = shared.load_client("victim")
    c["co_counsel"] = ["SophiaH"]
    shared.save_client(c)
    assert _call(other_attorney_session, method, url, payload).status_code != 404


@pytest.mark.parametrize("method,url,payload", ASSIGNED_ONLY)
def test_co_counsel_denied_assigned_only_routes(other_attorney_session, method, url, payload):
    c = shared.load_client("victim")
    c["co_counsel"] = ["SophiaH"]
    shared.save_client(c)
    assert _call(other_attorney_session, method, url, payload).status_code == 404


def test_upload_rejected_before_file_is_written(other_attorney_session, tmp_path):
    import io
    resp = other_attorney_session.post(
        "/portal/attorney/upload-document",
        data={"username": "victim", "category": "Other",
              "file": (io.BytesIO(b"x"), "evil.txt")},
        content_type="multipart/form-data")
    assert resp.status_code == 404
    assert not (tmp_path / "files" / "victim" / "documents" / "Other" / "evil.txt").exists()


def test_clients_list_only_accessible(other_attorney_session, make_client):
    make_client("mine", assigned_attorney="SophiaH")
    names = [c["username"] for c in other_attorney_session.get("/portal/attorney/clients").get_json()]
    assert names == ["mine"]


def test_archive_lead_requires_assignment(other_attorney_session, tmp_path):
    import json
    (tmp_path / "leads" / "l1.json").write_text(json.dumps(
        {"name": "Lead", "assigned_attorney": "Endocide"}))
    resp = other_attorney_session.post("/portal/attorney/archive-lead", json={"filename": "l1.json"})
    assert resp.status_code == 404


# Routes that read a username but legitimately do not load an existing client.
NO_CLIENT_ROUTES = {
    "attorney_portal", "portal_attorney_dashboard", "portal_create_client",
    "portal_leads_list", "attorney_token_usage", "insights_export_tax",
    "research_analyze", "research_authority", "portal_conflict_check",
}


def test_every_client_route_is_guarded():
    """Sweep: a new portal route that reads a client username must use
    load_client_for_attorney, or this test fails."""
    offenders = []
    for rule in flask_app.url_map.iter_rules():
        if not rule.endpoint.startswith("portal_attorney."):
            continue
        name = rule.endpoint.split(".", 1)[1]
        fn   = inspect.unwrap(flask_app.view_functions[rule.endpoint])
        src  = inspect.getsource(fn)
        reads_username = "<username>" in rule.rule or re.search(r'get\("username"', src)
        if reads_username and name not in NO_CLIENT_ROUTES \
                and "load_client_for_attorney" not in src:
            offenders.append(f"{name} ({rule.rule})")
    assert not offenders, "Unguarded client routes: " + ", ".join(offenders)
```

(`/portal/attorney/access-log/<username>` and `portal_conflict_check` don't exist yet. The access-log entries fail until Step 3 adds the route. `portal_conflict_check` is created in Task 18 and pre-listed here because its `username` is optional; it still calls `load_client_for_attorney` when one is given.)

- [ ] **Step 2: Run them to verify they fail** — `python -m pytest tests/test_client_access.py -q`. Expect many failures: the other attorney gets 200 and the sweep lists offenders.

- [ ] **Step 3: Implement the record routes.** In the `from shared import (...)` block of `portal_attorney.py`, add `can_access_client, load_client_for_attorney, public_client_view, _log_access,`. Then make these edits.

`portal_clients_list` and `portal_client_get`, with a new `portal_access_log` after them:

```python
@portal_attorney_bp.route("/portal/attorney/clients")
@require_attorney
def portal_clients_list():
    atty = session["username"]
    return jsonify([public_client_view(c) for c in all_clients() if can_access_client(atty, c)])


@portal_attorney_bp.route("/portal/attorney/client/<username>")
@require_attorney
def portal_client_get(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if _log_access(client, "view_record"):
        save_client(client)
    view = public_client_view(client)
    view["viewer_is_assigned"] = client.get("assigned_attorney") == session["username"]
    return jsonify(view)


@portal_attorney_bp.route("/portal/attorney/access-log/<username>")
@require_attorney
def portal_access_log(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    return jsonify(list(reversed(client.get("access_log", []))))
```

In `portal_archive_client` and `portal_unarchive_client`, replace `client = load_client(username)` with `client = load_client_for_attorney(username, assigned_only=True)`. Directly before `save_client(client)`, insert `_log_access(client, "edit_record", "File archived.")` (or `"File restored from archive."` for unarchive).

In `portal_update_client`, `portal_generate_summary`, `portal_billing_entry` and `portal_attorney_reply`, replace `client = load_client(username)` (or `client   = load_client(username)`) with `client = load_client_for_attorney(username)`. Then insert one line directly before the **first** `save_client(client)` in each:

| Route | Line to insert |
|---|---|
| update-client | **Do not insert separately**: the stale-copy replacement below adds this call |
| generate-summary | `_log_access(client, "edit_record", "AI summary regenerated.")` |
| billing-entry | `_log_access(client, "billing_entry", f"{hours} hrs — {note[:80]}")` |
| reply | `_log_access(client, "message_sent", text[:80])` |

**update-client stale-copy fix.** Today `portal_update_client` calls `save_client(client)`, then `_log_activity(...)`, which reloads the record from disk, appends and saves. Later Google Calendar branches then call `save_client(client)` again with the **stale** in-memory copy. That silently drops the activity entry, and now the access entry too. Fix it while you're here: replace

```python
    save_client(client)
    _log_activity(username, "info_updated", "Client info updated.")
```

with

```python
    client.setdefault("activity_log", []).append({
        "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "action_type": "info_updated",
        "description": "Client info updated.",
    })
    _log_access(client, "edit_record", "Client info updated.")
    save_client(client)
```

Every later `save_client(client)` then writes a copy that already contains both entries.

- [ ] **Step 4: Run** `python -m pytest tests/test_client_access.py -q`. Record-route params now pass; document and research params still fail. That's expected, and Task 7 fixes them.

- [ ] **Step 5: Commit**

```bash
git add blueprints/portal_attorney.py tests/test_client_access.py
git commit -m "feat(security): enforce client assignment on attorney record routes"
```

### Task 7: Guard the document, research and lead routes

**Files:**
- Modify: `blueprints/portal_attorney.py`: `list_documents` (~1148), `upload_document` (~1170), `delete_document` (~1230), `serve_document`, `preview_document`, `docx_preview` (~1248–1300), `portal_archive_lead` (~1102), research routes (~1351–1525)

- [ ] **Step 1: `list_documents`.** Replace the first line of the body (`uname  = safe_username(username)`) with:

```python
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if _log_access(client, "view_documents"):
        save_client(client)
    uname  = client["username"]
```

- [ ] **Step 2: `upload_document`.** Directly after the `if not username: ... 400` check, insert:

```python
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
```

Then replace the block from `billing_entry = None` through `total_hours = None` with:

```python
    entry = {
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "hours":    0.1,
        "note":     f"{category} — \"{dest.name}\" uploaded.",
        "type":     "document_upload",
        "category": "Filing",
    }
    client.setdefault("billing_log", []).append(entry)
    recalc_hours(client)
    _log_access(client, "document_upload", f"{category}/{dest.name}")
    save_client(client)
    _log_activity(username, "document_upload", f"{category} — \"{dest.name}\" uploaded.")
    billing_entry = entry
    total_hours   = client["hours_billed"]
```

- [ ] **Step 3: `delete_document`.** After the `if not all([...])` check, insert:

```python
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
```

After `path.unlink()`, insert:

```python
    _log_access(client, "document_delete", f"{category}/{safe_name}")
    save_client(client)
```

- [ ] **Step 4: Download and preview routes.** At the top of `serve_document`, `preview_document` and `docx_preview`, insert before the existing `_resolve_doc_path` line. In `docx_preview`, place it before the `MAMMOTH_AVAILABLE` check:

```python
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
```

After the `if path is None: return ...` check in each, insert:

```python
    # serve_document:
    _log_access(client, "download_document", f"{category}/{path.name}")
    save_client(client)
```

```python
    # preview_document and docx_preview:
    _log_access(client, "preview_document", f"{category}/{path.name}")
    save_client(client)
```

- [ ] **Step 5: `portal_archive_lead`.** Replace the `try:` block's first two lines (`with open(lead_path) as f: lead = json.load(f)`) with:

```python
        with open(lead_path) as f:
            lead = json.load(f)
        if lead.get("assigned_attorney") != session["username"]:
            return jsonify({"error": "Lead not found."}), 404
```

- [ ] **Step 6: Research routes.**

`research_issue_spot`: replace

```python
    client    = load_client(username)
    case_type = client.get("case_type", "Civil Litigation") if client else "Civil Litigation"
```

with

```python
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    case_type = client.get("case_type", "Civil Litigation")
```

`research_draft`: move the username block above `ai = get_anthropic_client()` and make it:

```python
    case_type = "Civil Litigation"
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        case_type = client.get("case_type", "Civil Litigation")
```

Delete the old `case_type = ...` / `if username:` block further down.

`research_save_draft`: after `if not all([...]) ... 400`, insert

```python
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
```

Then delete the later `client = load_client(username)` line and change `if client:` to always run, dedenting its body. Change the return's `"total_hours": client["hours_billed"] if client else None` to `"total_hours": client["hours_billed"]`. Set `billing_entry` and `entry_rev` directly; drop the `= None` initialisers.

`research_save_report`: replace `client = load_client(username)` with `client = load_client_for_attorney(username)`.

- [ ] **Step 7: Run the full suite** — `python -m pytest tests -q` → all pass, including every `test_client_access.py` param and the sweep.

If the sweep flags a route not listed here, add the guard. Only add it to `NO_CLIENT_ROUTES` if the route genuinely never loads an existing client.

- [ ] **Step 8: Commit**

```bash
git add blueprints/portal_attorney.py
git commit -m "feat(security): enforce client assignment on document, research, and lead routes"
```

### Task 8: Portal page and dashboard — co-counsel visibility, no hashes in page source

**Files:**
- Modify: `blueprints/portal_attorney.py`: `attorney_portal` (~534), `portal_attorney_dashboard` (~553)
- Modify: `templates/attorney_portal.html`: sidebar client loops (~line 600 and ~668), `{% block styles %}`
- Create: `tests/test_no_hash_leak.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_no_hash_leak.py`:

```python
"""Password hashes never leave the server (spec A2)."""

import shared


def test_portal_page_has_no_hashes(attorney_session, make_client):
    make_client("victim", password=shared.hash_password("s3cret-pass"))
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert "$2b$" not in html
    assert '"password":' not in html          # no JSON password key in _ALL_CLIENTS_DATA


def test_client_json_has_no_password(attorney_session, make_client):
    make_client("victim", password=shared.hash_password("s3cret-pass"))
    for url in ("/portal/attorney/clients", "/portal/attorney/client/victim"):
        body = attorney_session.get(url).get_data(as_text=True)
        assert "$2b$" not in body and '"password"' not in body


def test_co_counsel_client_in_sidebar_with_badge(other_attorney_session, make_client):
    make_client("shared1", client_name="Shared Person", co_counsel=["SophiaH"])
    html = other_attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert "Shared Person" in html
    assert ">Co-counsel</span>" in html      # the badge element, not just the CSS rule
```

- [ ] **Step 2: Run them to verify they fail** — the hash is present in `_ALL_CLIENTS_DATA`, and the co-counsel client is missing from the sidebar.

- [ ] **Step 3: Rewrite `attorney_portal()`**

```python
@portal_attorney_bp.route("/attorney-portal")
@require_attorney
def attorney_portal():
    atty_user = session["username"]
    atty_info = ATTORNEYS[atty_user]

    def _view(c):
        v = public_client_view(c)
        v["is_co_counsel"] = c.get("assigned_attorney") != atty_user
        return v

    all_mine = [c for c in all_clients() if can_access_client(atty_user, c)]
    clients          = sorted([_view(c) for c in all_mine if not c.get("archived")],
                              key=lambda c: c.get("last_communication") or "", reverse=True)
    archived_clients = [_view(c) for c in all_mine if c.get("archived")]
    return render_template("attorney_portal.html",
                           clients=clients,
                           archived_clients=archived_clients,
                           attorney=atty_info,
                           attorneys=[{"username": u, "display": i["display"]}
                                      for u, i in ATTORNEYS.items()],
                           viewer=atty_user)
```

- [ ] **Step 4: Dashboard.** In `portal_attorney_dashboard`, change the `my_clients` filter from `if c.get("assigned_attorney") == atty_user` to `if can_access_client(atty_user, c)`. Leave insights and the tax export untouched: revenue stays with the assigned attorney.

- [ ] **Step 5: Sidebar badge.** In `templates/attorney_portal.html`, inside both sidebar client loops (`{% for c in clients %}` and `{% for c in archived_clients %}`), change the button text line `{{ c.client_name or c.username }}` to:

```html
          {{ c.client_name or c.username }}{% if c.is_co_counsel %} <span class="cc-badge">Co-counsel</span>{% endif %}
```

In the `{% block styles %}` `<style>` block, add:

```css
.cc-badge, .conflict-badge { display:inline-block; font-family:Arial,sans-serif; font-size:.62rem;
  letter-spacing:.04em; text-transform:uppercase; padding:.05rem .35rem; border-radius:3px;
  margin-left:.3rem; vertical-align:middle; }
.cc-badge { background:rgba(255,255,255,.12); color:rgba(255,255,255,.75); }
.conflict-badge { background:#f0c040; color:#3a2a00; }
```

- [ ] **Step 6: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add blueprints/portal_attorney.py templates/attorney_portal.html tests/test_no_hash_leak.py
git commit -m "fix(security): strip password hashes from portal page; show co-counsel clients"
```

### Task 9: Co-counsel endpoint

**Files:**
- Modify: `blueprints/portal_attorney.py` (new route after `portal_access_log`)
- Create: `tests/test_co_counsel.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Co-counsel management (spec A3)."""

import shared


def _post(c, **body):
    return c.post("/portal/attorney/co-counsel", json={"username": "victim", **body})


def test_assigned_attorney_adds_and_removes(attorney_session, make_client):
    make_client("victim")
    r = _post(attorney_session, action="add", attorney="SophiaH")
    assert r.status_code == 200 and r.get_json()["co_counsel"] == ["SophiaH"]
    log = shared.load_client("victim")["access_log"]
    assert log[-1]["action"] == "co_counsel_change"
    r = _post(attorney_session, action="remove", attorney="SophiaH")
    assert r.get_json()["co_counsel"] == []


def test_adding_twice_is_idempotent(attorney_session, make_client):
    make_client("victim")
    _post(attorney_session, action="add", attorney="SophiaH")
    assert _post(attorney_session, action="add", attorney="SophiaH").get_json()["co_counsel"] == ["SophiaH"]


def test_cannot_add_self_or_unknown(attorney_session, make_client):
    make_client("victim")
    assert _post(attorney_session, action="add", attorney="Endocide").status_code == 400
    assert _post(attorney_session, action="add", attorney="Ghost").status_code == 400
    assert _post(attorney_session, action="promote", attorney="SophiaH").status_code == 400


def test_co_counsel_cannot_change_list(other_attorney_session, make_client):
    make_client("victim", co_counsel=["SophiaH"])
    assert _post(other_attorney_session, action="remove", attorney="SophiaH").status_code == 404
```

- [ ] **Step 2: Run them to verify they fail** (404, because the route doesn't exist yet).

- [ ] **Step 3: Implement**

```python
@portal_attorney_bp.route("/portal/attorney/co-counsel", methods=["POST"])
@require_attorney
def portal_co_counsel():
    data   = request.get_json() or {}
    client = load_client_for_attorney(data.get("username", ""), assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    action   = data.get("action")
    attorney = (data.get("attorney") or "").strip()
    if action not in ("add", "remove"):
        return jsonify({"error": "Invalid action."}), 400
    if attorney not in ATTORNEYS or attorney == client.get("assigned_attorney"):
        return jsonify({"error": "Invalid attorney."}), 400
    cc = client.setdefault("co_counsel", [])
    if action == "add" and attorney not in cc:
        cc.append(attorney)
    elif action == "remove" and attorney in cc:
        cc.remove(attorney)
    _log_access(client, "co_counsel_change", f"{action} {attorney}")
    save_client(client)
    return jsonify({"success": True, "co_counsel": cc})
```

- [ ] **Step 4: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add blueprints/portal_attorney.py tests/test_co_counsel.py
git commit -m "feat(security): co-counsel add/remove endpoint"
```

### Task 10: No default passwords on create-client

**Files:**
- Modify: `shared.py` (password helpers)
- Modify: `blueprints/portal_attorney.py`: `portal_create_client` (~866–872 and the return)
- Modify: `templates/attorney_portal.html`: line ~1341 (`nc-password` input), ~2908 (reset), ~2916 and ~2940 (`createClient`)
- Test: `tests/test_no_hash_leak.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_create_client_without_password_generates_one(attorney_session):
    r = attorney_session.post("/portal/attorney/create-client",
                              json={"username": "newbie", "client_name": "New Bie"})
    d = r.get_json()
    assert d["success"] and len(d["temp_password"]) >= 8
    rec = shared.load_client("newbie")
    assert shared.check_password(d["temp_password"], rec["password"])
    assert not shared.check_password("password", rec["password"])
    assert rec["must_change_password"] is True


def test_create_client_rejects_weak_password(attorney_session):
    d = attorney_session.post("/portal/attorney/create-client", json={
        "username": "weak", "client_name": "W", "password": "password",
        "must_change_password": False}).get_json()
    assert d["temp_password"] != "password"
    assert shared.load_client("weak")["must_change_password"] is True


def test_create_client_keeps_acceptable_password(attorney_session):
    d = attorney_session.post("/portal/attorney/create-client", json={
        "username": "ok1", "client_name": "O", "password": "Tr1cky-Horse"}).get_json()
    assert d["temp_password"] == "Tr1cky-Horse"


def test_portal_page_has_no_default_password(attorney_session):
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert 'value="password"' not in html and '|| "password"' not in html


def test_acceptable_password():
    assert shared.acceptable_password("Tr1cky-Horse", "jdoe")
    assert not shared.acceptable_password("short", "jdoe")
    assert not shared.acceptable_password("PASSWORD", "jdoe")
    assert not shared.acceptable_password("jdoe1234", "jdoe1234")
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Add the helper to `shared.py`** (after `MIN_PASSWORD_LENGTH`):

```python
_WEAK_PASSWORDS = frozenset({"password", "password1", "12345678", "changeme"})


def acceptable_password(pw: str, username: str) -> bool:
    pw = pw or ""
    return (len(pw) >= MIN_PASSWORD_LENGTH
            and pw.lower() not in _WEAK_PASSWORDS
            and pw.lower() != (username or "").lower())
```

- [ ] **Step 4: Update `portal_create_client`.** Add `acceptable_password, generate_temp_password,` to the `shared` imports. Replace

```python
    raw_password = data.get("password", "password") or "password"
```

with

```python
    posted_password = (data.get("password") or "").strip()
    temp_password   = (posted_password if acceptable_password(posted_password, username)
                       else generate_temp_password())
```

In `record`, replace `"password": hash_password(raw_password),` with `"password": hash_password(temp_password),`, and replace `"must_change_password": data.get("must_change_password", True),` with `"must_change_password": True,`. In the final `return jsonify(...)`, add `"temp_password": temp_password,`.

- [ ] **Step 5: Update the template.**
  - Line ~1341: replace `<input type="text" id="nc-password" value="password" ...` with `<input type="text" id="nc-password" value="" placeholder="Leave blank to generate one" style="width:100%;box-sizing:border-box" />`.
  - Line ~2908 (`resetNewClientForm`): `document.getElementById("nc-password").value   = "password";` (three spaces before `=`) becomes `document.getElementById("nc-password").value   = "";`.
  - Line ~2916: `const password = document.getElementById("nc-password").value.trim() || "password";` becomes `const password = document.getElementById("nc-password").value.trim();`.
  - Line ~2940: `document.getElementById("nc-success-password").textContent = password;` becomes `document.getElementById("nc-success-password").textContent = d.temp_password || "";`.

- [ ] **Step 6: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add shared.py blueprints/portal_attorney.py templates/attorney_portal.html tests/test_no_hash_leak.py
git commit -m "fix(security): no default 'password' on attorney-created clients"
```

### Task 11: Public calendar route stops touching client records

**Files:**
- Modify: `blueprints/calendar.py`: imports and the `for c in all_clients()` loop
- Create: `tests/test_calendar_schedule.py`

- [ ] **Step 1: Write the failing tests**

```python
"""/calendar/schedule is public; only attorneys may tie it to a client (spec A1)."""

import pytest

import blueprints.calendar as cal
import shared


class _Events:
    def insert(self, **kw):
        return self

    def execute(self):
        return {"htmlLink": "https://calendar.example/x"}


class _Service:
    def events(self):
        return _Events()


@pytest.fixture(autouse=True)
def fake_gcal(monkeypatch):
    monkeypatch.setattr(cal, "get_calendar_service", lambda: _Service())


BODY = {"client_name": "Test Client", "date": "2026-11-02", "time": "10:00"}


def test_anonymous_cannot_touch_client(client, make_client):
    make_client("victim")
    assert client.post("/calendar/schedule", json=BODY).status_code == 200
    assert shared.load_client("victim")["activity_log"] == []


def test_attorney_logs_on_accessible_client(attorney_session, make_client):
    make_client("victim")
    attorney_session.post("/calendar/schedule", json=BODY)
    assert shared.load_client("victim")["activity_log"][-1]["action_type"] == "meeting_scheduled"


def test_attorney_cannot_log_on_inaccessible_client(other_attorney_session, make_client):
    make_client("victim")
    other_attorney_session.post("/calendar/schedule", json=BODY)
    assert shared.load_client("victim")["activity_log"] == []
```

- [ ] **Step 2: Run them to verify they fail.** `test_anonymous_cannot_touch_client` and the inaccessible-client test both fail.

- [ ] **Step 3: Implement.** In `blueprints/calendar.py`, change `from flask import Blueprint, request, jsonify` to `from flask import Blueprint, request, jsonify, session`, and add `can_access_client` to the `shared` import. Replace the `for c in all_clients():` loop with:

```python
        if session.get("role") == "attorney":
            atty = session.get("username", "")
            for c in all_clients():
                if not can_access_client(atty, c):
                    continue
                if (c.get("client_name") or "").strip().lower() == client_name.strip().lower():
                    notes_short = (notes[:80] + "...") if len(notes) > 80 else notes
                    _log_activity(
                        c.get("username", ""), "meeting_scheduled",
                        f"Meeting scheduled: {date_str} at {time_str}"
                        + (f" — {notes_short}" if notes_short else "") + ".",
                    )
                    break
```

- [ ] **Step 4: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add blueprints/calendar.py tests/test_calendar_schedule.py
git commit -m "fix(security): public calendar booking no longer writes to client files"
```

---

## Chunk 3: Authentication, sessions, CSRF

### Task 12: `security.py` — login throttling

**Files:**
- Create: `security.py`, `tests/test_login_throttle.py`
- Modify: `blueprints/auth.py`, `blueprints/drafting.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_login_throttle.py`:

```python
"""5 failures in 15 minutes locks a username+IP for 15 minutes (spec B1)."""

import pytest

import security
import shared


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1_000_000.0}
    monkeypatch.setattr(security, "_now", lambda: t["now"])
    return t


@pytest.fixture
def atty_pw(monkeypatch):
    monkeypatch.setitem(shared.ATTORNEYS["Endocide"], "password",
                        shared.hash_password("correct-horse"))


def _login(c, pw):
    return c.post("/attorney-login", data={"username": "Endocide", "password": pw})


def test_unit_lock_after_five(clock):
    for _ in range(4):
        security.record_login_failure("client", "Bob", "1.1.1.1")
    assert security.login_locked("client", "bob", "1.1.1.1") == 0
    security.record_login_failure("client", "Bob", "1.1.1.1")
    assert security.login_locked("client", "bob", "1.1.1.1") > 0
    assert security.login_locked("client", "bob", "2.2.2.2") == 0
    clock["now"] += 15 * 60 + 1
    assert security.login_locked("client", "bob", "1.1.1.1") == 0


def test_failures_outside_window_do_not_count(clock):
    for _ in range(4):
        security.record_login_failure("client", "bob", "ip")
    clock["now"] += 16 * 60
    security.record_login_failure("client", "bob", "ip")
    assert security.login_locked("client", "bob", "ip") == 0


def test_attorney_login_locks_and_rejects_correct_password(client, clock, atty_pw):
    for _ in range(5):
        assert _login(client, "wrong").status_code == 200
    r = _login(client, "correct-horse")
    assert r.status_code == 429
    assert b"Too many failed attempts" in r.data


def test_success_clears_failures(client, clock, atty_pw):
    for _ in range(4):
        _login(client, "wrong")
    assert _login(client, "correct-horse").status_code == 302
    for _ in range(4):
        _login(client, "wrong")
    assert _login(client, "correct-horse").status_code == 302


def test_client_login_throttled(client, clock, make_client):
    make_client("jdoe", password=shared.hash_password("right-pass"))
    for _ in range(5):
        client.post("/client-login", data={"username": "jdoe", "password": "nope"})
    r = client.post("/client-login", data={"username": "jdoe", "password": "right-pass"})
    assert r.status_code == 429


def test_claim_document_throttled(client, clock, make_client):
    make_client("tclient", client_name="Test Client", password=shared.hash_password("right-pass"))
    body = {"full_name": "Test Client", "password": "wrong-pass", "draft_content": "<p>x</p>"}
    for _ in range(5):
        assert client.post("/drafting/claim-document", json=body).status_code == 403
    body["password"] = "right-pass"
    assert client.post("/drafting/claim-document", json=body).status_code == 429


def test_corrupt_state_file_is_treated_as_empty(clock):
    security._failures_path().write_text("{not json")
    assert security.login_locked("client", "bob", "ip") == 0
    security.record_login_failure("client", "bob", "ip")
```

(`base_username("Test Client")` is `tclient`, which is why the claim test seeds that username.)

- [ ] **Step 2: Run them to verify they fail** — `ModuleNotFoundError: security`.

- [ ] **Step 3: Create `security.py`** (throttling part; Tasks 13–15 extend it):

```python
"""security.py — login throttling, session hardening, CSRF, security headers.

Wire into the app with security.init_app(app).
"""

import json
import sys
import threading
import time

import shared

MAX_FAILURES   = 5
WINDOW_SECONDS = 15 * 60
LOCK_SECONDS   = 15 * 60

_state_lock = threading.Lock()


def _now() -> float:
    """Indirection so tests can move the clock."""
    return time.time()


# ── Login throttling ──────────────────────────────────────────────────────────

def _failures_path():
    return shared.SECURITY_STATE_DIR / "login-failures.json"


def _load_failures() -> dict:
    path = _failures_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"[warn] {path.name} unreadable — starting fresh", file=sys.stderr)
        return {}


def _save_failures(data: dict) -> None:
    now  = _now()
    keep = {k: v for k, v in data.items()
            if v.get("locked_until", 0) > now
            or any(now - t < 3600 for t in v.get("failures", []))}
    path = _failures_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep), encoding="utf-8")


def _key(kind: str, username: str, ip: str) -> str:
    return f"{kind}:{(username or '').strip().lower()}:{ip or ''}"


def login_locked(kind: str, username: str, ip: str) -> int:
    """Seconds until this kind/username/IP may try again; 0 if not locked."""
    with _state_lock:
        entry = _load_failures().get(_key(kind, username, ip))
    if not entry:
        return 0
    remaining = entry.get("locked_until", 0) - _now()
    return int(remaining) + 1 if remaining > 0 else 0


def record_login_failure(kind: str, username: str, ip: str) -> None:
    now = _now()
    with _state_lock:
        data  = _load_failures()
        entry = data.setdefault(_key(kind, username, ip), {"failures": [], "locked_until": 0})
        entry["failures"] = [t for t in entry["failures"] if now - t < WINDOW_SECONDS] + [now]
        if len(entry["failures"]) >= MAX_FAILURES:
            entry["locked_until"] = now + LOCK_SECONDS
            entry["failures"]     = []
        _save_failures(data)


def clear_login_failures(kind: str, username: str, ip: str) -> None:
    with _state_lock:
        data = _load_failures()
        if data.pop(_key(kind, username, ip), None) is not None:
            _save_failures(data)


def lockout_message(seconds: int) -> str:
    minutes = max(1, -(-seconds // 60))
    return f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."
```

- [ ] **Step 4: Wire into `blueprints/auth.py`.** Add `from security import login_locked, record_login_failure, clear_login_failures, lockout_message`. Replace the `if request.method == "POST":` blocks of both views.

`attorney_login`:

```python
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        ip       = request.remote_addr or ""
        wait     = login_locked("attorney", username, ip)
        if wait:
            return render_template("attorney_login.html", error=lockout_message(wait)), 429
        atty = ATTORNEYS.get(username)
        if atty and check_password(password, atty["password"]):
            clear_login_failures("attorney", username, ip)
            session["role"]     = "attorney"
            session["username"] = username
            return redirect(url_for("portal_attorney.attorney_portal"))
        record_login_failure("attorney", username, ip)
        error = "Invalid username or password."
```

`client_login`: same shape with kind `"client"`, template `client_login.html`, the existing `load_client` / `upgrade_password_if_needed` / `must_change_password` redirect logic inside the success branch, and `clear_login_failures("client", username, ip)` as its first line. (Task 13 replaces the two `session[...] =` lines in both views.)

- [ ] **Step 5: Wire into `drafting_claim_document`.** Add `from security import login_locked, record_login_failure, clear_login_failures, lockout_message`. Replace

```python
    existing = load_client(base_username(full_name))
    if existing and not check_password(password, existing.get("password", "")):
        return jsonify({
```

with

```python
    claim_user = base_username(full_name)
    ip         = request.remote_addr or ""
    wait       = login_locked("claim", claim_user, ip)
    if wait:
        return jsonify({"error": lockout_message(wait)}), 429
    existing = load_client(claim_user)
    if existing and not check_password(password, existing.get("password", "")):
        record_login_failure("claim", claim_user, ip)
        return jsonify({
```

Then directly after that 403 `return` block, add:

```python
    if existing:
        clear_login_failures("claim", claim_user, ip)
```

- [ ] **Step 6: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add security.py blueprints/auth.py blueprints/drafting.py tests/test_login_throttle.py
git commit -m "feat(security): throttle attorney, client, and claim-document logins"
```

### Task 13: Session hardening

**Files:**
- Modify: `security.py`, `app.py`, `blueprints/auth.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_session.py`:

```python
"""Session fixation, idle timeout, cookie flags (spec B2)."""

import pytest

import security
import shared
from conftest import flask_app


@pytest.fixture
def atty_pw(monkeypatch):
    monkeypatch.setitem(shared.ATTORNEYS["Endocide"], "password",
                        shared.hash_password("correct-horse"))


def test_login_resets_session_but_keeps_share_auth(client, atty_pw):
    with client.session_transaction() as s:
        s["planted"] = "attacker"
        s["share_authed"] = True
    client.post("/attorney-login", data={"username": "Endocide", "password": "correct-horse"})
    with client.session_transaction() as s:
        assert "planted" not in s
        assert s["share_authed"] is True
        assert s["role"] == "attorney" and "last_seen" in s


def test_login_cookie_flags(client, atty_pw):
    r = client.post("/attorney-login", data={"username": "Endocide", "password": "correct-horse"})
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_idle_session_json_gets_401(attorney_session):
    with attorney_session.session_transaction() as s:
        s["last_seen"] = security._now() - 31 * 60
    r = attorney_session.get("/portal/attorney/dashboard")
    assert r.status_code == 401
    assert r.headers["X-Session-Expired"] == "1"
    assert r.headers["X-Login-Url"].endswith("/attorney-login")
    with attorney_session.session_transaction() as s:
        assert "role" not in s


def test_idle_session_html_redirects(client_session):
    with client_session.session_transaction() as s:
        s["last_seen"] = security._now() - 31 * 60
    r = client_session.get("/client-portal", headers={"Accept": "text/html"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/client-login")


def test_active_session_refreshes_last_seen(attorney_session):
    with attorney_session.session_transaction() as s:
        s["last_seen"] = security._now() - 10 * 60
    attorney_session.get("/portal/attorney/token-usage")
    with attorney_session.session_transaction() as s:
        assert security._now() - s["last_seen"] < 5


def test_missing_last_seen_is_treated_as_fresh(attorney_session):
    assert attorney_session.get("/portal/attorney/token-usage").status_code == 200


def test_session_lifetime_configured():
    assert flask_app.permanent_session_lifetime.total_seconds() == 30 * 60
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Extend `security.py`.** Change the imports to

```python
import json
import sys
import threading
import time

from flask import jsonify, redirect, request, session, url_for

import shared
```

and append:

```python
# ── Sessions ──────────────────────────────────────────────────────────────────

IDLE_SECONDS = 30 * 60


def reset_session() -> None:
    """Clear the session but keep shared-mode Basic-Auth (require_auth's
    share_authed flag) — otherwise the next fetch() hits a 401 prompt."""
    share = session.get("share_authed")
    session.clear()
    if share:
        session["share_authed"] = True


def start_login_session(role: str, username: str) -> None:
    reset_session()                      # new session on login: blocks fixation
    session["role"]      = role
    session["username"]  = username
    session["last_seen"] = _now()
    session.permanent    = True


def enforce_idle_timeout():
    """before_request: expire sessions idle for more than 30 minutes."""
    role = session.get("role")
    if not role:
        return None
    now  = _now()
    last = session.get("last_seen")
    if last is not None and now - last > IDLE_SECONDS:
        reset_session()
        login = url_for("auth.attorney_login" if role == "attorney" else "auth.client_login")
        if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
            return redirect(login)
        resp = jsonify({"error": "Session expired."})
        resp.status_code = 401
        resp.headers["X-Session-Expired"] = "1"
        resp.headers["X-Login-Url"]       = login
        return resp
    session["last_seen"] = now
    return None


def init_app(app) -> None:
    app.before_request(enforce_idle_timeout)
```

- [ ] **Step 4: `app.py`.** Add `from datetime import timedelta` and `import security`. After the `app.config["TEMPLATES_AUTO_RELOAD"] = True` line, add:

```python
app.config.update(
    SESSION_COOKIE_HTTPONLY    = True,
    SESSION_COOKIE_SAMESITE    = "Lax",
    # Shared mode serves HTTPS (see __main__), so the cookie can be Secure there.
    SESSION_COOKIE_SECURE      = bool(os.getenv("SHARE_PASSWORD", "").strip()),
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30),
)
security.init_app(app)
```

- [ ] **Step 5: `auth.py`.** Import `start_login_session` from `security`. In both login views, replace the two lines `session["role"] = ...` / `session["username"] = username` with `start_login_session("attorney", username)` (or `"client"`). Leave `/logout`'s full `session.clear()` as-is.

- [ ] **Step 6: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add security.py app.py blueprints/auth.py tests/test_session.py
git commit -m "feat(security): session fixation fix, 30-min idle timeout, cookie flags"
```

### Task 14: CSRF protection and the fetch shim

**Files:**
- Modify: `security.py`, `templates/base.html` (`<head>`), `templates/attorney_login.html`, `templates/client_login.html`, `templates/change_password.html`
- Create: `tests/test_csrf.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_csrf.py`:

```python
"""CSRF token required on state-changing requests (spec B3)."""

import pytest

from conftest import flask_app


@pytest.fixture(autouse=True)
def csrf_on(monkeypatch):
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", True)


def _set_token(c, tok="tok123"):
    with c.session_transaction() as s:
        s["_csrf"] = tok
    return tok


def test_post_without_token_rejected(attorney_session, make_client):
    make_client("victim")
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "victim", "note": "x", "hours": 1})
    assert r.status_code == 400
    assert r.get_json() == {"error": "Invalid or missing CSRF token."}
    assert r.headers["X-CSRF-Failed"] == "1"


def test_post_with_header_accepted(attorney_session, make_client):
    make_client("victim")
    tok = _set_token(attorney_session)
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "victim", "note": "x", "hours": 1},
                              headers={"X-CSRF-Token": tok})
    assert r.status_code == 200


def test_wrong_token_rejected(attorney_session, make_client):
    make_client("victim")
    _set_token(attorney_session)
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "victim", "note": "x", "hours": 1},
                              headers={"X-CSRF-Token": "nope"})
    assert r.status_code == 400


def test_login_form_field_accepted(client):
    tok = _set_token(client)
    r = client.post("/attorney-login", data={"username": "x", "password": "y", "csrf_token": tok})
    assert r.status_code == 200  # wrong password, but not a CSRF failure


# /api/track-visit is also exempt but is left out here: posting to it writes
# the real page-visits.json, which conftest does not redirect.
@pytest.mark.parametrize("path", ["/webhooks/stripe", "/webhooks/coinbase", "/intake/submit",
                                  "/client-register", "/chat/message", "/capture/lead",
                                  "/follow-up/schedule"])
def test_exempt_paths(client, path):
    assert any(rule.rule == path for rule in flask_app.url_map.iter_rules()), path
    r = client.post(path, json={})
    assert r.headers.get("X-CSRF-Failed") is None


def test_get_never_checked(attorney_session):
    assert attorney_session.get("/portal/attorney/token-usage").status_code == 200


def test_pages_render_token_and_shim(client):
    html = client.get("/attorney-login").get_data(as_text=True)
    assert 'name="csrf-token"' in html
    assert 'name="csrf_token"' in html
    head = html.split("</head>")[0]
    assert "window.fetch = window.apiFetch" in head
    # The shim must run before any page script that could call fetch().
    assert head.index("window.fetch = window.apiFetch") < html.index("js/app.js")
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Extend `security.py`.** Add `import hmac` and `import secrets` to the imports, add `current_app` to the flask import, and append:

```python
# ── CSRF ──────────────────────────────────────────────────────────────────────

# Webhooks are signature-verified; the rest are anonymous public endpoints
# that act on no session. Everything else that changes state needs a token.
CSRF_EXEMPT_PATHS = frozenset({
    "/webhooks/stripe", "/webhooks/coinbase",
    "/intake/submit", "/client-register", "/chat/message",
    "/capture/lead", "/follow-up/schedule", "/api/track-visit",
})


def csrf_token() -> str:
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def csrf_protect():
    """before_request: reject state-changing requests without a valid token."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if not current_app.config.get("CSRF_ENABLED", True):
        return None
    if request.path in CSRF_EXEMPT_PATHS:
        return None
    sent     = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("_csrf", "")
    if expected and sent and hmac.compare_digest(sent, expected):
        return None
    resp = jsonify({"error": "Invalid or missing CSRF token."})
    resp.status_code = 400
    resp.headers["X-CSRF-Failed"] = "1"
    return resp
```

Update `init_app` (order matters: an expired session must get the 401, not a CSRF 400):

```python
def init_app(app) -> None:
    app.config.setdefault("CSRF_ENABLED", True)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(enforce_idle_timeout)
    app.before_request(csrf_protect)
```

- [ ] **Step 4: `templates/base.html`.** Directly after the `<meta name="viewport" ...>` line, insert:

```html
  <meta name="csrf-token" content="{{ csrf_token() }}" />
  <script>
  // Adds the CSRF token to every same-origin state-changing fetch() and sends
  // the user to the login page when the server reports an expired session.
  // Installed as window.fetch so every existing call site is covered.
  (function () {
    var nativeFetch = window.fetch.bind(window);
    function token() {
      var m = document.querySelector('meta[name="csrf-token"]');
      return m ? m.getAttribute("content") : "";
    }
    window.apiFetch = function (input, opts) {
      opts = opts || {};
      var url    = typeof input === "string" ? input : input.url;
      var method = (opts.method || (input && input.method) || "GET").toUpperCase();
      var same   = new URL(url, location.href).origin === location.origin;
      if (same && method !== "GET" && method !== "HEAD") {
        var headers = new Headers(opts.headers || {});
        headers.set("X-CSRF-Token", token());
        opts = Object.assign({}, opts, { headers: headers });
      }
      return nativeFetch(input, opts).then(function (resp) {
        if (same && resp.status === 401 && resp.headers.get("X-Session-Expired")) {
          location.href = resp.headers.get("X-Login-Url") || "/";
        } else if (same && resp.status === 400 && resp.headers.get("X-CSRF-Failed")) {
          alert("Your session changed — please reload the page and try again.");
        }
        return resp;
      });
    };
    window.fetch = window.apiFetch;
  })();
  </script>
```

- [ ] **Step 5: Hidden fields.** In `attorney_login.html`, `client_login.html` and `change_password.html`, add this as the first child of each `<form method="POST" ...>`:

```html
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />
```

- [ ] **Step 6: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 7: Manual browser check.**
  1. Start the app: `python app.py`, with `SECRET_KEY` set in `.env`.
  2. Log in as an attorney and add a billing entry. It should save.
  3. Then, in devtools, run `document.querySelector('meta[name=csrf-token]').content='x'` and add another entry. Expect the "reload the page" alert and no save.
  4. Log in as a client and send a message. It should save.

- [ ] **Step 8: Commit**

```bash
git add security.py templates/base.html templates/attorney_login.html templates/client_login.html templates/change_password.html tests/test_csrf.py
git commit -m "feat(security): CSRF tokens on all state-changing requests"
```

### Task 15: Security headers, decrypt-error handler, startup checks

**Files:**
- Modify: `security.py`, `app.py`
- Create: `tests/test_startup.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    assert app_module.check_startup_config() == []
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: `security.py`** — append:

```python
# ── Headers ───────────────────────────────────────────────────────────────────

def set_security_headers(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp
```

and add `app.after_request(set_security_headers)` as the last line of `init_app`.

- [ ] **Step 4: `app.py`.** Add `import shared` and change the flask import to `from flask import Flask, jsonify`. After `security.init_app(app)`:

```python
@app.errorhandler(shared.RecordDecryptError)
def _record_decrypt_error(exc):
    print(f"[error] could not decrypt client record: {exc}", flush=True)
    return jsonify({"error": "Client record could not be decrypted."}), 500


def check_startup_config() -> list:
    """Return human-readable problems that must be fixed before serving."""
    problems = []
    if not os.getenv("SECRET_KEY", "").strip():
        problems.append(
            "SECRET_KEY is not set in .env. Generate one with:\n"
            '    python -c "import secrets; print(secrets.token_hex(32))"')
    if not os.getenv("DATA_ENCRYPTION_KEY", "").strip():
        problems.append(
            "DATA_ENCRYPTION_KEY is not set in .env. Generate one with:\n"
            "    python scripts/generate_data_key.py\n"
            "  Back the key up OUTSIDE this folder — if it is lost, encrypted\n"
            "  client records cannot be recovered.")
    return problems
```

At the very top of the `if __name__ == "__main__":` block, before `sharing = ...`, insert:

```python
    problems = check_startup_config()
    if problems:
        print("\nCannot start — fix these in .env:\n")
        for p in problems:
            print("  * " + p + "\n")
        raise SystemExit(1)
    upgraded = shared.upgrade_all_plaintext_passwords()
    if upgraded:
        print(f"Secured {len(upgraded)} plaintext client password(s); those clients "
              "must choose a new password at next login.")
```

- [ ] **Step 5: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add security.py app.py tests/test_startup.py
git commit -m "feat(security): security headers, decrypt-error handler, startup config checks"
```

---

## Chunk 4: Conflict checker

### Task 16: Name normalisation and similarity

**Files:**
- Create: `conflicts.py`, `tests/test_conflicts.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_conflicts.py`:

```python
"""Fuzzy conflict matching (spec D2)."""

import pytest

import conflicts


@pytest.mark.parametrize("raw,expected", [
    ("Robert Smith Jr.", "robert smith"),
    ("Bob  SMITH", "robert smith"),
    ("Acme Roofing, LLC", "acme roofing"),
    ("Dr. Elizabeth O'Neil", "elizabeth o neil"),
    ("", ""),
])
def test_normalise_name(raw, expected):
    assert conflicts.normalise_name(raw) == expected


@pytest.mark.parametrize("a,b,level", [
    ("Bob Smith", "Robert Smith Jr.", "likely"),
    ("Smith, Robert", "Robert Smith", "likely"),
    ("Acme Roofing LLC", "ACME Roofing", "likely"),
    ("Jon Smith", "John Smith", "likely"),
    ("Smith", "Smith", "possible"),            # single token: capped, never "likely"
    ("Smith", "John Smith", None),             # surname alone never flags
    ("Alice Morris", "Derek Williams", None),
])
def test_similarity_levels(a, b, level):
    assert conflicts.level_for(conflicts.name_similarity(a, b)) == level
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Create `conflicts.py`**

```python
"""conflicts.py — fuzzy conflict-of-interest checks across clients, parties, and leads.

Used by intake, client creation, self-registration, the manual Conflict Check
tool, and client edits. Every check is recorded (see make_check_record).
"""

import json
import re
import secrets
import sys
import threading
from datetime import datetime
from difflib import SequenceMatcher

import shared

LIKELY           = 0.85
POSSIBLE         = 0.70
SINGLE_TOKEN_CAP = 0.75   # one-word names can be "possible" at most

_DROP_WORDS = frozenset({
    "mr", "mrs", "ms", "dr", "jr", "sr", "ii", "iii", "iv", "esq",
    "llc", "inc", "corp", "co", "ltd", "lp", "llp", "pllc", "company", "corporation",
})

_NICKNAMES = {
    "bob": "robert", "bobby": "robert", "rob": "robert", "robbie": "robert",
    "bill": "william", "billy": "william", "will": "william",
    "rick": "richard", "rich": "richard", "dick": "richard",
    "jim": "james", "jimmy": "james",
    "jack": "john", "johnny": "john",
    "liz": "elizabeth", "beth": "elizabeth", "betsy": "elizabeth",
    "kate": "katherine", "kathy": "katherine", "katie": "katherine",
    "maggie": "margaret", "peggy": "margaret",
    "mike": "michael", "chris": "christopher", "tony": "anthony", "joe": "joseph",
    "tom": "thomas", "tommy": "thomas", "dan": "daniel", "danny": "daniel",
    "jen": "jennifer", "jenny": "jennifer", "pat": "patricia", "patty": "patricia",
    "alex": "alexander",
}


def normalise_name(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    return " ".join(_NICKNAMES.get(t, t) for t in tokens if t not in _DROP_WORDS)


def name_similarity(a: str, b: str) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    direct    = SequenceMatcher(None, na, nb).ratio()
    tokenwise = SequenceMatcher(None, " ".join(sorted(na.split())),
                                " ".join(sorted(nb.split()))).ratio()
    score = max(direct, tokenwise)
    if len(na.split()) == 1 or len(nb.split()) == 1:
        score = min(score, SINGLE_TOKEN_CAP)
    return round(score, 3)


def level_for(score: float):
    if score >= LIKELY:
        return "likely"
    if score >= POSSIBLE:
        return "possible"
    return None
```

- [ ] **Step 4: Run** `python -m pytest tests/test_conflicts.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add conflicts.py tests/test_conflicts.py
git commit -m "feat(conflicts): name normalisation and fuzzy similarity"
```

### Task 17: Search, records, redaction, firm log

**Files:**
- Modify: `conflicts.py`
- Test: `tests/test_conflicts.py` (append)

- [ ] **Step 1: Write the failing tests.** Add these imports to the **top** of `tests/test_conflicts.py`, beside `import pytest`:

```python
import json

import shared
from conftest import flask_app
```

Then append:

```python
def _with_viewer(username):
    ctx = flask_app.test_request_context("/")
    ctx.push()
    shared.session["role"] = "attorney"
    shared.session["username"] = username
    return ctx


def test_sources(make_client, tmp_path):
    make_client("c1", client_name="Robert Smith", opposing_parties=["Acme Roofing LLC"],
                related_parties=[{"name": "Dana Morris", "relationship": "Spouse"}])
    make_client("c2", client_name="Old Client", archived=True)
    (tmp_path / "leads" / "l1.json").write_text(json.dumps(
        {"name": "Lena Lead", "case_type": "Real Estate", "assigned_attorney": "SophiaH"}))
    (tmp_path / "leads" / "l2.json").write_text(json.dumps(
        {"name": "Archived Lead", "archived": True}))

    def src(name):
        return [h["source"] for h in conflicts.run_conflict_check(other_names=[name])]

    assert src("Bob Smith") == ["client"]
    assert src("ACME Roofing") == ["opposing_party"]
    assert src("Dana Morris") == ["related_party"]
    assert src("Old Client") == ["former_client"]
    assert src("Lena Lead") == ["lead"]
    assert src("Archived Lead") == []


def test_exclude_username(make_client):
    make_client("c1", client_name="Robert Smith")
    assert conflicts.run_conflict_check(client_names=["Robert Smith"], exclude_username="c1") == []


def test_adverse_flags(make_client):
    make_client("c1", client_name="Robert Smith", opposing_parties=["Acme Roofing"])
    opp = conflicts.run_conflict_check(opposing_names=["Robert Smith"])
    assert opp[0]["adverse"] is True
    cli = conflicts.run_conflict_check(client_names=["Acme Roofing"])
    assert cli[0]["adverse"] is True
    other = conflicts.run_conflict_check(other_names=["Robert Smith"])
    assert other[0]["adverse"] is False


def test_likely_sorted_first(make_client):
    make_client("c1", client_name="John Smith")
    make_client("c2", client_name="Jon Smith")
    hits = conflicts.run_conflict_check(other_names=["John Smith"])
    assert hits[0]["matched_name"] == "John Smith"


def test_redaction_for_inaccessible_client(make_client):
    make_client("c1", client_name="Robert Smith", assigned_attorney="Endocide",
                related_parties=[{"name": "Dana Morris", "relationship": "Spouse"}])
    hits = conflicts.run_conflict_check(other_names=["Dana Morris"])
    ctx = _with_viewer("SophiaH")
    try:
        red = conflicts.redact_hits(hits, "SophiaH")[0]
    finally:
        ctx.pop()
    assert set(red) == set(conflicts.PUBLIC_HIT_FIELDS)
    assert red["assigned_attorney_display"] == shared.ATTORNEYS["Endocide"]["display"]
    full = conflicts.redact_hits(hits, "Endocide")[0]
    assert full["username"] == "c1" and full["relationship"] == "Spouse"


def test_record_check_appends_to_client(make_client):
    make_client("c1", client_name="Robert Smith")
    new = {"username": "newc"}
    rec = conflicts.record_check(new, "create", "Endocide", client_names=["Bob Smith", ""])
    assert new["conflict_checks"] == [rec]
    assert rec["names"] == ["Bob Smith"] and rec["decision"] is None
    assert rec["id"].startswith("cc_") and len(rec["hits"]) == 1
    assert conflicts.has_unresolved_conflict(new)
    rec["decision"] = "cleared"
    assert not conflicts.has_unresolved_conflict(new)


def test_firm_log_capped_and_redacted(make_client, tmp_path, monkeypatch):
    make_client("c1", client_name="Robert Smith")
    monkeypatch.setattr(conflicts, "_FIRM_LOG_MAX", 3)
    for _ in range(5):
        hits = conflicts.run_conflict_check(other_names=["Robert Smith"])
        conflicts.append_firm_log(conflicts.make_check_record("manual", "Endocide",
                                                              ["Robert Smith"], hits))
    log = json.loads((tmp_path / "security" / "conflict-checks.json").read_text())
    assert len(log) == 3
    assert "username" not in log[0]["hits"][0]


def test_clean_names_and_related():
    assert conflicts.clean_names([" A ", "", "a", None, "B" * 300]) == ["A", "B" * 200]
    assert conflicts.clean_related([{"name": " X ", "relationship": "Spouse"},
                                    {"name": ""}, "junk"]) == \
           [{"name": "X", "relationship": "Spouse"}]
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Append to `conflicts.py`**

```python
# ── Search ────────────────────────────────────────────────────────────────────

def _display(attorney: str) -> str:
    return shared.ATTORNEYS.get(attorney, {}).get("display", attorney or "")


def _candidates(exclude_username=None):
    for c in shared.all_clients():
        uname = c.get("username")
        if uname == exclude_username:
            continue
        atty = c.get("assigned_attorney", "")
        base = {"username": uname, "lead_file": None, "relationship": None,
                "matter": c.get("case_type", ""), "assigned_attorney": atty,
                "assigned_attorney_display": _display(atty)}
        if c.get("client_name"):
            yield dict(base, matched_name=c["client_name"],
                       source="former_client" if c.get("archived") else "client")
        for opp in c.get("opposing_parties") or []:
            yield dict(base, matched_name=opp, source="opposing_party")
        for rel in c.get("related_parties") or []:
            if isinstance(rel, dict) and rel.get("name"):
                yield dict(base, matched_name=rel["name"], source="related_party",
                           relationship=rel.get("relationship", ""))
    for path in sorted(shared.LEADS_DIR.glob("*.json")):
        try:
            lead = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if lead.get("archived") or not lead.get("name"):
            continue
        atty = lead.get("assigned_attorney", "")
        yield {"username": None, "lead_file": path.name, "relationship": None,
               "matter": lead.get("case_type", ""), "assigned_attorney": atty,
               "assigned_attorney_display": _display(atty),
               "matched_name": lead["name"], "source": "lead"}


def run_conflict_check(client_names=(), opposing_names=(), related_names=(),
                       other_names=(), exclude_username=None) -> list:
    searched = ([(n, "client") for n in clean_names(client_names)]
                + [(n, "opposing") for n in clean_names(opposing_names)]
                + [(n, "related") for n in clean_names(related_names)]
                + [(n, "other") for n in clean_names(other_names)])
    if not searched:
        return []
    candidates = list(_candidates(exclude_username))
    hits = []
    for name, role in searched:
        for cand in candidates:
            score = name_similarity(name, cand["matched_name"])
            level = level_for(score)
            if not level:
                continue
            adverse = ((role == "opposing" and cand["source"] in ("client", "former_client"))
                       or (role == "client" and cand["source"] == "opposing_party"))
            hits.append(dict(cand, searched_name=name, searched_role=role,
                             score=score, level=level, adverse=adverse))
    hits.sort(key=lambda h: (h["level"] != "likely", -h["score"]))
    return hits


# ── Input cleaning ────────────────────────────────────────────────────────────

def clean_names(names) -> list:
    out, seen = [], set()
    for n in names or []:
        if not isinstance(n, str):
            continue
        n = n.strip()[:200]
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:50]


def clean_related(items) -> list:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:200]
        if name:
            out.append({"name": name,
                        "relationship": str(item.get("relationship") or "").strip()[:60]})
    return out[:50]


# ── Records ───────────────────────────────────────────────────────────────────

DECISIONS = ("cleared", "waiver_obtained", "declined")


def make_check_record(trigger: str, run_by: str, names, hits) -> dict:
    now = datetime.now()
    return {
        "id":            f"cc_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(2)}",
        "timestamp":     now.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_by":        run_by,
        "trigger":       trigger,
        "names":         list(names),
        "hits":          hits,
        "decision":      None,
        "decision_note": "",
        "decided_by":    None,
        "decided_at":    None,
    }


def record_check(client: dict, trigger: str, run_by: str, client_names=(),
                 opposing_names=(), related_names=(), other_names=()) -> dict:
    """Run a check and append the record to client['conflict_checks'] (caller saves)."""
    hits = run_conflict_check(client_names, opposing_names, related_names, other_names,
                              exclude_username=client.get("username"))
    names = (clean_names(client_names) + clean_names(opposing_names)
             + clean_names(related_names) + clean_names(other_names))
    rec = make_check_record(trigger, run_by, names, hits)
    client.setdefault("conflict_checks", []).append(rec)
    return rec


def has_unresolved_conflict(client: dict) -> bool:
    return any(c.get("hits") and not c.get("decision")
               for c in client.get("conflict_checks") or [])


# ── Redaction (applied whenever hits leave the server) ────────────────────────

PUBLIC_HIT_FIELDS = ("searched_name", "searched_role", "matched_name", "score", "level",
                     "source", "matter", "assigned_attorney_display", "adverse")


def _viewer_can_see(hit: dict, viewer: str) -> bool:
    if hit.get("username"):
        try:
            c = shared.load_client(hit["username"])
        except shared.RecordDecryptError:
            return False
        return bool(c) and shared.can_access_client(viewer, c)
    return hit.get("assigned_attorney") == viewer


def _public(hit: dict) -> dict:
    return {k: hit.get(k) for k in PUBLIC_HIT_FIELDS}


def redact_hits(hits, viewer: str) -> list:
    return [dict(h) if _viewer_can_see(h, viewer) else _public(h) for h in hits or []]


def redact_checks(checks, viewer: str) -> list:
    return [dict(c, hits=redact_hits(c.get("hits"), viewer)) for c in checks or []]


_SOURCE_LABEL = {
    "client":         "an existing client",
    "former_client":  "a former client",
    "opposing_party": "an opposing party in another matter",
    "related_party":  "a related party in another matter",
    "lead":           "a prospective client (lead)",
}


def hit_message(hit: dict) -> str:
    msg = (f"{hit['level'].capitalize()} match: '{hit['searched_name']}' ≈ "
           f"'{hit['matched_name']}' — {_SOURCE_LABEL.get(hit['source'], hit['source'])}")
    if hit.get("relationship"):
        msg += f" ({hit['relationship']})"
    if hit.get("matter"):
        msg += f", {hit['matter']}"
    if hit.get("assigned_attorney_display"):
        msg += f"; handled by {hit['assigned_attorney_display']}"
    if hit.get("adverse"):
        msg += " — potentially adverse"
    return msg + "."


# ── Firm-wide log for checks not attached to a client ─────────────────────────

_FIRM_LOG_MAX  = 2000
_firm_log_lock = threading.Lock()


def append_firm_log(record: dict) -> None:
    path  = shared.SECURITY_STATE_DIR / "conflict-checks.json"
    entry = dict(record, hits=[_public(h) for h in record.get("hits") or []])
    with _firm_log_lock:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except Exception:
            print(f"[warn] {path.name} unreadable — starting fresh", file=sys.stderr)
            data = []
        data.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data[-_FIRM_LOG_MAX:], indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run** `python -m pytest tests/test_conflicts.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add conflicts.py tests/test_conflicts.py
git commit -m "feat(conflicts): firm-wide search, check records, redaction, firm log"
```

### Task 18: Wire the checker in; delete the old one

**Files:**
- Modify: `blueprints/intake.py`, `blueprints/portal_attorney.py` (`portal_create_client`, `portal_client_get`, `portal_update_client`, `attorney_portal`, new routes), `blueprints/auth.py` (`client_register`), `blueprints/drafting.py`, `shared.py`, `static/js/app.js`, `templates/attorney_portal.html`
- Create: `tests/test_intake_privacy.py`, `tests/test_conflict_routes.py`

- [ ] **Step 1: Write the failing tests.**

`tests/test_intake_privacy.py`:

```python
"""Public intake never reveals other clients (spec D3.1)."""

import shared


def test_intake_returns_no_conflict_data(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    r = client.post("/intake/submit", json={
        "full_name": "Bob Smith", "case_type": "Civil Litigation",
        "matter_description": "Fence dispute", "opposing_party": "Acme Roofing"})
    d = r.get_json()
    assert r.status_code == 200
    assert "conflict_warnings" not in d and "conflict_hits" not in d
    assert "Robert Smith" not in r.get_data(as_text=True)
    rec = shared.load_client(d["portal_account"]["username"])
    assert rec["opposing_parties"] == ["Acme Roofing"]
    chk = rec["conflict_checks"][0]
    assert chk["trigger"] == "intake" and chk["hits"][0]["matched_name"] == "Robert Smith"


def test_self_register_records_check(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    d = client.post("/client-register", json={"full_name": "Bob Smith",
                                               "password": "long-enough-1"}).get_json()
    assert "conflict" not in str(d).lower()
    assert shared.load_client(d["username"])["conflict_checks"][0]["trigger"] == "self_register"


def test_claim_document_new_account_records_check(client, make_client):
    make_client("rsmith", client_name="Robert Smith")
    d = client.post("/drafting/claim-document", json={
        "full_name": "Bob Smith", "password": "long-enough-1",
        "draft_content": "<p>x</p>"}).get_json()
    assert "conflict" not in str(d).lower()
    assert shared.load_client(d["username"])["conflict_checks"][0]["trigger"] == "claim"
```

(`base_username("Bob Smith")` is `bsmith`, so it doesn't collide with the seeded `rsmith` and a new account is created.)

`tests/test_conflict_routes.py`:

```python
"""Attorney conflict endpoints (spec D3, D4)."""

import json

import shared


def test_create_client_records_and_returns_redacted(other_attorney_session, make_client):
    make_client("rsmith", client_name="Robert Smith")        # Endocide's client
    d = other_attorney_session.post("/portal/attorney/create-client", json={
        "username": "bsmith", "client_name": "Bob Smith", "case_type": "Civil Litigation",
        "opposing_parties": ["Zed Corp"],
        "related_parties": [{"name": "Kim Smith", "relationship": "Spouse"}]}).get_json()
    assert d["conflict_warnings"] and "username" not in d["conflict_hits"][0]
    rec = shared.load_client("bsmith")
    assert rec["opposing_parties"] == ["Zed Corp"]
    assert rec["related_parties"] == [{"name": "Kim Smith", "relationship": "Spouse"}]
    assert rec["conflict_checks"][0]["trigger"] == "create"


def test_manual_check_unattached_goes_to_firm_log(attorney_session, make_client, tmp_path):
    make_client("c1", client_name="Robert Smith")
    d = attorney_session.post("/portal/attorney/conflict-check",
                              json={"names": ["Bob Smith"]}).get_json()
    assert d["check"]["hits"][0]["matched_name"] == "Robert Smith"
    log = json.loads((tmp_path / "security" / "conflict-checks.json").read_text())
    assert log[0]["names"] == ["Bob Smith"]


def test_manual_check_attached(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    attorney_session.post("/portal/attorney/conflict-check",
                          json={"names": ["Bob Smith"], "username": "c2"})
    c2 = shared.load_client("c2")
    assert c2["conflict_checks"][0]["trigger"] == "manual"
    assert c2["access_log"][-1]["action"] == "conflict_check"


def test_manual_check_validation(attorney_session, other_attorney_session, make_client):
    make_client("c1")
    assert attorney_session.post("/portal/attorney/conflict-check",
                                 json={"names": ["  "]}).status_code == 400
    assert other_attorney_session.post("/portal/attorney/conflict-check",
                                       json={"names": ["x"], "username": "c1"}).status_code == 404


def test_decision_flow(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    chk = attorney_session.post("/portal/attorney/conflict-check",
                                json={"names": ["Bob Smith"], "username": "c2"}).get_json()["check"]
    url = "/portal/attorney/conflict-decision"
    assert attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                            "decision": "maybe"}).status_code == 400
    assert attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                            "decision": "waiver_obtained"}).status_code == 400
    assert attorney_session.post(url, json={"username": "c2", "check_id": "nope",
                                            "decision": "cleared"}).status_code == 404
    r = attorney_session.post(url, json={"username": "c2", "check_id": chk["id"],
                                         "decision": "waiver_obtained",
                                         "note": "Signed waiver 10/1"})
    assert r.status_code == 200
    saved = shared.load_client("c2")["conflict_checks"][0]
    assert saved["decision"] == "waiver_obtained" and saved["decided_by"] == "Endocide"


def test_update_client_rechecks_new_parties_only(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person", opposing_parties=["Robert Smith"])
    r = attorney_session.post("/portal/attorney/update-client", json={
        "username": "c2", "opposing_parties": ["Robert Smith"], "related_parties": []})
    assert r.get_json()["conflict_hits"] == []          # nothing new
    r = attorney_session.post("/portal/attorney/update-client", json={
        "username": "c2", "related_parties": [{"name": "Bob Smith", "relationship": "Witness"}]})
    assert r.get_json()["conflict_hits"][0]["matched_name"] == "Robert Smith"
    assert shared.load_client("c2")["conflict_checks"][-1]["trigger"] == "edit"


def test_client_get_includes_redacted_checks_and_sidebar_badge(attorney_session, make_client):
    make_client("c1", client_name="Robert Smith")
    make_client("c2", client_name="Other Person")
    attorney_session.post("/portal/attorney/conflict-check",
                          json={"names": ["Bob Smith"], "username": "c2"})
    d = attorney_session.get("/portal/attorney/client/c2").get_json()
    assert len(d["conflict_checks"]) == 1 and "access_log" not in d
    html = attorney_session.get("/attorney-portal").get_data(as_text=True)
    assert 'title="Unresolved conflict check"' in html   # the badge element, not the CSS rule


def test_old_checker_removed():
    assert not hasattr(shared, "check_conflict_of_interest")
```

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Intake (`blueprints/intake.py`).**
  1. Remove `check_conflict_of_interest,` from the `shared` import and add `from conflicts import record_check`.
  2. Delete the `# Conflict-of-interest check` block (the `conflicts = check_conflict_of_interest(...)` call and `conflict_warnings = ...`).
  3. Change the import to `from conflicts import clean_names, record_check`. In `portal_record`, add `"opposing_parties": clean_names([data.get("opposing_party", "")]),` after `"assigned_attorney"`.
  4. Directly before the first `save_client(portal_record)` (the one after the AI-summary `try`), insert:

```python
    record_check(portal_record, "intake", "public_intake",
                 client_names=[data.get("full_name", "")],
                 opposing_names=[data.get("opposing_party", "")])
```

  5. In the final `return jsonify({...})`, delete the `"conflict_warnings": conflict_warnings,` line.

- [ ] **Step 4: `static/js/app.js`.** In `renderIntakeSummary`, delete the whole `// Build conflict-of-interest warning banner` block (the `let conflictHtml = "";` line through the closing `}` of its `if`). Delete the `${conflictHtml}` line in the template literal below it.

- [ ] **Step 5: `/client-register` (`blueprints/auth.py`).** Add `from conflicts import record_check`. Directly before `save_client(record)`, insert:

```python
    record_check(record, "self_register", "public", client_names=[full_name])
```

- [ ] **Step 6: `claim-document` (`blueprints/drafting.py`).** Add `from conflicts import record_check`. At the end of the `else:` branch that builds a new `record = {...}`, still inside the `else:`, add:

```python
        record_check(record, "claim", "public", client_names=[full_name])
```

- [ ] **Step 7: `portal_attorney.py`.**

Imports: remove `check_conflict_of_interest,` and add:

```python
from conflicts import (
    DECISIONS, append_firm_log, clean_names, clean_related, has_unresolved_conflict,
    hit_message, make_check_record, record_check, redact_checks, redact_hits,
    run_conflict_check,
)
```

`portal_create_client`: delete the `conflicts = check_conflict_of_interest(...)` / `conflict_warnings = ...` block. In `record`, add:

```python
        "opposing_parties":     clean_names(data.get("opposing_parties")
                                            or [data.get("opposing_party", "")]),
        "related_parties":      clean_related(data.get("related_parties")),
```

Directly before `save_client(record)`, insert:

```python
    check = record_check(record, "create", session["username"],
                         client_names=[record["client_name"] or username],
                         opposing_names=record["opposing_parties"],
                         related_names=[r["name"] for r in record["related_parties"]])
    visible_hits = redact_hits(check["hits"], session["username"])
```

and change the final return to:

```python
    return jsonify({"success": True, "username": username, "temp_password": temp_password,
                    "conflict_warnings": [hit_message(h) for h in visible_hits],
                    "conflict_hits": visible_hits})
```

`portal_client_get`: before `return jsonify(view)`, add

```python
    view["conflict_checks"] = redact_checks(client.get("conflict_checks"), session["username"])
```

`attorney_portal`: in `_view`, add `v["conflict_unresolved"] = has_unresolved_conflict(c)` before `return v`.

`portal_update_client`: directly after the `for field in (...)` assignment loop, insert:

```python
    prev_opp = set(client.get("opposing_parties") or [])
    prev_rel = {r.get("name") for r in client.get("related_parties") or []}
    if "opposing_parties" in data:
        client["opposing_parties"] = clean_names(data["opposing_parties"])
    if "related_parties" in data:
        client["related_parties"] = clean_related(data["related_parties"])
    new_opp = [n for n in client["opposing_parties"] if n not in prev_opp]
    new_rel = [r["name"] for r in client["related_parties"] if r["name"] not in prev_rel]
    conflict_hits = []
    if new_opp or new_rel:
        chk = record_check(client, "edit", session["username"],
                           opposing_names=new_opp, related_names=new_rel)
        conflict_hits = redact_hits(chk["hits"], session["username"])
```

Change its final return to `return jsonify({"success": True, "intake_pdf": intake_filename, "conflict_hits": conflict_hits})`.

New routes (after `portal_co_counsel`):

```python
@portal_attorney_bp.route("/portal/attorney/conflict-check", methods=["POST"])
@require_attorney
def portal_conflict_check():
    data   = request.get_json() or {}
    names  = clean_names(data.get("names"))
    viewer = session["username"]
    if not names:
        return jsonify({"error": "Enter at least one name."}), 400
    username = str(data.get("username") or "").strip()
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        rec = record_check(client, "manual", viewer, other_names=names)
        _log_access(client, "conflict_check", ", ".join(names))
        save_client(client)
    else:
        rec = make_check_record("manual", viewer, names, run_conflict_check(other_names=names))
        append_firm_log(rec)
    return jsonify({"success": True, "check": dict(rec, hits=redact_hits(rec["hits"], viewer))})


@portal_attorney_bp.route("/portal/attorney/conflict-decision", methods=["POST"])
@require_attorney
def portal_conflict_decision():
    data   = request.get_json() or {}
    client = load_client_for_attorney(data.get("username", ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    decision = data.get("decision")
    note     = (data.get("note") or "").strip()[:1000]
    if decision not in DECISIONS:
        return jsonify({"error": "Invalid decision."}), 400
    if decision == "waiver_obtained" and not note:
        return jsonify({"error": "Describe the waiver obtained."}), 400
    for chk in client.get("conflict_checks", []):
        if chk.get("id") == data.get("check_id"):
            chk.update(decision=decision, decision_note=note,
                       decided_by=session["username"],
                       decided_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            _log_access(client, "conflict_check", f"{decision} on {chk['id']}")
            save_client(client)
            return jsonify({"success": True,
                            "check": dict(chk, hits=redact_hits(chk["hits"], session["username"]))})
    return jsonify({"error": "Conflict check not found."}), 404
```

- [ ] **Step 8: Delete the old checker.** In `shared.py`, delete the whole `# Conflict-of-interest checker` section (`_normalise` and `check_conflict_of_interest`). Run `grep -rn "check_conflict_of_interest\|_normalise(" --include=*.py .` and expect no hits.

- [ ] **Step 9: Sidebar conflict badge.** In both sidebar loops in `attorney_portal.html`, extend the line edited in Task 8 so it reads:

```html
          {{ c.client_name or c.username }}{% if c.is_co_counsel %} <span class="cc-badge">Co-counsel</span>{% endif %}{% if c.conflict_unresolved %} <span class="conflict-badge" title="Unresolved conflict check">Conflict</span>{% endif %}
```

- [ ] **Step 10: Run** `python -m pytest tests -q` → all pass.

- [ ] **Step 11: Commit**

```bash
git add conflicts.py shared.py blueprints/ static/js/app.js templates/attorney_portal.html tests/test_intake_privacy.py tests/test_conflict_routes.py
git commit -m "feat(conflicts): wire fuzzy checker into intake, creation, edits; manual check + decisions; stop leaking conflicts publicly"
```

---

## Chunk 5: Attorney-portal UI

### Task 19: Parties & Security panel, Conflict Check tab

**Files:**
- Create: `static/js/attorney_security.js`
- Modify: `templates/attorney_portal.html`: sidebar permanent buttons (~line 577), `#atty-tabs` nav (~line 586), new panels after `#tab-documents` (~line 1278), `selectClient` (~line 1980), `{% block styles %}`, the `{% block scripts %}` tail

No unit tests: this is DOM code. Verify in the browser (Step 6).

**XSS rule for this task.** Client names, parties, notes and other client-entered values are untrusted.
- Build every new element with the `_el()` helper in `attorney_security.js`. It turns values into text nodes, never HTML.
- Do not use `innerHTML` or HTML template strings in new code.
- Attach handlers through `_el`'s `on*` props or `addEventListener`, never inline `onclick` strings.

- [ ] **Step 1: Nav buttons.** After the `+ New Client` button in the permanent-actions block, add:

```html
      <button class="portal-tab-btn" onclick="showConflictCheck(this)" id="conflict-check-btn">
        Conflict Check
      </button>
```

In `#atty-tabs`, after the Research button, add:

```html
      <button class="portal-tab-btn" onclick="showAttyTab('security', this)">Parties &amp; Security</button>
```

- [ ] **Step 2: Panels.** After the closing `</div>` of `#tab-documents`, add:

```html
    <!-- Parties & Security -->
    <div id="tab-security" class="portal-panel">
      <div class="page-header" style="margin-bottom:1.1rem">
        <h1 style="font-size:1.5rem">Parties &amp; Security</h1>
        <p style="font-size:.88rem">Opposing and related parties feed the conflict checker. Access history is visible to attorneys only.</p>
      </div>

      <div class="card" style="margin-bottom:1rem">
        <div class="portal-section-title">Parties</div>
        <div class="form-grid">
          <div class="form-group full">
            <label for="sec-opposing">Opposing parties (one per line)</label>
            <textarea id="sec-opposing" rows="3"></textarea>
          </div>
          <div class="form-group full">
            <label>Related parties</label>
            <div id="sec-related-list"></div>
            <button class="btn btn-secondary" type="button" id="sec-add-related">+ Add related party</button>
          </div>
        </div>
        <div class="btn-group" style="margin-top:.8rem">
          <button class="btn btn-primary" id="sec-save-parties">Save parties &amp; re-check</button>
        </div>
        <div id="sec-parties-result" style="margin-top:.6rem"></div>
      </div>

      <div class="card" style="margin-bottom:1rem">
        <div class="portal-section-title">Conflict checks</div>
        <div id="sec-checks"></div>
      </div>

      <div class="card" style="margin-bottom:1rem">
        <div class="portal-section-title">Co-counsel</div>
        <div id="sec-cocounsel-list" style="margin-bottom:.6rem"></div>
        <div id="sec-cocounsel-add" style="display:flex;gap:.5rem;align-items:center">
          <select id="sec-cocounsel-select"></select>
          <button class="btn btn-secondary" id="sec-cocounsel-add-btn">Add</button>
        </div>
      </div>

      <div class="card">
        <div class="portal-section-title">Access history</div>
        <button class="btn btn-secondary" id="sec-load-access">Load access history</button>
        <div id="sec-access-log" style="margin-top:.6rem;overflow-x:auto"></div>
      </div>

      <datalist id="sec-rel-options">
        <option value="Spouse"><option value="Co-defendant"><option value="Witness">
        <option value="Business partner"><option value="Employer"><option value="Parent/Guardian"><option value="Other">
      </datalist>
    </div>

    <!-- Conflict Check (firm-wide tool) -->
    <div id="tab-conflict-check" class="portal-panel">
      <div class="page-header" style="margin-bottom:1.1rem">
        <h1 style="font-size:1.5rem">Conflict Check</h1>
        <p style="font-size:.88rem">Search every client, former client, opposing party, related party, and lead. Every check is recorded.</p>
      </div>
      <div class="card">
        <div class="form-group">
          <label for="cc-names">Names to check (one per line)</label>
          <textarea id="cc-names" rows="5" placeholder="Jane Doe&#10;Acme Roofing LLC"></textarea>
        </div>
        <div class="form-group">
          <label for="cc-attach">Attach result to client (optional)</label>
          <select id="cc-attach"><option value="">— Not attached —</option></select>
        </div>
        <button class="btn btn-primary" id="cc-run">Run check</button>
        <div id="cc-results" style="margin-top:1rem;overflow-x:auto"></div>
      </div>
    </div>
```

Add to the `{% block styles %}` `<style>` block:

```css
.sec-table { width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:.82rem; margin-top:.4rem; }
.sec-table th, .sec-table td { text-align:left; padding:.35rem .5rem; border-bottom:1px solid var(--rule); vertical-align:top; }
.sec-note { font-family:Arial,sans-serif; font-size:.85rem; color:var(--gray-3); }
.sec-note.error { color:var(--red); }
```

- [ ] **Step 3: Hook into client selection, the New Client form, and load the script.**

Two functions load a client and set `_currentClient`. `selectClient` (~line 1968) serves the sidebar, and `selectClientAndTab` (~line 3556) serves the dashboard and the All Clients table. In **both**, add `populateSecurity(c);` right after `populateResearch(c);`. If only one of them gets it, opening a client from the dashboard leaves the previous client's parties in the panel, and clicking Save would write them onto the wrong client.

**New Client form (spec D1).** In `#tab-new-client`, after the `nc-legal-issue` form group (~line 1345), add:

```html
          <div class="form-group full">
            <label for="nc-opposing">Opposing parties (one per line)</label>
            <textarea id="nc-opposing" rows="2"></textarea>
          </div>
          <div class="form-group full">
            <label>Related parties</label>
            <div id="nc-related-list"></div>
            <button class="btn btn-secondary" type="button" id="nc-add-related">+ Add related party</button>
          </div>
```

In `createClient()`, add these two keys to the `JSON.stringify({...})` body:

```javascript
      opposing_parties:     document.getElementById("nc-opposing").value.split("\n").map(s => s.trim()).filter(Boolean),
      related_parties:      collectRelated(document.getElementById("nc-related-list")),
```

In `resetNewClientForm()`, add:

```javascript
  document.getElementById("nc-opposing").value = "";
  document.getElementById("nc-related-list").replaceChildren();
```

In `createClient()`'s success branch, replace the `if (d.conflict_warnings && d.conflict_warnings.length) { ... } else { ... }` block (it renders `conflict_warnings` with an HTML string) with:

```javascript
      if (d.conflict_hits && d.conflict_hits.length) {
        res.replaceChildren(
          _note("⚠ Conflict check matches — review before proceeding.", true),
          hitsTable(d.conflict_hits));
        document.getElementById("nc-success-card").appendChild(res);
      } else {
        res.replaceChildren();
      }
```

The success card is shown and the form card hidden, and `nc-result` sits inside the hidden form card. Moving it into the success card keeps the warnings visible. `resetNewClientForm` must move it back: add `document.getElementById("nc-form-card").appendChild(document.getElementById("nc-result"));` there.

**Archive buttons for co-counsel.** Spec A3 makes archiving assigned-only. `populateSecurity` (below) hides `#ov-archive-btn` and `#ov-unarchive-btn` when `!c.viewer_is_assigned`. It runs after `populateOverview`, so its choice wins.

At the end of the `{% block scripts %}` block, just before `{% endblock %}`, add:

```html
<script>
  window._ATTORNEYS = {{ attorneys | tojson }};
</script>
<script src="{{ url_for('static', filename='js/attorney_security.js') }}"></script>
```

- [ ] **Step 4: Create `static/js/attorney_security.js`**

```javascript
// Attorney portal — parties, conflict checks, co-counsel, access history,
// and the firm-wide Conflict Check tool.
// Relies on attorney_portal.html globals: _currentClient, _ALL_CLIENTS_DATA, _ATTORNEYS.
// XSS rule: every element is built with _el(); untrusted values only ever
// become text nodes or input .value. No HTML strings, no inline handlers.

// props are always literals written in this file — never pass data as props
// (any "on*" key becomes an event listener).
function _el(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([k, v]) => {
    if (k === "style") node.style.cssText = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node[k] = v;
  });
  children.flat(Infinity).forEach(c => {
    if (c === null || c === undefined || c === false) return;
    node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  });
  return node;
}

function _postJSON(url, body) {
  return fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  }).then(r => r.json());
}

function _note(text, isError) {
  return _el("p", {className: "sec-note" + (isError ? " error" : "")}, text);
}

function _show(container, ...nodes) {
  container.replaceChildren(...nodes);
}

function _badge(text) {
  return _el("span", {className: "conflict-badge"}, text);
}

function _table(headers, rows) {
  return _el("div", {style: "overflow-x:auto"},
    _el("table", {className: "sec-table"},
      _el("thead", {}, _el("tr", {}, headers.map(h => _el("th", {}, h)))),
      _el("tbody", {}, rows.map(cells => _el("tr", {}, cells.map(c => _el("td", {}, c)))))));
}

function hitsTable(hits) {
  if (!hits || !hits.length) return _note("No matches.");
  return _table(
    ["Level", "Searched", "Matched", "Source", "Matter", "Attorney"],
    hits.map(h => [
      [h.level === "likely" ? _el("strong", {}, "Likely") : "Possible",
       h.adverse ? [" ", _badge("Adverse")] : null],
      h.searched_name || "",
      (h.matched_name || "") + (h.relationship ? ` (${h.relationship})` : ""),
      (h.source || "").replace(/_/g, " "),
      h.matter || "",
      h.assigned_attorney_display || "",
    ]));
}

// ── Related-party rows (Parties panel and New Client form) ────────────────────
function addRelatedRow(container, name, relationship) {
  const row = _el("div", {className: "sec-related-row", style: "display:flex;gap:.5rem;margin-bottom:.4rem"});
  row.append(
    _el("input", {type: "text", className: "sec-rel-name", placeholder: "Name",
                  style: "flex:2", value: name || ""}),
    _el("input", {type: "text", className: "sec-rel-rel", placeholder: "Relationship",
                  style: "flex:1", value: relationship || ""}),
    _el("button", {type: "button", className: "btn btn-secondary", title: "Remove",
                   onclick: () => row.remove()}, "✕"));
  row.querySelector(".sec-rel-rel").setAttribute("list", "sec-rel-options");
  container.appendChild(row);
}

function collectRelated(container) {
  return Array.from(container.querySelectorAll(".sec-related-row")).map(r => ({
    name: r.querySelector(".sec-rel-name").value.trim(),
    relationship: r.querySelector(".sec-rel-rel").value.trim(),
  })).filter(r => r.name);
}

// ── Refresh just this panel (does not switch tabs or clear result boxes) ──────
function refreshSecurity() {
  if (!_currentClient) return Promise.resolve();
  const username = _currentClient.username;
  return fetch("/portal/attorney/client/" + encodeURIComponent(username))
    .then(r => r.json())
    .then(c => {
      if (!_currentClient || _currentClient.username !== username || c.error) return;
      _currentClient = c;
      _fillParties(c);
      _renderChecks(c.conflict_checks);
      _renderCoCounsel(c);
    })
    .catch(() => {});
}

// ── Parties ───────────────────────────────────────────────────────────────────
function _fillParties(c) {
  document.getElementById("sec-opposing").value = (c.opposing_parties || []).join("\n");
  const list = document.getElementById("sec-related-list");
  list.replaceChildren();
  (c.related_parties || []).forEach(r => addRelatedRow(list, r.name, r.relationship));
}

function saveParties() {
  if (!_currentClient) return;
  const out = document.getElementById("sec-parties-result");
  const opposing = document.getElementById("sec-opposing").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  const related = collectRelated(document.getElementById("sec-related-list"));
  _show(out, _note("Saving…"));
  _postJSON("/portal/attorney/update-client", {
    username: _currentClient.username, opposing_parties: opposing, related_parties: related,
  }).then(d => {
    if (!d.success) return _show(out, _note(d.error || "Save failed.", true));
    if (d.conflict_hits && d.conflict_hits.length) {
      _show(out, _el("p", {className: "sec-note"},
                     _el("strong", {}, "New parties matched existing records:")),
            hitsTable(d.conflict_hits));
    } else {
      _show(out, _note("Saved. No conflicts found for new parties."));
    }
    refreshSecurity();
  }).catch(() => _show(out, _note("Request failed — reload the page and try again.", true)));
}

// ── Conflict checks on this client ────────────────────────────────────────────
function _decisionControls(check) {
  const note = _el("input", {type: "text", placeholder: "Note (required for waiver)",
                             style: "flex:1;min-width:12rem"});
  const btn = (label, decision) => _el("button", {
    className: "btn btn-secondary",
    onclick: () => decideConflict(check.id, decision, note.value.trim()),
  }, label);
  return _el("div", {style: "display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.4rem"},
    note, btn("Cleared", "cleared"), btn("Waiver obtained", "waiver_obtained"),
    btn("Declined", "declined"));
}

function _renderChecks(checks) {
  const el = document.getElementById("sec-checks");
  if (!checks || !checks.length) return _show(el, _note("No conflict checks recorded."));
  _show(el, ...checks.slice().reverse().map(c => {
    const unresolved = c.hits && c.hits.length && !c.decision;
    const meta = _el("div", {className: "sec-note"},
      `${c.timestamp} · ${c.trigger} · run by ${c.run_by} · names: ${(c.names || []).join(", ")}`,
      unresolved ? [" ", _badge("Unresolved")] : null);
    const decided = c.decision
      ? _el("div", {className: "sec-note"}, "Decision: ",
            _el("strong", {}, c.decision.replace(/_/g, " ")),
            ` by ${c.decided_by || ""} ${c.decided_at || ""}`,
            c.decision_note ? ` — ${c.decision_note}` : "")
      : (unresolved ? _decisionControls(c) : null);
    return _el("div", {style: "border-top:1px solid var(--rule);padding:.6rem 0"},
               meta, hitsTable(c.hits), decided);
  }));
}

function decideConflict(checkId, decision, note) {
  if (!_currentClient) return;
  _postJSON("/portal/attorney/conflict-decision", {
    username: _currentClient.username, check_id: checkId, decision, note,
  }).then(d => {
    if (!d.success) return alert(d.error || "Could not record decision.");
    refreshSecurity();
  }).catch(() => alert("Request failed — reload the page and try again."));
}

// ── Co-counsel ────────────────────────────────────────────────────────────────
function _renderCoCounsel(c) {
  const list = document.getElementById("sec-cocounsel-list");
  const add  = document.getElementById("sec-cocounsel-add");
  const sel  = document.getElementById("sec-cocounsel-select");
  const attorneys = window._ATTORNEYS || [];
  const byUser = Object.fromEntries(attorneys.map(a => [a.username, a.display]));
  const cc = c.co_counsel || [];

  if (!cc.length) {
    _show(list, _note("None."));
  } else {
    _show(list, ...cc.map(u => _el("span", {
        style: "display:inline-flex;gap:.3rem;align-items:center;margin-right:.6rem;font-family:Arial,sans-serif;font-size:.88rem"},
      byUser[u] || u,
      c.viewer_is_assigned
        ? _el("button", {className: "btn btn-secondary", style: "padding:.1rem .45rem",
                         onclick: () => changeCoCounsel("remove", u)}, "✕")
        : null)));
  }

  _show(sel, ...attorneys
    .filter(a => a.username !== c.assigned_attorney && !cc.includes(a.username))
    .map(a => _el("option", {value: a.username}, a.display)));
  add.style.display = c.viewer_is_assigned && sel.options.length ? "flex" : "none";
}

function changeCoCounsel(action, attorney) {
  if (!attorney || !_currentClient) return;
  _postJSON("/portal/attorney/co-counsel", {username: _currentClient.username, action, attorney})
    .then(d => {
      if (!d.success) return alert(d.error || "Could not update co-counsel.");
      refreshSecurity();
    })
    .catch(() => alert("Request failed — reload the page and try again."));
}

// ── Access history ────────────────────────────────────────────────────────────
function loadAccessLog() {
  if (!_currentClient) return;
  const el = document.getElementById("sec-access-log");
  _show(el, _note("Loading…"));
  fetch("/portal/attorney/access-log/" + encodeURIComponent(_currentClient.username))
    .then(r => r.json())
    .then(rows => {
      if (!Array.isArray(rows)) return _show(el, _note(rows.error || "Could not load.", true));
      if (!rows.length) return _show(el, _note("No access recorded yet."));
      _show(el, _table(["When", "Attorney", "Action", "Detail", "IP"],
        rows.map(r => [r.timestamp || "", r.attorney || "",
                       (r.action || "").replace(/_/g, " "), r.detail || "", r.ip || ""])));
    })
    .catch(() => _show(el, _note("Request failed — reload the page and try again.", true)));
}

// ── Populate on client select (called from selectClient and selectClientAndTab) ─
function populateSecurity(c) {
  _fillParties(c);
  document.getElementById("sec-parties-result").replaceChildren();
  document.getElementById("sec-access-log").replaceChildren();
  _renderChecks(c.conflict_checks);
  _renderCoCounsel(c);
  // Archiving is assigned-attorney only (spec A3); runs after populateOverview.
  if (!c.viewer_is_assigned) {
    document.getElementById("ov-archive-btn").style.display   = "none";
    document.getElementById("ov-unarchive-btn").style.display = "none";
  }
}

// ── Firm-wide Conflict Check tab ──────────────────────────────────────────────
// The attach list holds active clients only (from _ALL_CLIENTS_DATA); checks on
// an archived client's matter are rare and can be run unattached.
function showConflictCheck(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-conflict-check").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  const sel = document.getElementById("cc-attach");
  if (sel.options.length <= 1) {
    (window._ALL_CLIENTS_DATA || []).forEach(c =>
      sel.appendChild(_el("option", {value: c.username}, c.client_name || c.username)));
  }
}

function runManualConflictCheck() {
  const out   = document.getElementById("cc-results");
  const names = document.getElementById("cc-names").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  if (!names.length) return _show(out, _note("Enter at least one name.", true));
  const body   = {names};
  const attach = document.getElementById("cc-attach").value;
  if (attach) body.username = attach;
  _show(out, _note("Checking…"));
  _postJSON("/portal/attorney/conflict-check", body).then(d => {
    if (!d.success) return _show(out, _note(d.error || "Check failed.", true));
    _show(out,
      _note(`Recorded as ${d.check.id}${attach ? " on the selected client" : " in the firm log"}.`),
      hitsTable(d.check.hits));
  }).catch(() => _show(out, _note("Request failed — reload the page and try again.", true)));
}

// ── Static button wiring ──────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("sec-add-related").addEventListener("click", () =>
    addRelatedRow(document.getElementById("sec-related-list")));
  document.getElementById("nc-add-related").addEventListener("click", () =>
    addRelatedRow(document.getElementById("nc-related-list")));
  document.getElementById("sec-save-parties").addEventListener("click", saveParties);
  document.getElementById("sec-load-access").addEventListener("click", loadAccessLog);
  document.getElementById("sec-cocounsel-add-btn").addEventListener("click", () =>
    changeCoCounsel("add", document.getElementById("sec-cocounsel-select").value));
  document.getElementById("cc-run").addEventListener("click", runManualConflictCheck);
});
```

- [ ] **Step 5: Run** `python -m pytest tests -q` → still all pass. This task is template and JS only; the template must still render.

- [ ] **Step 6: Browser verification** (use the preview tools).
  1. Start the app with `SECRET_KEY` and `DATA_ENCRYPTION_KEY` in `.env`, and log in as an attorney.
  2. Select a client and open **Parties & Security**.
  3. Add an opposing party matching another client's name and save. The match table stays visible on the same tab, and the Conflict checks card updates without leaving the tab. The sidebar shows a **Conflict** badge after reload.
  4. Open the same client from a dashboard row instead of the sidebar, and confirm Parties & Security shows *that* client's parties. Create a new client with an opposing party that matches an existing client, and confirm the match table appears on the success card.
  5. Record **Waiver obtained** without a note. Expect the error alert. Add a note and record it. The badge disappears after reload.
  6. Add the other attorney as co-counsel, log in as them, and confirm the client appears with a **Co-counsel** badge. The co-counsel add/remove controls and the Archive button should be hidden, and delete-document should fail with 404.
  7. Click **Load access history**. The entries list the actions just taken.
  8. Open **Conflict Check**, run a name unattached and then attached, and confirm both report where they were recorded.
  9. Enter a party name like `<img src=x onerror=alert(1)>`, save, and reload. It must render as literal text with no alert.
  10. Check the console: no errors.
  11. Resize to mobile width and confirm the page has no horizontal scroll (tables scroll inside their containers).

- [ ] **Step 7: Commit**

```bash
git add static/js/attorney_security.js templates/attorney_portal.html
git commit -m "feat(ui): parties & security panel, conflict decisions, co-counsel, access history, conflict check tool"
```

### Task 20: Migrate the real data and verify end-to-end

This task runs against the live `client-accounts/` folder. Do it last and keep the backup.

- [ ] **Step 1: Full suite** — `python -m pytest tests -q`. Expect everything to pass: 88 original tests plus the new ones.

- [ ] **Step 2: Keys.**
  1. Run `python scripts/generate_data_key.py` and add the printed line to `.env`.
  2. If `.env` lacks `SECRET_KEY`, add one using `python -c "import secrets; print(secrets.token_hex(32))"`.
  3. **Tell the user to back the data key up outside the OneDrive folder before continuing.** Do not proceed until they confirm.

- [ ] **Step 3: Migrate.** Run `python scripts/encrypt_existing_records.py --backup-dir "C:\Users\Endoc\law-office-backups"`. The user may pick a different folder outside OneDrive. Expect `Failed (restored): 0`, with the encrypted count matching the number of account files.

- [ ] **Step 4: Start the app** with `python app.py`. Expect the "Secured N plaintext client password(s)" line, about 32 on first start, and no startup errors.

- [ ] **Step 5: Smoke test in the browser.**
  1. Attorney login works, and the sidebar and dashboard load.
  2. A client record opens.
  3. View the page source and confirm there is no `$2b$`.
  4. A client login with an old plaintext password is forced to the change-password page.
  5. Six bad logins in a row produce the lockout message.

- [ ] **Step 6: Report** to the user:
  - the migration counts
  - the number of passwords secured
  - the backup location
  - a reminder that affected clients must reset their passwords at next login, which may mean resending credentials to clients who never logged in

---

## Done criteria

- `python -m pytest tests -q` passes.
- The `test_every_client_route_is_guarded` sweep passes.
- Records on disk are ciphertext. No password hashes reach the browser. Public intake shows no conflict data.
- Every item in the spec's Testing section has a matching test, or a manual-verification step for UI-only behaviour.
