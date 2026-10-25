"""
shared.py — Configuration, constants, helpers, and decorators shared across all blueprints.

Import this module in blueprints instead of importing from app.py to avoid circular imports.
"""

import os
import json
import re
import secrets
import sys
import threading
import time
import functools
import anthropic
import bcrypt

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import request, Response, session, redirect, url_for
from cryptography.fernet import Fernet, InvalidToken

# Google Calendar / Drive libraries (optional).
# InstalledAppFlow is imported here only to prove google_auth_oauthlib is present —
# /calendar/authorize needs it, and GOOGLE_LIBS gates that route.
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build as google_build
    GOOGLE_LIBS = True
except ImportError:
    GOOGLE_LIBS = False

# Optional document libraries
try:
    import mammoth  # noqa: F401 - availability probe for MAMMOTH_AVAILABLE
    MAMMOTH_AVAILABLE = True
except ImportError:
    MAMMOTH_AVAILABLE = False

try:
    import pypdf  # noqa: F401 - availability probe for PYPDF_AVAILABLE
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    from fpdf import FPDF  # noqa: F401 - availability probe for FPDF_AVAILABLE
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

# ── Base directory ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

# ── Firm identity ─────────────────────────────────────────────────────────────
# MT Legal is a solo practice. Every public page, email, PDF and AI prompt reads
# the firm and managing-partner names from here, so a rename is one edit.

FIRM_NAME     = "MT Legal"
FIRM_TAGLINE  = "Nashville & Middle Tennessee"
FIRM_CITY     = "Nashville, Tennessee"

MANAGING_PARTNER = {
    "username": "Endocide",
    "name":     "Madison T. Biggs",
    "display":  "Madison T. Biggs, Esq.",
    "title":    "Founder & Managing Partner",
    "role":     "AI · Blockchain · Estate · Litigation",
    "photo":    "managing-partner.jpg",
}

# Counties the marketing site names as the firm's service area.
SERVICE_COUNTIES = [
    "Davidson", "Williamson", "Rutherford", "Wilson", "Sumner",
    "Maury", "Montgomery", "Robertson", "Bedford", "Dickson",
]


def partner_photo_filename() -> str:
    """The managing partner's headshot, or a monogram placeholder until the
    real photo is saved to static/images/managing-partner.jpg."""
    if (BASE_DIR / "static" / "images" / MANAGING_PARTNER["photo"]).exists():
        return MANAGING_PARTNER["photo"]
    return "managing-partner-placeholder.svg"


# ── Attorney registry ─────────────────────────────────────────────────────────

ATTORNEYS = {
    "Endocide": {
        "password":  os.getenv("ATTORNEY_ENDOCIDE_HASH", ""),
        "display":   MANAGING_PARTNER["display"],
        "case_type": "Criminal Defense",
    },
    "SophiaH": {
        "password":  os.getenv("ATTORNEY_SOPHIAH_HASH", ""),
        "display":   "Sophia L. Hargrove, Esq.",
        "case_type": "Civil Litigation",
    },
}

# Solo practice: every matter is handled by the managing partner.
CASE_ATTORNEY_MAP = {
    "Criminal Defense":           "Endocide",
    "Civil Litigation":           "Endocide",
    "Contract Dispute":           "Endocide",
    "Personal Injury":            "Endocide",
    "Family Law — Divorce":       "Endocide",
    "Family Law — Child Custody": "Endocide",
    "Family Law — Other":         "Endocide",
    "Real Estate":                "Endocide",
    "Employment Law":             "Endocide",
    "DeFi / Crypto Law":          "Endocide",
    "Crypto LLC Formation":       "Endocide",
    "Real World Assets Tokenization": "Endocide",
    "AI / Technology Law":        "Endocide",
    "Civil Rights":               "Endocide",
    "Stablecoins / Digital Payments": "Endocide",
    "Estate Planning":            "Endocide",
    "Other":                      "Endocide",
}

# ── Deployment ────────────────────────────────────────────────────────────────
# APP_ENV=production turns on HTTPS-only cookies and HSTS, and fails fast at
# startup on missing secrets. PUBLIC_SITE_ONLY=1 serves only the marketing site
# and intake: portals, logins, and attorney tools return 404 (see app.py).

def _env(name: str) -> str:
    """An env var with surrounding whitespace and stray quotes removed, so a
    value pasted into a hosting dashboard as "1" or 'production' still counts."""
    return os.getenv(name, "").strip().strip("\"'").strip()


IS_PRODUCTION    = _env("APP_ENV").lower() == "production"
PUBLIC_SITE_ONLY = _env("PUBLIC_SITE_ONLY").lower() in ("1", "true", "yes", "on")

# ── Data directories ──────────────────────────────────────────────────────────
# DATA_DIR points every runtime data folder at a persistent disk in hosting
# (e.g. /var/data); locally it defaults to the project folder as before.

DATA_ROOT = Path(_env("DATA_DIR") or BASE_DIR)

CLIENT_DATA_DIR      = DATA_ROOT / "client-data"
RESEARCH_HISTORY_DIR = DATA_ROOT / "research-history"
DRAFT_HISTORY_DIR    = DATA_ROOT / "draft-history"
LEADS_DIR            = DATA_ROOT / "leads"
CLIENT_ACCOUNTS_DIR  = DATA_ROOT / "client-accounts"
CLIENT_FILES_DIR     = DATA_ROOT / "client-files"
CASE_SEARCHES_DIR    = DATA_ROOT / "case-searches"
TOKEN_USAGE_DIR      = DATA_ROOT / "token-usage"
SECURITY_STATE_DIR   = DATA_ROOT / "security-state"
CLIENT_BILLING_DIR   = DATA_ROOT / "client-billing"
FIRM_SETTINGS_DIR    = DATA_ROOT / "firm-settings"

for _d in (
    CLIENT_DATA_DIR, RESEARCH_HISTORY_DIR, DRAFT_HISTORY_DIR, LEADS_DIR,
    CLIENT_ACCOUNTS_DIR, CLIENT_FILES_DIR, CASE_SEARCHES_DIR, TOKEN_USAGE_DIR,
    SECURITY_STATE_DIR, CLIENT_BILLING_DIR, FIRM_SETTINGS_DIR,
):
    _d.mkdir(exist_ok=True)

# ── API / payment config ──────────────────────────────────────────────────────

ANTHROPIC_API_KEY        = os.getenv("ANTHROPIC_API_KEY")
MODEL                    = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

HOURLY_RATE              = float(os.getenv("HOURLY_RATE", "350"))
MONTHLY_RENT             = float(os.getenv("MONTHLY_RENT")         or "0")
MONTHLY_SALARIES         = float(os.getenv("MONTHLY_SALARIES")     or "0")
MONTHLY_SOFTWARE         = float(os.getenv("MONTHLY_SOFTWARE")     or "0")
MONTHLY_INSURANCE        = float(os.getenv("MONTHLY_INSURANCE")    or "0")
MONTHLY_MARKETING        = float(os.getenv("MONTHLY_MARKETING")    or "0")
MONTHLY_MISC             = float(os.getenv("MONTHLY_MISC")         or "0")
OVERHEAD_RESERVE_PCT     = float(os.getenv("OVERHEAD_RESERVE_PCT") or "0.35")

# ── Document categories & allowed extensions ──────────────────────────────────

DOCS_CATEGORIES = [
    "Intake",
    "Generated Documents",
    "Motions",
    "Litigation Drafts",
    "Court Orders",
    "Scheduling Orders",
    "Warrants & Discovery",
    "Research",
    "Other",
]

ALLOWED_DOC_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".txt", ".rtf", ".odt", ".html",
}

STRIPE_SECRET_KEY                = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY           = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET            = os.getenv("STRIPE_WEBHOOK_SECRET", "")
COINBASE_COMMERCE_API_KEY        = os.getenv("COINBASE_COMMERCE_API_KEY", "")
COINBASE_COMMERCE_WEBHOOK_SECRET = os.getenv("COINBASE_COMMERCE_WEBHOOK_SECRET", "")

# ── Google Calendar config ────────────────────────────────────────────────────

CALENDAR_SCOPES  = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
]
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE       = DATA_ROOT / "calendar-token.json"


# ═════════════════════════════════════════════════════════════════════════════
# Anthropic client
# ═════════════════════════════════════════════════════════════════════════════

def get_anthropic_client():
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set. Please add it to your .env file.")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═════════════════════════════════════════════════════════════════════════════
# Route decorators
# ═════════════════════════════════════════════════════════════════════════════

def require_auth(f):
    """Gate every route behind HTTP Basic Auth when SHARE_PASSWORD is set.
    After first successful Basic Auth, stores a session flag so that
    JS fetch() calls (which send cookies but not Basic Auth headers) also pass.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        password = os.getenv("SHARE_PASSWORD", "").strip()
        if password:
            # Session cookie already set from a prior successful auth — let through
            if session.get("share_authed"):
                return f(*args, **kwargs)
            auth = request.authorization
            if not auth or auth.password != password:
                return Response(
                    "Authentication required.",
                    401,
                    {"WWW-Authenticate": 'Basic realm="Law Office App"'},
                )
            # Stamp the session so fetch() calls don't need to re-send Basic Auth
            session["share_authed"] = True
        return f(*args, **kwargs)
    return decorated


def require_attorney(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "attorney":
            return redirect(url_for("auth.attorney_login"))
        return f(*args, **kwargs)
    return decorated


def require_client(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "client":
            return redirect(url_for("auth.client_login"))
        return f(*args, **kwargs)
    return decorated


# ═════════════════════════════════════════════════════════════════════════════
# Client file I/O helpers
# ═════════════════════════════════════════════════════════════════════════════

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
    """Encrypt and write a client account file atomically.

    On Windows os.replace fails with PermissionError while another handle
    (OneDrive sync, antivirus, a concurrent all_clients() read) has the target
    open, so retry with exponential backoff before giving up."""
    token = _fernet().encrypt(json.dumps(data, indent=2).encode("utf-8"))
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(token)
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
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    if not path.exists():
        return None
    with _get_client_lock(username):
        data = _read_record(path)
    return _apply_client_defaults(data)


def save_client(data: dict):
    username = data["username"]
    if not username or safe_username(username) != username:
        raise ValueError(f"Refusing to save client with unsafe username: {username!r}")
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        _write_record(path, data)
    # Outside the client lock — see the LOCK-ORDER INVARIANT above _get_client_lock.
    import billing
    billing.after_client_save(username)


def all_clients(skipped: list | None = None):
    clients = []
    for p in sorted(CLIENT_ACCOUNTS_DIR.glob("*.json")):
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
    base = CLIENT_FILES_DIR / safe_username(username) / "documents"
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


# ═════════════════════════════════════════════════════════════════════════════
# Password helpers
# ═════════════════════════════════════════════════════════════════════════════

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
    for path in sorted(CLIENT_ACCOUNTS_DIR.glob("*.json")):
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


# ═════════════════════════════════════════════════════════════════════════════
# Username / activity helpers
# ═════════════════════════════════════════════════════════════════════════════

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
    existing = {p.stem for p in CLIENT_ACCOUNTS_DIR.glob("*.json")}
    if base not in existing:
        return base
    for i in range(2, 100):
        candidate = f"{base}{i}"
        if candidate not in existing:
            return candidate
    return base


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


def log_access_atomic(username: str, action: str, detail: str = "") -> None:
    """Record an access entry for a read-only route without clobbering
    concurrent writes: re-read the record under the lock, append, write."""
    if not username or safe_username(username) != username:
        return
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        if not path.exists():
            return
        record = _read_record(path)
        if _log_access(record, action, detail):
            _write_record(path, record)


def update_client_field_atomic(username: str, field: str, value) -> None:
    """Set one top-level field without clobbering concurrent writes:
    re-read the record under the lock, set, write."""
    if not username or safe_username(username) != username:
        return
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
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
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
    with _get_client_lock(username):
        if not path.exists():
            return None
        client = _apply_client_defaults(_read_record(path))
        mutate(client)
        _write_record(path, client)
    # Outside the client lock — see the LOCK-ORDER INVARIANT above _get_client_lock.
    import billing
    billing.after_client_save(username)
    return client


# ═════════════════════════════════════════════════════════════════════════════
# Token usage logger
# ═════════════════════════════════════════════════════════════════════════════

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
        path = TOKEN_USAGE_DIR / f"{uname}.json"
        with _token_usage_mutex:
            data = {"total_input_tokens": 0, "total_output_tokens": 0, "log": []}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            data.setdefault("log", []).append(entry)
            data["log"] = data["log"][-_TOKEN_LOG_MAX_ENTRIES:]
            data["total_input_tokens"]  = data.get("total_input_tokens",  0) + entry["input_tokens"]
            data["total_output_tokens"] = data.get("total_output_tokens", 0) + entry["output_tokens"]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Payment helper
# ═════════════════════════════════════════════════════════════════════════════

def _apply_payment(username, amount_paid, method, reference):
    """Credit a payment to a client. Idempotent on `reference`.

    Both the provider webhook and the browser redirect can report the same
    payment, so a reference that is already recorded is silently ignored.
    """
    if not username or safe_username(username) != username:
        return False
    path = CLIENT_ACCOUNTS_DIR / f"{username}.json"
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
            sum(p.get("amount", 0) for p in payments) / HOURLY_RATE, 2
        )
        _write_record(path, client)
    _log_activity(username, "payment_received",
                  f"Payment received: ${amount_paid:.2f} via {method} (ref: {reference})")
    return True


# ═════════════════════════════════════════════════════════════════════════════
# Google Calendar / Drive helpers
# ═════════════════════════════════════════════════════════════════════════════

def _google_credentials(not_authorized_message: str):
    """Load stored Google credentials, refreshing them if they have expired.

    Raises ValueError with a user-facing message when the app has never been
    authorized (or the refresh token is gone and the user must re-consent).
    """
    if not GOOGLE_LIBS:
        raise ValueError("Google libraries not installed. Run: pip install -r requirements.txt")
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), CALENDAR_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        else:
            raise ValueError(not_authorized_message)
    return creds


def get_drive_service():
    creds = _google_credentials(
        "Google Drive not authorized. "
        "Go to the Dashboard and click 'Authorize Google Calendar'."
    )
    return google_build("drive", "v3", credentials=creds)


def get_calendar_service():
    creds = _google_credentials(
        "Google Calendar not authorized. "
        "Go to the Dashboard and click 'Authorize Google Calendar'."
    )
    return google_build("calendar", "v3", credentials=creds)


def create_intake_doc(record, urgent_dates):
    from googleapiclient.http import MediaInMemoryUpload

    def row(label, val):
        if not val:
            return ""
        return (
            f"<tr><td style='padding:6px 12px;font-weight:bold;width:38%;"
            f"border-bottom:1px solid #eee'>{label}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{val}</td></tr>"
        )

    urgent_html = ""
    if urgent_dates:
        items = "".join(
            f"<li><strong>{d['label']}:</strong> {d['date']} "
            f"({d['days_away']} day{'s' if d['days_away'] != 1 else ''} away)</li>"
            for d in urgent_dates
        )
        urgent_html = (
            f"<div style='background:#fde8e8;border:2px solid #c0392b;"
            f"padding:12px 16px;margin-bottom:16px;border-radius:4px'>"
            f"<strong style='color:#c0392b'>⚠ URGENT DEADLINES</strong>"
            f"<ul>{items}</ul></div>"
        )

    html = (
        f"<html><body style='font-family:Georgia,serif;max-width:800px;"
        f"margin:0 auto;padding:24px'>"
        f"<h1 style='color:#1a2c4e;border-bottom:2px solid #c9a84c;"
        f"padding-bottom:8px'>Client Intake — {record['full_name']}</h1>"
        f"<p style='color:#888;font-size:14px'>Created: "
        f"{record['timestamp'][:4]}-{record['timestamp'][4:6]}-{record['timestamp'][6:8]}"
        f" &nbsp;|&nbsp; File: {record['saved_file']}</p>"
        f"{urgent_html}"
        f"<h2 style='color:#1a2c4e'>Client Information</h2>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"{row('Full Name', record['full_name'])}"
        f"{row('Date of Birth', record.get('dob', ''))}"
        f"{row('Phone', record.get('phone', ''))}"
        f"{row('Email', record.get('email', ''))}"
        f"{row('Case Type', record.get('case_type', ''))}"
        f"{row('Referral Source', record.get('referral_source', ''))}"
        f"</table>"
        f"<h2 style='color:#1a2c4e'>Matter Description</h2>"
        f"<p style='line-height:1.6'>"
        f"{record.get('matter_description', '').replace(chr(10), '<br>')}</p>"
        f"<h2 style='color:#1a2c4e'>Key Dates</h2>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"{row('Arrest Date', record.get('arrest_date', ''))}"
        f"{row('Court Date', record.get('court_date_1', ''))}"
        f"</table></body></html>"
    )

    service = get_drive_service()
    file_metadata = {
        "name":     f"Intake — {record['full_name']} ({record['timestamp'][:8]})",
        "mimeType": "application/vnd.google-apps.document",
    }
    media = MediaInMemoryUpload(html.encode("utf-8"), mimetype="text/html")
    f = service.files().create(
        body=file_metadata, media_body=media, fields="id,webViewLink"
    ).execute()
    return f.get("webViewLink")


def _push_court_date_to_gcal(client_name: str, court_date_str: str):
    if not GOOGLE_LIBS or not TOKEN_FILE.exists():
        return None
    try:
        court_date = datetime.strptime(court_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    try:
        service = get_calendar_service()
        event = {
            "summary":     f"Court Date: {client_name}",
            "description": f"Court date for client {client_name} — MT Legal",
            "start": {"date": court_date_str},
            "end":   {"date": (court_date + timedelta(days=1)).isoformat()},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return created.get("id")
    except Exception:
        return None


def _gcal_status(exc) -> int | None:
    resp = getattr(exc, "resp", None)
    try:
        return int(getattr(resp, "status", None))
    except (TypeError, ValueError):
        return None


def gcal_connected() -> bool:
    return bool(GOOGLE_LIBS and TOKEN_FILE.exists())


def _gcal_all_day_body(summary: str, description: str, date_str: str):
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    return {"summary": summary, "description": description,
            "start": {"date": date_str},
            "end":   {"date": (day + timedelta(days=1)).isoformat()}}


def gcal_create_all_day(summary: str, description: str, date_str: str):
    """Create an all-day event. Returns its id, or None (not connected / error)."""
    if not GOOGLE_LIBS or not TOKEN_FILE.exists():
        return None
    try:
        body = _gcal_all_day_body(summary, description, date_str)
        created = get_calendar_service().events().insert(calendarId="primary", body=body).execute()
        return created.get("id")
    except Exception:
        return None


def gcal_update_all_day(event_id: str, summary: str, description: str, date_str: str) -> str:
    """Move an all-day event. Returns "ok", "gone" (404/410) or "error"."""
    if not GOOGLE_LIBS or not TOKEN_FILE.exists() or not event_id:
        return "error"
    try:
        body = _gcal_all_day_body(summary, description, date_str)
        get_calendar_service().events().patch(calendarId="primary", eventId=event_id,
                                              body=body).execute()
        return "ok"
    except Exception as exc:
        return "gone" if _gcal_status(exc) in (404, 410) else "error"


def gcal_delete_event(event_id: str) -> str:
    """Delete an event. Returns "ok", "gone" (already deleted) or "error"."""
    if not GOOGLE_LIBS or not TOKEN_FILE.exists() or not event_id:
        return "error"
    try:
        get_calendar_service().events().delete(calendarId="primary", eventId=event_id).execute()
        return "ok"
    except Exception as exc:
        return "gone" if _gcal_status(exc) in (404, 410) else "error"


def _fetch_gcal_events(days_ahead: int = 180) -> list:
    if not GOOGLE_LIBS or not TOKEN_FILE.exists():
        return []
    try:
        service    = get_calendar_service()
        now        = datetime.now(timezone.utc)
        now_iso    = now.isoformat()
        cutoff_iso = (now + timedelta(days=days_ahead)).isoformat()
        result = service.events().list(
            calendarId   = "primary",
            timeMin      = now_iso,
            timeMax      = cutoff_iso,
            maxResults   = 250,
            singleEvents = True,
            orderBy      = "startTime",
        ).execute()
        events = []
        for item in result.get("items", []):
            start        = item.get("start", {})
            date_str     = start.get("date", "")
            datetime_str = start.get("dateTime", "")
            events.append({
                "summary":        item.get("summary", ""),
                "start_date":     date_str or datetime_str[:10],
                "start_datetime": datetime_str,
                "gcal_id":        item.get("id", ""),
            })
        return events
    except Exception:
        return []


# ═════════════════════════════════════════════════════════════════════════════
# Page-visit tracker
# ═════════════════════════════════════════════════════════════════════════════

_PAGE_VISITS_FILE = DATA_ROOT / "page-visits.json"


def _load_page_visits():
    if _PAGE_VISITS_FILE.exists():
        try:
            with open(_PAGE_VISITS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_page_visits(data: dict):
    try:
        with open(_PAGE_VISITS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# AI system prompts
# ═════════════════════════════════════════════════════════════════════════════

CRIMINAL_SYSTEM_PROMPT = """You are an expert criminal defense legal research assistant.
When given a legal question or issue, produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Constitutional Issues &amp; Suppression Arguments</h3>
<h3>Relevant Case Law</h3>
<h3>Sentencing Considerations</h3>
<h3>Recommended Next Steps</h3>

Focus on: constitutional protections (4th, 5th, 6th Amendment), suppression arguments,
Brady/Giglio material, sentencing guidelines and mitigation, and procedural defenses.
Be thorough but concise. Flag any area where verification is especially important."""

CIVIL_SYSTEM_PROMPT = """You are an expert civil litigation legal research assistant.
When given a legal question or issue, produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Causes of Action &amp; Elements</h3>
<h3>Available Defenses</h3>
<h3>Relevant Case Law &amp; Statutes</h3>
<h3>Procedural Posture &amp; Strategy</h3>
<h3>Recommended Next Steps</h3>

Focus on: elements of each cause of action, affirmative defenses, damages theories,
discovery strategy, and dispositive motion practice.
Be thorough but concise. Flag any area where verification is especially important."""

DEFI_SYSTEM_PROMPT = """You are an expert DeFi and cryptocurrency legal research assistant.
When given a legal question or issue involving blockchain, digital assets, or decentralized finance,
produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Regulatory Framework</h3>
<h3>Relevant Case Law &amp; Guidance</h3>
<h3>Risk Assessment</h3>
<h3>Recommended Next Steps</h3>

Focus on:
- Securities law: Howey Test, Reg D (506b/506c), Reg A+, Reg S, Reg CF
- Token standards and classifications: ERC-20, ERC-1400, ERC-3643, ERC-721/1155
- Smart contract legal exposure: admin key risks, upgrade proxy risks, oracle dependencies, reentrancy (liability)
- DAO entity structures: Wyoming DAO LLC, Cayman Islands Foundation, Marshall Islands, Swiss Association, BVI
- Crypto estate planning: crypto wills, multi-sig inheritance vaults, hardware wallet succession, trust amendments
- Regulatory bodies: SEC, CFTC, IRS (crypto as property, capital gains, staking income, FBAR/FATCA), FinCEN

Important disclaimers to include in every memo:
- This is legal information, not legal advice, until a formal engagement letter is signed.
- DeFi law is rapidly evolving — always verify current SEC/CFTC guidance at the time of review.
- Smart contract code review by a qualified Solidity auditor is recommended alongside legal review.
- Tax advice requires a CPA or tax attorney.

Be thorough but concise. Use plain English first, then introduce technical terms with brief definitions."""

FAMILY_SYSTEM_PROMPT = """You are an expert family law legal research assistant.
When given a question or issue involving divorce, child custody, child support, or domestic relations,
produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Applicable Legal Standard</h3>
<h3>Key Statutory &amp; Case Authority</h3>
<h3>Factors the Court Will Consider</h3>
<h3>Strategic Considerations</h3>
<h3>Recommended Next Steps</h3>

Focus on Tennessee family law: T.C.A. § 36-6-106 (custody factors), child support guidelines,
alimony types (T.C.A. § 36-5-121), UCCJEA, UIFSA, domestic violence protections.
Be thorough but concise. Always note outcomes depend heavily on specific facts and judicial discretion."""

PERSONAL_INJURY_SYSTEM_PROMPT = """You are an expert personal injury and tort law legal research assistant.
When given a question involving negligence, premises liability, auto accidents, or other torts,
produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Elements of the Claim</h3>
<h3>Damages Available</h3>
<h3>Key Defenses</h3>
<h3>Relevant Authority</h3>
<h3>Practical &amp; Strategic Notes</h3>
<h3>Recommended Next Steps</h3>

Focus on Tennessee tort law: modified comparative fault (50% rule, T.C.A. § 29-11-103),
HCLA requirements (T.C.A. § 29-26-115), TPLA, statutes of limitations (§ 28-3-104).
Flag when expert testimony is required and when pre-suit procedural steps apply."""

EMPLOYMENT_SYSTEM_PROMPT = """You are an expert employment law legal research assistant.
When given a question involving workplace discrimination, wrongful termination, wage/hour violations,
harassment, or retaliation, produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Legal Framework &amp; Applicable Statutes</h3>
<h3>Elements of the Claim</h3>
<h3>Employer Defenses</h3>
<h3>Damages &amp; Remedies</h3>
<h3>Administrative Prerequisites &amp; Deadlines</h3>
<h3>Recommended Next Steps</h3>

Focus on: Title VII, ADA, ADEA, Tennessee THRA (T.C.A. § 4-21-101), FLSA, FMLA,
Tennessee Restrictive Covenant Act (T.C.A. § 47-25-101). Flag tight EEOC deadlines."""

REAL_ESTATE_SYSTEM_PROMPT = """You are an expert real estate law legal research assistant.
When given a question involving property transactions, title disputes, landlord-tenant matters,
zoning, foreclosure, or easements, produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Applicable Legal Framework</h3>
<h3>Key Statutes &amp; Case Authority</h3>
<h3>Risk Analysis</h3>
<h3>Transactional / Litigation Considerations</h3>
<h3>Recommended Next Steps</h3>

Focus on Tennessee real estate: URLTA (T.C.A. § 66-28-101), eviction procedure (T.C.A. § 29-18-101),
non-judicial foreclosure (T.C.A. § 35-5-101), mechanic's liens (T.C.A. § 66-11-101).
Distinguish transactional and litigation contexts. Flag recording deadlines."""

CONTRACT_SYSTEM_PROMPT = """You are an expert contracts and commercial law legal research assistant.
When given a question involving contract formation, breach, enforcement, or commercial disputes,
produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Contract Analysis</h3>
<h3>Breach &amp; Damages Theory</h3>
<h3>Defenses &amp; Counterclaims</h3>
<h3>Key Authority</h3>
<h3>Recommended Next Steps</h3>

Focus on: contract formation, statute of frauds (T.C.A. § 29-2-101), UCC Article 2,
Tennessee statutes of limitations (§ 28-3-109 written, § 28-3-105 oral), economic loss rule,
arbitration clauses. Flag when choice-of-law clause may change the analysis."""

SYSTEM_PROMPTS = {
    "Criminal Defense":           CRIMINAL_SYSTEM_PROMPT,
    "DeFi / Crypto Law":          DEFI_SYSTEM_PROMPT,
    "Family Law — Divorce":       FAMILY_SYSTEM_PROMPT,
    "Family Law — Child Custody": FAMILY_SYSTEM_PROMPT,
    "Family Law — Other":         FAMILY_SYSTEM_PROMPT,
    "Personal Injury":            PERSONAL_INJURY_SYSTEM_PROMPT,
    "Employment Law":             EMPLOYMENT_SYSTEM_PROMPT,
    "Real Estate":                REAL_ESTATE_SYSTEM_PROMPT,
    "Contract Dispute":           CONTRACT_SYSTEM_PROMPT,
}
