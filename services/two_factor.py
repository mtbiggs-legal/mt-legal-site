"""services/two_factor.py — authenticator-app codes for the attorney login.

TOTP per RFC 6238 (SHA-1, 6 digits, 30-second steps: what Google
Authenticator, 1Password, Authy and others use), plus ten single-use
recovery codes. State lives encrypted in SECURITY_STATE_DIR/attorney-2fa.json:

    {"<username>": {"secret": "...", "enabled": true, "last_counter": 123,
                    "pending_secret": "...", "recovery": ["<sha256>", ...]}}

A code is accepted once: last_counter stops a code that was just used (or
watched over a shoulder) from working again within its window.
To reset a lost device: python scripts/reset_attorney_2fa.py <username>
"""

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
from urllib.parse import quote

import shared
from services import storage

STEP, DIGITS, WINDOW = 30, 6, 1
RECOVERY_CODES = 10
_lock = threading.Lock()


# ── TOTP ──────────────────────────────────────────────────────────────────────

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def _now() -> float:
    return time.time()


def match_counter(secret: str, code: str, after: int = -1):
    """The time step `code` is valid for (now ±WINDOW) and later than `after`,
    or None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = int(_now() // STEP)
    for counter in range(now - WINDOW, now + WINDOW + 1):
        if counter > after and hmac.compare_digest(code_at(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: str, account: str) -> str:
    issuer = shared.FIRM_NAME
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}")


# ── State ─────────────────────────────────────────────────────────────────────

def _path():
    return shared.SECURITY_STATE_DIR / "attorney-2fa.json"


def _load() -> dict:
    data = storage.read_encrypted_json(_path(), {})
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    storage.write_encrypted_json(_path(), data)


def _digest(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def is_enabled(username: str) -> bool:
    return bool(_load().get(username, {}).get("enabled"))


def pending_secret(username: str) -> str:
    """The secret being set up for `username`, created on first call. Stays the
    same until setup finishes, so reloading the page shows the same key."""
    with _lock:
        data = _load()
        entry = data.setdefault(username, {})
        if entry.get("enabled"):
            return ""
        if not entry.get("pending_secret"):
            entry["pending_secret"] = new_secret()
            _save(data)
        return entry["pending_secret"]


def confirm_setup(username: str, code: str):
    """Turn 2FA on once the first code from the app checks out. Returns the
    recovery codes to show once, or None if the code is wrong."""
    with _lock:
        data = _load()
        entry = data.get(username) or {}
        secret = entry.get("pending_secret")
        counter = match_counter(secret, code) if secret else None
        if counter is None:
            return None
        codes = ["-".join((secrets.token_hex(2), secrets.token_hex(2))) for _ in range(RECOVERY_CODES)]
        data[username] = {"secret": secret, "enabled": True, "last_counter": counter,
                          "recovery": [_digest(c) for c in codes]}
        _save(data)
    return codes


def verify(username: str, code: str) -> bool:
    """Check a login code: an authenticator code, or an unused recovery code."""
    with _lock:
        data = _load()
        entry = data.get(username) or {}
        if not entry.get("enabled"):
            return False
        counter = match_counter(entry["secret"], code, entry.get("last_counter", -1))
        if counter is not None:
            entry["last_counter"] = counter
            _save(data)
            return True
        d = _digest(code or "")
        if d in (entry.get("recovery") or []):
            entry["recovery"].remove(d)
            _save(data)
            return True
    return False


def recovery_left(username: str) -> int:
    return len(_load().get(username, {}).get("recovery") or [])


def reset(username: str) -> bool:
    """Remove 2FA for `username` (lost device). The next login sets it up again."""
    with _lock:
        data = _load()
        if username not in data:
            return False
        del data[username]
        _save(data)
    return True
