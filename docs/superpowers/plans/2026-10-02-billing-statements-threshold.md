# Billing Statements & Per-Attorney Threshold Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clients see billing only through statements. A statement is issued automatically when a client's unbilled time reaches the assigned attorney's threshold (default $2,000), or manually by an attorney. Issuing a statement emails the client.

**Spec:** `docs/superpowers/specs/2026-10-02-billing-statements-threshold-design.md`. Read it first: it explains the separate-ledger design and the lock-order invariant.

**Architecture:** A new `billing.py` owns a per-client encrypted **ledger** (`client-billing/<user>.json`) holding `covered_through` and the statements. `shared.save_client` calls `billing.after_client_save()` after it releases the client lock. That call issues a threshold statement from the freshly saved record and dispatches email notices (claim → send → finalise).

Client-facing routes compute everything from the ledger. Attorney routes add a summary, a manual issue button, resend and settings. A one-time migration issues silent opening statements, and startup is blocked until it has run.

**Tech stack:** Flask, Fernet (via `shared._read_record` / `_write_record`), pytest.

**Run tests with:** `python -m pytest tests -q`. The baseline is **289 passed**.

**Branch:** `feat/security-hardening` was merged. Work on `feat/billing-statements`, which already holds the spec commits.

**Safety rules for every task:**
- Never touch the real `client-accounts/`, `client-billing/`, `client-files/`, `leads/`, `firm-settings/` or `.env`.
- Never start the app server.
- Never run `git checkout` of an old commit: it deletes `.env`.
- Never run `git add -A`.
- Preserve each file's line endings: CRLF in `shared.py`, `portal_attorney.py`, `attorney_portal.html`, `client_portal.html` and `base.html`; LF elsewhere. Use a `newline=""` Python helper when editing CRLF files.
- New front-end code builds the DOM with `textContent` or `_el`. No `innerHTML` and no HTML strings built from data.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `billing.py` | create | Ledger I/O, thresholds, issuing, views, notices, resend, baseline, migration flag |
| `shared.py` | modify | `CLIENT_BILLING_DIR`, `FIRM_SETTINGS_DIR`, `billing_seen_at` default, `save_client` hook, `update_client_field_atomic`, lock-order comment |
| `blueprints/email_service.py` | modify | `send_statement_email` |
| `blueprints/portal_client.py` | modify | `_balance_for`, `/portal/client/billing`, overview vars |
| `blueprints/research.py` | modify | client research-save returns billed hours |
| `blueprints/drafting.py` | modify | claim-document returns billed hours |
| `blueprints/portal_attorney.py` | modify | `billing_summary` on client GET; issue-statement, statement-notice and billing-settings routes |
| `templates/client_portal.html` | modify | Billing tab, overview card, New badge |
| `templates/attorney_portal.html` | modify | Billing status card, settings card, script include |
| `static/js/attorney_billing.js` | create | Attorney billing UI |
| `scripts/issue_opening_statements.py` | create | Migration |
| `app.py` | modify | Blocking startup check and fresh-install auto-mark |
| `.gitignore` | modify | `client-billing/`, `firm-settings/` |
| `tests/conftest.py` | modify | New dirs, mark migrated, synchronous notices, email stub, `issue_test_statement` fixture |
| `tests/test_payments.py` | modify | Balances come from issued statements |
| new tests | create | `test_billing_ledger.py`, `test_billing_settings.py`, `test_billing_hook.py`, `test_billing_notices.py`, `test_client_billing_view.py`, `test_attorney_billing_routes.py`, `test_opening_statements.py` |

---

## Chunk 1: Ledger foundations

### Task 1: Shared plumbing and the test harness

**Files:** `shared.py`, `.gitignore`, `tests/conftest.py`

- [ ] **Step 1: Directories in `shared.py`.** In the data-directories block, add these two lines after `SECURITY_STATE_DIR`:

```python
CLIENT_BILLING_DIR   = BASE_DIR / "client-billing"
FIRM_SETTINGS_DIR    = BASE_DIR / "firm-settings"
```

Add both to the `for _d in (...)` mkdir tuple. Append `client-billing/` and `firm-settings/` to `.gitignore` under the client-data block.

- [ ] **Step 2: `load_client` default.** After the `for field in _CLIENT_LIST_DEFAULTS:` loop, add `data.setdefault("billing_seen_at", "")`.

- [ ] **Step 3: Lock-order comment.** Put this directly above `def _get_client_lock`:

```python
# LOCK-ORDER INVARIANT: never take a billing ledger lock, call any billing.*
# function, or call save_client() while holding a client lock. billing.py may
# take a client lock (via load_client) while holding a ledger lock — never the
# reverse — so the two can't deadlock.
```

- [ ] **Step 4: `update_client_field_atomic`.** Add it right after `log_access_atomic`:

```python
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
```

- [ ] **Step 5: conftest.** In `patch_dirs`, add `billing_dir = tmp_path / "billing"` and `settings_dir = tmp_path / "settings"` to the directories it creates. Then:

```python
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
```

Change `patch_dirs`'s signature to `def patch_dirs(tmp_path, monkeypatch, sent_statement_emails):`, and define the list as its own fixture **above** `patch_dirs`. Pytest caches fixture values per test, so the test and the stub share one list:

```python
@pytest.fixture
def sent_statement_emails():
    return []
```

`billing` doesn't exist until Task 2. Wrap the `import billing` line and its `monkeypatch.setattr` in `try: ... except ImportError: pass` for now, and remove the `try` in Task 2 Step 3.

Also add, near the top of conftest right after `import shared`, the capture of the real sender for Task 3's test (it is `None` until Task 3 adds the function):

```python
import blueprints.email_service as _email_real  # noqa: E402
REAL_SEND_STATEMENT_EMAIL = getattr(_email_real, "send_statement_email", None)
```

Since this runs at conftest import, *before* Task 3 adds the function, it will be `None` during Tasks 1–2 and the real function from Task 3 on — conftest is re-imported on every pytest run.

- [ ] **Step 6:** Run `python -m pytest tests -q`. Expect **289 passed**.

- [ ] **Step 7: Commit** with the message `chore(billing): ledger/settings dirs, atomic field update, test harness`.

### Task 2: `billing.py` — settings and the ledger

**Files:** create `billing.py`, `tests/test_billing_settings.py`, `tests/test_billing_ledger.py` (first part).

- [ ] **Step 1: Failing tests.** Create `tests/test_billing_settings.py`:

```python
"""Per-attorney statement thresholds (spec A4)."""

import pytest

import billing
import shared


def test_default_threshold():
    assert billing.get_threshold("Endocide") == 2000.0
    assert billing.get_threshold(None) == 2000.0


def test_set_and_get_per_attorney():
    assert billing.set_threshold("SophiaH", "1500") == 1500.0
    assert billing.get_threshold("SophiaH") == 1500.0
    assert billing.get_threshold("Endocide") == 2000.0


@pytest.mark.parametrize("bad", [99, 100001, "abc", None, float("nan"), float("inf")])
def test_set_threshold_rejects(bad):
    with pytest.raises(ValueError):
        billing.set_threshold("Endocide", bad)


def test_corrupt_settings_file_falls_back(capsys):
    (shared.FIRM_SETTINGS_DIR / "attorney-settings.json").write_text("{nope")
    assert billing.get_threshold("Endocide") == 2000.0
    assert "unreadable" in capsys.readouterr().err


def test_out_of_range_stored_value_falls_back():
    (shared.FIRM_SETTINGS_DIR / "attorney-settings.json").write_text(
        '{"Endocide": {"statement_threshold": 5}}')
    assert billing.get_threshold("Endocide") == 2000.0


def test_migration_flag(tmp_path):
    assert billing.is_migrated()            # conftest marks it
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    assert not billing.is_migrated()
    billing.mark_migrated()
    assert billing.is_migrated()
```

Create `tests/test_billing_ledger.py`:

```python
"""Statement issuing and the ledger (spec A1–A2, B1, B4)."""

import billing
import shared


def _entry(hours, date="2026-10-01", note="work"):
    return {"date": date, "hours": hours, "note": note, "category": "Other"}


def _client(make_client, username="bc", hours=(), **extra):
    log = [_entry(h) for h in hours]
    return make_client(username, billing_log=log,
                       hours_billed=round(sum(hours), 2), **extra)


def test_empty_ledger_for_new_client(make_client):
    _client(make_client)
    led = billing.load_ledger("bc")
    assert led == {"covered_through": 0, "covered_fingerprint": None, "statements": []}


def test_manual_issue_covers_all_unbilled(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _client(make_client, hours=(1.0, 0.0, 2.5))
    st = billing.issue_statement("bc", reason="manual", issued_by="Endocide", notify=False)
    assert (st["number"], st["id"], st["hours"], st["rate"], st["amount"]) == (1, "st_1", 3.5, 350.0, 1225.0)
    assert (st["entries_from"], st["entries_to"]) == (0, 3)
    assert st["notice"]["status"] == "skipped"
    led = billing.load_ledger("bc")
    assert led["covered_through"] == 3 and led["covered_fingerprint"][1] == 2.5


def test_no_statement_when_nothing_or_nonpositive(make_client):
    _client(make_client, hours=(0.0,))
    assert billing.issue_statement("bc", reason="manual", issued_by="x", notify=False) is None
    _client(make_client, "bc2", hours=(1.0, -1.0))
    assert billing.issue_statement("bc2", reason="manual", issued_by="x", notify=False) is None
    assert billing.load_ledger("bc2")["covered_through"] == 0


def test_threshold_only_issue(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 100.0)
    _client(make_client, hours=(19.99,))                       # $1,999
    assert billing.issue_statement("bc", reason="threshold", issued_by="system",
                                   notify=True, only_if_over_threshold=True) is None
    _client(make_client, "bc2", hours=(20.0,))                 # exactly $2,000
    st = billing.issue_statement("bc2", reason="threshold", issued_by="system",
                                 notify=True, only_if_over_threshold=True)
    assert st and st["notice"]["status"] == "pending"


def test_uses_assigned_attorneys_threshold(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 100.0)
    billing.set_threshold("SophiaH", 500)
    _client(make_client, hours=(6.0,), assigned_attorney="SophiaH")
    assert billing.issue_statement("bc", reason="threshold", issued_by="system",
                                   notify=False, only_if_over_threshold=True)


def test_numbering_and_second_statement(make_client):
    rec = _client(make_client, hours=(1.0,))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c = shared.load_client("bc")
    c["billing_log"].append(_entry(2.0, "2026-10-05"))
    shared._write_record(shared.CLIENT_ACCOUNTS_DIR / "bc.json", c)   # avoid the save hook
    st2 = billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    assert (st2["number"], st2["entries_from"], st2["entries_to"], st2["billed_through"]) == (2, 1, 2, "2026-10-05")


def test_amount_due_never_negative(make_client):
    _client(make_client, hours=(1.0,), payments=[{"amount": 99999.0}])
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c, led = shared.load_client("bc"), billing.load_ledger("bc")
    assert billing.amount_due(c, led) == 0.0


def test_shortened_billing_log_does_not_crash(make_client):
    _client(make_client, hours=(1.0, 1.0))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c = shared.load_client("bc"); c["billing_log"] = c["billing_log"][:1]
    shared._write_record(shared.CLIENT_ACCOUNTS_DIR / "bc.json", c)
    led = billing.load_ledger("bc")
    assert billing.unbilled_entries(c, led) == []
    assert billing.issue_statement("bc", reason="manual", issued_by="x", notify=False) is None


def test_stale_client_save_cannot_remove_statement(make_client):
    _client(make_client, hours=(1.0,))
    stale = shared.load_client("bc")
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    shared.save_client(stale)
    assert len(billing.load_ledger("bc")["statements"]) == 1


def test_ledger_is_encrypted(make_client):
    _client(make_client, hours=(1.0,))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    raw = (shared.CLIENT_BILLING_DIR / "bc.json").read_bytes()
    assert not shared._is_plaintext(raw)


def test_set_baseline(make_client):
    _client(make_client, hours=(0.0, 0.0))
    assert billing.set_baseline("bc") is True
    assert billing.load_ledger("bc")["covered_through"] == 2
    assert billing.set_baseline("bc") is False
```

- [ ] **Step 2: Run them and confirm they fail.** Expect `ModuleNotFoundError: billing`.

- [ ] **Step 3: Create `billing.py`.** It contains the first part below. Task 3 appends the hook, notices and views. Also remove Task 1's `try/except ImportError` around `import billing` in conftest.

```python
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
        log = client.get("billing_log") or []
        start = min(ledger["covered_through"], len(log))
        entries = log[start:]
        hours = _hours(entries)
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
```

- [ ] **Step 4:** Run `python -m pytest tests/test_billing_settings.py tests/test_billing_ledger.py -q` and confirm everything passes. Expect `test_stale_client_save_cannot_remove_statement` to pass already: the hook doesn't exist yet, and saving the client record never touches the ledger.

- [ ] **Step 5:** Run the full suite and expect all tests to pass. **Commit** with `feat(billing): ledger, thresholds, statement issuing`.

### Task 3: Views, hook, notices, email

**Files:** `billing.py` (append), `shared.py` (`save_client`), `blueprints/email_service.py`, and three new test files: `tests/test_billing_hook.py`, `tests/test_billing_notices.py`, and `tests/test_billing_ledger.py` for the view tests.

- [ ] **Step 1: Failing tests.**

Append to `tests/test_billing_ledger.py`:

```python
def test_client_view_hides_unbilled(make_client):
    _client(make_client, hours=(1.0, 2.0))
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c = shared.load_client("bc"); c["billing_log"].append(_entry(5.0, note="SECRET unbilled"))
    shared._write_record(shared.CLIENT_ACCOUNTS_DIR / "bc.json", c)
    view = billing.client_billing_view(shared.load_client("bc"), billing.load_ledger("bc"))
    blob = repr(view)
    assert "SECRET" not in blob and "threshold" not in blob and "notice" not in blob
    assert [e["statement_number"] for e in view["entries"]] == [1, 1]
    assert view["billed_hours"] == 3.0 and view["latest_billed_through"] == "2026-10-01"


def test_has_new_statement(make_client):
    _client(make_client, hours=(1.0,), billing_seen_at="")
    billing.issue_statement("bc", reason="manual", issued_by="x", notify=False)
    c, led = shared.load_client("bc"), billing.load_ledger("bc")
    assert billing.client_billing_view(c, led)["has_new_statement"] is True
    c["billing_seen_at"] = "9999-12-31T00:00:00"
    assert billing.client_billing_view(c, led)["has_new_statement"] is False


def test_billing_summary_fields(make_client, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 100.0)
    _client(make_client, hours=(3.0,))
    s = billing.billing_summary(shared.load_client("bc"), billing.load_ledger("bc"))
    assert (s["unbilled_hours"], s["unbilled_amount"], s["threshold"], s["amount_due"]) == (3.0, 300.0, 2000.0, 0.0)
```

`tests/test_billing_hook.py`:

```python
"""after_client_save issues threshold statements on every save path (spec B2)."""

import billing
import shared


def _over(make_client, username="hk", **kw):
    # 6 hrs * $350 = $2,100 >= $2,000
    return make_client(username, billing_log=[{"date": "2026-10-01", "hours": 6.0, "note": "x"}],
                       hours_billed=6.0, **kw)


def test_save_issues_statement_when_over(make_client, sent_statement_emails, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    shared.save_client(_over(make_client, email="hk@example.com"))
    led = billing.load_ledger("hk")
    assert len(led["statements"]) == 1 and led["statements"][0]["reason"] == "threshold"
    assert led["statements"][0]["notice"]["status"] == "sent"
    assert len(sent_statement_emails) == 1


def test_save_without_email_marks_no_email(make_client, sent_statement_emails, monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    shared.save_client(_over(make_client))
    assert billing.load_ledger("hk")["statements"][0]["notice"]["status"] == "no_email"
    assert sent_statement_emails == []


def test_no_statement_under_threshold(make_client):
    rec = make_client("hk", billing_log=[{"date": "d", "hours": 1.0, "note": "x"}], hours_billed=1.0)
    shared.save_client(rec)
    assert billing.load_ledger("hk")["statements"] == []


def test_inert_until_migrated(make_client):
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    shared.save_client(_over(make_client))
    assert billing.load_ledger("hk")["statements"] == []


def test_hook_errors_never_fail_save(make_client, monkeypatch, capsys):
    monkeypatch.setattr(billing, "issue_statement",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    shared.save_client(_over(make_client))          # must not raise
    assert "boom" in capsys.readouterr().err


def test_attorney_billing_entry_path(attorney_session, make_client):
    make_client("hk")
    r = attorney_session.post("/portal/attorney/billing-entry",
                              json={"username": "hk", "note": "trial prep", "hours": 6})
    assert r.status_code == 200
    assert len(billing.load_ledger("hk")["statements"]) == 1


def test_create_client_path_builds_log_inline(attorney_session):
    # create-client builds billing_log inline (no recalc_hours); still hooked via save_client.
    r = attorney_session.post("/portal/attorney/create-client",
                              json={"username": "newc", "client_name": "New C"})
    assert r.status_code == 200 and shared.load_client("newc") is not None
    assert billing.load_ledger("newc")["statements"] == []   # 0.2 hrs: under threshold, no crash


def test_fingerprint_mismatch_warns(make_client, capsys):
    rec = make_client("hk", billing_log=[{"date": "d", "hours": 1.0, "note": "a"}], hours_billed=1.0)
    billing.issue_statement("hk", reason="manual", issued_by="x", notify=False)
    rec["billing_log"] = [{"date": "d", "hours": 9.0, "note": "different"}]
    shared.save_client(rec)
    assert "fingerprint" in capsys.readouterr().err
```

`tests/test_billing_notices.py`:

```python
"""Statement notices: claim → send → finalise (spec B3, C4)."""

import threading

import billing
import blueprints.email_service as email_service
import shared


def _issue(make_client, email="c@example.com", username="nt"):
    make_client(username, email=email, client_name="Nora T",
                billing_log=[{"date": "2026-10-01", "hours": 1.0, "note": "x"}], hours_billed=1.0)
    return billing.issue_statement(username, reason="manual", issued_by="Endocide", notify=True)


def _status(username="nt"):
    return billing.load_ledger(username)["statements"][-1]["notice"]


def test_sent(make_client, sent_statement_emails):
    st = _issue(make_client)
    billing.send_pending_notices("nt")
    assert _status()["status"] == "sent"
    (args, _), = sent_statement_emails
    assert args == ("Nora T", "c@example.com", st["number"], st["amount"], st["billed_through"])


def test_not_configured_and_failed(make_client, monkeypatch):
    _issue(make_client)
    monkeypatch.setattr(email_service, "send_statement_email", lambda *a: "not_configured")
    billing.send_pending_notices("nt")
    assert (_status()["status"], _status()["error"]) == ("failed", "email not configured")
    assert billing.request_resend("nt", "st_1")
    monkeypatch.setattr(email_service, "send_statement_email", lambda *a: "failed")
    billing.send_pending_notices("nt")
    assert (_status()["status"], _status()["error"]) == ("failed", "send failed")


def test_sender_exception_is_failed(make_client, monkeypatch):
    _issue(make_client)
    monkeypatch.setattr(email_service, "send_statement_email",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("smtp down")))
    billing.send_pending_notices("nt")
    assert _status()["status"] == "failed"


def test_no_or_invalid_email(make_client, sent_statement_emails):
    _issue(make_client, email="not-an-email")
    billing.send_pending_notices("nt")
    assert _status()["status"] == "no_email" and sent_statement_emails == []


def test_concurrent_dispatch_sends_once(make_client, monkeypatch):
    _issue(make_client)
    calls = []
    gate = threading.Event()
    def slow(*a):
        calls.append(a); gate.wait(1); return "sent"
    monkeypatch.setattr(email_service, "send_statement_email", slow)
    ts = [threading.Thread(target=billing.send_pending_notices, args=("nt",)) for _ in range(4)]
    [t.start() for t in ts]; gate.set(); [t.join() for t in ts]
    assert len(calls) == 1 and _status()["status"] == "sent"


def test_stale_client_save_does_not_resend(make_client, sent_statement_emails):
    _issue(make_client)
    stale = shared.load_client("nt")
    billing.send_pending_notices("nt")
    shared.save_client(stale)            # triggers after_client_save
    assert len(sent_statement_emails) == 1


def test_stale_sending_is_reclaimed(make_client, monkeypatch, sent_statement_emails):
    _issue(make_client)
    led = billing.load_ledger("nt")
    led["statements"][0]["notice"].update(status="sending", claimed_at="2000-01-01T00:00:00")
    billing._write_ledger("nt", led)
    billing.send_pending_notices("nt")
    assert _status()["status"] == "sent"


def test_resend_refused_when_sent_or_fresh_sending(make_client):
    _issue(make_client)
    billing.send_pending_notices("nt")
    assert billing.request_resend("nt", "st_1") is False
    assert billing.request_resend("nt", "st_999") is False


def test_send_statement_email_not_configured(monkeypatch):
    from conftest import REAL_SEND_STATEMENT_EMAIL
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    assert REAL_SEND_STATEMENT_EMAIL("A", "a@b.co", 1, 10.0, "2026-10-01") == "not_configured"
```

This test calls the real sender, captured in conftest before the autouse stub (Task 1 Step 5).

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Append the rest of `billing.py`:**

```python
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

    def number_for(index):
        for s in statements:
            if s["entries_from"] <= index < s["entries_to"]:
                return s["number"]
        return None

    entries = [{"date": e.get("date", ""), "hours": e.get("hours", 0), "note": e.get("note", ""),
                "category": e.get("category", ""), "statement_number": number_for(i)}
               for i, e in enumerate(log[:covered])]
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
                if statement["id"] in results and statement["notice"].get("status") == "sending":
                    status, error = results[statement["id"]]
                    statement["notice"].update(status=status, at=_now(), error=error)
            _write_ledger(username, ledger)
    except Exception as exc:
        print(f"[billing] notice delivery failed for {username}: {exc!r}", file=sys.stderr)


def request_resend(username: str, statement_id: str) -> bool:
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
    Cost per save: one extra load_client, two small ledger reads and the
    migration-flag read — fine at this app's scale."""
    try:
        if not is_migrated():
            return
        client = shared.load_client(username)
        if not client:
            return
        _check_fingerprint(username, client, _read_ledger(username))
        issue_statement(username, reason="threshold", issued_by="system",
                        notify=True, only_if_over_threshold=True)
        if any(_claimable(s) for s in load_ledger(username)["statements"]):
            send_pending_notices(username)
    except Exception as exc:
        print(f"[billing] after_client_save failed for {username}: {exc!r}", file=sys.stderr)
```

- [ ] **Step 4: Hook in `shared.save_client`.** After the `with _get_client_lock(username):` block, at the function's top indentation level, add:

```python
    # Outside the client lock — see the LOCK-ORDER INVARIANT above _get_client_lock.
    import billing
    billing.after_client_save(username)
```

- [ ] **Step 5: `send_statement_email`.** Add to `blueprints/email_service.py` after `send_intake_email`, following its style:

```python
def send_statement_email(name: str, email: str, statement_number: int,
                         amount: float, billed_through: str) -> str:
    """Notify a client that a billing statement was issued.
    Returns "not_configured", "sent", or "failed". No itemisation is included."""
    if not _api_key():
        return "not_configured"
    portal = _firm_website().rstrip("/") + "/client-login"
    subject = f"Statement #{statement_number} from {_from_name()}"
    text = (f"Hello {name},\n\nStatement #{statement_number} for services through "
            f"{billed_through} has been issued. Amount due: ${amount:,.2f}.\n\n"
            f"View it and pay securely in your client portal: {portal}\n\n"
            f"Questions? Call {_firm_phone()}.\n")
    html_body = _html_wrapper(
        f"<p>Hello {escape(name)},</p>"
        f"<p>Statement <strong>#{statement_number}</strong> for services through "
        f"<strong>{escape(billed_through)}</strong> has been issued.</p>"
        f"<p style='font-size:1.15em'><strong>Amount due: ${amount:,.2f}</strong></p>"
        f"<p><a href='{escape(portal)}'>View and pay in your client portal</a></p>"
        f"<p>Questions? Call {escape(_firm_phone())}.</p>")
    return "sent" if _send(email, name, subject, html_body, text) else "failed"
```

Add `from html import escape` to `email_service.py`'s imports (it has none today) and keep the `escape()` calls exactly as written — do **not** copy `send_intake_email`'s unescaped style.

- [ ] **Step 6:** Run the full suite. Everything should pass. `test_payments.py` is unaffected until Task 4 changes `_balance_for`, and its clients have empty `billing_log`s, so the hook issues nothing. If anything fails, report it. Don't fix failures by weakening assertions.

- [ ] **Step 7: Commit** with `feat(billing): views, save hook, statement notices, statement email`.

---

## Chunk 2: Client side

### Task 4: Amount due from statements; client billing route; payment tests

**Files:** `blueprints/portal_client.py`, `tests/conftest.py`, `tests/test_payments.py`, and a new `tests/test_client_billing_view.py`.

- [ ] **Step 1: Fixture.** Add to conftest:

```python
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
```

- [ ] **Step 2: Update `tests/test_payments.py`.** Wherever a test does `make_client(hours_billed=X, ...)` and expects a balance, change it to `make_client(...)` without `hours_billed`, followed by `issue_test_statement("testclient", X)`. Payments given via `payments=[...]` stay as they are. Rewrite the billing-summary test (`test_billing_summary_returns_balance`) for the new response shape:

```python
def test_billing_summary_returns_balance(client_session, make_client, issue_test_statement):
    make_client(payments=[{"amount": 350.0, "date": "2026-10-02", "method": "card"}])
    issue_test_statement("testclient", 3.0)
    data = client_session.get("/portal/client/billing").get_json()
    assert data["billed_hours"] == 3.0
    assert data["amount_due"] == pytest.approx(700.0)      # $1,050 billed − $350 paid
    assert "hours_billed" not in data and "billing_log" not in data
```

The zero-balance test (`hours_billed=2.0, hours_paid=2.0`) becomes `make_client(payments=[{"amount": 700.0}])` followed by `issue_test_statement("testclient", 2.0)`; the fixture keeps existing payments. Keep the other test logic unchanged. Webhook tests only need a positive balance to exist if their handler checks one; read each test.

- [ ] **Step 3: Write the failing tests** in `tests/test_client_billing_view.py`:

```python
"""Client-facing billing never shows unbilled time (spec C1, C2)."""

import pytest

import billing
import shared


@pytest.fixture(autouse=True)
def _rate(monkeypatch):
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)


def test_billing_route_view_and_seen(client_session, make_client, issue_test_statement):
    make_client(email="t@example.com")
    issue_test_statement("testclient", 1.0)
    c = shared.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 4.0, "note": "UNBILLED-SECRET"})
    shared._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    r = client_session.get("/portal/client/billing")
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "UNBILLED-SECRET" not in body and "threshold" not in body and "notice" not in body
    d = r.get_json()
    assert d["has_new_statement"] is True and d["billed_hours"] == 1.0
    assert shared.load_client("testclient")["billing_seen_at"] != ""
    assert client_session.get("/portal/client/billing").get_json()["has_new_statement"] is False


def test_stripe_charges_statement_amount_only(client_session, make_client, issue_test_statement, monkeypatch):
    import stripe
    captured = {}
    monkeypatch.setattr(shared, "STRIPE_SECRET_KEY", "sk_test_x")
    class _Session:
        @staticmethod
        def create(**kw):
            captured.update(kw)
            return type("S", (), {"url": "https://stripe.example/x", "id": "cs_1"})()
    monkeypatch.setattr(stripe, "checkout", type("C", (), {"Session": _Session}), raising=False)
    make_client()
    issue_test_statement("testclient", 2.0)                      # $700
    c = shared.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 3.0, "note": "unbilled"})
    shared._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    client_session.post("/portal/client/payment/stripe")
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 70000


def test_overview_shows_billed_hours(client_session, make_client, issue_test_statement):
    make_client()
    issue_test_statement("testclient", 1.5)
    c = shared.load_client("testclient")
    c["billing_log"].append({"date": "2026-10-03", "hours": 4.0, "note": "unbilled"})
    c["hours_billed"] = 5.5                                       # live total must not show
    shared._write_record(shared.CLIENT_ACCOUNTS_DIR / "testclient.json", c)
    html = client_session.get("/client-portal").get_data(as_text=True)
    assert "5.5" not in html and "1.5" in html


def test_client_research_save_returns_billed_hours(client_session, make_client):
    make_client()
    d = client_session.post("/portal/client/research-save",
                            json={"memo": "<p>memo</p>", "question": "Is X legal?"}).get_json()
    assert d["success"] and "total_hours" not in d
    assert d["billed_hours"] == 0.0            # the 0.2 hrs just logged stays unbilled


def test_coinbase_charges_statement_amount_only(client_session, make_client, issue_test_statement, monkeypatch):
    # Mirror tests/test_payments.py::test_coinbase_charge_returns_url's stubbing of the
    # Coinbase HTTP call, capture the JSON body, and assert local_price.amount == "700.00"
    # with 3.0 hrs of unbilled time also present.
    ...


def test_claim_document_returns_billed_hours(client):
    d = client.post("/drafting/claim-document", json={
        "full_name": "Cal Claimant", "password": "long-enough-1",
        "draft_content": "<p>x</p>"}).get_json()
    assert d["billed_hours"] == 0 and "hours_billed" not in d
```

Write `test_coinbase_charges_statement_amount_only` by copying the stub from `test_payments.py::test_coinbase_charge_returns_url` (read it); the body shown above is a description, not code to paste. The Stripe stubbing above must match how `client_payment_stripe` actually calls Stripe. Read the route, and copy the stubbing style already used in `tests/test_payments.py::test_stripe_checkout_returns_url`. The research-save route takes `{memo, question}` (see `blueprints/research.py`).

- [ ] **Step 4: Implement.**
  - `portal_client.py`: `import billing`.
    - `_balance_for(client)`: `due = billing.amount_due(client, billing.load_ledger(client["username"]))`, then return `(round(due / shared.HOURLY_RATE, 2) if shared.HOURLY_RATE else 0, due)`.
    - `client_billing()`: return `{**billing.client_billing_view(client, billing.load_ledger(username)), "card_enabled": ..., "crypto_enabled": ...}`. Then call `shared.update_client_field_atomic(username, "billing_seen_at", billing._now())`. The response must be computed **before** updating `billing_seen_at`.
    - `client_portal()`: compute `ledger = billing.load_ledger(username)` and pass `billed_hours=billing.billed_hours(ledger)` and `has_new_statement=billing.client_billing_view(client, ledger)["has_new_statement"]` to `render_template`.
  - `research.py` client route: replace `total_hours = recalc_hours(client_rec)` with `recalc_hours(client_rec)`. After the save, respond with `"billed_hours": billing.billed_hours(billing.load_ledger(username))` in place of `total_hours`.
  - `drafting.py` claim route: replace `"hours_billed": record["hours_billed"]` with `"billed_hours": billing.billed_hours(billing.load_ledger(username))`.
  - Front end: `templates/drafting.html` and `templates/client_portal.html` don't read `hours_billed` from the claim response or `total_hours` from research-save (verified by grep). Only `renderBilling` reads `d.hours_billed`, and Task 5 rewrites it.

- [ ] **Step 5:** Run the full suite. Expect everything green. **Commit** with `feat(billing): client sees statement-billed amounts only; payments charge statements`.

### Task 5: Client portal template

**Files:** `templates/client_portal.html` only. It is **CRLF**.

- [ ] **Step 1: Overview card (~line 44).** Change `{{ client.hours_billed or 0 }}` to `{{ billed_hours or 0 }}`.
- [ ] **Step 2: Billing tab button (~line 18).** Right after the label text, add `{% if has_new_statement %} <span class="new-badge">New</span>{% endif %}`. Add a `.new-badge` style beside the existing portal styles, in a block that already holds styles. Base it on the attorney portal's `.conflict-badge` look.
- [ ] **Step 3: Billing tab markup.**
  - Remove the "Hours Paid" stat card.
  - Relabel "Hours Billed" to "Billed Hours".
  - Add a **Statements** card before the time-log card: `<div class="card" id="billing-statements-card">`, holding a table with `<tbody id="billing-statements-body">` (columns #, Issued, Billed Through, Hours, Amount) and a `<p id="billing-statements-empty">No statements yet.</p>`.
  - Add a `<p id="billing-next-note" class="...">` under the time-log card.
  - In the time-log table, add a "Statement" column header.
  - In the payment-history table, remove the "Hours" column header.
- [ ] **Step 4: JS (`renderBilling`, `renderBillingLog`, payment history).** Rewrite these to the new response fields:
  - `billed_hours` and `amount_due` replace `hours_billed`, `hours_paid` and `balance_due`.
  - Fill the statements table from `d.statements`.
  - Fill the entries from `d.entries`, using `statement_number`, or "—" when it's null.
  - `billing-next-note`: when `d.latest_billed_through`, set it to `"Time logged after " + d.latest_billed_through + " will appear on your next statement."`; otherwise leave it empty.
  - Drop the `hours_credited` cell.
  - Keep the Pay Now logic, keyed on `d.amount_due > 0`.
  - Keep the `textContent`-only DOM style already used in this file. Read `renderBillingLog` first and adapt it rather than rewriting from scratch.
- [ ] **Step 5:** Run the full suite, which must stay green. Do a manual browser check later in the sandbox (the controller does this). **Commit** with `feat(billing): client portal shows statements, billed hours, new-statement badge`.

---

## Chunk 3: Attorney side

### Task 6: Attorney routes

**Files:** `blueprints/portal_attorney.py`, and a new `tests/test_attorney_billing_routes.py`.

- [ ] **Step 1: Write the failing tests.**

```python
"""Attorney billing routes (spec C3)."""

import billing
import shared


def _client(make_client, hours=1.0, **kw):
    return make_client("ab", billing_log=[{"date": "2026-10-01", "hours": hours, "note": "x"}],
                       hours_billed=hours, email="ab@example.com", **kw)


def test_client_get_includes_billing_summary(attorney_session, make_client):
    _client(make_client)
    s = attorney_session.get("/portal/attorney/client/ab").get_json()["billing_summary"]
    assert s["unbilled_hours"] == 1.0 and s["threshold"] == 2000.0


def test_issue_statement(attorney_session, make_client, sent_statement_emails):
    _client(make_client)
    r = attorney_session.post("/portal/attorney/issue-statement", json={"username": "ab"})
    d = r.get_json()
    assert r.status_code == 200 and d["statement"]["reason"] == "manual"
    assert d["billing_summary"]["unbilled_hours"] == 0.0
    assert len(sent_statement_emails) == 1
    assert shared.load_client("ab")["access_log"][-1]["action"] == "statement_issued"
    r2 = attorney_session.post("/portal/attorney/issue-statement", json={"username": "ab"})
    assert r2.status_code == 400 and r2.get_json()["error"] == "No unbilled time to bill."


def test_issue_statement_access(other_attorney_session, make_client):
    _client(make_client)
    assert other_attorney_session.post("/portal/attorney/issue-statement",
                                       json={"username": "ab"}).status_code == 404
    _client(make_client, co_counsel=["SophiaH"])
    assert other_attorney_session.post("/portal/attorney/issue-statement",
                                       json={"username": "ab"}).status_code == 200


def test_statement_notice_resend(attorney_session, make_client, monkeypatch):
    import blueprints.email_service as es
    _client(make_client)
    monkeypatch.setattr(es, "send_statement_email", lambda *a: "failed")
    attorney_session.post("/portal/attorney/issue-statement", json={"username": "ab"})
    monkeypatch.setattr(es, "send_statement_email", lambda *a: "sent")
    r = attorney_session.post("/portal/attorney/statement-notice",
                              json={"username": "ab", "statement_id": "st_1"})
    assert r.status_code == 200
    assert billing.load_ledger("ab")["statements"][0]["notice"]["status"] == "sent"
    r = attorney_session.post("/portal/attorney/statement-notice",
                              json={"username": "ab", "statement_id": "st_1"})
    assert r.status_code == 400


def test_billing_settings(attorney_session):
    assert attorney_session.get("/portal/attorney/billing-settings").get_json() == {
        "threshold": 2000.0, "default": 2000.0}
    r = attorney_session.post("/portal/attorney/billing-settings", json={"threshold": 50})
    assert r.status_code == 400
    assert attorney_session.post("/portal/attorney/billing-settings",
                                 json={"threshold": 1200}).get_json()["threshold"] == 1200.0
    assert billing.get_threshold("Endocide") == 1200.0 and billing.get_threshold("SophiaH") == 2000.0
```

- [ ] **Step 2: Implement.** In `portal_attorney.py`, add `import billing`.
  - `portal_client_get`: before the return, add `view["billing_summary"] = billing.billing_summary(client, billing.load_ledger(client["username"]))`.
  - New routes, placed after the conflict routes:

```python
@portal_attorney_bp.route("/portal/attorney/issue-statement", methods=["POST"])
@require_attorney
def portal_issue_statement():
    data   = request.get_json() or {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username  = client["username"]
    statement = billing.issue_statement(username, reason="manual",
                                        issued_by=session["username"], notify=True)
    if not statement:
        return jsonify({"error": "No unbilled time to bill."}), 400
    log_access_atomic(username, "statement_issued",
                      f"{statement['id']} ${statement['amount']:,.2f}")
    billing.send_pending_notices(username)
    fresh = load_client(username)
    return jsonify({"success": True, "statement": statement,
                    "billing_summary": billing.billing_summary(fresh, billing.load_ledger(username))})


@portal_attorney_bp.route("/portal/attorney/statement-notice", methods=["POST"])
@require_attorney
def portal_statement_notice():
    data   = request.get_json() or {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username = client["username"]
    if not billing.request_resend(username, str(data.get("statement_id") or "")):
        return jsonify({"error": "Notice can't be resent in its current state."}), 400
    billing.send_pending_notices(username)
    return jsonify({"success": True,
                    "billing_summary": billing.billing_summary(load_client(username),
                                                               billing.load_ledger(username))})


@portal_attorney_bp.route("/portal/attorney/billing-settings", methods=["GET", "POST"])
@require_attorney
def portal_billing_settings():
    atty = session["username"]
    if request.method == "POST":
        try:
            value = billing.set_threshold(atty, (request.get_json() or {}).get("threshold"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "threshold": value})
    return jsonify({"threshold": billing.get_threshold(atty),
                    "default": billing.DEFAULT_STATEMENT_THRESHOLD})
```

Add `log_access_atomic` to the `shared` import if it isn't already imported there. The access sweep test in `tests/test_client_access.py` must still pass: the two client routes call `load_client_for_attorney`, and `billing-settings` reads no client username.

- [ ] **Step 3:** Run the full suite and expect it to be green. **Commit** with `feat(billing): attorney issue-statement, resend notice, billing settings routes`.

### Task 7: Attorney UI

**Files:** a new `static/js/attorney_billing.js`, and `templates/attorney_portal.html` (**CRLF**).

- [ ] **Step 1: Markup.**
  - **Time & Notes tab** (`#tab-time`, ~line 1178): add a **Billing status** card at the top of the panel, with `id="bill-status-card"`. It contains:
    - `<div id="bill-status-summary"></div>`
    - `<button type="button" class="btn btn-primary" id="bill-issue-btn">Issue statement now</button>`
    - `<div id="bill-status-result"></div>`
    - `<div id="bill-statements" style="overflow-x:auto"></div>`
  - **Insights tab** (`#tab-insights`, ~line 698): add a **Billing settings** card, `id="bill-settings-card"`. It contains:
    - a label `for="bill-threshold"`, with the text "Statement threshold ($)"
    - `<input type="number" id="bill-threshold" min="100" max="100000" step="50">`
    - `<button type="button" class="btn btn-secondary" id="bill-threshold-save">Save</button>`
    - `<div id="bill-settings-result"></div>`
    - the help text "A statement is issued automatically when a client's unbilled time reaches this amount."
  - Include `<script src="{{ url_for('static', filename='js/attorney_billing.js') }}"></script>` after the `attorney_security.js` include.
- [ ] **Step 2: Hooks.**
  - In `selectClient` and `selectClientAndTab`, after `populateSecurity(c);`, add `if (window.populateBilling) populateBilling(c);`.
  - In `showInsights`, at the end, add `if (window.loadBillingSettings) loadBillingSettings();`.
- [ ] **Step 3: `static/js/attorney_billing.js`.** Follow `attorney_security.js` exactly:
  - Reuse its global `_el`, `_show`, `_note` and `_table`, since it loads first.
  - Reuse the globals `_el`, `_show`, `_note`, `_table`, `_stale`, `_busy` and `_postJSON` from `attorney_security.js`. **Define no `_`-prefixed top-level names** in `attorney_billing.js` (a second `function _stale` would silently replace the shared one); prefix private helpers with `bill`.
  - Never use `innerHTML`.
  - Functions:
    - `populateBilling(c)`: render `c.billing_summary` as follows.
      - **Summary line:** "Unbilled: $X of $T threshold · Amount due: $D".
      - **Statements table** (number, issued, billed through, amount, email status). Email status text comes from `notice.status`: pending, sending, sent, failed (append the error), no email, or skipped.
      - **Resend button:** add one when the status is `failed` or `no_email`. It POSTs to `/portal/attorney/statement-notice` with `{username, statement_id}`. On success, re-render from the response's `billing_summary`. On error, write the message to `#bill-status-result`.
    - `issueStatementNow()`: confirm first with `confirm("Issue a statement for $X of unbilled time and email the client?")`. Then POST to `/portal/attorney/issue-statement`, re-render from the response, and show "Statement #N issued." in `#bill-status-result`.
    - `loadBillingSettings()`: GET `/portal/attorney/billing-settings` and fill the input.
    - `saveBillingSettings()`: POST, then show "Saved." or the error.
  - Wire the static buttons with `addEventListener` in `DOMContentLoaded`.
  - Format money with `toLocaleString("en-US", {style: "currency", currency: "USD"})`.
- [ ] **Step 4:** Run `node --check static/js/attorney_billing.js` and the full suite. **Commit** with `feat(billing): attorney billing status and settings UI`.

---

## Chunk 4: Migration and rollout guard

### Task 8: Opening statements script and startup check

**Files:**
- New: `scripts/issue_opening_statements.py`
- Modify: `app.py`
- New tests: `tests/test_opening_statements.py`, plus additions to `tests/test_startup.py`

- [ ] **Step 1: Write the failing tests.**

```python
"""Opening-statement migration and rollout guard (spec D)."""

import json
import sys
from pathlib import Path

import pytest

import billing
import shared

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _seed(make_client, username, hours, payments=()):
    make_client(username, billing_log=[{"date": "2026-09-01", "hours": h, "note": "old"} for h in hours],
                hours_billed=round(sum(hours), 2),
                hours_paid=round(sum(payments) / 350.0, 2),     # as _apply_payment keeps it
                payments=[{"amount": a} for a in payments])


def test_migration_issues_silent_opening_statements(make_client, tmp_path, monkeypatch, sent_statement_emails):
    import issue_opening_statements as mig
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    monkeypatch.setattr(shared, "HOURLY_RATE", 350.0)
    _seed(make_client, "m1", (3.0, 4.0), payments=(350.0,))     # 7 hrs billed
    _seed(make_client, "m2", (0.0,))                             # notes only
    _seed(make_client, "m3", ())
    counts = mig.migrate(tmp_path / "bk", project_root=tmp_path / "project")
    assert counts == {"opening": 1, "baseline": 1, "covered": 1, "unreadable": 0}
    st = billing.load_ledger("m1")["statements"][0]
    assert (st["reason"], st["notice"]["status"], st["amount"]) == ("opening", "skipped", 2450.0)
    assert billing.load_ledger("m2")["covered_through"] == 1
    assert sent_statement_emails == []
    assert billing.is_migrated()
    c = shared.load_client("m1")
    due = billing.amount_due(c, billing.load_ledger("m1"))
    assert due == round(7.0 * 350.0, 2) - 350.0
    legacy = round(round(c["hours_billed"] - c["hours_paid"], 2) * 350.0, 2)
    assert abs(due - legacy) < 1.0
    assert mig.LAST_BACKUP is not None and mig.LAST_BACKUP.exists()
    assert mig.migrate(tmp_path / "bk", project_root=tmp_path / "project") == \
        {"opening": 0, "baseline": 0, "covered": 3, "unreadable": 0}


def test_migration_refuses_backup_inside_project(make_client, tmp_path):
    import issue_opening_statements as mig
    project = tmp_path / "project"; project.mkdir()
    with pytest.raises(SystemExit):
        mig.migrate(project / "bk", project_root=project)


def test_startup_blocks_until_migrated(make_client, monkeypatch):
    import app as app_module
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    shared.save_client({"username": "sx"})
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    assert any("Opening statements" in p for p in app_module.check_startup_config())
    billing.mark_migrated()
    assert not any("Opening statements" in p for p in app_module.check_startup_config())


def test_fresh_install_auto_marks(monkeypatch):
    import app as app_module
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    (shared.FIRM_SETTINGS_DIR / "migrations.json").unlink()
    assert app_module.check_startup_config() == []
    assert billing.is_migrated()
```

In both startup tests, add `monkeypatch.setattr(shared, "_fernet_cache", None)` right after the `setenv` calls, so the save and the check use the same new key and the cache is restored afterwards.

- [ ] **Step 2: `scripts/issue_opening_statements.py`.** Model it on `encrypt_existing_records.py`:

```python
"""Issue silent opening statements so clients keep seeing today's balance.

Usage (stop the app first):
    python scripts/issue_opening_statements.py --backup-dir D:\\law-office-backups

Backs up client-accounts/ and client-billing/ to a timestamped folder under
--backup-dir (refused inside this OneDrive-synced project), then for each
client: issues an 'opening' statement (no email) for all not-yet-covered time,
or a baseline when there's nothing positive to bill. Safe to re-run.
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import shared   # noqa: E402
import billing  # noqa: E402

LAST_BACKUP = None


def migrate(backup_root: Path, project_root: Path = ROOT) -> dict:
    shared.require_outside_dir(backup_root, project_root)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    dest = Path(backup_root).resolve() / f"billing-migration-{stamp}"
    shutil.copytree(shared.CLIENT_ACCOUNTS_DIR, dest / "client-accounts")
    if shared.CLIENT_BILLING_DIR.exists():
        shutil.copytree(shared.CLIENT_BILLING_DIR, dest / "client-billing")
    counts = {"opening": 0, "baseline": 0, "covered": 0, "unreadable": 0}
    for path in sorted(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")):
        username = path.stem
        try:
            client = shared.load_client(username)
            if not client:
                continue
            ledger = billing.load_ledger(username)
            log = client.get("billing_log") or []
            if ledger["covered_through"] >= len(log):
                counts["covered"] += 1
            elif billing.issue_statement(username, reason="opening", issued_by="migration",
                                         notify=False):
                counts["opening"] += 1
            elif billing.set_baseline(username):
                counts["baseline"] += 1
            else:
                counts["covered"] += 1
        except Exception as exc:
            print(f"  ! {username}: {exc}")
            counts["unreadable"] += 1
    billing.mark_migrated()
    global LAST_BACKUP
    LAST_BACKUP = dest
    return counts
```

Add a `main()` like the one in `encrypt_existing_records.py`:
- require `--backup-dir`;
- check that `shared._fernet()` succeeds, otherwise print the error and exit 2;
- print the counts and "Backup written to <path> (encrypted copies; keep until you've checked balances)";
- exit 1 if there was any unreadable record.

`migrate` returns `counts` (a dict) and records the backup folder in a module-level `LAST_BACKUP` (initialised to `None`), which `main()` prints. Put `load_dotenv(ROOT / ".env")` inside `main()`, not at import time, so importing the script in tests can't pull real keys into the test process.

Note: `require_outside_dir`'s signature is `(path, root)` and it raises `SystemExit`. Check it in `shared.py`.

- [ ] **Step 3: `app.py`.** At the end of `check_startup_config()`, before `return problems`, add:

```python
    import billing
    if not billing.is_migrated():
        if not any(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")):
            billing.mark_migrated()          # fresh install: nothing to migrate
        else:
            problems.append(
                "Opening statements have not been issued. Stop here and run:\n"
                "    python scripts/issue_opening_statements.py --backup-dir <folder outside OneDrive>")
```

- [ ] **Step 4:** Run the full suite and expect it to be green. Run `python -m py_compile scripts/*.py`. **Commit** with `feat(billing): opening-statement migration and startup guard`.

### Task 9 (controller only — live data)

These steps aren't done by the implementer. The controller runs them with the user's consent:

1. Stop the app.
2. Back up `.env` to the scratchpad before any git operation.
3. Run `python scripts/issue_opening_statements.py --backup-dir "C:\Users\Endoc\law-office-backups\billing"`.
4. Verify that every client's new amount due is within $1.00 of the legacy balance.
5. Run the startup checks.
6. Merge to `master` once the user approves.

---

## Done criteria

- `python -m pytest tests -q` is green, and the access sweep test still passes.
- Client JSON from these sources never includes unbilled entries, the unbilled amount, the threshold, notice details or `hours_billed`:
  - the billing route
  - research-save
  - claim-document
- Stripe and Coinbase charge only the statement amount due.
- A stale client save can't remove a statement or re-send a notice. Tests cover both cases.
- Startup is blocked until the migration has run, except on a fresh install.
