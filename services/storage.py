"""services/storage.py — encrypted client records, per-client locks, and the
small JSON stores (token usage, page visits).

Configuration (data folders, rates) is read as shared.<NAME> at call time."""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

import shared


# ── Client file I/O helpers ───────────────────────────────────────────────────

_client_locks: dict = {}
_client_locks_mutex = threading.Lock()


# LOCK-ORDER INVARIANT: never take a billing ledger lock, call any billing.*
# function, or call save_client() while holding a client lock. billing.py may
# take a client lock (via load_client) while holding a ledger lock — never the
# reverse — so the two can't deadlock.
def _get_client_lock(username: str) -> threading.Lock:
    with _client_locks_mutex:
        if username not in _client_locks:
            _client_locks[username] = threading.Lock()
        return _client_locks[username]


def require_outside_dir(path, root) -> None:
    """Exit unless `path` is outside `root` (e.g. a backup must not land in the
    OneDrive-synced project folder)."""
    path = Path(path).resolve()
    root = Path(root).resolve()
    if path == root or root in path.parents:
        raise SystemExit(f"Refusing: {path} is inside the project folder, "
                         "which OneDrive syncs. Choose a folder outside it.")


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
        try:
            _fernet_cache = Fernet(key.encode())
        except ValueError as exc:
            raise RuntimeError(
                "DATA_ENCRYPTION_KEY is malformed — regenerate with "
                "python scripts/generate_data_key.py"
            ) from exc
    return _fernet_cache


def _is_plaintext(raw: bytes) -> bool:
    """True for a legacy plaintext JSON record (tolerating a UTF-8 BOM)."""
    return raw.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{")


def _read_record(path: Path) -> dict:
    """Read a client account file. Plaintext JSON (legacy) and Fernet tokens
    are both accepted so records can be migrated gradually."""
    raw = path.read_bytes()
    if _is_plaintext(raw):
        return json.loads(raw.decode("utf-8-sig"))
    try:
        return json.loads(_fernet().decrypt(raw).decode("utf-8"))
    except InvalidToken as exc:
        raise RecordDecryptError(path.stem) from exc


def _write_record(path: Path, data: dict) -> None:
    """Encrypt and write a client account file atomically."""
    _atomic_write(path, _fernet().encrypt(json.dumps(data, indent=2).encode("utf-8")))


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write `payload` to a temp file, fsync it, then swap it into place.

    On Windows os.replace fails with PermissionError while another handle
    (OneDrive sync, antivirus, a concurrent all_clients() read) has the target
    open, so retry with exponential backoff before giving up."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    delay = 0.05
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 7:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(delay)
            delay = min(delay * 2, 1.0)


# ── Plain JSON files (leads, history, settings, logs) ─────────────────────────
# Every unencrypted JSON store goes through these two, so reads tolerate a
# missing or damaged file the same way everywhere and writes are always atomic.

def read_json(path: Path, default=None):
    """Return the parsed contents of `path`, or `default` when the file is
    missing or unreadable (an unreadable file is reported on stderr)."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        print(f"[warn] {path.name} unreadable - using defaults", file=sys.stderr)
        return default


def write_json(path: Path, data, indent: int | None = 2, ensure_ascii: bool = True) -> None:
    """Write `data` as JSON to `path` atomically, creating the folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(data, indent=indent, ensure_ascii=ensure_ascii).encode("utf-8"))


_CLIENT_LIST_DEFAULTS = ("co_counsel", "access_log", "opposing_parties",
                         "related_parties", "conflict_checks")


def _apply_client_defaults(data: dict) -> dict:
    """Fill in fields older records predate. Shared by load_client and
    update_client_atomic so both return the same shape."""
    data.setdefault("hours_paid", 0)
    data.setdefault("payments", [])
    data.setdefault("legal_issue_summary", "")
    data.setdefault("activity_log", [])
    data.setdefault("billing_log", [])
    data.setdefault("esignature", None)
    for field in _CLIENT_LIST_DEFAULTS:
        data.setdefault(field, [])
    data.setdefault("billing_seen_at", "")
    data.setdefault("case_dates", {})
    data.setdefault("case_dates_history", [])
    return data


def load_client(username: str):
    # Reject anything that isn't a plain account name so a crafted username
    # cannot read a file from outside CLIENT_ACCOUNTS_DIR.
    if not username or safe_username(username) != username:
        return None
    path = shared.CLIENT_ACCOUNTS_DIR / f"{username}.json"
    if not path.exists():
        return None
    with _get_client_lock(username):
        data = _read_record(path)
    return _apply_client_defaults(data)


def save_client(data: dict):
    username = data["username"]
    if not username or safe_username(username) != username:
        raise ValueError(f"Refusing to save client with unsafe username: {username!r}")
    path = shared.CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        _write_record(path, data)
    # Outside the client lock — see the LOCK-ORDER INVARIANT above _get_client_lock.
    from services import billing
    billing.after_client_save(username)


def all_clients(skipped: list | None = None):
    clients = []
    for p in sorted(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")):
        try:
            clients.append(_read_record(p))
        except RecordDecryptError:
            print(f"[warn] could not decrypt client record: {p.stem}", file=sys.stderr)
            if skipped is not None:
                skipped.append(p.stem)
        except Exception:
            pass
    return clients


def safe_username(username: str) -> str:
    """Strip a username down to characters that cannot escape a directory.

    Every path built from a request-supplied username must go through this —
    otherwise a value like '..\\..\\etc' walks out of CLIENT_FILES_DIR.
    Returns "" when nothing usable remains, which callers must treat as invalid.
    """
    return "".join(c for c in (username or "").strip() if c.isalnum() or c in "_-")


def _client_docs_dir(username, category=None):
    base = shared.CLIENT_FILES_DIR / safe_username(username) / "documents"
    if category:
        d = base / category
        d.mkdir(parents=True, exist_ok=True)
        return d
    base.mkdir(parents=True, exist_ok=True)
    return base


def recalc_hours(client: dict) -> float:
    """Recompute hours_billed from the billing log — the single source of truth.

    Every code path that appends to billing_log must call this instead of
    incrementing hours_billed in place, or the two drift apart.
    """
    total = round(sum(float(e.get("hours", 0) or 0) for e in client.get("billing_log", [])), 2)
    client["hours_billed"] = total
    return total


# ── Activity log ──────────────────────────────────────────────────────────────

def _log_activity(username: str, action_type: str, description: str):
    """Append a timestamped activity entry to the client's activity_log. Silent on error."""
    try:
        client = load_client(username)
        if not client:
            return
        client.setdefault("activity_log", []).append({
            "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action_type": action_type,
            "description": description,
        })
        save_client(client)
    except Exception:
        pass


# ── Atomic record updates ─────────────────────────────────────────────────────

def update_client_field_atomic(username: str, field: str, value) -> None:
    """Set one top-level field without clobbering concurrent writes:
    re-read the record under the lock, set, write."""
    if not username or safe_username(username) != username:
        return
    path = shared.CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        if not path.exists():
            return
        record = _read_record(path)
        record[field] = value
        _write_record(path, record)


def update_client_atomic(username: str, mutate):
    """Re-read the client record under its lock, apply `mutate(client)` in
    place, and write it back — then run the billing save-hook outside the
    lock, exactly like save_client().

    Use this instead of load_client() ... save_client() whenever the gap
    between the two would be long enough for something else to write the
    same record in between (an AI call, a second request) — that plain
    read-modify-write silently drops whatever the other write added, because
    the later save() still has only the record as it was at the top of the
    request.

    `mutate` receives the freshly-read, defaulted client dict and changes it
    in place; its return value is ignored. Returns the saved client, or None
    if the record does not exist.
    """
    if not username or safe_username(username) != username:
        return None
    path = shared.CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        if not path.exists():
            return None
        client = _apply_client_defaults(_read_record(path))
        mutate(client)
        _write_record(path, client)
    # Outside the client lock — see the LOCK-ORDER INVARIANT above _get_client_lock.
    from services import billing
    billing.after_client_save(username)
    return client


# ── Token usage logger ────────────────────────────────────────────────────────

_token_usage_mutex = threading.Lock()


# Keep the per-user log bounded so the file stays small and fast to read.
_TOKEN_LOG_MAX_ENTRIES = 2000


def _log_token_usage(username: str, label: str, usage):
    """Append one AI call to the user's aggregate token-usage file.

    Writes TOKEN_USAGE_DIR/<username>.json in the shape the attorney portal's
    token-usage view reads: running totals plus a timestamped log.
    """
    uname = safe_username(username) or "unknown"
    try:
        entry = {
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "label":         label,
            "input_tokens":  getattr(usage, "input_tokens",  0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }
        path = shared.TOKEN_USAGE_DIR / f"{uname}.json"
        with _token_usage_mutex:
            data = read_json(path) or {"total_input_tokens": 0, "total_output_tokens": 0, "log": []}
            data.setdefault("log", []).append(entry)
            data["log"] = data["log"][-_TOKEN_LOG_MAX_ENTRIES:]
            data["total_input_tokens"]  = data.get("total_input_tokens",  0) + entry["input_tokens"]
            data["total_output_tokens"] = data.get("total_output_tokens", 0) + entry["output_tokens"]
            write_json(path, data)
    except Exception:
        pass


# ── Payment helper ────────────────────────────────────────────────────────────

def _apply_payment(username, amount_paid, method, reference):
    """Credit a payment to a client. Idempotent on `reference`.

    Both the provider webhook and the browser redirect can report the same
    payment, so a reference that is already recorded is silently ignored.
    """
    if not username or safe_username(username) != username:
        return False
    path = shared.CLIENT_ACCOUNTS_DIR / f"{username}.json"
    # Load, duplicate check, credit and save must be one critical section, or
    # the webhook and the browser redirect can both credit the same reference.
    # The lock is not re-entrant, so use the record I/O directly.
    with _get_client_lock(username):
        if not path.exists():
            return False
        client   = _read_record(path)
        payments = client.setdefault("payments", [])
        if reference and any(p.get("reference") == reference for p in payments):
            return False
        payments.append({
            "date":      datetime.now().strftime("%Y-%m-%d"),
            "amount":    amount_paid,
            "method":    method,
            "reference": reference,
        })
        client["hours_paid"] = round(
            sum(p.get("amount", 0) for p in payments) / shared.HOURLY_RATE, 2
        )
        _write_record(path, client)
    _log_activity(username, "payment_received",
                  f"Payment received: ${amount_paid:.2f} via {method} (ref: {reference})")
    return True


# ── Page-visit tracker ────────────────────────────────────────────────────────

_PAGE_VISITS_FILE = shared.DATA_ROOT / "page-visits.json"


def _load_page_visits():
    return read_json(_PAGE_VISITS_FILE, {})


def _save_page_visits(data: dict):
    try:
        write_json(_PAGE_VISITS_FILE, data, indent=None)
    except Exception:
        pass
