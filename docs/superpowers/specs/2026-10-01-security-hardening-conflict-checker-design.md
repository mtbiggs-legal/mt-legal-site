# Security Hardening & Conflict Checker — Design Spec

**Date:** 2026-10-01
**Status:** Draft — awaiting review
**Sub-project:** 1 of 5 in the portal-functionality roadmap (see "Roadmap" at the end)

---

## Overview

The attorney portal gates every route on "is an attorney" but never on "is *this client's*
attorney". Any logged-in attorney can read, bill, message, or delete documents for any client
by putting a username in a URL or request body. Two JSON endpoints return full client records
including password hashes. Client records sit as plaintext JSON in a OneDrive-synced folder.
There is no login throttling, no idle timeout, no CSRF protection, and no record of who viewed
a file. The conflict checker only catches exact name matches.

This spec closes those gaps and replaces the conflict checker. It does not add new
client-facing features.

### Decisions made during brainstorming

| Question | Decision |
|---|---|
| Who may open a client file? | Assigned attorney **plus** explicitly added co-counsel. Everything else is denied. |
| Conflict scope | Active clients, archived (former) clients, opposing parties, related parties, leads. Fuzzy matching. Every check recorded. |
| Encryption at rest | Encrypt client account records (`client-accounts/*.json`). Uploaded documents, leads, research and draft history stay plaintext in this sub-project. |

---

## Section A — Access control

### A1. `can_access_client` and `load_client_for_attorney`

New in `shared.py`:

```python
def can_access_client(attorney_username: str, client: dict) -> bool:
    return (client.get("assigned_attorney") == attorney_username
            or attorney_username in client.get("co_counsel", []))

def load_client_for_attorney(username: str, assigned_only: bool = False) -> dict | None:
    """load_client + access check against session["username"]. Returns None
    (caller sends 404) when the client does not exist OR the session attorney
    may not see it — the two cases are deliberately indistinguishable.
    assigned_only=True excludes co-counsel."""
```

Every attorney route that takes a client username replaces `load_client(username)` with
`load_client_for_attorney(username)` and returns **404 `{"error": "Client not found."}`** on
`None`. Routes that build a file path from a username without loading the record first
(`list_documents`, `delete_document`, `serve_document`, `preview_document`, `docx_preview`,
`save-draft`, `issue-spot`) must call `load_client_for_attorney` first and stop on `None`.
`upload_document` currently saves the file **before** loading the client; the access check
moves ahead of `file.save`. `save-report` already loads the record and just swaps the call.
`research/draft` takes an **optional** username: the check applies only when one is
supplied.

Routes in scope (all in `blueprints/portal_attorney.py`):

- `GET  /portal/attorney/client/<username>`
- `POST /portal/attorney/archive-client`, `/unarchive-client`, `/update-client`
- `POST /portal/attorney/generate-summary`, `/billing-entry`, `/reply`
- `GET  /portal/attorney/documents/<username>`
- `POST /portal/attorney/upload-document`, `/delete-document`
- `GET  /portal/attorney/document/…`, `/preview/…`, `/docx-preview/…`
- `POST /portal/attorney/research/issue-spot`, `/research/draft`, `/research/save-draft`, `/research/save-report`

Other attorney routes:

- `GET /portal/attorney/clients` — filter to accessible clients (currently returns **every**
  client).
- `GET /attorney-portal` (sidebar) and `/portal/attorney/dashboard` — include co-counsel
  clients, shown with a "Co-counsel" badge.
- `POST /portal/attorney/archive-lead` — load the lead and require
  `lead["assigned_attorney"] == session attorney`; 404 otherwise.
- `/portal/attorney/insights` and `/insights/export-tax` keep counting **assigned** clients
  only (revenue belongs to the assigned attorney, not co-counsel).
- `POST /calendar/schedule` (`blueprints/calendar.py`) is used **publicly** (the "Schedule
  Initial Call (Free)" button on the intake success card in `static/js/app.js`), but today
  also writes activity onto any client whose name matches the posted `client_name` — so an
  anonymous visitor can append entries to an existing client's timeline. The route stays
  public, but the client-name matching and `_log_activity` call only run when
  `session["role"] == "attorney"`, and then only against clients that attorney can access.

**Co-counsel permissions.** Co-counsel may view the record and documents, log billing,
message the client, upload documents, run research, and record conflict decisions. Only the
**assigned** attorney may archive/unarchive, delete documents, or change the co-counsel
list. These assigned-only routes use `load_client_for_attorney(username, assigned_only=True)`.

### A2. Never expose password hashes

New helper `public_client_view(client) -> dict` returns a copy without `password` and
`must_change_password`. Applied everywhere a client record leaves the server:

- `jsonify` in `/portal/attorney/clients` and `/portal/attorney/client/<username>`.
- The `/attorney-portal` template context: `templates/attorney_portal.html` embeds
  `window._ALL_CLIENTS_DATA = {{ clients | tojson }}` (line ~1793), which today writes every
  full record — hashes included — into the page source. `attorney_portal()` passes
  `[public_client_view(c) for c in …]` for both `clients` and `archived_clients`.

### A2b. No default passwords

`portal_create_client` currently defaults the password to the literal `"password"` and
reads `must_change_password` from the request body; the portal JS
(`attorney_portal.html` ~line 2916) *also* substitutes `|| "password"` before posting, so a
server-side default alone would not close the hole.

Changes:

- **Server:** use the posted password only if it meets `MIN_PASSWORD_LENGTH` **and** is not
  in a small deny-list (`password`, `password1`, `12345678`, `changeme`, the username);
  otherwise `generate_temp_password()`. Always `must_change_password = True`. The response
  gains `temp_password` (the password actually set, plaintext, returned once).
- **JS:** remove the `|| "password"` fallback (send empty when the field is blank), and the
  success card (~line 2939) displays `d.temp_password` from the response instead of the
  browser-side variable.

### A3. Co-counsel

- New client field `co_counsel: list[str]` of attorney usernames, defaulted to `[]` in
  `load_client`.
- `POST /portal/attorney/co-counsel` with `{username, action: "add"|"remove", attorney}`.
  Only the **assigned** attorney may call it (co-counsel cannot add further co-counsel).
  `attorney` must be a key of `ATTORNEYS` and must not be the assigned attorney. Logged to
  `activity_log` and `access_log`.
- UI: client detail panel gets a "Co-counsel" row listing names with ✕ buttons and a
  dropdown of other attorneys + "Add". Hidden for co-counsel viewers.

### A4. Access log

New client field `access_log: list[{timestamp, attorney, action, detail, ip}]`.
`_log_access(client, action, detail)` mutates the in-memory `client` dict only; the route
must call it **before** its own `save_client(client)`. (Existing `_log_activity` reloads and
saves separately, *after* the route's save — so ordering is: mutate → `_log_access` →
`save_client` → `_log_activity`, which then reloads a record that already contains the access
entry.) Read-only routes that have no save of their own call
`_log_access_and_save(username, action, detail)`, which does load → append → save under the
client lock.

Logged actions: `view_record` (GET client), `view_documents`, `download_document`,
`preview_document`, `edit_record`, `billing_entry`, `message_sent`, `document_upload`,
`document_delete`, `co_counsel_change`, `conflict_check`.

To avoid a write on every GET, view actions are de-duplicated: a `view_*` entry is skipped if
the same attorney logged the same action for the same client within the previous 10 minutes.
The log is capped at the most recent 1,000 entries per client.

`access_log` is attorney-only: it is stripped by `public_client_view` and never sent to the
client portal. UI: "Access history" collapsible table in the client detail panel.

`activity_log` (existing, client-visible timeline) is unchanged.

---

## Section B — Authentication & session hardening

### B1. Login throttling

New module `security.py` (kept out of the already-large `shared.py`):

```python
def login_locked(kind: str, username: str, ip: str) -> int   # seconds remaining, 0 if not locked
def record_login_failure(kind: str, username: str, ip: str) -> None
def clear_login_failures(kind: str, username: str, ip: str) -> None
```

- Key is `f"{kind}:{username.lower()}:{ip}"`, `kind` ∈ `{"attorney", "client", "claim"}`.
  Keying on IP means there is no global per-account lockout; acceptable because the app is
  local or behind the share password. Noted, not solved here.
- Storage directory is `shared.SECURITY_STATE_DIR` (overridable, so tests point it at
  `tmp_path`).
- 5 failures within 15 minutes → locked for 15 minutes from the 5th failure.
- Stored in `security-state/login-failures.json` (new directory, git-ignored), guarded by a
  module-level lock, entries older than 1 hour pruned on each write.
- `attorney_login` and `client_login` check `login_locked` **before** checking the
  password, so a locked account cannot be probed. Locked response: the normal login page
  with "Too many failed attempts. Try again in N minutes." and HTTP 429.
- Success calls `clear_login_failures`.
- **`/drafting/claim-document`** (`blueprints/drafting.py`) also verifies an existing
  client's password from a posted full name — an unthrottled password oracle today. It uses
  the same throttle with `kind="claim"` and the matched username; locked → 429 JSON.

### B2. Session settings (`app.py`)

```python
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE   = sharing   # True only in HTTPS shared mode
PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
```

- On successful login: reset the session before setting role/username (prevents session
  fixation), then `session.permanent = True`.
- `before_request` hook: if `role` is set and `last_seen` is older than 30 minutes, reset the
  session and redirect to the matching login page (JSON requests get 401
  `{"error": "Session expired."}`). Otherwise update `last_seen`. A session with `role` but
  **no** `last_seen` (pre-upgrade cookies, tests) is treated as fresh and stamped. The
  portal JS treats a 401 from `apiFetch` as "redirect to login".
- **"Reset" means `security.reset_session()`**, not a bare `session.clear()`: it clears
  everything except `share_authed` (set by `require_auth` in shared mode). A bare clear would
  wipe it and make the next `fetch` hit a Basic-Auth 401. `/logout` keeps its full clear —
  logging out should drop shared-mode auth too.
- `SECRET_KEY`: if unset, app startup **fails** with a message explaining how to generate
  one. (Today it silently falls back to `os.urandom`, which logs everyone out on every
  restart and hides misconfiguration.) The check lives in `check_startup_config()` in
  `app.py`, called from the `__main__` block — not at import — so tests (which import `app`
  and set `SECRET_KEY` / `DATA_ENCRYPTION_KEY` in `conftest.py`) are unaffected. The same
  function performs the `DATA_ENCRYPTION_KEY` check (C3) and the password cleanup (B5).

### B3. CSRF

- `security.py` provides `csrf_token()` (per-session random token, created lazily) and a
  `before_request` check: for `POST/PUT/PATCH/DELETE`, the token must match either the
  `X-CSRF-Token` header or a `csrf_token` form field. Mismatch → 400
  `{"error": "Invalid or missing CSRF token."}`.
- **Exempt:** `/webhooks/stripe` and `/webhooks/coinbase` (verified by signature already),
  and public anonymous endpoints that take no session-bound action: `/intake/submit`,
  `/client-register`, `/chat/message`, `/capture/lead`, `/follow-up/schedule`,
  `/api/track-visit`. Exemptions are a single explicit set in `security.py`. Every other
  POST (including `/research/query`, `/drafting/generate`, `/drafting/claim-document`,
  `/calendar/schedule`, client-portal routes) requires the token — the meta tag is in
  `base.html`, which every page extends.
- Login forms are **not** exempt (login CSRF): they render the hidden field.
- `base.html` renders `<meta name="csrf-token" content="{{ csrf_token() }}">` and defines a
  global `apiFetch(url, opts)` wrapper that adds the header and handles 401. Every existing
  `fetch(` call that sends a POST switches to `apiFetch`: `attorney_portal.html`,
  `client_portal.html`, `drafting.html`, `base.html`, `client_login.html`, `index.html`, and
  **`static/js/app.js`** (loaded from `base.html`; posts to `/research/query` and
  `/calendar/schedule`, which require the token). A test greps templates and `static/js`
  for `fetch(` with `method: "POST"` outside `apiFetch` and fails if any remain.
- **Test strategy:** `app.config["CSRF_ENABLED"]` (default `True`). `conftest.py` sets it
  `False` so the 33 existing `.post(` calls keep working; `test_csrf.py` turns it on. HTML forms (`attorney_login`, `client_login`, `change_password`) add
  `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.

### B4. Security headers

`after_request` in `app.py`:
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: same-origin`. No CSP in this sub-project (the templates use inline
handlers extensively; a CSP would need its own pass).

### B5. Plaintext password cleanup

At startup, after the encryption key is loaded, `shared.upgrade_all_plaintext_passwords()`
walks client accounts and hashes any `password` that is not a bcrypt hash, setting
`must_change_password = True` on each one it touches. This reuses the logic in
`scripts/hash_existing_passwords.py` (moved into a shared function the script now calls).
Scale today: **32 of 40** account records hold plaintext passwords, 20 of them the literal
`"password"`. All 32 get hashed and forced to change password on next login.

---

## Section C — Encryption at rest (client account records)

### C1. Format

- Library: `cryptography` (Fernet) — added to `requirements.txt`.
- Key: `DATA_ENCRYPTION_KEY` in `.env` (urlsafe base64 Fernet key). Loaded **lazily** by
  `shared._fernet()` on first record read/write (cached), not at import — so tests only need
  the env var set before the first request, and `check_startup_config()` reports a missing
  key cleanly instead of an import-time traceback.
- Encrypted files are written as `client-accounts/<username>.json` containing the Fernet
  token bytes (begins with `gAAAAA`). Filename unchanged so existing globbing and username
  lookup keep working.
- `_read_record(path) -> dict`: if the file starts with `{` parse as plaintext JSON;
  otherwise Fernet-decrypt then parse. `_write_record(path, dict)`: always writes encrypted.
  This makes migration gradual and lets tests write plaintext fixtures.

### C2. Single choke point

All client-record I/O already lives in `shared.py`. Every direct `open()` of a
`CLIENT_ACCOUNTS_DIR` file is replaced by `_read_record` / `_write_record`:
`load_client`, `save_client`, `all_clients`, `check_conflict_of_interest` (being rewritten
anyway), and `scripts/hash_existing_passwords.py`. Writes go to a temp file then
`os.replace` so a crash mid-write cannot leave a half-encrypted record.

A test greps the codebase (excluding `tests/`) for `CLIENT_ACCOUNTS_DIR` combined with
`open(`, `read_text`, `read_bytes`, or `json.load` outside these helpers and fails if it finds
one. `tests/test_activity_log.py` currently reads saved account files with
`json.loads(path.read_text())`; it switches to `shared._read_record`.

### C3. Key handling

- Missing key at startup → app refuses to start with: how to generate one
  (`python scripts/generate_data_key.py`) and a warning that losing it makes records
  unrecoverable and it must be backed up somewhere other than this folder.
- Key present but a record fails to decrypt → `load_client` raises a clear
  `RecordDecryptError(username)`; routes return 500 "Client record could not be decrypted";
  `all_clients` skips the record and logs the username to stderr (so one bad file does not
  take down the dashboard).

### C4. Migration script

`scripts/encrypt_existing_records.py`:

1. Refuses to run without `DATA_ENCRYPTION_KEY`.
2. Copies `client-accounts/` to a timestamped backup directory given by `--backup-dir`
   (required argument; the script refuses a path inside the OneDrive-synced project folder).
3. Encrypts each plaintext record in place via `_write_record`.
4. Re-reads every record with `_read_record` and compares to the original dict; on any
   mismatch, restores that file from backup and exits non-zero.
5. Prints counts: encrypted / already encrypted / failed.

Idempotent: already-encrypted files are skipped.

### C5. Explicitly not encrypted in this sub-project

`client-files/` (uploaded documents), `leads/`, `client-data/`, `research-history/`,
`draft-history/`, `case-searches/`, `token-usage/`. Leads contain contact details and should
be next; noted in the Roadmap.

---

## Section D — Conflict checker

### D1. Data model changes (client record)

```json
"opposing_parties": ["Acme Roofing LLC"],
"related_parties":  [{"name": "Dana Morris", "relationship": "Spouse"}]
```

- `load_client` defaults both to `[]`. No migration: today no code path stores
  `opposing_party` on a client record — intake and create-client pass it to the checker and
  discard it. From now on both **save** it: intake and create-client write the submitted
  `opposing_party` (if any) into `opposing_parties`, and create-client accepts
  `related_parties` from the New Client form.
- `relationship` is free text with UI suggestions: Spouse, Co-defendant, Witness, Business
  partner, Employer, Parent/Guardian, Other.
- Editable in the client detail panel (tag-style list inputs) and on the New Client form.

### D2. Matching — new module `conflicts.py`

```python
def normalise_name(name: str) -> str
def name_similarity(a: str, b: str) -> float        # 0.0–1.0
def run_conflict_check(names: list[str], exclude_username: str | None = None) -> list[Hit]
```

`normalise_name`: lowercase; strip punctuation; drop honorifics and suffixes
(`mr mrs ms dr jr sr ii iii iv esq`) and entity suffixes (`llc inc corp co ltd lp llp pllc
company corporation`); map common nicknames to a canonical first name via a small table in
the module (robert/bob/rob/bobby, william/bill/will/billy, richard/rick/dick, james/jim/jimmy,
john/jack, elizabeth/liz/beth/betsy, katherine/kate/kathy/katie, margaret/maggie/peggy,
michael/mike, christopher/chris, anthony/tony, joseph/joe, thomas/tom, daniel/dan/danny,
jennifer/jen/jenny, patricia/pat/patty, alexander/alex, alexandra/alex — about 25 entries,
no more); collapse whitespace.

`name_similarity`: max of (a) `difflib.SequenceMatcher` ratio on the normalised strings and
(b) the same ratio on the token-sorted strings (handles "Smith, Robert" vs "Robert Smith").
A single-token name (e.g. just "Smith") is capped at 0.69 so surnames alone never
auto-flag.

Thresholds: **≥ 0.85 = "likely"**, **0.70–0.849 = "possible"**, below 0.70 ignored.

`Hit`:

```python
{
  "searched_name": str,
  "matched_name":  str,
  "score":         float,
  "level":         "likely" | "possible",
  "source":        "client" | "former_client" | "opposing_party" | "related_party" | "lead",
  "relationship":  str | None,       # for related_party
  "username":      str | None,       # client the hit belongs to
  "lead_file":     str | None,
  "matter":        str,              # case_type / charges, for context
  "assigned_attorney": str,
}
```

Sources: every client record (`former_client` if `archived`), each of its
`opposing_parties` and `related_parties`, and each non-archived lead's `name` field
(`leads/*.json` — leads have no opposing-party field). `client-data/` intake snapshots are
**not** searched: every intake also creates a client account, so those people are already
covered via `client-accounts/`. Hits sorted likely-first, then by score.

**Adverse-direction tagging** (kept from today's checker, now on fuzzy hits): if a searched
*opposing* name matches a client, or a searched *client* name matches someone's opposing
party, the hit message says "potentially adverse".

**Visibility across attorneys:** conflict results must search the whole firm (that is the
point), so hits on another attorney's client are returned — but only `matched_name`,
`source`, `level`, `matter` category (case type, not charges or notes), and the assigned
attorney's display name. No username, no link. The attorney is told to ask their colleague.

### D3. Where it runs

1. **Public intake** (`/intake/submit`) — **fix an existing leak:** today the response
   returns `conflict_warnings` naming existing clients and their case types, and
   `static/js/app.js` displays them to the anonymous visitor. After this change the public
   response contains **no** conflict information (the `app.js` banner is removed; the
   intake page's existing "conflict review" disclaimer stays). The check result is stored
   in the new client record's `conflict_checks` (trigger `intake`) and surfaces to the
   assigned attorney via the unresolved-conflict badge.
2. **Attorney create-client** — as today, via `run_conflict_check` over client name +
   opposing parties + related parties. Warnings shown to the attorney; creation not
   blocked; result stored with trigger `create`.
3. **Unauthenticated account creation** — `/client-register` and `/drafting/claim-document`
   (when it creates a new account) run the check on the full name and store it in the new
   record's `conflict_checks` (triggers `self_register` / `claim`). Nothing is returned to
   the requester.

4. **Manual tool** — new "Conflict Check" tab in the attorney portal: textarea of names (one
   per line), optional "attach to client" selector, "Run check" button, results table.
   Endpoint: `POST /portal/attorney/conflict-check` `{names: [...], username?: str}`.
5. **Re-check on edit** — when `update-client` changes `opposing_parties` or
   `related_parties`, the new names are checked and any hits returned in the response.

**Redaction is applied at read time, not only at storage.** Stored hits keep full detail;
every endpoint that returns hits (create-client response, client detail, manual tool)
passes them through `redact_hits(hits, viewer=session attorney)`. For any hit on a client
or lead the viewer cannot access, it keeps **only** `searched_name`, `matched_name`,
`score`, `level`, `source`, `matter` (case type only), and the assigned attorney's display
name — the same field list as D2, defined once in `redact_hits`. So
co-counsel added later never sees more than they are entitled to.

### D4. Recording checks and decisions

Client field `conflict_checks: list`:

```json
{
  "id": "cc_20261001_142233",
  "timestamp": "2026-10-01T14:22:33",
  "run_by": "SophiaH",
  "trigger": "intake" | "create" | "self_register" | "claim" | "manual" | "edit",
  "names": ["Dana Morris"],
  "hits": [ ...Hit... ],
  "decision": null | "cleared" | "waiver_obtained" | "declined",
  "decision_note": "",
  "decided_by": null,
  "decided_at": null
}
```

- `POST /portal/attorney/conflict-decision` `{username, check_id, decision, note}` —
  requires client access; `note` required when decision is `waiver_obtained`.
- Client detail panel shows a "Conflicts" section: each check with hit count and decision.
  A check with hits and no decision shows an amber "Unresolved conflict check" badge on the
  client in the sidebar.
- Manual checks not attached to a client are stored in
  `security-state/conflict-checks.json` (same shape, capped at 2,000 entries) so the firm
  still has a record. They contain only names and hit summaries.

### D5. Removal

`check_conflict_of_interest` in `shared.py` is deleted; its two callers move to
`conflicts.run_conflict_check`. The **attorney** create-client response keeps a
`conflict_warnings: [str]` list (built from hits) so the existing portal JS keeps working,
plus a new `conflict_hits` list for the richer display. The **public** intake response drops
`conflict_warnings` entirely (D3.1).

---

## Error handling summary

| Situation | Behaviour |
|---|---|
| Attorney requests a client they can't access | 404 "Client not found." + nothing logged to that client |
| Locked-out login | Login page, 429, minutes remaining |
| Session idle > 30 min | HTML: redirect to login. JSON: 401, `apiFetch` redirects |
| Missing/bad CSRF token | 400 JSON error; `apiFetch` shows "Your session changed — reload the page." |
| `SECRET_KEY` or `DATA_ENCRYPTION_KEY` missing | App exits at startup with setup instructions |
| One record fails to decrypt | That client 500s; lists/dashboards skip it and log to stderr |
| Conflict check on empty names | 400 "Enter at least one name." |
| `security-state/*.json` corrupt | Treated as empty, file rewritten; logged to stderr |

---

## Files touched

| File | Change |
|---|---|
| `shared.py` | `_read_record`/`_write_record`, encryption key load, `can_access_client`, `load_client_for_attorney`, `public_client_view`, `_log_access`, new field defaults, `upgrade_all_plaintext_passwords`; delete `check_conflict_of_interest` |
| `security.py` (new) | Login throttling, CSRF token + check, exempt set |
| `conflicts.py` (new) | Normalisation, similarity, `run_conflict_check` |
| `app.py` | Session config, `SECRET_KEY` enforcement, before/after-request hooks, startup checks |
| `blueprints/auth.py` | Throttling, session fixation fix, CSRF field |
| `blueprints/portal_attorney.py` | Access checks on all client routes, co-counsel, conflict-check + decision endpoints, access logging |
| `blueprints/intake.py` | New conflict checker; stop returning conflicts publicly; save `opposing_parties` |
| `blueprints/drafting.py` | Throttle `claim-document`; conflict check on account creation |
| `blueprints/calendar.py` | `/calendar/schedule` stays public; client matching + activity logging only for attorneys, access-scoped |
| `static/js/app.js` | `apiFetch`; remove public conflict banner |
| `templates/intake.html`, `templates/research.html` | No changes — they load `app.js` and get `apiFetch` / the meta tag via `base.html` |
| `tests/conftest.py` | `DATA_ENCRYPTION_KEY`, `CSRF_ENABLED=False`, `SECURITY_STATE_DIR` → `tmp_path` |
| `tests/test_activity_log.py` | Read records via `_read_record` |
| `templates/base.html` | CSRF meta tag, `apiFetch` |
| `templates/attorney_portal.html` | `apiFetch`, remove `|| "password"` fallback, success card shows `d.temp_password`, co-counsel UI, access history, parties editors, Conflict Check tab, conflict section + badge |
| `templates/client_portal.html`, `drafting.html`, `index.html`, login/change-password templates | `apiFetch` / hidden CSRF field |
| `scripts/generate_data_key.py`, `scripts/encrypt_existing_records.py` (new) | Key generation, migration |
| `scripts/hash_existing_passwords.py` | Call shared function |
| `requirements.txt` | `cryptography` |
| `.gitignore` | `security-state/` |

---

## Testing

New pytest modules (existing `tests/conftest.py` pattern — temp data dirs, Flask test
client):

- `test_client_access.py` — for each in-scope route: assigned attorney 200, co-counsel 200,
  other attorney 404, response bodies never contain `"password"`. A sweep test lists every
  `portal_attorney` rule containing `<username>` or reading `username` and asserts it is in
  the tested set, so a new unguarded route fails CI.
- `test_co_counsel.py` — add/remove, only assigned attorney may change, cannot add self or
  unknown attorney; co-counsel gets 404 on archive/unarchive/delete-document.
- `test_no_hash_leak.py` — `/attorney-portal` HTML, `/portal/attorney/clients`, and
  `/portal/attorney/client/<u>` contain no `$2b$` hash and no `"password"` key;
  create-client without a password returns a generated temp password and never stores
  `"password"` hashed from the literal `"password"`.
- `test_intake_privacy.py` — `/intake/submit` with a name matching an existing client
  returns no conflict data; the new record has a `conflict_checks` entry.
- `test_access_log.py` — entries written, view de-dup window, cap at 1,000, never in client
  portal responses.
- `test_login_throttle.py` — 5th failure locks, correct password rejected while locked,
  unlock after window (time patched), success clears; same for `/drafting/claim-document`.
- `test_csrf.py` — POST without token 400 with the JSON error body `apiFetch` keys on,
  with header 200, with form field 200, webhooks and public endpoints exempt. (The
  client-side "reload the page" message is a 3-line branch in `apiFetch`; verified manually
  in the browser during implementation, not unit-tested.)
- `test_calendar_schedule.py` — anonymous POST does not touch any client record; attorney
  POST logs activity only on an accessible client.
- `test_session.py` — idle expiry for HTML and JSON, session cleared on login, cookie flags.
- `test_encryption.py` — round trip, plaintext still readable, written file is not
  plaintext, decrypt failure path, migration script backup + verify + idempotence, the
  `open(` grep guard.
- `test_conflicts.py` — table of name pairs with expected levels (Bob Smith/Robert Smith Jr.
  likely; Smith alone ignored; "Acme Roofing LLC"/"ACME Roofing" likely; unrelated names
  none), sources incl. former client and lead, cross-attorney redaction, decisions stored,
  waiver requires note.

All existing tests must keep passing (`conftest.py` gains a generated
`DATA_ENCRYPTION_KEY`, `CSRF_ENABLED = False`, and points `SECURITY_STATE_DIR` at
`tmp_path`; it already sets `SECRET_KEY`).

---

## Out of scope

- Two-factor authentication.
- Content-Security-Policy.
- Encrypting uploaded documents, leads, and history folders.
- Role/permission tiers beyond assigned + co-counsel (e.g. paralegal accounts).
- Blocking intake on a conflict (warnings only; the attorney decides).
- `/logout` is a GET (cross-site logout possible; low impact).
- Per-account (IP-independent) lockout.
- `/client-register` (and other public routes) lacking `@require_auth` in shared mode — an
  existing gap in share-password gating, to be handled with the productization work.

---

## Roadmap (remaining sub-projects, each gets its own spec)

2. **Billing visibility threshold** — clients see balance/billing only after unbilled amount
   reaches a per-attorney threshold (default $2,000).
3. **Scheduling-order upload** — new document category; extract First Discussion, Second
   Discussion, Motions Deadline, Pre-Trial Conference, Trial dates; attorney confirms; push
   to calendar.
4. **Voicemail summaries** — summarise voicemails into client correspondence and auto-bill
   0.2 hrs. Needs the voicemail source decided first.
5. **Documents tab refresh** — search, client-visible flag, new categories.
6. *(follow-up)* Encrypt leads and uploaded documents.
