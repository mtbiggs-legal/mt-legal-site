# Voicemail Summaries — Design Spec

**Date:** 2026-10-02
**Status:** Reviewed (three review passes) — awaiting user approval
**Sub-project:** 4 of 5 in the portal-functionality roadmap (1–3 shipped)

---

## Overview

The office's phone system emails each voicemail (with a transcript) to a Gmail / Google
Workspace mailbox. The app reads those emails (read-only), has Claude summarise the message,
matches the caller-ID number to a client, and adds an **attorney-only** voicemail note to that
client's correspondence, billing **0.2 hrs**. Unknown or ambiguous callers go to a **Voicemail
inbox** where an attorney assigns or dismisses them.

### Decisions made during brainstorming

| Question | Decision |
|---|---|
| Source | Voicemail-to-email into Gmail / Google Workspace, emails include a transcript |
| Matching | Auto-match by caller ID; exactly one match ⇒ note + bill; otherwise ⇒ inbox queue |
| Visibility | Attorney-only note (never shown to the client, never sent to the client AI chat) |

Out of scope: audio transcription, replying to callers, modifying the mailbox (labels, read
state, deletion), non-Gmail providers.

### Pre-existing bugs fixed as part of this project

1. **Stored XSS.** `populateMessages` in `templates/attorney_portal.html` (~line 2390) puts
   `m.text`, `m.from` and `m.date` into `innerHTML` unescaped. Voicemail summaries come from
   email content, so the attorney message thread is rebuilt with the shared `_el` helpers.
2. **Lost message updates.** `client_send_message` (`portal_client.py`) loads the client, makes
   a multi-second AI call, then saves the record it loaded, overwriting anything written in
   between; the attorney reply route (`portal_attorney.py`) does a plain load/save (shorter
   window, same problem). Once a background poller writes voicemail notes, these would drop
   them. Both routes are changed to append their messages/billing through an atomic helper
   (Section B6).

---

## Section A — Google access

### A1. Scopes and existing tokens

Adding a scope to the list used when **loading** a token would break Calendar/Drive at the next
refresh (google-auth requests exactly the listed scopes; Google answers `invalid_scope` for an
ungranted one). So:

- `shared.CALENDAR_SCOPES` is unchanged. New `shared.GMAIL_SCOPE =
  "https://www.googleapis.com/auth/gmail.readonly"` and `shared.AUTHORIZE_SCOPES =
  CALENDAR_SCOPES + [GMAIL_SCOPE]`.
- `_google_credentials` loads the token with **no scopes argument**
  (`Credentials.from_authorized_user_file(str(TOKEN_FILE))`) so refresh uses the scopes the
  token was actually issued with. A `google.auth.exceptions.RefreshError` during refresh is
  converted into the existing `ValueError(not_authorized_message)`.
- `/calendar/authorize` (blueprints/calendar.py) requests `AUTHORIZE_SCOPES`, with
  `os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")` set once at calendar.py import (otherwise oauthlib raises
  "Scope has changed" when the user unticks a scope on Google's granular consent screen, and the
  route 500s). After the flow:
  - `granted = creds.granted_scopes` (split on spaces if a string; `[]` if None — never fall
    back to `creds.scopes`, which is the *requested* list);
  - the token JSON is written with its `"scopes"` field **replaced by `granted`**, so later
    loads/refreshes never ask for an ungranted scope;
  - the grants are recorded in `SECURITY_STATE_DIR/google-grants.json` via `_write_record`:
    `{"granted": [...], "at": ISO}`.
  The grants record is the authority for `gmail_authorized()`; tokens issued before this change
  have no record, which simply means "re-authorize to enable voicemail".
- `shared.gmail_authorized() -> bool`: token file exists **and** the grants record contains
  `GMAIL_SCOPE`. Local checks only; never raises; never calls Google.
- `shared.get_gmail_service()`: raises `ValueError("Gmail not authorized. Re-authorize Google
  from the dashboard.")` unless `gmail_authorized()`; otherwise `_google_credentials(...)` and
  `google_build("gmail", "v1", credentials=creds, ...)` (match how the calendar service is
  built).
- A Gmail `HttpError` with status 401/403 during a run ⇒ result `not_authorized` (covers a
  revoked or narrowed grant).
- `/calendar/status` gains `"gmail_authorized": <bool>` (local, like the rest of that route).

Setup note (added to `GOOGLE_CALENDAR_SETUP.md`): `gmail.readonly` is a restricted scope; with
an OAuth app in "Testing" status, refresh tokens expire after 7 days, so publish the app
(internal for Workspace) or expect weekly re-authorization.

### A2. Configuration (`.env`, documented in `.env.example`)

| Variable | Default | Meaning |
|---|---|---|
| `VOICEMAIL_GMAIL_QUERY` | *(empty ⇒ feature off)* | Gmail search selecting voicemail emails, e.g. `from:voice-noreply@google.com` |
| `VOICEMAIL_POLL_SECONDS` | `300` | Background poll interval; `0` disables the poller (button still works) |
| `VOICEMAIL_MODEL` | `claude-opus-5-5` | Model for the summary |
| `VOICEMAIL_LOOKBACK_DAYS` | `14` | Gmail search window (`newer_than:Nd`) |
| `VOICEMAIL_MAX_PER_RUN` | `25` | Max **unprocessed** emails summarised per run |

---

## Section B — Processing (`voicemail.py`, new module)

### B1. State

One encrypted file `SECURITY_STATE_DIR/voicemail.json` (`_read_record` / `_write_record`;
missing ⇒ empty) guarded by a module `threading.Lock` (`_STATE_LOCK`):

```json
{
  "enabled_at": "2026-10-02T15:00:00+00:00",
  "processed": {"<gmail_id>": "matched" | "inbox" | "skipped" | "failed:<n>"},
  "inbox": [
    {"id": "vm_<gmail_id>", "gmail_id": "...", "received_at": "2026-10-02T09:14:00-05:00",
     "caller_phone": "6155551234" | "", "caller_name": "...", "callback_number": "",
     "summary": "...", "urgent": false, "urgency_reason": "", "needs_review": false,
     "candidates": ["username", ...], "status": "open" | "assigning" | "assigned" | "dismissed",
     "status_at": "...", "resolved_by": null, "assigned_to": null}
  ],
  "last_run": {"at": "...", "by": "...", "result": {...}}
}
```

**Locking rule:** every state change is a short read-modify-write under `_STATE_LOCK` that
touches one item (helpers `_mark_processed(gmail_id, value)`, `_add_inbox_item(item)`,
`_transition(item_id, from_status, to_status, **fields) -> item | None`). Gmail, Claude,
`attach_to_client` and `save_client` are **never** called while `_STATE_LOCK` is held, and
`_STATE_LOCK` is never taken while holding a client lock. Runs never write back a snapshot of the
whole state.

Caps: `processed` keeps the newest 5,000 entries (insertion order); `inbox` keeps every
`open`/`assigning` item plus the 200 most recent resolved ones.

**First-run cutoff:** the first run that finds `enabled_at` missing sets it to now. Emails whose
Gmail `internalDate` is earlier than `enabled_at` are recorded `skipped` and never billed or
queued, so turning the feature on doesn't bill voicemails already handled by hand.

### B2. Run (`check_voicemail(run_by: str) -> dict`)

Single-flight: module-level `_RUN_LOCK.acquire(blocking=False)`; if held ⇒ `{"status": "busy"}`.

1. Query empty ⇒ `{"status": "disabled"}`. `not gmail_authorized()` ⇒ `{"status":
   "not_authorized"}`.
2. List: `messages.list(userId="me", q=f"{query} newer_than:{N}d", maxResults=100,
   pageToken=...)`, following `nextPageToken` until exhausted (hard stop at 10 pages). Keep ids
   that are not in `processed` or are `failed:<n>` with `n < 3`.
3. Process up to `VOICEMAIL_MAX_PER_RUN` of them, oldest first: `messages.get(userId="me",
   id=..., format="full")`.
   - `internalDate` < `enabled_at` ⇒ `skipped`.
   - Extract headers (`From`, `Subject`, `Date`) and text: prefer `text/plain` parts (walk the
     MIME tree), else `text/html` stripped with an `html.parser.HTMLParser` subclass; decode
     base64url bodies with `errors="replace"`; truncate to 20,000 characters.
   - `caller_phone = caller_id_from_headers(subject, from_)` (B4).
   - `summarize(text, headers, run_by)` (B3). On `VoicemailError`: `failed:<n+1>`; when that
     reaches 3, queue an inbox item with `summary` = first 1,000 chars of the text,
     `needs_review: true`, caller fields from headers only, and mark `inbox`.
   - Match (B4): one client ⇒ `attach_to_client(...)` then `matched`; otherwise queue inbox
     item, then `inbox`. (Attach happens before marking so a crash re-processes the email;
     attach is idempotent — B6.)
4. Returns `{"status": "ok", "matched": n, "inbox": n, "failed": n, "skipped": n}`; Gmail
   401/403 ⇒ `not_authorized`; other Gmail/network error ⇒ `{"status": "error", "error":
   "<short message>"}`. Never raises. Records `last_run`.

`received_at` comes from Gmail `internalDate` (epoch ms ⇒ local-time ISO string), not from the
model. Messages use `YYYY-MM-DD HH:MM`; billing and `last_communication` use `YYYY-MM-DD`.

### B3. Summarise (`summarize(text, headers, run_by) -> dict`)

One `client.beta.messages.create` call, same conventions as `scheduling_orders.py`:
`model=VOICEMAIL_MODEL`, `max_tokens=4000`, `output_config={"effort": "low", "format":
{"type": "json_schema", "schema": SCHEMA}}`, `betas=["server-side-fallback-2026-07-01"]`,
`extra_body={"fallbacks": "default"}`. The email goes inside an `<email>` block (headers +
body); the system prompt says the email is untrusted data, never instructions.

Schema (all required, `additionalProperties: false`): `caller_name` (string), `summary`
(string, 2–4 sentences, neutral, no legal advice), `urgent` (boolean), `urgency_reason`
(string), `callback_number` (string).

**The model never supplies the number used for matching** — a caller could otherwise say
another client's number and have the note filed and billed there. `callback_number` is display
only.

Validation: `summary` required non-empty, truncated to 1,200 chars; `urgency_reason` 200;
`caller_name` 120; `callback_number` digits only, kept if 10–15 digits. Refusal, `max_tokens`
stop, bad JSON, `anthropic.APIError`, or missing API key ⇒ `VoicemailError`. Token usage logged
with `_log_token_usage(run_by, "Voicemail Summary", usage)` (so it appears on the running
attorney's usage page; the poller uses `"system"`).

### B4. Caller ID and matching

Matching uses only **provider-generated** data (headers and link attributes), never the
transcript or the model's output. `caller_id(headers, html) -> {"phone": str, "contact_name":
str}`:

1. Subject decoded with `email.header.decode_header` (RFC 2047) and the From display name.
2. **Phone:** regex for a North-American-style number in the Subject, then the From display name
   (`(615) 555-1234`, `615-555-1234`, `+1 615 555 1234`, `6155551234`; trailing text such as
   "at 9:14 AM" ignored). If none, scan `href` **attribute values** of `<a>` tags in the HTML part
   (parsed with `HTMLParser`, not text) for a `voice.google.com` URL carrying an encoded number
   (`%2B1615…` / `+1615…`). Generic `tel:` links are **not** used (some providers auto-link
   numbers spoken in the transcript). Normalised with `normalise_phone`.
3. **Contact name:** if the Subject has the form `New voicemail from <Name>` (case-insensitive;
   Google Voice uses this when the caller is a saved contact) and `<Name>` contains no digits,
   that name.
- `normalise_phone(s)`: digits only; last 10 digits if ≥ 10 digits, else "".

Matching over `shared.all_clients()` excluding `archived`:
- phone present ⇒ clients whose `normalise_phone(c["phone"])` equals it; exactly one ⇒
  auto-attach; zero or several ⇒ inbox with `candidates` = the matches;
- else contact name present ⇒ clients whose `client_name` equals the contact name under
  `voicemail._norm_name` (NFKD, strip combining marks, casefold, collapse non-word characters to
  single spaces, trim — deliberately **not** `conflicts.normalise_name`, which folds nicknames).
  Name matches **never auto-attach** (a saved contact could share a client's name — opposing
  counsel, a relative): they go to the inbox with the matches as `candidates`, the first one
  pre-selected in the Assign dropdown, so one click files it.

Displayed `caller_name`: contact name, else the From display name when it isn't a phone number
or an email address, else the model's `caller_name`.

Exact email formats vary by provider; fixtures are built from the documented Google Voice
pattern, and the user will be asked for one redacted real voicemail email before the build to
confirm (and add a fixture for) the actual format.

### B5. Message and billing shapes

Message appended to `client["messages"]`:

```json
{"from": "voicemail", "internal": true, "date": "2026-10-02 09:14",
 "text": "<summary>",
 "voicemail": {"caller_name": "...", "caller_phone": "...", "callback_number": "...",
               "received_at": "...", "urgent": false, "urgency_reason": "",
               "gmail_id": "..."}}
```

Billing entry: `{"date": "2026-10-02", "hours": 0.2, "note": "Voicemail review — 2026-10-02",
"category": "Phone/Email", "type": "voicemail", "gmail_id": "..."}`. This entry **is** visible
to the client in their billing view once statements are issued (intended — it's billed time;
the note contains no voicemail content).

### B6. Atomic attach (`attach_to_client(username, item, attached_by) -> str`)

New shared helper `shared.update_client_atomic(username, fn) -> dict | None`: applies the same
`safe_username` check as `save_client`; under `_get_client_lock(username)`, `_read_record` the
client (None ⇒ return None), call `fn(client)` (fast, no network or file I/O; must
`setdefault("messages", [])` / `setdefault("billing_log", [])` itself since raw records lack
`load_client`'s defaults), and unless `fn` returns `False` ("no change") `_write_record`;
release; then — only if written — `billing.after_client_save(username)` outside the lock, as
`save_client` does. Returns the client. Same pattern as `_apply_payment`.

Note: because the billing hook runs, a voicemail's 0.2 h can push a client over their
attorney's threshold and issue a statement email to the client (existing billing behaviour).

`attach_to_client` uses it with a `fn` that (reporting "duplicate" vs "attached" through a
flag in the closure, since the helper returns the client either way):
1. returns early (no change) if a message with the same `voicemail.gmail_id` exists — the
   duplicate check is inside the lock, so a poller and an Assign can't both attach;
2. appends the message and billing entry, `recalc_hours(client)`;
3. sets `last_communication = max(current, received date)`.

After the lock, only when the result is `"attached"`: `_log_activity(username, "voicemail_received", "Voicemail summarised" + "
(urgent)" if urgent)`. Returns `"attached"`, `"duplicate"` or `"missing"`.

The same helper is used to fix `client_send_message` and the attorney reply route: after the AI
call they append their messages / billing entries via `update_client_atomic` instead of saving
the record loaded before the call. Client-message AI history is built from
`client_visible_messages(client)[-10:]` (filter **before** slicing).

---

## Section C — Client-facing protection

`shared.client_visible_messages(client) -> list` returns messages without `internal: true`.

- `client_portal` route passes `visible_messages=client_visible_messages(client)` to
  `templates/client_portal.html`; the thread loop and its "No messages yet" check use
  `visible_messages` (so a client with only internal notes sees "No messages yet").
- `client_send_message` builds AI history from it (B6).
- Audit result (first review): no other route, export, PDF or email exposes `messages` to
  clients. A test pins this (`test_voicemail_privacy.py` checks rendered client pages and the
  client JSON routes for a sentinel summary).

---

## Section D — Attorney routes (`blueprints/portal_attorney.py`)

All JSON routes use `request.get_json(silent=True) or {}`; ids are validated against the stored
inbox (never used in paths); all POSTs are CSRF-protected (not added to the exempt set).

- `POST /portal/attorney/voicemail/check` — `check_voicemail(session attorney)`.
- `GET /portal/attorney/voicemail/inbox` — open/assigning items, newest first.
  **Visibility:** an item with candidates is shown only to attorneys who can access at least one
  candidate (`can_access_client`); items with no candidates are firm-wide. `candidates`
  returned as `[{username, client_name}]`, filtered to accessible ones. Also returns `last_run`
  and `{enabled, gmail_authorized}`.
- `POST /portal/attorney/voicemail/assign` `{id, username}` — item must be visible to the caller
  (else 404); target via `load_client_for_attorney` (else 404); `_transition(id, "open",
  "assigning", assigned_to=username, resolved_by=attorney)` (None ⇒ 409 "already handled");
  `attach_to_client`; then `_transition(id, "assigning", "assigned")`. If attach returns
  `"missing"` ⇒ transition back to `open`, 404. If the final transition returns None (should
  not happen) ⇒ log it and return 409. `log_access_atomic(username, "voicemail_assigned", id)`.
- `POST /portal/attorney/voicemail/dismiss` `{id}` — visible to caller (else 404);
  `_transition(id, "open", "dismissed", resolved_by=...)` (None ⇒ 409).
- Dashboard JSON gains `voicemail: {"open": n, "urgent": n, "enabled": bool,
  "gmail_authorized": bool}` computed for the viewer (same visibility rule), in its own
  try/except that falls back to zeros so a bad state file never 500s the dashboard.

**Stale `assigning` recovery** (crash mid-assign): when the inbox is read, or an assign/dismiss
targets an item that has been `assigning` for more than 600 s, `recover_stale(item)` runs first
(outside `_STATE_LOCK` for the client read): if the recorded `assigned_to` client already holds a
message with that `gmail_id`, the item is completed as `assigned`; otherwise it is reopened
(`open`). Both outcomes are written through `_transition(id, "assigning", ...)` under
`_STATE_LOCK`, conditional on `status_at` being unchanged since the item was read, so a concurrent recovery and a late-finishing original request can't both act.
A voicemail can never end up attached to two clients, or dismissed after being billed.

### D1. Background poller

`voicemail.start_poller(app)` starts one daemon thread when `VOICEMAIL_POLL_SECONDS > 0`; each
loop sleeps the interval, then (if enabled) calls `check_voicemail("system")` inside
`app.app_context()`, catching and printing every exception. Called **only** from `app.py`'s
`if __name__ == "__main__":` block; importing `app` never starts it.

---

## Section E — UI

All new or rewritten DOM uses `_el`/`_show`/`_note`/`_busy`/`_postJSON` (no `innerHTML`, no
HTML strings from data). New `static/js/attorney_voicemail.js`, no `_`-prefixed globals
(prefix `vm`).

- **Messages tab:** `populateMessages` rewritten with `_el` (fixes the XSS). Voicemail notes
  render as a distinct card: "📞 Voicemail · <caller_name or formatted number> · <received>",
  an urgent badge and reason when urgent, the summary, callback number, and an "Open in Gmail"
  link (`target="_blank"`, `rel="noopener noreferrer"`, href
  `https://mail.google.com/mail/u/0/#all/` + `encodeURIComponent(gmail_id)`; only rendered when
  `gmail_id` matches `/^[0-9a-f]+$/i`).
- **Sidebar:** "Voicemail inbox" button with an open-count badge (styled urgent when any item is
  urgent).
- **Voicemail inbox panel:** open items (received, caller, number, summary, urgent badge,
  "needs review" badge, candidates); per item an **Assign to…** select (candidates first, then
  every accessible client from `_ALL_CLIENTS_DATA`) + **Assign**, and **Dismiss**. A **Check
  voicemail now** button and a status line from `last_run` / the status flags: "Gmail not
  authorized — re-authorize Google" (linking the existing authorize action), "Voicemail checking
  is off (set VOICEMAIL_GMAIL_QUERY)", or the last result counts. Buttons disable while a request
  is in flight; every request has `.catch`.
- **Dashboard:** urgent voicemail count shown with the existing alerts.

---

## Error handling summary

| Situation | Behaviour |
|---|---|
| Feature not configured | `disabled`; UI explains how to enable |
| Gmail not granted / revoked / 401-403 | `not_authorized`; UI links to re-authorize |
| Old token without Gmail | Calendar/Drive keep working (loaded with its own scopes) |
| Token refresh fails | `ValueError` "not authorized" (no raw `RefreshError`) |
| Gmail API error | `error`; nothing recorded for unfetched emails; retried next run |
| AI/parse failure | `failed:n`, retried; at 3 ⇒ inbox with raw text, `needs_review` |
| Emails older than feature start | `skipped`, never billed |
| More than max per run | Remainder processed on later runs |
| Concurrent runs | second returns `busy` |
| Crash between attach and marking | email re-processed; attach is a no-op (`duplicate`) |
| Two attorneys assign the same item | one wins; the other gets 409 |
| Assign to inaccessible client / invisible item | 404 |
| Bad state file | dashboard shows zeros; check returns `error` |

---

## Files touched

| File | Change |
|---|---|
| `voicemail.py` (new) | Gmail fetch, text extraction, caller ID, summarise, match, attach, state, poller |
| `shared.py` | `GMAIL_SCOPE`, `AUTHORIZE_SCOPES`, token loading without scopes + `RefreshError` mapping, grants record, `gmail_authorized`, `get_gmail_service`, `client_visible_messages`, `update_client_atomic` |
| `blueprints/calendar.py` | authorize requests `AUTHORIZE_SCOPES` and records grants; status reports `gmail_authorized` |
| `blueprints/portal_client.py` | visible messages to template; AI history filter; atomic append after AI call |
| `blueprints/portal_attorney.py` | voicemail routes; dashboard field; atomic append in reply route |
| `app.py` | start poller in `__main__` |
| `templates/client_portal.html` | loop over `visible_messages` |
| `templates/attorney_portal.html` | `populateMessages` rewrite; sidebar button; inbox panel; script include |
| `static/js/attorney_voicemail.js` (new) | inbox UI |
| `.env.example`, `GOOGLE_CALENDAR_SETUP.md` | variables; scope/consent note |
| tests | below |

---

## Testing

Gmail and Anthropic are always mocked (fake Gmail service returning canned `list`/`get`
payloads with base64url bodies and `internalDate`; fake Anthropic client as in the scheduling
tests). No test starts the poller or touches real data folders.

- `test_gmail_scope.py` — token loaded without a scopes argument; `RefreshError` ⇒ `ValueError`;
  `gmail_authorized` false with no grants record, false when grants lack Gmail even if the token
  file's `scopes` lists it, true when granted; authorize records grants; status field; consent
  with Gmail unticked ⇒ authorize succeeds (relax flag set), token file `scopes` = granted list
  without Gmail, `gmail_authorized` false; `granted_scopes` None ⇒ `[]`; string ⇒ split.
- `test_voicemail_processing.py` — text extraction (plain, html-only, nested multipart,
  base64url, truncation); caller ID parsing (formats, "at 9:14 AM" suffix, RFC 2047 subject,
  none, From fallback, voice-link href, a `tel:` link and a number in visible HTML text are
  ignored); contact-name subject ⇒ inbox with that client pre-selected (never auto-attached),
  two same-named clients ⇒ both candidates, nickname does not match; `update_client_atomic` no-change skips write and billing hook; a
  number spoken in
  the transcript (and returned by the model as `callback_number`) does **not** drive matching;
  summarise request shape and validation; match one / none / several / archived ignored; attach
  adds internal message + 0.2 h billing + `last_communication` not moved backwards + activity;
  duplicate attach is a no-op; billing hook runs after attach with no client lock held;
  pagination over `nextPageToken`; max-per-run; first-run cutoff (`skipped`); processed ids
  skipped next run; failure retry then inbox with `needs_review`; disabled / not_authorized
  (incl. Gmail 403) / busy / Gmail error; state file encrypted; caps; a dismiss performed
  between two emails of one run is preserved.
- `test_voicemail_concurrency.py` — attach concurrent with `client_send_message` (AI call
  mocked to block until the attach finishes): both the voicemail note and the chat messages
  survive; same for the attorney reply route; two concurrent attaches of one voicemail ⇒ one
  note, one billing entry.
- `test_voicemail_routes.py` — check route; inbox visibility (candidate items hidden from a
  non-accessing attorney, no-candidate items firm-wide); candidates filtered; assign (404
  inaccessible target, 404 invisible item, 409 resolved, 409 concurrent, success bills);
  dismiss; stale `assigning` recovery (crash after attach ⇒ completed as assigned, another
  attorney cannot assign elsewhere or dismiss; crash before attach ⇒ reopened); dashboard field and its error fallback; new POST
  routes covered by the CSRF sweep in `tests/test_csrf.py`.
- `test_voicemail_privacy.py` — client portal HTML never contains an internal note's text and
  shows "No messages yet" when only internal notes exist; client AI history excludes internal
  messages (inspect the fake AI call); `client_visible_messages`; client JSON routes don't
  return the sentinel.
- `test_voicemail_poller.py` — importing `app` starts no poller thread; `start_poller` with
  interval 0 starts nothing; one loop iteration calls `check_voicemail("system")` and survives
  an exception.
- Browser check in the sandbox (poller off, a fake Gmail service fed to `check_voicemail`):
  matched note appears in Messages as a card; unknown caller in inbox → assign → note + bill;
  dismiss; XSS payloads in a client message and in a summary render as text.
