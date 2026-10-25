# Scheduling-Order Upload & Case Dates — Design Spec

**Date:** 2026-10-02
**Status:** Approved (two review passes)
**Sub-project:** 3 of 5 in the portal-functionality roadmap (1 security, 2 billing statements — shipped)

---

## Overview

When an attorney uploads a court scheduling order, the app reads it with Claude and pre-fills
five case dates — **First Discussion, Second Discussion, Motions deadline, Pre-Trial
Conference, Trial** — on a review panel. The attorney corrects anything wrong and confirms;
only then are the dates saved to the client, shown on the dashboard Master Calendar and
deadlines list, and pushed to Google Calendar (when connected). An amended order replaces the
dates (updating, not duplicating, Google events) and the prior set is kept in history.

### Decisions made during brainstorming

| Question | Decision |
|---|---|
| Destination | App calendar (client record + dashboard) **and** Google Calendar when connected |
| Extraction | Claude reads the file and pre-fills; **an attorney must confirm** before anything is saved |
| Amended orders | Replace the dates, move existing Google events, keep a history of prior sets |

Out of scope: dates other than the five; recurring/relative deadlines ("30 days after…") beyond
what Claude resolves to an absolute date with evidence; client-portal display of these dates;
reminders/notifications.

---

## Section A — Data model (client record)

Two new fields, defaulted by `load_client` (`case_dates` → `{}`, `case_dates_history` → `[]`):

```json
"case_dates": {
  "first_discussion":  {"date": "2026-11-04", "gcal_event_id": "abc", "source": "Smith_Order.pdf",
                        "confirmed_by": "SophiaH", "confirmed_at": "2026-10-02T14:05:11"},
  "second_discussion": { ... },
  "motions":           { ... },
  "pretrial":          { ... },
  "trial":             { ... }
},
"case_dates_history": [
  {"replaced_at": "2026-12-01T09:00:00", "replaced_by": "SophiaH",
   "previous": { ...the whole prior case_dates object... }}
]
```

- Keys are exactly `first_discussion`, `second_discussion`, `motions`, `pretrial`, `trial`
  (constant `CASE_DATE_KINDS`, with display labels "First Discussion", "Second Discussion",
  "Motions Deadline", "Pre-Trial Conference", "Trial").
- A kind absent from `case_dates` has no date. Clearing a date on save removes the key (and its
  Google event, see C3).
- `case_dates_history` is capped at the 20 most recent entries.
- Both fields are attorney-facing. They are **not** added to `shared._PRIVATE_CLIENT_FIELDS`
  (attorneys need them in the client GET); no client-portal route sends them (the client portal
  renders individual fields, not the record).

`next_court_date` is unchanged and independent.

---

## Section B — Extraction (`scheduling_orders.py`, new module)

### B1. Interface

```python
SCHEDULING_ORDER_MODEL = os.getenv("SCHEDULING_ORDER_MODEL", "claude-opus-5-5")
MAX_BYTES = 20 * 1024 * 1024        # base64 inflates ~4/3; API request cap is 32 MB
SUPPORTED_EXTS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt"}

class ExtractionError(Exception): ...   # message is shown to the attorney

def extract_case_dates(path: Path) -> dict
```

The function does no logging and takes no username; it returns the API `usage` so the route
can log tokens against the session attorney.

Returns:

```python
{
  "dates": {
    "first_discussion":  {"date": "2026-11-04" | None, "page": 2 | None,
                          "evidence": "short verbatim quote" | "", "confidence": "high"|"medium"|"low"},
    ... one entry for each of the five kinds ...
  },
  "notes": "free-text caveats from the model, e.g. 'trial date is subject to court availability'",
  "model": "<model id that answered>",
  "usage": <the response usage object; the route logs it and strips it before responding>,
}
```

Raises `ExtractionError` with a user-readable message for: unsupported extension, file over
`MAX_BYTES`, empty DOCX text, no API key (`shared.get_anthropic_client()` raises `ValueError`),
API errors — catch `anthropic.APIError` (the base class of rate-limit / server / connection
errors; it exists in the test stub too) with the message "The AI reader is unavailable right
now; enter the dates manually." A 400 whose message mentions pages gets "This document has too
many pages for the AI reader; enter the dates manually." Also: refusal, `max_tokens`
truncation, or a response that fails validation (B3 below).

### B2. Request

- Client: `shared.get_anthropic_client()` (existing). Uses `client.beta.messages.create` so the
  refusal fallback can be enabled: `betas=["server-side-fallback-2026-07-01"]` and
  `extra_body={"fallbacks": "default"}` — the installed SDK (0.84.0) has no `fallbacks`
  keyword, so it must go through `extra_body` (passing it as a kwarg raises `TypeError`).
- `model=SCHEDULING_ORDER_MODEL`, `max_tokens=16000` (adaptive thinking counts against it),
  `output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}`. No `thinking` parameter (Opus 5.5
  thinks adaptively by default). No assistant prefill; no forced `tool_choice`.
- Content by file type:
  - `.pdf` → `{"type": "document", "source": {"type": "base64", "media_type":
    "application/pdf", "data": <b64, no newlines>}}` (handles scanned PDFs).
  - `.png/.jpg/.jpeg` → `{"type": "image", "source": {"type": "base64", "media_type": ...}}`.
  - `.docx` → text via `mammoth.extract_raw_text` (tests monkeypatch it; the test stub has
    no such attribute), sent as a text block wrapped in
    `<document>…</document>`; `page` is always `null` for DOCX.
  - `.txt` → read as UTF-8 text, same wrapping.
  - The document block comes **before** the instruction text block.
- System prompt (constant `SYSTEM_PROMPT`): explains the five kinds and common court synonyms —
  first discussion ≈ initial/Rule 16/status/case-management conference or first discussion;
  second discussion ≈ second/follow-up status conference; motions ≈ dispositive / pretrial
  motions deadline; pretrial ≈ final pretrial conference; trial ≈ trial date / trial setting /
  jury selection. Rules: return a date only if the document states it (or states it
  unambiguously, e.g. "the week of" → first day, flagged `low`); never infer from typical
  timelines; ISO `YYYY-MM-DD`; evidence must be a verbatim quote ≤ 200 chars; page is the
  1-based PDF page; if several candidates exist for a kind, pick the controlling one and
  explain in `notes`.

### B3. Schema and validation

`SCHEMA` (strict JSON schema, `additionalProperties: false`, all keys `required`): object with
`dates` (object with the five keys, each `{date: string|null, page: integer|null, evidence:
string, confidence: enum["high","medium","low"]}`) and `notes` (string).

After the call:
1. If `stop_reason == "refusal"` ⇒ `ExtractionError("The AI reader declined this document; enter the dates manually.")`.
2. If `stop_reason == "max_tokens"` ⇒ `ExtractionError("The AI reader's answer was cut off; enter the dates manually.")`.
3. Take the first `text` block, `json.loads` it.
4. Validate each date with `datetime.strptime(d, "%Y-%m-%d")`; an unparseable date becomes
   `None` with confidence `low` and a note appended. Dates before 2000-01-01 or after
   2100-12-31 are treated the same way.
5. Truncate `evidence` to 200 chars and `notes` to 1,000.
6. Return `usage`; the extract route calls `shared._log_token_usage(session attorney,
   "Scheduling Order Extraction", usage)` and removes `usage` from the JSON response.

Never returns raw model text to the browser except through these validated fields.

---

## Section C — Routes and flow (`blueprints/portal_attorney.py`)

### C1. Documents category

Add `"Scheduling Orders"` to `shared.DOCS_CATEGORIES` (after "Court Orders"). Allowed extensions
are the existing set. The Documents tab gains the category tab button. Because the client
portal builds its document tabs from `DOCS_CATEGORIES` (as it already does for "Court Orders"),
clients will see and can download their scheduling orders — intended, same as court orders.

### C2. Extract

`POST /portal/attorney/scheduling-order/extract` `{username, filename}` — access via
`load_client_for_attorney` (assigned or co-counsel); file resolved with the existing
`_resolve_doc_path(username, "Scheduling Orders", filename)` (404 if missing).
Calls `extract_case_dates(path)`.

- Success ⇒ `{success: true, extraction: <B1 result>, current: <client.case_dates>}`.
- `ExtractionError` ⇒ **200** with `{success: false, error: "<message>", current: ...}` so the
  UI opens the panel for manual entry.
- `log_access_atomic(client["username"], "scheduling_order_read", path.name)` (sanitised values).

The upload route itself is unchanged; the UI calls extract after a successful upload into the
"Scheduling Orders" category, and a **Read dates** button on each file in that category re-runs
it.

### C3. Confirm

`POST /portal/attorney/scheduling-order/confirm`
`{username, filename, dates: {kind: "YYYY-MM-DD" | "" ...}}` — same access check. Only the
`dates` strings, `username` and `filename` are read from the body; anything else is ignored.

1. Validate: body and `dates` must be objects; unknown kinds rejected (400); each value `""` or a
   valid ISO date in range (400 `"Invalid date for <Label>."`). `filename` must resolve via
   `_resolve_doc_path(..., "Scheduling Orders", filename)` (404 otherwise); from here on use
   `source = path.name` (sanitised), never the raw request value.
2. **Diff** on dates only: `old = {kind: entry["date"]}` from `case_dates`; `new = {kind: value}`
   for non-empty values. If `old == new` ⇒ return `{success: true, case_dates, warnings: [],
   unchanged: true}` — no Google calls, no history, no billing.
3. **Google first, outside any client lock** (they can take seconds). For each kind whose date
   changed:
   - new set & old has `gcal_event_id` ⇒ `gcal_update_all_day` → `"ok"` keep the id; `"gone"`
     ⇒ `gcal_create_all_day`, use the new id (or `null` if that fails); `"error"` ⇒ keep the
     old id, warn;
   - new set & no old event ⇒ `gcal_create_all_day` (id or `null`);
   - new empty & old has event ⇒ `gcal_delete_event`; `"error"` ⇒ warn that the event may be
     left behind.
   Remember every event id **this request created** (for rollback in step 4). Google failures
   never fail the save. If Google isn't connected at all, return a **single** warning
   ("Google Calendar not connected — dates saved in the app only") rather than one per kind.
   Unchanged kinds are not touched (no Google call; keep their stored entry, including the
   original `confirmed_*`).
4. **Then re-load the client** (`load_client_for_attorney` again; 404 if it vanished) and check
   it hasn't changed underneath us: compare `{kind: (date, gcal_event_id)}` of the re-loaded
   `case_dates` with the snapshot from step 2. If they differ (someone else confirmed in
   between) ⇒ delete the events this request created (best effort), and return **409**
   `{"error": "These dates were just changed by someone else. Reload and try again."}`.
   Otherwise apply the changes and save right away. (This is two separately locked steps, a
   re-load and a `save_client`, like the rest of the app — the window is now milliseconds, not
   the seconds the Google calls take, which is acceptable.)
   - push `{replaced_at, replaced_by, previous: <case_dates as loaded now>}` onto
     `case_dates_history` (cap 20) when `case_dates` was non-empty;
   - set each changed kind to `{date, gcal_event_id, source, confirmed_by, confirmed_at}`;
     remove cleared kinds;
   - append billing `{"date": today, "hours": 0.2, "note": "Scheduling order review — <source>",
     "category": "Filing", "type": "scheduling_order"}` and `recalc_hours` (this may push unbilled
     time over the threshold; the billing hook then issues a statement as designed);
   - `_log_access(client, "case_dates_confirmed", source)`; `save_client`;
   - then `_log_activity(username, "case_dates_updated", "Case dates updated from <source>.")`.
5. Response: `{success: true, case_dates, warnings: [...]}`.

### C4. Google Calendar helpers (`shared.py`)

Generalise the existing `_push_court_date_to_gcal` pattern into three helpers that return
`None`/`False` on any failure or when Google isn't connected (never raise):

```python
def gcal_create_all_day(summary: str, description: str, date_str: str) -> str | None
def gcal_update_all_day(event_id: str, summary: str, description: str, date_str: str) -> str
    # returns "ok" | "gone" (HTTP 404/410: event no longer exists) | "error" (anything else,
    # including Google not connected)
def gcal_delete_event(event_id: str) -> str
    # returns "ok" | "gone" | "error"
```

Summary: `"<Label>: <client name>"`; description: `"<Label> for <client name> — from <source> — Endo-Legal"`.
`_push_court_date_to_gcal` is left as-is (no refactor in this project).
Only an update result of `"gone"` leads the route to recreate the event. On `"error"` the route
**keeps the old `gcal_event_id`** (the event still exists, just with the old date) and adds a
warning "Google Calendar event for <Label> could not be moved — update it manually". A delete
`"error"` means the event may be left behind: the warning says so and names the date.

### C5. Dashboard

`portal_attorney_dashboard` adds every accessible client's `case_dates` to:
- `calendar_events` as `{date, date_display, time: "", client_name, username,
  type: "Court Date", matter: <Label>}` — `type: "Court Date"` reuses the existing court-date
  pill styling in `renderMonthCal`, and the label shows in the tooltip via `matter`;
- `deadlines` when within 0–90 days, same shape as court-date deadlines with `charges` = Label.

To avoid duplicates, collect the set of `gcal_event_id`s from all `case_dates` and skip any
Google event whose `gev["gcal_id"]` is in that set — in **both** Google loops (calendar and
deadlines). (The deadlines Google loop already ignores summaries without court/meeting
keywords; that is unchanged.)

### C6. Client GET

`case_dates` and `case_dates_history` are part of the attorney client record (no change needed
beyond the `load_client` defaults).

---

## Section D — UI (`templates/attorney_portal.html`, new `static/js/attorney_schedule.js`)

Same rules as projects 1–2: build DOM with the shared `_el` helpers (no `innerHTML`, no HTML
strings from data), reuse `_stale`/`_busy`/`_postJSON`, define no `_`-prefixed globals.

- **Documents tab:** "Scheduling Orders" category button. `renderDocList` currently builds rows
  as HTML strings; it is **rewritten with `_el`** (same columns and buttons as today) so the new
  **Read dates** button (shown only for files in "Scheduling Orders") follows the no-innerHTML
  rule. After a successful upload in this category, the review panel opens automatically for the
  file **named in the response** (`d.file.name` — the server may rename it, e.g. `order_2.pdf`).
- **Review panel** (modal or inline card `#sched-review`): title with the filename; a spinner
  "Reading the order…" while extracting; then five rows, each:
  `Label · [date input] · old date (if any) → shown as "was 2026-11-04" · confidence chip ·
  evidence quote (page N)`. A banner with `notes` when present; a banner with the error when
  extraction failed ("Enter the dates manually."). Buttons **Save to calendar** (disabled while
  busy) and **Cancel**. Low-confidence rows are highlighted.
- **Case Overview tab:** a **Case dates** card listing the five dates (or "—"), each with its
  source filename; a small "History (N)" toggle showing prior sets (date-only).
- After save: show warnings (e.g. "Google Calendar not connected — dates saved in the app only"),
  refresh the client, and refresh the dashboard calendar if it's loaded.

---

## Error handling summary

| Situation | Behaviour |
|---|---|
| No API key / API error / refusal / truncation / bad JSON | Panel opens empty with the reason; manual entry still possible |
| Unsupported type / too large / empty DOCX | Same, with the specific reason |
| Invalid date or unknown kind on confirm | 400 with message; nothing saved |
| Google not connected | Saved in app; warning returned |
| Google event missing on update (`"gone"`) | Recreated; new id stored |
| Google error on update | Saved in app; **old event id kept**; warning "could not be moved" |
| Google error on create | Saved in app; `gcal_event_id: null`; warning |
| Google error on delete | Date removed in app; warning that the event may be left behind |
| Someone else confirmed in between | 409; events this request created are deleted; nothing saved |
| Other attorney | 404 (access check) |

---

## Privacy

The scheduling-order file (and nothing else from the client record) is sent to the Anthropic
API, consistent with the app's existing AI research features. Token usage is logged as today.

---

## Files touched

| File | Change |
|---|---|
| `scheduling_orders.py` (new) | Extraction: request building, schema, validation |
| `shared.py` | `DOCS_CATEGORIES` + "Scheduling Orders"; `case_dates` defaults; Google helpers |
| `blueprints/portal_attorney.py` | extract & confirm routes; dashboard integration |
| `templates/attorney_portal.html` | category button, `renderDocList` rewritten with `_el`, review panel markup, Case dates card, script include |
| `static/js/attorney_schedule.js` (new) | Review panel, Read dates, confirm, Case dates card |
| `.env.example` | `SCHEDULING_ORDER_MODEL=claude-opus-5-5` |
| tests | see below |

---

## Testing

The Anthropic client is always mocked (no network in tests): monkeypatch
`shared.get_anthropic_client` (and therefore `scheduling_orders`' use of it) to return a fake
whose `beta.messages.create` records kwargs and returns a canned response. Google Calendar is
mocked by monkeypatching `gcal_create_all_day` / `gcal_update_all_day` / `gcal_delete_event`
in the `blueprints.portal_attorney` namespace (it imports them by name); `GOOGLE_LIBS` is False
in tests, so the real helpers would return None.

- `test_scheduling_extraction.py` — request shape per file type (PDF document block first,
  image block, DOCX text, txt), model id from env, the fallback beta in `betas` and
  `extra_body == {"fallbacks": "default"}`, `output_config` format present, `max_tokens` 16000,
  no `thinking` param; parsing a well-formed response; unparseable/out-of-range
  dates nulled with a note; refusal / max_tokens / bad JSON / API error / no key ⇒
  `ExtractionError` messages; size and extension limits; evidence/notes truncation; token usage
  logged.
- `test_scheduling_routes.py` — access (other attorney 404, co-counsel allowed); extract success
  and failure shapes; confirm validation (unknown kind, bad date, missing file); confirm saves
  dates, history on change, identical re-save ⇒ `unchanged` with no history/billing/Google
  calls, cap 20, billing 0.2 h with a date, access log, activity, `source` is the sanitised
  name, extra body fields ignored; a concurrent write between the Google calls and the save is
  preserved (simulate by writing a message inside the mocked Google call); a concurrent
  *confirm* in that window ⇒ 409 and the created events are deleted; update `"error"` keeps the
  old id and warns, `"gone"` recreates; not-connected yields exactly one warning; Google create/update/delete paths incl. not-connected, failure, and missing-event
  recreate; sweep test still passes.
- `test_scheduling_dashboard.py` — case dates appear in calendar and in 90-day deadlines; Google
  events already represented are not duplicated.
- Browser check in the sandbox with the extractor monkeypatched to return fixed dates: upload →
  panel → edit → save → dashboard; amended order shows "was …"; XSS check with a malicious
  evidence string.
