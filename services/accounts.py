"""services/accounts.py — passwords, account names, and attorney access control."""

import re
import secrets
from datetime import datetime, timedelta

import bcrypt
from flask import request, session

import shared
from services.storage import (
    RecordDecryptError, _get_client_lock, _read_record, _write_record,
    load_client, safe_username, save_client,
)


# ── Password helpers ──────────────────────────────────────────────────────────

MIN_PASSWORD_LENGTH = 8
_WEAK_PASSWORDS = frozenset({"password", "password1", "12345678", "changeme"})


def acceptable_password(pw: str, username: str) -> bool:
    pw = pw or ""
    return (len(pw) >= MIN_PASSWORD_LENGTH
            and pw.lower() not in _WEAK_PASSWORDS
            and pw.lower() != (username or "").lower())


def generate_temp_password() -> str:
    """Return a random single-use password for a newly created client account.

    Never reuse a fixed string here: temp passwords are emailed in plaintext and
    the account is reachable until the client completes their first login.
    """
    return secrets.token_urlsafe(9)


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def check_password(plaintext: str, stored: str) -> bool:
    """Verify plaintext against a bcrypt hash OR a legacy plaintext password."""
    if not plaintext or not stored:
        return False
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(plaintext.encode(), stored.encode())
        except Exception:
            return False
    return plaintext == stored


def upgrade_password_if_needed(client: dict, plaintext: str) -> bool:
    stored = client.get("password", "")
    if stored and not stored.startswith("$2"):
        client["password"] = hash_password(plaintext)
        save_client(client)
        return True
    return False


def upgrade_all_plaintext_passwords(apply: bool = True, skipped: list = None) -> list:
    """Hash every client password still stored in plaintext and force a change
    on next login. Returns the usernames upgraded (or, with apply=False, the
    ones that would be). If `skipped` is a list, names of records that could
    not be decrypted are appended to it."""
    upgraded = []
    for path in sorted(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")):
        stem = path.stem
        if safe_username(stem) != stem:
            continue
        # Hold the per-client lock across read-modify-write so a concurrent
        # save cannot be overwritten. The lock is not re-entrant, hence the
        # direct _read_record/_write_record calls.
        with _get_client_lock(stem):
            try:
                client = _read_record(path)
            except (RecordDecryptError, ValueError):
                if skipped is not None:
                    skipped.append(stem)
                continue
            pw = client.get("password", "")
            if not pw or pw.startswith("$2"):
                continue
            upgraded.append(stem)
            if apply:
                client["password"]             = hash_password(pw)
                client["must_change_password"] = True
                _write_record(path, client)
    return upgraded


# ── Account names ─────────────────────────────────────────────────────────────

def base_username(full_name: str) -> str:
    """Derive the natural account name for a person (first initial + surname).

    Unlike _make_username this does NOT avoid collisions, so callers can tell
    whether an account for this name already exists.
    """
    parts = full_name.strip().split()
    if len(parts) >= 2:
        base = (parts[0][0] + parts[-1]).lower()
    else:
        base = parts[0].lower() if parts else "client"
    return re.sub(r"[^a-z0-9]", "", base)[:20] or "client"


def _make_username(full_name: str) -> str:
    """Return an account name for full_name that is not already taken."""
    base     = base_username(full_name)
    existing = {p.stem for p in shared.CLIENT_ACCOUNTS_DIR.glob("*.json")}
    if base not in existing:
        return base
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if candidate not in existing:
            return candidate
    return base


# ── Attorney access control & access log ──────────────────────────────────────

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


def log_access_atomic(username: str, action: str, detail: str = "") -> None:
    """Record an access entry for a read-only route without clobbering
    concurrent writes: re-read the record under the lock, append, write."""
    if not username or safe_username(username) != username:
        return
    path = shared.CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        if not path.exists():
            return
        record = _read_record(path)
        if _log_access(record, action, detail):
            _write_record(path, record)
