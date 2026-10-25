# Billing Statements & Per-Attorney Threshold — Design Spec

**Date:** 2026-10-02
**Status:** Approved (two review passes)
**Sub-project:** 2 of 5 in the portal-functionality roadmap (1 = security hardening, shipped)

---

## Overview

Today the client portal shows every billing entry and a live balance the moment an attorney
logs time. The firm wants clients to see billing only once it amounts to something worth
invoicing: when a client's **unbilled** time reaches a threshold (default **$2,000**,
adjustable per attorney), the app issues a **statement**. The client sees statements, the
entries they cover, payments and the amount due — never time logged after the latest statement.

### Decisions made during brainstorming

| Question | Decision |
|---|---|
| Visibility model | **Statements**: crossing the threshold freezes a "billed through" snapshot; later time stays hidden until the next statement |
| Issuing | **Auto-issue** at the threshold **plus** an attorney "Issue statement now" button for sub-threshold amounts |
| Notification | **Email via SendGrid** (amount + portal link, no itemisation); portal badge if email unavailable |

Out of scope: per-attorney hourly rates (one firm `HOURLY_RATE`), editing/voiding statements,
PDF invoices, allocating payments to specific statements (payments reduce the overall amount due).

### Key design choice: a separate billing ledger

Routes in this app load a client record, work on it (sometimes for seconds, e.g. an AI call), and
save the whole record back without holding a lock. Any state kept *inside* the client record can
therefore be rolled back by a stale save. If statements lived there, a stale save could delete an
already-emailed statement or reset a `sent` notice to `pending` and email the client twice.

So statement state lives in a **separate encrypted ledger file per client**, and is only ever
changed by locked read-modify-write in `billing.py`. Client-record saves never touch it.

And because `billing_log` is append-only (every write path appends or extends; nothing edits,
removes or reorders entries — verified), a statement doesn't stamp entries. The ledger records
**how many leading `billing_log` entries are covered**; everything after that index is unbilled.

---

## Section A — Data model

### A1. The ledger file

Path: `client-billing/<username>.json` (new directory `CLIENT_BILLING_DIR`, created at import,
git-ignored, written with `shared._write_record` so it is Fernet-encrypted like client records;
read with `shared._read_record`). Missing file ⇒ empty ledger.

```json
{
  "covered_through": 14,
  "statements": [
    {
      "id": "st_3",
      "number": 3,
      "issued_at": "2026-10-02T14:05:11",
      "billed_through": "2026-10-02",
      "entries_from": 9,
      "entries_to": 14,
      "hours": 6.1,
      "rate": 350.0,
      "amount": 2135.0,
      "reason": "threshold",
      "issued_by": "system",
      "notice": {"status": "pending", "at": null, "error": "", "claimed_at": null}
    }
  ]
}
```

- `covered_through` — number of leading `billing_log` entries visible to the client.
  Entries `billing_log[covered_through:]` are **unbilled**.
- A statement covers `billing_log[entries_from:entries_to]`; `entries_to` becomes the new
  `covered_through`.
- `number` = previous max + 1 (per client, from 1); `id = f"st_{number}"`.
- `billed_through` = latest `date` among covered entries, else the issue date.
- `hours` = Σ `hours` of covered entries; `rate` = `HOURLY_RATE` at issue time;
  `amount = round(hours * rate, 2)`.
- `reason` ∈ `threshold | manual | opening`; `issued_by` ∈ `system | <attorney> | migration`.
- `notice.status` ∈ `pending | sending | sent | failed | no_email | skipped`.
- All timestamps are `datetime.now().strftime("%Y-%m-%dT%H:%M:%S")` (fixed width, so string
  comparison is chronological).
- The ledger also stores `covered_fingerprint`: `[date, hours, note[:40]]` of entry
  `covered_through - 1` (or `null` when 0).
- **Known limit (pre-existing lost-update bug, not fixed here):** routes save whole client
  records without a lock, so a stale save can shorten `billing_log` or put a different entry at
  an already-covered index. If `billing_log` is shorter than `covered_through`, unbilled is empty
  and nothing crashes. If the entry at `covered_through - 1` no longer matches
  `covered_fingerprint`, `after_client_save` logs a stderr warning naming the client, so the
  drift is visible. It does not try to repair it.

### A2. Money

- **Statement total** = Σ `statement.amount`.
- **Paid** = Σ `payment.amount` from the client record's existing `payments` list.
- **Amount due (client-visible)** = `max(0, round(statement total − paid, 2))`.
- **Unbilled amount (attorney-only)** = `round(Σ hours of unbilled entries × HOURLY_RATE, 2)`.
- **Billed hours (client-visible)** = Σ `statement.hours`.
- `hours_billed` / `hours_paid` on the client record keep their meaning for attorneys and
  Insights. Insights and tax export are unchanged.

### A3. Client record

One new field, `billing_seen_at` (timestamp string, A1 format), defaulted to `""` by
`load_client`. It is written only via a locked read-modify-write helper (see C1).

### A4. Attorney settings

`firm-settings/attorney-settings.json` (new directory `FIRM_SETTINGS_DIR`, git-ignored,
plaintext — no client data), shape `{"<attorney>": {"statement_threshold": 2000.0}}`.
Missing ⇒ `DEFAULT_STATEMENT_THRESHOLD = 2000.0`. Valid range **100 – 100,000**. Written
atomically (tmp + `os.replace`) under a module lock; unreadable ⇒ treated as empty, stderr
warning, never blocks billing.

`firm-settings/migrations.json` records completed one-time migrations (Section D).

---

## Section B — `billing.py` (new module)

Sole owner of ledger state. Imports `shared`; `shared` imports `billing` only lazily inside
functions. `billing` imports `blueprints.email_service` lazily and calls
`email_service.send_statement_email` through the module attribute (so tests can stub it).

```python
DEFAULT_STATEMENT_THRESHOLD = 2000.0
NOTICE_ASYNC = True            # tests set False to send inline
NOTICE_STALE_SECONDS = 900     # a 'sending' claim older than this is re-claimable

def get_threshold(attorney: str | None) -> float
def set_threshold(attorney: str, amount) -> float      # validates, raises ValueError

def load_ledger(username: str) -> dict                  # read-only snapshot
def unbilled_entries(client: dict, ledger: dict) -> list
def unbilled_amount(client: dict, ledger: dict) -> float
def amount_due(client: dict, ledger: dict) -> float
def billing_summary(client: dict, ledger: dict) -> dict # attorney view
def client_billing_view(client: dict, ledger: dict) -> dict

def issue_statement(username: str, *, reason: str, issued_by: str, notify: bool,
                    only_if_over_threshold: bool = False) -> dict | None
def after_client_save(username: str) -> None
def send_pending_notices(username: str) -> None
def request_resend(username: str, statement_id: str) -> bool   # C3
def set_baseline(username: str) -> bool                         # D1: cover all entries, no statement
def is_migrated() -> bool
def mark_migrated() -> None
```

**Lock-order invariant** (also written as a comment at the top of `billing.py` and above
`shared._get_client_lock`): a ledger lock may be held while briefly taking a client lock
(`load_client`), but **never** take a ledger lock, call any `billing.*` function, or call
`save_client` while holding a client lock. `save_client` therefore calls the hook only after
its `with` block exits.

### B1. `issue_statement`

Under the **ledger lock** for `username` (a per-username `threading.Lock` owned by
`billing.py`, distinct from the client-record lock):

1. Read the client record fresh from disk (`shared.load_client`) and the ledger.
2. Unbilled = `billing_log[covered_through:]`. If empty, or Σ hours ≤ 0 ⇒ return `None`,
   change nothing (no empty or non-positive statements).
3. If `only_if_over_threshold` and `unbilled_amount < get_threshold(client.get("assigned_attorney"))`
   ⇒ return `None`.
4. Append the A1 statement (`entries_from = covered_through`, `entries_to = len(billing_log)`),
   set `covered_through = entries_to`, notice `pending` if `notify` else `skipped`; write ledger.
5. Return the statement.

The client record is never written by this function.

### B2. `after_client_save` — the hook

`shared.save_client(data)` calls `billing.after_client_save(data["username"])` **after** the
`with _get_client_lock(...)` block has exited (the lock is not re-entrant). It:

1. Returns immediately if `not is_migrated()` (see D3).
2. Calls `issue_statement(username, reason="threshold", issued_by="system", notify=True,
   only_if_over_threshold=True)`.
3. Calls `send_pending_notices(username)` if the ledger has any `pending` (or stale `sending`)
   notice.
4. Catches **every** exception, logs it to stderr with the username, and returns. A failure
   here can never fail the request that saved the record.

Because it runs on every `save_client`, it covers every billing path (attorney entry, upload,
research saves, client AI message, client research save, intake, claim-document, and the
create-client route that builds `billing_log` inline) with no per-route change. Cost per save is
two small file reads plus a comparison; acceptable.

`shared.recalc_hours` is **not** changed.

### B3. `send_pending_notices`

1. **Claim** under the ledger lock: re-read the ledger; for each statement whose notice is
   `pending`, or `sending` with `claimed_at` older than `NOTICE_STALE_SECONDS`, set
   `status="sending"`, `claimed_at=now`; write. Collect the claimed ids.
2. **Send** (in a daemon thread when `NOTICE_ASYNC`, else inline), outside any lock, for each
   claimed statement:
   - client email missing or without `@` ⇒ result `no_email`;
   - else `status = email_service.send_statement_email(name, email, number, amount, billed_through)`,
     which returns `"sent" | "not_configured" | "failed"`; map `not_configured` ⇒ `failed`
     with error `"email not configured"`, `failed` ⇒ `failed` with error `"send failed"`.
3. **Finalise** under the ledger lock: re-read; for each claimed statement still `sending`,
   set the final `status`, `at=now`, `error`; write.

Notice state lives only in the ledger, which only this module writes, so a stale client-record
save can never reset it. The claim step prevents two dispatchers from emailing the same
statement; the stale-claim timeout recovers from a crash between claim and finalise.
Delivery is therefore **at-least-once**: a crash after SendGrid accepts an email but before
finalise means the re-claim sends it again. A rare duplicate notice is accepted.

### B4. Views

`billing_summary(client, ledger)` (attorney):
`{unbilled_amount, unbilled_hours, threshold, statement_total, paid, amount_due, billed_hours,
statements: [... newest first, including notice]}`.

`client_billing_view(client, ledger)` (client) — only client-safe data:

```python
{
  "statements": [{id, number, issued_at, billed_through, hours, rate, amount}],  # newest first
  "entries": [{date, hours, note, category, statement_number}],  # billing_log[:covered_through], newest first
  "payments": [...],                     # newest first, fields date, amount, method
  "statement_total", "paid", "amount_due", "billed_hours",
  "has_new_statement": bool,             # latest issued_at > client["billing_seen_at"]
  "latest_billed_through": str | None,
  "hourly_rate": HOURLY_RATE,
}
```

`statement_number` for each visible entry comes from which statement's `[entries_from,
entries_to)` contains its index; entries covered by the opening baseline with no statement
(D2) show `null`. Never included: unbilled entries or amount, threshold, notice details,
`hours_billed`.

---

## Section C — Routes, responses and UI

### C1. Client portal (`blueprints/portal_client.py`, `templates/client_portal.html`)

- `GET /portal/client/billing` → `client_billing_view` + existing `card_enabled` /
  `crypto_enabled`. Then sets `billing_seen_at = now` via a new
  `shared.update_client_field_atomic(username, field, value)` (lock → `_read_record` → set →
  `_write_record`; same pattern as `log_access_atomic`) so it cannot clobber concurrent writes.
- `_balance_for(client)` ⇒ `amount_due` from the ledger; returns
  `(round(amount_due / HOURLY_RATE, 2), amount_due)`. Stripe and Coinbase therefore charge
  only the statement-billed amount due. `_apply_payment` unchanged.
- `client_portal()` passes `billed_hours` and `has_new_statement` to the template. The
  Overview "Hours Billed" card shows `billed_hours`; the Billing tab button shows a "New" badge
  when `has_new_statement`.
- `POST /portal/client/research-save` (`blueprints/research.py`) currently returns
  `total_hours` = all logged time ⇒ return `billed_hours` from the ledger instead.
- Billing tab rewrite: statements list; billed entries table with a "Statement #" column;
  payment history (date, amount, method — the always-zero "Hours Credited" column and the
  "Hours Paid" stat card are removed); amount due + Pay Now (hidden when 0); the line "Time
  logged after <latest_billed_through> will appear on your next statement."; "No statements
  yet." when empty. Payment-redirect banner kept. New DOM via `textContent` only.

### C2. Public drafting claim (`blueprints/drafting.py`)

`/drafting/claim-document` currently returns `"hours_billed": record["hours_billed"]` to the
claimant ⇒ return `billed_hours` from the ledger (0 for a new account).

### C3. Attorney portal (`blueprints/portal_attorney.py`)

- `GET /portal/attorney/client/<u>` adds `billing_summary` (B4).
- `POST /portal/attorney/issue-statement` `{username}` — `load_client_for_attorney`
  (assigned or co-counsel) ⇒ `issue_statement(reason="manual", issued_by=<session attorney>,
  notify=True)`; `None` ⇒ 400 `"No unbilled time to bill."`; `log_access_atomic(username,
  "statement_issued", "st_N $X")`; then `send_pending_notices(username)`. Returns the statement
  and a fresh `billing_summary`.
- `POST /portal/attorney/statement-notice` `{username, statement_id}` — same access check;
  allowed when the notice is `failed`, `no_email`, or a stale `sending`; sets it `pending`
  under the ledger lock (via a `billing.request_resend(username, statement_id)` helper), then
  `send_pending_notices`. Otherwise 400 `"Notice can't be resent in its current state."`.
- `GET /portal/attorney/billing-settings` ⇒ `{threshold, default}` for the session attorney;
  `POST {threshold}` ⇒ `set_threshold`; 400 `"Threshold must be between $100 and $100,000."`.
  Only one's own threshold.
- UI: new `static/js/attorney_billing.js` (project-1 `_el` / no-innerHTML rule; stale-client
  and double-submit guards like `attorney_security.js`). A **Billing status** card on the Time &
  Notes tab: unbilled vs threshold ("$1,240 of $2,000"), amount due, statements table (number,
  date, amount, email status, **Resend notice** where allowed), **Issue statement now**. A
  **Billing settings** card on the Insights tab.

### C4. Email (`blueprints/email_service.py`)

`send_statement_email(name, email, statement_number, amount, billed_through) -> str`
returning `"not_configured"` when `_api_key()` is empty, `"sent"` on success, `"failed"`
otherwise. Body: greeting, "Statement #N for services through <date>: $X due", link to
`<FIRM_WEBSITE>/client-login`, firm contact line. No notes, no hours.

---

## Section D — Migration and rollout

### D1. Script

`scripts/issue_opening_statements.py --backup-dir <outside project>` (stop the app first):

1. Refuses without a valid `DATA_ENCRYPTION_KEY`; `--backup-dir` must be outside the project
   (`shared.require_outside_dir`); copies `client-accounts/` (and `client-billing/` if present)
   there first.
2. For each client: if the ledger's `covered_through` < `len(billing_log)`:
   - if unbilled Σ hours > 0 ⇒ `issue_statement(reason="opening", issued_by="migration",
     notify=False)`;
   - else (only 0-hour or net-non-positive entries) ⇒ set `covered_through = len(billing_log)`
     with no statement (a "baseline"), so those entries stay visible as they are today.
3. Writes `{"opening_statements": "<timestamp>"}` to `firm-settings/migrations.json`.
4. Prints counts: opening statements / baselines / already covered / unreadable.
5. Idempotent: a second run finds every ledger already covered and changes nothing.

### D2. Result

Every client sees the same entries as before deployment. Amount due becomes
`max(0, round(hours_billed × rate, 2) − Σ payments)`. It may differ from the legacy figure
`round(round(hours_billed − hours_paid, 2) × rate, 2)` by rounding of `hours_paid`; the new
value is the arithmetically correct one. Tests assert the new formula exactly, and assert the
legacy figure is within $1.00.

### D3. Rollout guard

- `billing.is_migrated()` ⇔ `migrations.json` has `opening_statements`.
- Fresh install: if `client-accounts/` contains no `*.json` records, `check_startup_config()`
  calls `billing.mark_migrated()` instead of blocking (there is nothing to migrate).
- Until migrated, `after_client_save` does nothing (no auto-issue on historical time).
- `app.py` `check_startup_config()` adds a **blocking** problem when not migrated:
  "Opening statements have not been issued. Stop here and run:
  python scripts/issue_opening_statements.py --backup-dir <folder outside OneDrive>".
- Tests: conftest marks the migration done by default (writes `migrations.json` in a tmp
  `FIRM_SETTINGS_DIR`); dedicated tests cover the un-migrated state.

---

## Error handling summary

| Situation | Behaviour |
|---|---|
| Unbilled hours ≤ 0 (auto or manual) | No statement; manual ⇒ 400 "No unbilled time to bill." |
| Any exception in `after_client_save` | Logged to stderr; the saving request succeeds |
| SendGrid not configured / send fails | Statement stands; notice `failed` + error; attorney can Resend |
| Client email missing / invalid | Notice `no_email`; portal badge only |
| Crash between claim and finalise | `sending` re-claimable after 15 min (auto on next save, or Resend) |
| Stale client-record save | Cannot affect statements or notices (separate ledger) |
| `billing_log` shorter than `covered_through` | Unbilled = empty; no crash |
| Settings file unreadable | Default threshold; stderr warning |
| Threshold invalid | 400 with message |
| Not migrated | App refuses to start; hook inert |

---

## Files touched

| File | Change |
|---|---|
| `billing.py` (new) | Ledger, thresholds, issuing, views, notices, resend, migration flag |
| `shared.py` | `CLIENT_BILLING_DIR`, `FIRM_SETTINGS_DIR`; `billing_seen_at` default; `save_client` → `after_client_save` after the lock; `update_client_field_atomic` |
| `blueprints/portal_client.py` | `_balance_for` from ledger; billing view; template vars |
| `blueprints/research.py` | research-save returns billed hours |
| `blueprints/drafting.py` | claim-document returns billed hours |
| `blueprints/portal_attorney.py` | `billing_summary`; issue-statement, statement-notice, billing-settings routes |
| `blueprints/email_service.py` | `send_statement_email` |
| `templates/client_portal.html` | Billing tab rewrite, Overview card, New badge |
| `templates/attorney_portal.html` | Billing status + settings cards, script include |
| `static/js/attorney_billing.js` (new) | Attorney billing UI |
| `scripts/issue_opening_statements.py` (new) | Migration |
| `app.py` | Blocking startup check |
| `.gitignore` | `client-billing/`, `firm-settings/` |
| `tests/conftest.py` | Redirect new dirs; mark migrated; `NOTICE_ASYNC=False`; stub `send_statement_email` |

---

## Testing

- `test_billing_ledger.py` — threshold crossing (below / exactly at / above), assigned
  attorney's threshold (default when unassigned), rate recorded, numbering, `entries_from/to`,
  0-hour entries covered, non-positive unbilled ⇒ no statement, manual below threshold, amount
  due across statements and payments never negative, shortened `billing_log` ⇒ no crash,
  **a stale client save after issuing does not remove the statement**.
- `test_billing_hook.py` — every billing path (attorney entry, upload, research saves, client
  AI message, client research save, intake, claim, create-client) triggers auto-issue when over
  threshold; hook exceptions don't fail the request; inert when not migrated.
- `test_billing_notices.py` — pending→sent; not_configured / failed ⇒ failed + error; no or
  invalid email ⇒ no_email; concurrent dispatch emails once; **stale client save after send
  does not trigger a second email**; stale `sending` re-claimed; resend allowed / refused by state.
- `test_billing_settings.py` — default, override, range, own-only, corrupt file.
- `test_client_billing_view.py` — client billing JSON, research-save and claim-document
  responses never expose unbilled entries/amount/threshold/notice/`hours_billed`; New badge and
  `billing_seen_at`; Stripe amount = statement amount due (Stripe stubbed); Overview shows
  billed hours.
- `test_attorney_billing_routes.py` — access (other attorney 404, co-counsel allowed), 400s,
  summary fields; route sweep still passes.
- `test_opening_statements.py` — backup required and outside project, no emails, baselines
  for 0-hour clients, idempotent, D2 amount assertions, writes the migration flag;
  startup check blocks until migrated.
- Browser check in the sandbox: before/after threshold in the client portal, Pay Now amount,
  attorney Issue / Resend / settings.
