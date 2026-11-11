"""security.py — login throttling, session hardening, CSRF, security headers.

Wire into the app with security.init_app(app).
"""

import hmac
import json
import secrets
import sys
import threading
import time

from flask import (current_app, jsonify, make_response, redirect, render_template, request,
                   session, url_for)

import shared
from services import storage

MAX_FAILURES   = 5
WINDOW_SECONDS = 15 * 60
LOCK_SECONDS   = 15 * 60
IP_MAX_FAILURES  = 20      # per-IP bucket, across all usernames
ACCOUNT_MAX_FAILURES = 10  # per-account bucket, across all IPs
MAX_TRACKED_KEYS = 5000

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
    if len(keep) > MAX_TRACKED_KEYS:
        def rank(item):
            v = item[1]
            activity = max([v.get("locked_until", 0)] + list(v.get("failures", [])))
            return (v.get("locked_until", 0) > now, activity)   # unlocked, oldest first
        ordered = sorted(keep.items(), key=rank)
        keep = dict(ordered[len(keep) - MAX_TRACKED_KEYS:])
    path = _failures_path()
    try:
        storage.write_json(path, keep, indent=None)
    except Exception as exc:
        # A login must never 500 because the throttle file is locked.
        print(f"[warn] could not save {path.name}: {exc}", file=sys.stderr)


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


def _bump(data: dict, key: str, limit: int, now: float) -> None:
    entry = data.setdefault(key, {"failures": [], "locked_until": 0})
    entry["failures"] = [t for t in entry["failures"] if now - t < WINDOW_SECONDS] + [now]
    if len(entry["failures"]) >= limit:
        entry["locked_until"] = now + LOCK_SECONDS
        entry["failures"]     = []


def begin_login_attempt(kind: str, username: str, ip: str) -> int:
    """Atomically check the lock and count this attempt as a failure.

    Returns seconds remaining if the IP, the username/IP key, or the account
    itself is locked, else 0 after recording the attempt pessimistically (call
    clear_login_failures on success). One lock hold closes the race where
    parallel requests all pass the check during a slow password hash. The IP
    bucket is never cleared by a success, so spraying many usernames from one
    IP still accumulates; the account bucket stops guessing one account's
    password from many IPs."""
    now      = _now()
    ip_key   = f"ip:{ip or ''}"
    usr_key  = _key(kind, username, ip)
    acct_key = _acct_key(kind, username)
    with _state_lock:
        data = _load_failures()
        for k in (ip_key, usr_key, acct_key):
            remaining = data.get(k, {}).get("locked_until", 0) - now
            if remaining > 0:
                return int(remaining) + 1
        _bump(data, ip_key, IP_MAX_FAILURES, now)
        _bump(data, usr_key, MAX_FAILURES, now)
        _bump(data, acct_key, ACCOUNT_MAX_FAILURES, now)
        _save_failures(data)
    return 0


def _acct_key(kind: str, username: str) -> str:
    return f"acct:{kind}:{(username or '').strip().lower()}"


def clear_login_failures(kind: str, username: str, ip: str) -> None:
    with _state_lock:
        data    = _load_failures()
        changed = data.pop(_key(kind, username, ip), None) is not None
        acct = data.get(_acct_key(kind, username))
        if acct and acct.get("locked_until", 0) <= _now():
            data.pop(_acct_key(kind, username))
            changed = True
        # Withdraw this attempt's pessimistic entry from the IP bucket so
        # successful logins behind a shared IP (NAT) never add up to a lock.
        # A lock that is already set is left alone.
        now      = _now()
        ip_entry = data.get(f"ip:{ip or ''}")
        if ip_entry and ip_entry.get("locked_until", 0) <= now:
            past = [t for t in ip_entry["failures"] if t <= now]
            if past:
                ip_entry["failures"].remove(max(past))
                changed = True
        if changed:
            _save_failures(data)


def lockout_message(seconds: int) -> str:
    minutes = max(1, -(-seconds // 60))
    return f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."


# ── Rate limits for anonymous endpoints ───────────────────────────────────────
# In memory: one gunicorn worker (render.yaml), and a restart forgetting the
# counts is harmless. Keyed by client IP (ProxyFix makes that the real one).

_rate_lock = threading.Lock()
_rate_hits: dict = {}


def rate_limited(bucket: str, key: str, limit: int, window: int) -> bool:
    """Count one hit for bucket/key; True if it is over `limit` per `window` s."""
    if not current_app.config.get("RATE_LIMITS_ENABLED", True):
        return False
    now, k = _now(), f"{bucket}:{key}"
    with _rate_lock:
        hits = [t for t in _rate_hits.get(k, ()) if now - t < window]
        over = len(hits) >= limit
        if not over:
            hits.append(now)
        _rate_hits[k] = hits
        if len(_rate_hits) > MAX_TRACKED_KEYS:
            for stale in [x for x, v in _rate_hits.items() if not v or now - v[-1] > 3600]:
                del _rate_hits[stale]
    return over


def rate_limit(bucket: str, limit: int, window: int):
    """Decorator: answer 429 once an IP passes `limit` requests per `window` s."""
    import functools

    def wrap(f):
        @functools.wraps(f)
        def inner(*a, **kw):
            if rate_limited(bucket, request.remote_addr or "", limit, window):
                resp = jsonify({"error": "Too many requests. Please try again later."})
                resp.status_code = 429
                resp.headers["Retry-After"] = str(window)
                return resp
            return f(*a, **kw)
        return inner
    return wrap


# ── Sessions ──────────────────────────────────────────────────────────────────

IDLE_SECONDS = 30 * 60

# Background polls for live updates (blueprints/live.py), and the refreshes
# they trigger (sent with an X-Live-Refresh: 1 header), are checked against
# the idle timeout but never extend it: an open tab is not activity. The
# header can only withhold an extension, never grant one.
LIVE_POLL_PATHS = frozenset({"/portal/attorney/live", "/portal/client/live"})
LIVE_REFRESH_HEADER = "X-Live-Refresh"


def _is_background_refresh() -> bool:
    return request.path in LIVE_POLL_PATHS or request.headers.get(LIVE_REFRESH_HEADER) == "1"


def reset_session() -> None:
    """Clear the session but keep shared-mode Basic-Auth (require_auth's
    share_authed flag) — otherwise the next fetch() hits a 401 prompt."""
    share = session.get("share_authed")
    session.clear()
    if share:
        session["share_authed"] = True


# ── Session versions (server-side revocation) ──────────────────────────────────
# Sessions are signed cookies, so the server can't delete one. Each session
# instead carries the account's version number from login time; bumping the
# number (password change, invitation used, 2FA reset, "sign out everywhere")
# makes every older session fail the check below.

def _versions_path():
    return shared.SECURITY_STATE_DIR / "session-versions.json"


def session_version(role: str, username: str) -> int:
    data = storage.read_json(_versions_path(), {}) or {}
    return int(data.get(f"{role}:{username}", 0) or 0)


def bump_session_version(role: str, username: str) -> int:
    with _state_lock:
        data = storage.read_json(_versions_path(), {}) or {}
        key = f"{role}:{username}"
        data[key] = int(data.get(key, 0) or 0) + 1
        storage.write_json(_versions_path(), data, indent=None)
        return data[key]


def start_login_session(role: str, username: str) -> None:
    reset_session()                      # new session on login: blocks fixation
    session["role"]      = role
    session["username"]  = username
    session["last_seen"] = _now()
    session["sv"]        = session_version(role, username)
    session.permanent    = True


def _session_revoked(role: str, username: str) -> bool:
    if role == "attorney" and username not in shared.ATTORNEYS:
        return True
    return int(session.get("sv", 0) or 0) != session_version(role, username)


def enforce_idle_timeout():
    """before_request: end sessions idle for more than 30 minutes, and
    sessions revoked by a session-version bump."""
    if request.endpoint == "static":
        return None
    role = session.get("role")
    if not role:
        return None
    now  = _now()
    last = session.get("last_seen")
    revoked = _session_revoked(role, session.get("username", ""))
    if revoked or (last is not None and now - last > IDLE_SECONDS):
        reset_session()
        login = url_for("auth.attorney_login" if role == "attorney" else "auth.client_login")
        if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
            return redirect(login)
        resp = jsonify({"error": "Session expired."})
        resp.status_code = 401
        resp.headers["X-Session-Expired"] = "1"
        resp.headers["X-Login-Url"]       = login
        return resp
    if not _is_background_refresh():
        session["last_seen"] = now
    return None


# ── CSRF ──────────────────────────────────────────────────────────────────────

# Views opt out with @shared.csrf_exempt: signature-verified webhooks and
# anonymous endpoints that act on no session. Everything else that changes
# state needs a token.

def _csrf_exempt_view() -> bool:
    view = current_app.view_functions.get(request.endpoint or "")
    return bool(view and getattr(view, shared.CSRF_EXEMPT_ATTR, False))


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
    if _csrf_exempt_view():
        return None
    sent     = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("_csrf", "")
    if expected and sent and hmac.compare_digest(sent, expected):
        return None
    if request.path.startswith("/blog/review/"):
        resp = _review_expired_page()
    else:
        resp = jsonify({"error": "Invalid or missing CSRF token."})
    resp.status_code = 400
    resp.headers["X-CSRF-Failed"] = "1"
    return resp


def _review_expired_page():
    """Review links are opened from email, so a lost session gets a page, not
    JSON. The token is in the URL, hence the same headers as other review pages."""
    resp = make_response(render_template(
        "blog_action.html", heading="This page expired",
        message="Nothing was changed. Reload the link in the email and try again."))
    resp.headers["X-Robots-Tag"] = "noindex"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def init_app(app) -> None:
    app.config.setdefault("CSRF_ENABLED", True)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["csp_nonce"]  = csp_nonce
    app.before_request(enforce_idle_timeout)
    app.before_request(csrf_protect)
    app.after_request(set_security_headers)


# ── Headers ───────────────────────────────────────────────────────────────────

# Scripts run only from our own files or from inline <script> blocks that
# carry this request's nonce; inline on*= handlers are blocked (pages use
# data-on-* attributes, see static/js/events.js). Styles may stay inline.
# Responses that set their own policy (document previews) keep it.
# Frames: the blog's YouTube videos, from the privacy-enhanced domain only.
CSP = ("default-src 'self'; script-src 'self' 'nonce-{nonce}'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; "
       "connect-src 'self'; frame-src 'self' https://www.youtube-nocookie.com; frame-ancestors 'none'; "
       "form-action 'self'; base-uri 'self'; object-src 'none'")


def csp_nonce() -> str:
    from flask import g
    if not getattr(g, "csp_nonce", None):
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def set_security_headers(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    if request.endpoint != "static":
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("Content-Security-Policy", CSP.format(nonce=csp_nonce()))
    return resp
