# Self-Hosted License Productization — Design Spec

**Date:** 2026-09-04
**Status:** Approved (revised after spec review)
**Approach:** Sell one install by hand, then extract the patterns

---

## Overview

Turn the law office app from a single-firm practice site into a self-hosted product sold to
solo attorneys, with a low license fee plus a paid setup and customization engagement.

The app is already a product in feature terms: public marketing site with AI intake chat and
lead capture, a client portal (documents, secure messages, billing, Stripe and Coinbase
payments), an attorney portal (client records, time and billing entries, document vault,
insights and tax export, AI research, drafting, issue-spotting, case search, conflict-of-interest
checks), plus Google Calendar and Drive integration. Comparable hosted tools charge $60–150 per
user per month.

Its single-tenant, no-cloud, file-on-disk design is the product's wedge rather than its
limitation. Client files never leave the office: no third-party custodian, no cloud vendor
subpoena exposure, a simpler conversation about privilege and state bar confidentiality duties.
Hosted competitors cannot make that claim.

This spec covers only what must be true before the app can safely be placed in another
attorney's hands, plus the playbook for doing so repeatably. It deliberately does not
productize the install.

**Scope note:** Sections 1 and 2 are independent subsystems sharing no code. They become two
implementation plans, executed in the order given under Build Order.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sales model | Self-hosted license | No hosting liability, no third-party PII custody, matches the existing local-first architecture |
| Revenue | Low license fee (~$199) + paid setup/customization ($500–1500) | Highest revenue per customer; turns install friction into a billable line item rather than a bottleneck |
| Target buyer | Solo attorneys | The app already assumes exactly one practising attorney; `ATTORNEYS` supports more if needed |
| Customer #1 | Tennessee criminal defense attorney | Jurisdiction is hardcoded into the AI prompts, a statewide court dataset, and the clerk-lookup URLs; this buyer needs none of it reworked |
| AI access | Optional, buyer supplies their own Anthropic key | No proxy server, no token costs, no privileged data crossing our infrastructure |
| AI absent | App degrades gracefully; AI surfaces hidden | Protects install rate. Requires work — see Section 2 item 7; it is not true today |
| Sequencing | Sell one by hand, then extract config | Real customer feedback defines the config boundary instead of guesswork |
| Data store | Unchanged — flat JSON on disk | Adequate for one solo firm; a rewrite would consume weeks and be invisible to customers |
| Backup archive | AES-encrypted zip via `pyzipper` | The archive holds every client file and every password hash; encryption at rest is a confidentiality story worth one dependency |
| Export archive | Unencrypted | Authenticated session download whose entire purpose is immediate portability |

### Rejected

**Proxying AI through our own server.** It would smooth onboarding and justify a subscription,
but it routes privileged client matters through infrastructure we own. That contradicts the
core sales pitch and creates real compliance exposure in a regulated profession.

**Building the config layer first.** Two to three weeks of construction for customers who do
not exist yet, guessing at what needs to be configurable. The hand-built first install produces
that answer for free.

---

## Section 1 — Backup and Export

There is no backup mechanism anywhere in the app today. The only copy operation in the codebase
is a `shutil.copytree` inside `scripts/hash_existing_passwords.py:74`, a one-off migration.
A firm's entire practice would live in loose JSON files in one folder on one laptop with no
snapshots and no export. Across ten installs, an eventual drive failure is close to certain, and
in a profession with file-retention duties the consequence is a bar complaint and a lawsuit
rather than a support ticket. This is the gate on every other item in this spec.

### Scope

Back up `client-data/`, `client-files/`, `client-accounts/`, `leads/`, `draft-history/`,
`research-history/`, `case-searches/`, `token-usage/`, and `page-visits.json`.

`client-data/` is durable, not derived, despite intake also writing into
`client-files/<user>/documents/Intake/`. The JSON holds a 15-field structured record; what lands
in `Intake/` is a rendered PDF (`blueprints/intake.py:198-207`) with an HTML fallback, and that
write sits inside a bare `try/except Exception: pass`, so it can silently produce nothing. The
record is not reconstructible from the artifact and may have no artifact at all. It stays in
scope.

Also include the three secret files, all of which `.gitignore` lists at lines 2–4:

- `.env` — holds the attorney password hashes as `ATTORNEY_*_HASH`. An archive that cannot
  restore logins is not a backup.
- `credentials.json` — the Google OAuth client. Not regenerable by the attorney unaided.
- `calendar-token.json` — the Calendar/Drive grant. Regenerable, but only by repeating the
  OAuth flow, which is exactly the kind of task a restore should avoid.

### Destination

A `BACKUP_DIR` setting. The default must not be `./backups`: that path sits inside the git
working tree, `.gitignore` has no `backups/` entry, and the result would be encrypted archives
of all privileged client data staged for commit alongside directories the repo carefully
excludes one by one. Default to a sibling directory outside the tree, and add `backups/` to
`.gitignore` as a second line of defence.

Setup then repoints it at an external drive or synced folder, and the setup checklist treats an
off-disk destination as mandatory. A backup on the same disk as the original protects against
mistakes, not hardware failure.

### Schedule

On startup and once daily from a background thread, but skipped when a successful backup already
exists within the last 12 hours. Without that guard, retention and the startup trigger fight each
other: a machine rebooted 30 times in one day would silently evict a month of history.

A "Back up now" button in the attorney portal displays the last successful backup time. The
visible timestamp is the point — silent backups that stopped months ago are the standard failure
mode.

### Writes

The backup acquires the per-client locks from `_get_client_lock` (`shared.py:225`) while reading
**`client-accounts/`**, so a backup taken mid-write cannot capture a torn JSON file. That is the
directory those locks actually protect — `load_client` (`shared.py:232`) and `save_client`
(`:258`) both operate on `CLIENT_ACCOUNTS_DIR`, and it is the hot one, mutated on every billing
entry, message, payment, and note.

`client-data/` has no lock available: `blueprints/intake.py:93` writes it with a bare
`open(..., "w")`, and that is its only writer. The backup cannot serialise against it, so a
backup taken during an intake submission could in principle capture a partial record. The
exposure is genuinely small — one writer, write-once, never updated — and it is accepted rather
than fixed, since adding a lock to a single write-once path is not worth the coupling.

Note also that `_FCNTL_AVAILABLE` is false on Windows, so the `flock` layer inside those helpers
is a no-op here and only the in-process `threading.Lock` applies. The backup therefore has to run
as a thread inside the app process, not as a separate scheduled script.

Write the archive to a temporary file and atomically rename it into place, so a crash mid-write
never leaves a truncated archive as the most recent one. Retain the last 30 and delete older.

### Encryption and the passphrase

The archive is AES-encrypted with `BACKUP_PASSPHRASE`, read from `.env` because the background
thread needs it unattended at every backup.

That creates an obvious trap: the passphrase's only copy would live inside the very archive it
decrypts. So setup has a mandatory, explicit step — **the passphrase is recorded off-machine**
(password manager, or written and kept with the firm's other critical credentials) and the
checklist is not complete until that is confirmed. `scripts/restore.py` prompts for it rather
than reading `.env`, since during a real restore no `.env` exists yet.

### Restore

No restore UI. A documented procedure (stop the app, run the script, restart) plus
`scripts/restore.py`, which prompts for the passphrase, decrypts, and unpacks behind a
confirmation prompt. Setup is a hands-on engagement; the rare restore can be too.

### Export

A "Download all my data" control in the attorney portal that streams an **unencrypted** zip of
the same content, minus `.env`, `credentials.json`, and `calendar-token.json` — those are
machine secrets, not the attorney's records.

**Excluding those three files is not sufficient.** Every record in `client-accounts/` carries a
`password` field (written by `blueprints/auth.py:82` and `blueprints/intake.py:116`), and today
most of them are not hashed — see Section 2 item 8. An export that shipped `client-accounts/`
verbatim would stream live client passwords through a browser download in an unencrypted zip,
which is strictly worse than the `.env` it excludes for exactly that reason.

So the export path strips `password` and `must_change_password` from every `client-accounts/`
record before writing it into the archive, with a test asserting no `password` key survives.
This applies to the export only. The backup archive keeps those fields, because it must be able
to restore logins and it is encrypted.

It is delivered over an authenticated session, and its whole purpose is that the contents are
immediately usable. "You can leave at any time and take everything with you" is a sales asset as
much as a feature, and a passphrase-locked archive the attorney may not have to hand defeats it.

### Verification

A round-trip test: seed a data directory, back up, wipe, restore, assert the resulting tree is
byte-identical. A second test asserts the lock is held during the `client-accounts/` read, since
the round-trip test alone has nothing writing concurrently and would pass despite torn writes. A
third, specified under Export above, asserts no `password` key survives into an export archive.

---

## Section 2 — Security Pass

### Already correct — do not disturb

`_resolve_doc_path` (`blueprints/portal_attorney.py:244`) sanitizes both username and filename
and validates the category against `DOCS_CATEGORIES`, so the document routes are not
traversable. Uploads enforce an extension allowlist and de-duplicate name collisions. Password
*handling* is correct — bcrypt via `hash_password`, with an upgrade path for legacy values —
though the stored data is not, which is item 8 below rather than a flaw in this code.

### Must fix before third-party client data is present

**1. No CSRF protection anywhere.** Every state-changing route is a cookie-authenticated POST
with no token. An attorney with the portal open who visits a malicious page can have their
browser silently issue `create-client`, `archive-client`, `delete-document`, or `billing-entry`
requests. Introduce Flask-WTF `CSRFProtect` and add the token to the existing fetch calls.

Three things size and constrain this item:

- **The payment webhooks must be exempted.** `/webhooks/stripe`
  (`blueprints/portal_client.py:194`) and `/webhooks/coinbase` (`:283`) are unauthenticated
  external POSTs carrying their own signature headers. `CSRFProtect` registers app-wide and
  would reject both with a 400. They need `@csrf.exempt`; their signature verification is what
  authenticates them. Silent payment-webhook failure is precisely the breakage that surfaces
  weeks later as missing client payments.
- **Blast radius:** 47 `fetch()` call sites across 6 templates and 38 POST routes, with 33 of
  the fetch calls in `attorney_portal.html` alone. Best handled by a shared helper rather than
  47 hand edits.
- **The test suite is affected.** Six of the eight test modules in `tests/` issue POSTs and will need
  token handling or an app-level test exemption.

**2. Secret key falls back to `os.urandom(24)`.** `app.py:19` silently generates a fresh key per
boot when `SECRET_KEY` is unset, invalidating all sessions on every restart. Generate and
persist a key during setup, and fail on a missing one rather than degrading silently.

`SECRET_KEY` is currently absent from `.env.example` and must be added, since setup copies from
it. The failure needs a documented dev/test escape hatch: `tests/conftest.py` imports `app`
directly, so an unconditional hard failure breaks the suite and bare development runs.

**3. No login rate limiting or lockout.** Add an in-process attempt counter with backoff keyed on
username and IP. No new dependency. This covers three credential paths, not two: the attorney
login, the client login, and the HTTP Basic Auth in `require_auth` (`shared.py:174`), which gates
every route when `SHARE_PASSWORD` is set and today accepts unlimited guesses. Share *mode* is
otherwise out of scope, but its credential path is in.

**4. Session cookies unhardened.** Set `SameSite=Lax`, `Secure` when serving over HTTPS, and a
session lifetime — an unattended office machine should not remain authenticated to client files
indefinitely. Modern browsers already default to `SameSite=Lax`, so this is defence in depth
behind item 1 rather than a load-bearing CSRF mitigation.

**5. No `MAX_CONTENT_LENGTH`.** A single oversized upload can exhaust disk or memory. One line.

**6. `docx-preview` interpolates unsanitized HTML.** `blueprints/portal_attorney.py:1268` passes
`mammoth.convert_to_html()` output directly into an f-string page. Clients cannot upload, so the
file always arrives through the attorney — but attorneys routinely open documents from opposing
counsel and unknown senders, so a crafted `.docx` could execute script inside the attorney's
authenticated session. Sanitize the output or render it in a sandboxed iframe with CSP.

**7. AI surfaces fail loudly, and one leaks internals to the public.** The Decisions table claims
the app is usable without an Anthropic key. That is not true today. `get_anthropic_client`
(`shared.py:164`) raises `ValueError` when `ANTHROPIC_API_KEY` is unset, and the public intake
chat at `blueprints/public.py:153` returns `jsonify({"error": str(e)}), 500` — handing an
internal exception string to an unauthenticated visitor. The six AI call sites in
`portal_attorney.py` share the shape.

Two fixes: return a generic message publicly and log the detail server-side, and detect a missing
key at startup so AI surfaces are hidden or disabled rather than presented and broken. The intake
form's AI summary already degrades correctly (`blueprints/intake.py:157`) and is the pattern to
follow.

**8. Most stored client passwords are plaintext.** Of the 38 records in `client-accounts/`
today, 6 are bcrypt and **32 are plaintext**. The mechanism is fine; the data is not.
`upgrade_password_if_needed` (`shared.py:350`) is called from exactly one place — the login flow
at `blueprints/auth.py:38` — so a client who has never logged in keeps a plaintext password
indefinitely.

A fresh install starts empty, so this bites two cases that both matter: the demo instance used to
sell, and any install seeded by migrating an existing firm's records. `scripts/hash_existing_passwords.py`
already solves it and hashes in place from the stored plaintext.

Three deliverables. Run it with `--apply` as a named, verified step in the setup checklist. Add
a startup check that logs a prominent warning when any unhashed record is present — a warning
rather than a hard failure, since locking an attorney out of their own practice over a
data-hygiene problem is worse than the problem.

And first, add `client-accounts-backup-*/` to `.gitignore`. The script copies the whole directory
to `BASE_DIR/client-accounts-backup-<stamp>/` before hashing (`scripts/hash_existing_passwords.py:73-74`),
and while `.gitignore:7` covers `client-accounts/`, it does not cover that name — verified with
`git check-ignore`. Running the step as written would drop 38 records, 32 of them plaintext, into
the working tree where `git add .` would pick them up. This is the same hazard Section 1 reasons
through for `./backups`, arriving by a different door. Do it in the same commit as the rest of
item 8, so the step is never run against an unprotected tree.

### Operational

Never ship a copy carrying our own `.env`. It contains the Anthropic key, Stripe keys, and
attorney password hashes. The install procedure generates fresh secrets per firm, and a
preflight check refuses to start when sample or known-shared values are detected.

Because Plan A runs first, that check must cover `BACKUP_PASSPHRASE` as well as the pre-existing
secrets. A shipped-shared backup passphrase — every customer's archive openable with the same
string — is precisely the failure this check exists to catch.

### Out of scope

The app runs on Flask's development server. For a local single-user tool this is tolerable, and
replacing it with `waitress` belongs in a later stability pass rather than this security work.
"Share mode" and its self-signed certificate are documented as local-network-only; a customer
wanting genuine remote access needs a VPN, not adhoc TLS.

---

## Section 3 — Customization Playbook

### Why customer #1 must be Tennessee criminal defense

Counting `Tennessee`, `Tenn.`, `T.C.A.`, `Nashville`, and `Davidson County` across
`blueprints/`, `shared.py`, `templates/`, and `seed_cases.py` gives **117 occurrences**; the bare
word "Tennessee" accounts for 43 of them. They are not equally difficult, and the split is what
drives the pricing tiers:

| Location | Count | Difficulty |
|---|---|---|
| `blueprints/portal_attorney.py` | 34 | **Hard** — 30 in prompt constants, 4 live clerk URLs |
| `blueprints/drafting.py` | 7 | **Hard** — inside prompt constants |
| `templates/attorney_portal.html` | 21 | **Hard** — a statewide court dataset, see below |
| `seed_cases.py` | 17 | Easy — seed data, regenerable |
| `shared.py` | 17 | Mixed |
| Public templates, `email_service.py` | 21 | Easy — display strings |

The hardest prompt-side occurrences are embedded in the AI prompts themselves; the other two
Hard rows are covered in the subsection below. `_RESEARCH_AUTHORITY_PROMPT` opens with
"an expert legal researcher specializing in Tennessee criminal defense" and directs the model to
cite T.C.A. sections and Tennessee Court of Criminal Appeals decisions.

That is why this is not a string swap. Sold as-is to a Texas family-law attorney, the research
tool would produce Tennessee criminal citations for a Texas custody matter. Given Rule 11
sanctions and the accumulating record of discipline over fabricated citations, that is the
failure that ends the business rather than generating a support ticket.

### Two dependencies the count does not capture

Both are worse than the prompt problem, and anyone pricing a non-Tennessee engagement off the
table above would badly underestimate it.

**A hardcoded statewide court dataset.** `templates/attorney_portal.html:1796-1894` defines
`TN_COUNTIES` — all 95 Tennessee counties — and `TN_COURTS`, holding 491 court names
("Anderson County Circuit Court", "Blount County Juvenile Court", and so on). Only 17 of those
586 jurisdiction-specific strings match the counting pattern, because a name like
"Anderson County Circuit Court" contains none of the five terms. Re-jurisdicting means sourcing
an equivalent dataset for the buyer's state.

**Case search silently produces dead links outside Tennessee.** `_clerk_url`
(`blueprints/portal_attorney.py:522`) special-cases Davidson County to the Nashville clerk
endpoints in `_DAVIDSON_URLS` (`:515`), then falls back for every other county to
`https://{county}.tncrtinfo.com/...` — the Tennessee Court Clerks' statewide portal. A Texas
buyer's case search does not error. It builds plausible-looking URLs that go nowhere, and
`tncrtinfo` matches none of the counting patterns.

This sharpens the customer-#1 argument rather than weakening it. For a Tennessee criminal defense
attorney every one of these is already correct. For anyone else, case search is not
mis-configured, it is functionally broken — a worse and more immediate failure than the
fabricated-citation risk, and one a demo would expose in the first five minutes.

Selling first into the niche the app was built for means zero prompt rework, a correct court
dataset, working clerk links, correct seeded case law, and a product demonstrated at its
strongest.

### Tier 1 — cosmetic, one to two hours per firm

Firm name — `Endo-Legal` appears roughly 38 times across 12 templates and about 67 repo-wide;
treat these as approximate and re-count at edit time. Attorney entries in `ATTORNEYS` and
`CASE_ATTORNEY_MAP` (`shared.py:65`). Bios and photographs in `templates/index.html` and
`templates/meet_the_firm.html`. Contact details, accent colors.

Rather more is already environment-driven than a first pass suggests, and all of it is a head
start on `firm.json`: `HOURLY_RATE` (`shared.py:116`), `TIMEZONE`, the six `MONTHLY_*` overhead
values with `OVERHEAD_RESERVE_PCT`, and `FROM_NAME`, `CAL_BOOKING_URL`, `FIRM_PHONE`,
`FIRM_WEBSITE` (`blueprints/email_service.py:28-31`). Note those four carry Endo-Legal defaults
in code, so setup must override them explicitly rather than relying on absence — with extra care
on `FIRM_PHONE`, whose default `(615) 000-0000` carries a Nashville area code and so is
jurisdiction-specific as well as firm-specific. The phone numbers in templates are already
`(555) 000-0000` placeholders.

### Tier 2 — substantive, only when leaving Tennessee criminal defense

Four distinct pieces of work, priced as a separate and more expensive engagement because it is
one:

1. The 37 prompt-embedded occurrences across `portal_attorney.py` and `drafting.py`.
2. `TN_COUNTIES` and `TN_COURTS` (`templates/attorney_portal.html:1796-1894`) — replaced with an
   equivalent dataset for the buyer's state.
3. `_DAVIDSON_URLS` and the `tncrtinfo.com` fallback in `_clerk_url`
   (`blueprints/portal_attorney.py:515-529`) — repointed at the buyer's state clerk portal, or
   the case-search feature disabled outright if no equivalent exists.
4. The case-type lists and seed data.

Items 2 and 3 are invisible to the occurrence count above. Scope them by reading the code, not by
grepping for the state name.

### Deliverable

`CUSTOMIZATION.md` — a literal checklist of every file and line touched per firm, written while
performing customer #1. It keeps hand-built installs consistent and becomes the specification
for `firm.json` when the config layer is eventually built.

### Eventual config boundary

A `firm.json` holding identity, attorneys, practice areas, jurisdiction, and rate, injected into
templates through a Flask context processor. Secrets remain in `.env`. Not built now — the
checklist determines its contents.

---

## Section 4 — Explicitly Not Building

Each of these is a real feature that a different business model would require.

- **Database migration.** Flat JSON — with per-client locks on the records that are actually
  mutated — suits one solo firm with a few hundred active clients, one user, one machine.
  Correct at customer #30, not customer #1.
- **License keys and activation.** Installs are performed by hand; enforcement addresses a piracy
  problem that does not exist.
- **One-click installer and auto-update.** Same reasoning. Manual updates for the first handful.
- **Restore UI, multi-user roles, product marketing site.** `ATTORNEYS` already holds two
  accounts, solo buyers need one, and customer #1 is sold in conversation.
- **Payment collection for our own license.** The Stripe and Coinbase integrations exist so a
  firm's clients can pay the firm. Buyers are invoiced directly.

## Non-Code Deliverables Gating Customer #1

A written license agreement disclaiming warranties, limiting liability, and stating that AI
output requires independent attorney verification before filing. A vendor confidentiality
agreement, since setup and client-list migration involve handling privileged files, which
attorneys are generally expected to paper with vendors who access client data.

Both precede the first install.

## Build Order

Two plans, executed in sequence.

**Plan A — Backup and export.** Section 1 in full: the backup module, encryption and passphrase
handling, `scripts/restore.py`, the export endpoint with credential stripping, the `.gitignore`
entry, and all three tests.

**Plan B — Security pass.** Section 2 items 1–8, the preflight secrets check, the `.env.example`
additions, and updating the six affected test modules.

Each plan adds one runtime dependency currently absent from `requirements.txt` — `pyzipper` for
Plan A, `Flask-WTF` for Plan B — and updating that file is part of each plan's deliverables.
Neither can be stubbed the way `tests/conftest.py:25-33` stubs the optional heavy dependencies:
`CSRFProtect` is exercised directly by the affected tests, and `pyzipper` performs the real
encryption in the round-trip test.

Plan B must re-measure its own blast radius rather than trusting the 47 fetch sites cited in
item 1: that figure is current as of today, and Plan A adds at least two more state-changing
controls to the attorney portal ("Back up now" and "Download all my data"). Both plans also
extend `.env.example` and the setup checklist — Plan A adds `BACKUP_PASSPHRASE`, Plan B adds
`SECRET_KEY` — so Plan B appends to what Plan A left rather than rewriting it.

Then, outside these plans: the license and confidentiality agreements, followed by the customer
#1 install with `CUSTOMIZATION.md` written during it.
