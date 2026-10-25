"""security.py — login throttling, session hardening, CSRF, security headers.

Wire into the app with security.init_app(app).
"""

import hmac
import json
import os
import secrets
import sys
import threading
import time

from flask import current_app, jsonify, redirect, request, session, url_for

import shared

MAX_FAILURES   = 5
WINDOW_SECONDS = 15 * 60
LOCK_SECONDS   = 15 * 60
IP_MAX_FAILURES  = 20      # per-IP bucket, across all usernames
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
    tmp  = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(keep), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    except Exception as exc:
        # A login must never 500 because the throttle file is locked.
        print(f"[warn] could not save {path.name}: {exc}", file=sys.stderr)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


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

    Returns seconds remaining if the IP or username/IP key is locked, else 0
    after recording the attempt pessimistically (call clear_login_failures on
    success). One lock hold closes the race where parallel requests all pass
    the check during a slow password hash. The IP bucket is never cleared by
    a success, so spraying many usernames from one IP still accumulates."""
    now     = _now()
    ip_key  = f"ip:{ip or ''}"
    usr_key = _key(kind, username, ip)
    with _state_lock:
        data = _load_failures()
        for k in (ip_key, usr_key):
            remaining = data.get(k, {}).get("locked_until", 0) - now
            if remaining > 0:
                return int(remaining) + 1
        _bump(data, ip_key, IP_MAX_FAILURES, now)
        _bump(data, usr_key, MAX_FAILURES, now)
        _save_failures(data)
    return 0


def clear_login_failures(kind: str, username: str, ip: str) -> None:
    with _state_lock:
        data    = _load_failures()
        changed = data.pop(_key(kind, username, ip), None) is not None
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
    if request.endpoint == "static":
        return None
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


def init_app(app) -> None:
    app.config.setdefault("CSRF_ENABLED", True)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(enforce_idle_timeout)
    app.before_request(csrf_protect)
    app.after_request(set_security_headers)


# ── Headers ───────────────────────────────────────────────────────────────────

def set_security_headers(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.endpoint != "static":
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp
