"""billing.py — client billing statements, per-attorney thresholds, notices.

Statement state lives in a per-client encrypted ledger
(client-billing/<username>.json) that only this module writes, using locked
read-modify-write. Client-record saves never touch it, so a stale save can't
undo a statement or a sent notice. billing_log is append-only; the ledger
records how many leading entries are covered ("covered_through").

LOCK-ORDER INVARIANT: a ledger lock may be held while briefly taking a client
lock (shared.load_client). Never take a ledger lock, call any billing function,
or call shared.save_client while holding a client lock.
"""

import json
import math
import os
import sys
import threading
from datetime import datetime

import shared

DEFAULT_STATEMENT_THRESHOLD = 2000.0
MIN_THRESHOLD = 100.0
MAX_THRESHOLD = 100_000.0
NOTICE_ASYNC = True
NOTICE_STALE_SECONDS = 900
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"

_ledger_locks: dict = {}
_ledger_locks_mutex = threading.Lock()
_settings_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime(_TS_FORMAT)


# ── Small JSON files (settings, migration flag) ──────────────────────────────

def _read_json(path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        print(f"[warn] {path.name} unreadable — using defaults", file=sys.stderr)
        return {}


def _write_json(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── Thresholds ───────────────────────────────────────────────────────────────

def _settings_path():
    return shared.FIRM_SETTINGS_DIR / "attorney-settings.json"


def get_threshold(attorney) -> float:
    entry = _read_json(_settings_path()).get(attorney or "", {})
    try:
        value = float(entry.get("statement_threshold", DEFAULT_STATEMENT_THRESHOLD))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_STATEMENT_THRESHOLD
    if math.isfinite(value) and MIN_THRESHOLD <= value <= MAX_THRESHOLD:
        return value
    return DEFAULT_STATEMENT_THRESHOLD


def set_threshold(attorney: str, amount) -> float:
    try:
        value = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("Threshold must be between $100 and $100,000.")
    if not math.isfinite(value) or not (MIN_THRESHOLD <= value <= MAX_THRESHOLD):
        raise ValueError("Threshold must be between $100 and $100,000.")
    with _settings_lock:
        data = _read_json(_settings_path())
        data.setdefault(attorney, {})["statement_threshold"] = value
        _write_json(_settings_path(), data)
    return value


# ── Migration flag ───────────────────────────────────────────────────────────

def _migrations_path():
    return shared.FIRM_SETTINGS_DIR / "migrations.json"


def is_migrated() -> bool:
    return bool(_read_json(_migrations_path()).get("opening_statements"))


def mark_migrated() -> None:
    data = _read_json(_migrations_path())
    data["opening_statements"] = _now()
    _write_json(_migrations_path(), data)


# ── Ledger I/O ───────────────────────────────────────────────────────────────

def _ledger_lock(username: str) -> threading.Lock:
    with _ledger_locks_mutex:
        return _ledger_locks.setdefault(username, threading.Lock())


def _ledger_path(username: str):
    if not username or shared.safe_username(username) != username:
        raise ValueError("unsafe username")
    return shared.CLIENT_BILLING_DIR / f"{username}.json"


def _empty_ledger() -> dict:
    return {"covered_through": 0, "covered_fingerprint": None, "statements": []}


def _read_ledger(username: str) -> dict:
    path = _ledger_path(username)
    if not path.exists():
        return _empty_ledger()
    ledger = shared._read_record(path)
    for key, value in _empty_ledger().items():
        ledger.setdefault(key, value)
    return ledger


def _write_ledger(username: str, ledger: dict) -> None:
    shared.CLIENT_BILLING_DIR.mkdir(parents=True, exist_ok=True)
    shared._write_record(_ledger_path(username), ledger)


def load_ledger(username: str) -> dict:
    """Read-only snapshot of a client's ledger (empty if none)."""
    if not username or shared.safe_username(username) != username:
        return _empty_ledger()
    return _read_ledger(username)


# ── Money ────────────────────────────────────────────────────────────────────

def _hours(entries) -> float:
    return round(sum(float(e.get("hours", 0) or 0) for e in entries), 2)


def _fingerprint(entry: dict) -> list:
    return [entry.get("date", ""), float(entry.get("hours", 0) or 0),
            (entry.get("note") or "")[:40]]


def unbilled_entries(client: dict, ledger: dict) -> list:
    log = client.get("billing_log") or []
    return list(log[min(ledger["covered_through"], len(log)):])


def unbilled_amount(client: dict, ledger: dict) -> float:
    return round(_hours(unbilled_entries(client, ledger)) * shared.HOURLY_RATE, 2)


def statement_total(ledger: dict) -> float:
    return round(sum(float(s.get("amount", 0)) for s in ledger["statements"]), 2)


def billed_hours(ledger: dict) -> float:
    return round(sum(float(s.get("hours", 0)) for s in ledger["statements"]), 2)


def paid_total(client: dict) -> float:
    return round(sum(float(p.get("amount", 0) or 0) for p in client.get("payments") or []), 2)


def amount_due(client: dict, ledger: dict) -> float:
    return max(0.0, round(statement_total(ledger) - paid_total(client), 2))


# ── Issuing ──────────────────────────────────────────────────────────────────

def issue_statement(username: str, *, reason: str, issued_by: str, notify: bool,
                    only_if_over_threshold: bool = False):
    """Issue a statement for all unbilled entries. Returns the statement, or
    None when there's nothing (or nothing positive) to bill, or when
    only_if_over_threshold and the threshold isn't reached."""
    if not username or shared.safe_username(username) != username:
        return None
    with _ledger_lock(username):
        client = shared.load_client(username)
        if not client:
            return None
        ledger = _read_ledger(username)
        _check_fingerprint(username, client, ledger)
        log = client.get("billing_log") or []
        start = min(ledger["covered_through"], len(log))
        entries = log[start:]
        hours = _hours(entries)
        if not math.isfinite(hours):
            print(f"billing: non-finite hours for client {username!r}; no statement issued",
                  file=sys.stderr)
            return None
        if not entries or hours <= 0:
            return None
        rate = float(shared.HOURLY_RATE)
        amount = round(hours * rate, 2)
        if only_if_over_threshold and amount < get_threshold(client.get("assigned_attorney")):
            return None
        number = max((s["number"] for s in ledger["statements"]), default=0) + 1
        dates = [e.get("date") for e in entries if e.get("date")]
        now = _now()
        statement = {
            "id": f"st_{number}", "number": number, "issued_at": now,
            "billed_through": max(dates) if dates else now[:10],
            "entries_from": start, "entries_to": len(log),
            "hours": hours, "rate": rate, "amount": amount,
            "reason": reason, "issued_by": issued_by,
            "notice": {"status": "pending" if notify else "skipped",
                       "at": None, "error": "", "claimed_at": None},
        }
        ledger["statements"].append(statement)
        ledger["covered_through"] = len(log)
        ledger["covered_fingerprint"] = _fingerprint(log[-1])
        _write_ledger(username, ledger)
        return json.loads(json.dumps(statement))


def set_baseline(username: str) -> bool:
    """Mark every current entry as visible without issuing a statement
    (used by the migration for clients with no positive time)."""
    if not username or shared.safe_username(username) != username:
        return False
    with _ledger_lock(username):
        client = shared.load_client(username)
        if not client:
            return False
        ledger = _read_ledger(username)
        log = client.get("billing_log") or []
        if ledger["covered_through"] >= len(log):
            return False
        ledger["covered_through"] = len(log)
        ledger["covered_fingerprint"] = _fingerprint(log[-1]) if log else None
        _write_ledger(username, ledger)
        return True


# ── Views ────────────────────────────────────────────────────────────────────

_PUBLIC_STATEMENT_FIELDS = ("id", "number", "issued_at", "billed_through", "hours", "rate", "amount")


def billing_summary(client: dict, ledger: dict) -> dict:
    """Attorney-facing billing state."""
    unbilled = unbilled_entries(client, ledger)
    return {
        "unbilled_hours":  _hours(unbilled),
        "unbilled_amount": unbilled_amount(client, ledger),
        "threshold":       get_threshold(client.get("assigned_attorney")),
        "statement_total": statement_total(ledger),
        "paid":            paid_total(client),
        "amount_due":      amount_due(client, ledger),
        "billed_hours":    billed_hours(ledger),
        "statements":      [json.loads(json.dumps(s)) for s in reversed(ledger["statements"])],
    }


def client_billing_view(client: dict, ledger: dict) -> dict:
    """Client-safe billing data: statements and the entries they cover only."""
    log = client.get("billing_log") or []
    covered = min(ledger["covered_through"], len(log))
    statements = ledger["statements"]

    def statement_for(index):
        for s in statements:
            if s["entries_from"] <= index < s["entries_to"]:
                return s
        return None

    def entry_view(i, e):
        s = statement_for(i)
        hours = float(e.get("hours", 0) or 0)
        return {"date": e.get("date", ""), "hours": e.get("hours", 0), "note": e.get("note", ""),
                "category": e.get("category", ""),
                "statement_number": s["number"] if s else None,
                "amount": round(hours * float(s["rate"]), 2) if s else None}

    entries = [entry_view(i, e) for i, e in enumerate(log[:covered])]
    latest = statements[-1] if statements else None
    return {
        "statements":      [{k: s[k] for k in _PUBLIC_STATEMENT_FIELDS} for s in reversed(statements)],
        "entries":         list(reversed(entries)),
        "payments":        [{"date": p.get("date", ""), "amount": p.get("amount", 0),
                             "method": p.get("method", "")}
                            for p in reversed(client.get("payments") or [])],
        "statement_total": statement_total(ledger),
        "paid":            paid_total(client),
        "amount_due":      amount_due(client, ledger),
        "billed_hours":    billed_hours(ledger),
        "has_new_statement": bool(latest) and latest["issued_at"] > (client.get("billing_seen_at") or ""),
        "latest_billed_through": latest["billed_through"] if latest else None,
        "hourly_rate":     shared.HOURLY_RATE,
    }


# ── Notices ──────────────────────────────────────────────────────────────────

def _claimable(statement: dict) -> bool:
    notice = statement.get("notice") or {}
    if notice.get("status") == "pending":
        return True
    if notice.get("status") == "sending" and notice.get("claimed_at"):
        try:
            claimed = datetime.strptime(notice["claimed_at"], _TS_FORMAT)
        except ValueError:
            return True
        return (datetime.now() - claimed).total_seconds() > NOTICE_STALE_SECONDS
    return False


def send_pending_notices(username: str) -> None:
    """Claim pending notices under the ledger lock, send outside it, finalise."""
    if not username or shared.safe_username(username) != username:
        return
    with _ledger_lock(username):
        ledger = _read_ledger(username)
        claimed = []
        for statement in ledger["statements"]:
            if _claimable(statement):
                statement["notice"].update(status="sending", claimed_at=_now())
                claimed.append(json.loads(json.dumps(statement)))
        if not claimed:
            return
        _write_ledger(username, ledger)
    if NOTICE_ASYNC:
        threading.Thread(target=_deliver, args=(username, claimed), daemon=True).start()
    else:
        _deliver(username, claimed)


def _deliver(username: str, claimed: list) -> None:
    try:
        from blueprints import email_service
        client = shared.load_client(username) or {}
        email = (client.get("email") or "").strip()
        name = client.get("client_name") or username
        results = {}
        claims = {s["id"]: s["notice"].get("claimed_at") for s in claimed}
        for statement in claimed:
            if "@" not in email:
                results[statement["id"]] = ("no_email", "")
                continue
            try:
                outcome = email_service.send_statement_email(
                    name, email, statement["number"], statement["amount"],
                    statement["billed_through"])
            except Exception:
                outcome = "failed"
            results[statement["id"]] = {
                "sent": ("sent", ""),
                "not_configured": ("failed", "email not configured"),
            }.get(outcome, ("failed", "send failed"))
        with _ledger_lock(username):
            ledger = _read_ledger(username)
            for statement in ledger["statements"]:
                notice = statement["notice"]
                # Only finalise our own claim: a stale re-claim has a newer claimed_at.
                if (statement["id"] in results and notice.get("status") == "sending"
                        and notice.get("claimed_at") == claims[statement["id"]]):
                    status, error = results[statement["id"]]
                    statement["notice"].update(status=status, at=_now(), error=error)
            _write_ledger(username, ledger)
    except Exception as exc:
        print(f"[billing] notice delivery failed for {username}: {exc!r}", file=sys.stderr)


def request_resend(username: str, statement_id: str) -> bool:
    if not username or shared.safe_username(username) != username:
        return False
    with _ledger_lock(username):
        ledger = _read_ledger(username)
        for statement in ledger["statements"]:
            if statement["id"] != statement_id:
                continue
            status = statement["notice"].get("status")
            if status in ("failed", "no_email") or (status == "sending" and _claimable(statement)):
                statement["notice"].update(status="pending", error="", claimed_at=None)
                _write_ledger(username, ledger)
                return True
            return False
    return False


# ── The save hook ────────────────────────────────────────────────────────────

def _check_fingerprint(username: str, client: dict, ledger: dict) -> None:
    covered, fp = ledger["covered_through"], ledger.get("covered_fingerprint")
    log = client.get("billing_log") or []
    if covered and len(log) < covered:
        print(f"[billing] WARNING: billing_log for {username} is shorter than the billed "
              "range — a stale save may have dropped entries", file=sys.stderr)
    elif covered and fp is not None and _fingerprint(log[covered - 1]) != fp:
        print(f"[billing] WARNING: billing_log fingerprint mismatch for {username} — "
              "a stale save may have altered billed entries", file=sys.stderr)


def after_client_save(username: str) -> None:
    """Called by shared.save_client after it releases the client lock.
    Cost per save: the migration-flag read, then one locked load_client +
    ledger read in issue_statement (which also checks the fingerprint), then
    one locked ledger read in send_pending_notices — fine at this app's scale."""
    try:
        if not is_migrated():
            return
        issue_statement(username, reason="threshold", issued_by="system",
                        notify=True, only_if_over_threshold=True)
        send_pending_notices(username)
    except Exception as exc:
        print(f"[billing] after_client_save failed for {username}: {exc!r}", file=sys.stderr)
