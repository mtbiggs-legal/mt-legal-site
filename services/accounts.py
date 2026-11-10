"""services/accounts.py — passwords, account names, and attorney access control."""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

import bcrypt
from flask import session

import shared
from services.storage import (
    RecordDecryptError, all_usernames, client_exists, load_client, safe_username,
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
    """Verify plaintext against a bcrypt hash. A stored value that isn't a
    bcrypt hash (a legacy plaintext password) never matches: those are hashed
    at startup by upgrade_all_plaintext_passwords, which also forces a change."""
    if not plaintext or not stored or not stored.startswith("$2"):
        return False
    try:
        return bcrypt.checkpw(plaintext.encode(), stored.encode())
    except Exception:
        return False


def upgrade_all_plaintext_passwords(apply: bool = True, skipped: list = None) -> list:
    """Hash every client password still stored in plaintext and force a change
    on next login. Returns the usernames upgraded (or, with apply=False, the
    ones that would be). If `skipped` is a list, names of records that could
    not be decrypted are appended to it."""
    from services.storage import update_client_atomic
    upgraded = []
    for username in all_usernames():
        try:
            client = load_client(username)
        except RecordDecryptError:
            if skipped is not None:
                skipped.append(username)
            continue
        pw = (client or {}).get("password", "")
        if not pw or pw.startswith("$2"):
            continue
        upgraded.append(username)
        if apply:
            def _upgrade(c):
                stored = c.get("password", "")
                if stored and not stored.startswith("$2"):
                    c["password"] = hash_password(stored)
                    c["must_change_password"] = True
            update_client_atomic(username, _upgrade)
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


_ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"     # no 0/o, 1/l/i look-alikes


def new_client_username() -> str:
    """A random account name ("c" + 8 characters) that is not taken.

    Account names are deliberately not derived from the person's name: a
    name-based one tells anyone who sees it (or probes for it) who the firm's
    clients are, and colliding names used to overwrite each other."""
    for _ in range(50):
        candidate = "c" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(8))
        if not client_exists(candidate):
            return candidate
    raise RuntimeError("Could not allocate a client account name.")


def _make_username(full_name: str = "") -> str:
    """Kept for older callers; account names no longer use the person's name."""
    return new_client_username()


# ── Invitations ───────────────────────────────────────────────────────────────
# A new client account has no password. The client gets a single-use link,
# valid for INVITE_TTL, and chooses a password there. Only a SHA-256 of the
# secret part is stored, so a copy of the record can't be used to sign in.

INVITE_TTL = timedelta(days=7)


def _invite_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def issue_invite(username: str):
    """Create a fresh invitation for `username` (replacing any earlier one) and
    return the token for the link, or None if the account doesn't exist."""
    from services.storage import update_client_atomic
    secret  = secrets.token_urlsafe(32)
    expires = (datetime.now() + INVITE_TTL).strftime("%Y-%m-%dT%H:%M:%S")

    def _set(c):
        c["invite"] = {"digest": _invite_digest(secret), "expires": expires}
    if not update_client_atomic(username, _set):
        return None
    return f"{username}.{secret}"


def _split_invite(token: str):
    username, _, secret = (token or "").partition(".")
    if not username or not secret or safe_username(username) != username:
        return None, None
    return username, secret


def check_invite(token: str):
    """The client record a valid, unexpired invitation token belongs to, else None."""
    username, secret = _split_invite(token)
    if not username:
        return None
    client = load_client(username)
    inv    = (client or {}).get("invite") or {}
    if not inv.get("digest") or not hmac.compare_digest(inv["digest"], _invite_digest(secret)):
        return None
    try:
        if datetime.strptime(inv.get("expires", ""), "%Y-%m-%dT%H:%M:%S") < datetime.now():
            return None
    except ValueError:
        return None
    return client


def redeem_invite(token: str, new_password: str):
    """Set the password for the invited account and use up the invitation.
    Returns the username, or None if the token isn't valid (anymore)."""
    from services.storage import update_client_atomic
    client = check_invite(token)
    if not client:
        return None
    username, secret = _split_invite(token)
    hashed = hash_password(new_password)
    used   = {}

    def _apply(c):
        inv = c.get("invite") or {}
        # Re-check under the lock so two submissions can't both redeem it.
        if not inv.get("digest") or not hmac.compare_digest(inv["digest"], _invite_digest(secret)):
            return
        c["password"]             = hashed
        c["must_change_password"] = False
        c["invite"]               = None
        used["ok"] = True
    update_client_atomic(username, _apply)
    if not used.get("ok"):
        return None
    from services.security import bump_session_version
    bump_session_version("client", username)      # any older session ends
    return username


def invite_url(token: str) -> str:
    base = shared.portal_base()
    return f"{base}/client-portal/invite/{token}"


# ── Attorney access control & access log ──────────────────────────────────────

_PRIVATE_CLIENT_FIELDS = frozenset({"password", "must_change_password", "invite",
                                    "session_version", "client_folder",
                                    "access_log", "conflict_checks"})




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
    """Record attorney access to `client` in the audit log (services/audit.py).
    Written straight away, whether or not the caller saves the record.
    view_* actions repeated by the same attorney within 10 minutes are
    skipped. Returns True if an entry was written."""
    from services import audit
    username = (client or {}).get("username", "")
    attorney = session.get("username", "")
    if action.startswith("view_") and audit.recently_viewed(attorney, username, action):
        return False
    audit.record(action, client=username, detail=detail)
    return True


def log_access_atomic(username: str, action: str, detail: str = "") -> None:
    """Record access for a read-only route (kept for existing callers)."""
    if not username or safe_username(username) != username:
        return
    _log_access({"username": username}, action, detail)
