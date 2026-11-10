"""services/assistant_tools.py — the tools the portal assistant can call.

Data tools read portal records and run immediately. Action tools change a
record, so they never run on their own: the assistant proposes them, the
attorney confirms each one in the chat panel, and only then does execute()
run (see services/assistant.py).

Every tool is scoped to the attorney it runs for: clients come from
can_access_client(), exactly like the portal routes. Results are plain JSON
text for the model. Client-written text inside them (messages, notes, lead
details) is data, never instructions; the system prompt says so too.
"""

import json
import re
from datetime import date, datetime, timedelta

import shared
from services import client_files
from services import billing, felony, firm_admin, storage
from services.accounts import _log_access, can_access_client
from services.scheduling_orders import CASE_DATE_LABELS

MAX_TEXT = 4000           # longest message / note the assistant may write
MAX_HOURS = 24.0
MAX_PAYMENT = 1_000_000.0


class ToolError(Exception):
    """A user-facing problem with a tool call (bad input, unknown client)."""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(value, field="date") -> date:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ToolError(f"{field} must be a date in YYYY-MM-DD form.")


def _my_clients(attorney: str, include_archived: bool = False) -> list:
    return [c for c in storage.all_clients()
            if can_access_client(attorney, c)
            and (include_archived or not c.get("archived"))]


def _name(c: dict) -> str:
    return c.get("client_name") or c.get("username", "")


def resolve_client(attorney: str, ref: str) -> dict:
    """Find one accessible client by username or (part of) their name."""
    ref = (ref or "").strip()
    if not ref:
        raise ToolError("Name the client.")
    clients = _my_clients(attorney, include_archived=True)
    exact = [c for c in clients if c.get("username", "").lower() == ref.lower()
             or _name(c).lower() == ref.lower()]
    if len(exact) == 1:
        return storage.load_client(exact[0]["username"]) or exact[0]
    words = ref.lower().split()
    partial = [c for c in clients if all(w in _name(c).lower() for w in words)]
    if len(partial) == 1:
        return storage.load_client(partial[0]["username"]) or partial[0]
    if not partial:
        raise ToolError(f"No client of yours matches {ref!r}.")
    names = ", ".join(f"{_name(c)} ({c['username']})" for c in partial[:8])
    raise ToolError(f"Several clients match {ref!r}: {names}. Say which one.")


def _meeting_date(raw: str):
    """(date, time text) from the portal's next_meeting text, else (None, "")."""
    raw = (raw or "").strip()
    m = re.search(r"(\w+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M)", raw)
    if m:
        try:
            dt = datetime.strptime(m.group(1) + " " + m.group(2), "%B %d, %Y %I:%M %p")
            return dt.date(), dt.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?", raw)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date(), m.group(2) or ""
        except ValueError:
            pass
    return None, ""


def _money(x) -> float:
    return round(float(x or 0), 2)


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ── Data tools ───────────────────────────────────────────────────────────────

def get_schedule(attorney: str, start_date: str, end_date: str) -> str:
    start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
    if end < start:
        raise ToolError("end_date is before start_date.")
    if (end - start).days > 366:
        raise ToolError("Ask for at most one year at a time.")
    events = []

    def add(d, kind, c, what, time=""):
        if d and start <= d <= end:
            events.append({"date": d.isoformat(), "weekday": d.strftime("%A"), "time": time,
                           "type": kind, "client": _name(c), "username": c.get("username", ""),
                           "matter": what, "county": c.get("county", ""), "court": c.get("court", "")})

    for c in _my_clients(attorney):
        matter = c.get("charges") or c.get("case_type") or ""
        if c.get("next_court_date"):
            try:
                add(_parse_date(c["next_court_date"]), "Court date", c, matter)
            except ToolError:
                pass
        case_dates = c.get("case_dates") if isinstance(c.get("case_dates"), dict) else {}
        for kind, entry in case_dates.items():
            if isinstance(entry, dict) and entry.get("date"):
                try:
                    add(_parse_date(entry["date"]), "Case deadline", c, CASE_DATE_LABELS.get(kind, kind))
                except ToolError:
                    pass
        md, mt = _meeting_date(c.get("next_meeting", ""))
        add(md, "Meeting", c, matter, mt)

    try:
        from services.gcal import _fetch_gcal_events
        days = (end - date.today()).days
        for g in (_fetch_gcal_events(days_ahead=days + 1) if days >= 0 else []):
            try:
                d = _parse_date(g.get("start_date"))
            except ToolError:
                continue
            if start <= d <= end:
                events.append({"date": d.isoformat(), "weekday": d.strftime("%A"),
                               "time": (g.get("start_datetime") or "")[11:16], "type": "Google Calendar",
                               "client": "", "username": "", "matter": g.get("summary", ""),
                               "county": "", "court": ""})
    except Exception:
        pass                                  # calendar not connected: client dates still count

    events.sort(key=lambda e: (e["date"], e["time"]))
    return _dump({"start_date": start.isoformat(), "end_date": end.isoformat(),
                  "count": len(events), "events": events})


def find_clients(attorney: str, query: str = "", include_archived: bool = False) -> str:
    words = (query or "").lower().split()
    rows = []
    for c in _my_clients(attorney, include_archived):
        hay = " ".join(str(c.get(k, "")) for k in
                       ("client_name", "username", "case_type", "county", "court", "charges", "case_no")).lower()
        if words and not all(w in hay for w in words):
            continue
        ledger = billing.load_ledger(c["username"])
        rows.append({"client": _name(c), "username": c["username"], "case_type": c.get("case_type", ""),
                     "county": c.get("county", ""), "court": c.get("court", ""),
                     "case_no": c.get("case_no", ""), "next_court_date": c.get("next_court_date", ""),
                     "last_communication": c.get("last_communication", ""),
                     "hours_logged": c.get("hours_billed", 0),
                     "amount_due": billing.amount_due(c, ledger), "archived": bool(c.get("archived"))})
    rows.sort(key=lambda r: r["client"].lower())
    return _dump({"count": len(rows), "clients": rows[:100]})


def get_client_details(attorney: str, client: str) -> str:
    c = resolve_client(attorney, client)
    ledger = billing.load_ledger(c["username"])
    docs_root = shared.CLIENT_FILES_DIR / c["username"] / "documents"
    documents = []
    if docs_root.exists():
        for cat in sorted(p for p in docs_root.iterdir() if p.is_dir()):
            documents += [f"{cat.name}/{f.name}" for f in sorted(cat.iterdir()) if f.is_file()]
    case_dates = c.get("case_dates") if isinstance(c.get("case_dates"), dict) else {}
    return _dump({
        "client": _name(c), "username": c["username"], "case_type": c.get("case_type", ""),
        "phone": c.get("phone", ""), "email": c.get("email", ""),
        "case_no": c.get("case_no", ""), "charges": c.get("charges", ""),
        "county": c.get("county", ""), "court": c.get("court", ""),
        "legal_issue": c.get("legal_issue", ""), "summary": c.get("legal_issue_summary", ""),
        "opposing_parties": c.get("opposing_parties") or [],
        "next_court_date": c.get("next_court_date", ""), "next_meeting": c.get("next_meeting", ""),
        "case_dates": {CASE_DATE_LABELS.get(k, k): v.get("date") for k, v in case_dates.items()
                       if isinstance(v, dict) and v.get("date")},
        "last_communication": c.get("last_communication", ""),
        "recent_messages": (c.get("messages") or [])[-8:],
        "billing": {k: v for k, v in billing.billing_summary(c, ledger).items() if k != "statements"},
        "documents": documents[:60], "archived": bool(c.get("archived")),
        "charge_level": c.get("charge_level", ""),
        "felony_checklist": [{"item": i["key"], "label": i["label"], "done": i["done"], "date": i["at"][:10]}
                             for i in felony.checklist_view(c)],
        "discovery_draft": c.get("discovery_draft"),
    })


def get_billing_status(attorney: str, client: str) -> str:
    c = resolve_client(attorney, client)
    ledger = billing.load_ledger(c["username"])
    summary = billing.billing_summary(c, ledger)
    return _dump({
        "client": _name(c), "username": c["username"], "hourly_rate": shared.HOURLY_RATE,
        "amount_due": summary["amount_due"], "total_billed": summary["statement_total"],
        "total_paid": summary["paid"], "unbilled_hours": summary["unbilled_hours"],
        "unbilled_amount": summary["unbilled_amount"],
        "statements": [{"number": s.get("number"), "issued": (s.get("issued_at") or "")[:10],
                        "hours": s.get("hours"), "amount": s.get("amount")}
                       for s in summary["statements"]],
        "payments": [{"date": p.get("date", ""), "amount": p.get("amount", 0), "method": p.get("method", "")}
                     for p in reversed(c.get("payments") or [])],
    })


def get_billing_report(attorney: str, month: str) -> str:
    try:
        first = datetime.strptime((month or "").strip(), "%Y-%m").date()
    except ValueError:
        raise ToolError("month must be in YYYY-MM form.")
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    in_month = lambda s: bool(s) and first.isoformat() <= str(s)[:10] < nxt.isoformat()
    rate = float(shared.HOURLY_RATE)
    per_client, hours_total, billed, paid, outstanding = [], 0.0, 0.0, 0.0, []
    for c in _my_clients(attorney, include_archived=True):
        ledger = billing.load_ledger(c["username"])
        hrs = round(sum(float(e.get("hours", 0) or 0) for e in c.get("billing_log") or []
                        if in_month(e.get("date"))), 2)
        st = _money(sum(float(s.get("amount", 0)) for s in ledger["statements"] if in_month(s.get("issued_at"))))
        pd = _money(sum(float(p.get("amount", 0) or 0) for p in c.get("payments") or [] if in_month(p.get("date"))))
        due = billing.amount_due(c, ledger)
        hours_total += hrs; billed += st; paid += pd
        if hrs or st or pd:
            per_client.append({"client": _name(c), "hours": hrs, "value_at_rate": _money(hrs * rate),
                               "billed": st, "paid": pd})
        if due > 0:
            outstanding.append({"client": _name(c), "amount_due": due})
    per_client.sort(key=lambda r: -r["hours"])
    outstanding.sort(key=lambda r: -r["amount_due"])
    return _dump({
        "month": first.strftime("%Y-%m"), "hourly_rate": rate,
        "hours_logged": round(hours_total, 2), "value_of_hours": _money(hours_total * rate),
        "statements_issued": _money(billed), "payments_received": _money(paid),
        "outstanding_total_all_time": _money(sum(o["amount_due"] for o in outstanding)),
        "by_client": per_client, "clients_owing": outstanding,
    })


def get_attention_items(attorney: str) -> str:
    today = date.today()
    soon, follow_up, unanswered, conflicts = [], [], [], []
    for c in _my_clients(attorney):
        try:
            d = _parse_date(c.get("next_court_date"))
            if 0 <= (d - today).days <= 7:
                soon.append({"client": _name(c), "date": d.isoformat(), "days": (d - today).days,
                             "county": c.get("county", ""), "court": c.get("court", "")})
        except ToolError:
            pass
        try:
            days = (today - _parse_date(c.get("last_communication"))).days
            if days >= 30:
                follow_up.append({"client": _name(c), "days_since_contact": days})
        except ToolError:
            pass
        msgs = c.get("messages") or []
        if msgs and msgs[-1].get("from") == "client":
            unanswered.append({"client": _name(c), "sent": msgs[-1].get("date", ""),
                               "message": (msgs[-1].get("text") or "")[:300]})
        if c.get("conflict_unresolved"):
            conflicts.append(_name(c))
    drafts = [{"client": d["client_name"], "document": f"{d['category']}/{d['filename']}", "note": d["text"]}
              for d in felony.pending_reviews(_my_clients(attorney))]
    leads = [l for l in _leads(attorney)]
    return _dump({"court_within_7_days": sorted(soon, key=lambda x: x["days"]),
                  "need_follow_up": sorted(follow_up, key=lambda x: -x["days_since_contact"]),
                  "unanswered_client_messages": unanswered, "unresolved_conflicts": conflicts,
                  "open_leads": len(leads), "drafts_to_review": drafts,
                  "firm_admin_due": firm_admin.reminders()})


def get_firm_admin(attorney: str) -> str:
    """Firm compliance items (bar, tax, entity filings), their next due dates,
    reminder status, and the records of what was done."""
    data = firm_admin.overview()
    items = [{"id": o["id"], "title": o["title"], "category": o["category"], "status": o["status"],
              "next_due": o["next_due"], "days_left": o["days_left"], "usual_amount": o["amount"],
              "notes": o["notes"], "last_done": (o["last_record"] or {}).get("completed_on", "")}
             for o in data["obligations"]]
    records = [{k: r.get(k, "") for k in ("title", "due", "completed_on", "amount", "confirmation", "note")}
               for r in data["records"][:40]]
    return _dump({"items": items, "records": records,
                  "reminder_days": data["reminder_days"]})


def _leads(attorney: str) -> list:
    out = []
    for p in sorted(shared.LEADS_DIR.glob("*.json"), reverse=True):
        lead = storage.read_encrypted_json(p)
        if isinstance(lead, dict) and lead.get("assigned_attorney") == attorney and not lead.get("archived"):
            out.append(lead)
    return out


def list_leads(attorney: str, limit: int = 20) -> str:
    limit = max(1, min(int(limit or 20), 50))
    rows = [{"name": l.get("name", ""), "received": l.get("timestamp", ""), "case_type": l.get("case_type", ""),
             "phone": l.get("phone", ""), "email": l.get("email", ""), "source": l.get("source", ""),
             "notes": (l.get("notes") or "")[:500]} for l in _leads(attorney)[:limit]]
    return _dump({"count": len(rows), "leads": rows})


def get_signature_status(attorney: str, client: str) -> str:
    from services import esign
    c = resolve_client(attorney, client)
    reqs = esign.refresh(c["username"])
    return _dump({"client": _name(c), "e_signing_configured": esign.configured(),
                  "requests": [{"title": r["title"], "document": r["document"], "status": r["status"],
                                "sent": r.get("sent_at", "")[:10], "test_mode": r.get("test_mode"),
                                "signers": [{"name": s["name"], "status": s["status"],
                                             "signed_at": s.get("signed_at", "")} for s in r["signers"]],
                                "signed_copy": r.get("signed_file", "")} for r in reqs]})


def _find_document(c: dict, ref: str):
    """(category, filename) for "Category/file.pdf" or a unique (part of a) file name."""
    from services import esign
    ref = (ref or "").strip()
    if "/" in ref:
        cat, name = ref.split("/", 1)
        if cat in shared.DOCS_CATEGORIES:
            return cat, name
    root = shared.CLIENT_FILES_DIR / c["username"] / "documents"
    hits = []
    if root.exists():
        for cat in shared.DOCS_CATEGORIES:
            d = root / cat
            if d.is_dir():
                hits += [(cat, f.name) for f in d.iterdir()
                         if f.is_file() and ref.lower() in f.name.lower()
                         and f.suffix.lower() in esign.SIGNABLE_EXTS]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ToolError(f"No PDF or Word document in {_name(c)}'s file matches {ref!r}.")
    raise ToolError("Several documents match: " + ", ".join(f"{a}/{b}" for a, b in hits[:8]) + ". Say which one.")


DRAFT_CATEGORY = "Drafts"
MAX_DRAFT_CHARS = 200_000


def save_draft_document(attorney: str, client: str, title: str, content: str) -> str:
    """Save a drafted document as a Word file in the client's attorney-only
    Drafts folder. The client portal never lists or serves that folder, so a
    draft reaches no one until the attorney finalizes it and files it where
    the client can see it; that is why this runs without a confirmation."""
    import re as _re
    from services.docx_writer import text_to_docx
    c = resolve_client(attorney, client)
    title = re.sub(r"\s+", " ", (title or "").strip())[:120]
    if not title:
        raise ToolError("Give the document a title.")
    content = (content or "").strip()
    if len(content) < 40:
        raise ToolError("content must be the full document text.")
    if len(content) > MAX_DRAFT_CHARS:
        raise ToolError("The document is too long to save in one piece.")
    category = DRAFT_CATEGORY
    folder = storage._client_docs_dir(c["username"], category)
    stem = _re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")[:70] or "Draft"
    stem = f"DRAFT_{stem}_{date.today():%Y%m%d}"
    dest = folder / f"{stem}.docx"
    n = 2
    while dest.exists():
        dest = folder / f"{stem}_{n}.docx"
        n += 1
    client_files.write_path(dest, text_to_docx(title, content, shared.MANAGING_PARTNER["display"]))
    storage._log_activity(c["username"], "document_generated", f"Draft saved: {category}/{dest.name}")
    return _dump({"saved": True, "client": _name(c), "username": c["username"],
                  "category": category, "filename": dest.name, "title": title,
                  "words": len(content.split())})


# ── Action tools (run only after the attorney confirms) ──────────────────────

def _prep_esign(attorney, inp):
    from services import esign
    c = resolve_client(attorney, inp.get("client"))
    category, filename = _find_document(c, inp.get("document"))
    try:
        esign.document_path(c["username"], category, filename)
        signers = esign.clean_signers(inp.get("signers") or [{"name": c.get("client_name", ""),
                                                               "email": c.get("email", "")}])
    except esign.EsignError as exc:
        raise ToolError(str(exc))
    who = ", ".join(f"{s['name']} <{s['email']}>" for s in signers)
    mode = " (test mode, not legally binding)" if shared.DROPBOX_SIGN_TEST_MODE else ""
    summary = f"Send {category}/{filename} for e-signature{mode} to: {who}"
    if (inp.get("message") or "").strip():
        summary += f"\n\nMessage: {inp['message'].strip()}"
    return c, category, filename, signers, summary


def _run_esign(attorney, inp):
    from services import esign
    c, category, filename, signers, _ = _prep_esign(attorney, inp)
    try:
        entry = esign.send(c["username"], category, filename, signers, inp.get("subject", ""),
                           inp.get("message", ""), attorney)
    except esign.EsignError as exc:
        raise ToolError(str(exc))
    return f"Sent {entry['title']} for signature to " + ", ".join(s["name"] for s in signers) + "."


def _check_text(text, field="text") -> str:
    text = (text or "").strip()
    if not text:
        raise ToolError(f"{field} is empty.")
    if len(text) > MAX_TEXT:
        raise ToolError(f"{field} is longer than {MAX_TEXT} characters.")
    return text


def _prep_log_time(attorney, inp):
    c = resolve_client(attorney, inp.get("client"))
    try:
        hours = round(float(inp.get("hours")), 2)
    except (TypeError, ValueError):
        raise ToolError("hours must be a number.")
    if not 0 <= hours <= MAX_HOURS:
        raise ToolError(f"hours must be between 0 and {MAX_HOURS:g}.")
    note = _check_text(inp.get("note"), "note")
    when = _parse_date(inp["date"]) if inp.get("date") else date.today()
    category = (inp.get("category") or "Other").strip()[:40] or "Other"
    entry = {"date": when.isoformat(), "hours": hours, "note": note, "category": category}
    summary = f"Log {hours:g} hr for {_name(c)} on {when:%b %d, %Y} ({category}): {note}"
    return c, entry, summary


def _run_log_time(attorney, inp):
    c, entry, _ = _prep_log_time(attorney, inp)

    def mutate(cl):
        cl.setdefault("billing_log", []).append(dict(entry))
        storage.recalc_hours(cl)
        cl["last_communication"] = date.today().isoformat()
        _log_access(cl, "billing_entry", f"{entry['hours']} hrs — {entry['note'][:80]} (assistant)")

    saved = storage.update_client_atomic(c["username"], mutate)
    storage._log_activity(c["username"], "time_logged", f"{entry['hours']} hrs — {entry['note'][:80]}")
    return f"Logged {entry['hours']:g} hr for {_name(c)}. Total hours now {saved['hours_billed']:g}."


def _prep_message(attorney, inp):
    c = resolve_client(attorney, inp.get("client"))
    text = _check_text(inp.get("text"), "text")
    return c, text, f"Send this portal message to {_name(c)}:\n\n{text}"


def _run_message(attorney, inp):
    c, text, _ = _prep_message(attorney, inp)

    def mutate(cl):
        cl.setdefault("messages", []).append({"from": "attorney",
                                              "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "text": text})
        cl["last_communication"] = date.today().isoformat()
        _log_access(cl, "message_sent", text[:80])

    storage.update_client_atomic(c["username"], mutate)
    storage._log_activity(c["username"], "message_sent",
                          "Attorney message: " + text[:80] + ("..." if len(text) > 80 else ""))
    return f"Message sent to {_name(c)} in the client portal."


CASE_FIELDS = {"next_court_date": "next court date", "next_meeting": "next meeting",
               "county": "county", "court": "court", "case_no": "case number",
               "charges": "charges / claims", "phone": "phone", "email": "email"}


def _prep_case_update(attorney, inp):
    c = resolve_client(attorney, inp.get("client"))
    changes = {k: str(v).strip() for k, v in (inp.get("changes") or {}).items()
               if k in CASE_FIELDS and v is not None}
    if not changes:
        raise ToolError("No supported fields to change. Allowed: " + ", ".join(CASE_FIELDS) + ".")
    if changes.get("next_court_date"):
        _parse_date(changes["next_court_date"], "next_court_date")
    for k, v in changes.items():
        if len(v) > 300:
            raise ToolError(f"{k} is too long.")
    lines = [f"- {CASE_FIELDS[k]}: {c.get(k) or '(blank)'} → {v or '(blank)'}" for k, v in changes.items()]
    return c, changes, f"Update {_name(c)}'s case info:\n" + "\n".join(lines)


def _run_case_update(attorney, inp):
    c, changes, _ = _prep_case_update(attorney, inp)

    def mutate(cl):
        cl.update(changes)
        _log_access(cl, "edit_record", "Case info updated by assistant: " + ", ".join(changes))

    storage.update_client_atomic(c["username"], mutate)
    storage._log_activity(c["username"], "info_updated",
                          "Case info updated: " + ", ".join(CASE_FIELDS[k] for k in changes) + ".")
    note = (" Google Calendar was not updated; change the court date on the client page to sync it."
            if "next_court_date" in changes else "")
    return f"Updated {_name(c)}: " + ", ".join(CASE_FIELDS[k] for k in changes) + "." + note


def _prep_payment(attorney, inp):
    c = resolve_client(attorney, inp.get("client"))
    try:
        amount = _money(inp.get("amount"))
    except (TypeError, ValueError):
        raise ToolError("amount must be a number.")
    if not 0 < amount <= MAX_PAYMENT:
        raise ToolError("amount must be more than 0.")
    method = (inp.get("method") or "").strip()[:30] or "check"
    ref = (inp.get("reference") or "").strip()[:60]
    summary = f"Record a ${amount:,.2f} {method} payment from {_name(c)}" + (f" (ref {ref})" if ref else "")
    return c, amount, method, ref, summary


def _run_payment(attorney, inp):
    c, amount, method, ref, _ = _prep_payment(attorney, inp)
    reference = ref or f"manual-{datetime.now():%Y%m%d%H%M%S}"
    if not storage._apply_payment(c["username"], amount, method, reference):
        return f"Not recorded: a payment with reference {reference!r} is already on file for {_name(c)}."
    due = billing.amount_due(storage.load_client(c["username"]), billing.load_ledger(c["username"]))
    return f"Recorded ${amount:,.2f} from {_name(c)}. Balance due now ${due:,.2f}."


def _prep_flat_fee(attorney, inp):
    c = resolve_client(attorney, inp.get("client"))
    if inp.get("remove"):
        if not billing.flat_fee(c):
            raise ToolError(f"{_name(c)} is already billed hourly.")
        return c, None, f"Switch {_name(c)} back to hourly billing (remove the flat fee)"
    try:
        amount = _money(inp.get("amount"))
    except (TypeError, ValueError):
        raise ToolError("amount must be a number.")
    if not 0 < amount <= billing.MAX_FLAT_FEE:
        raise ToolError("amount must be more than 0.")
    plan = inp.get("plan") or "full"
    if plan not in billing.FLAT_FEE_PLANS:
        raise ToolError("plan must be 'full' or 'half'.")
    due = (inp.get("due_date") or "").strip()
    try:
        billing._valid_date(due)
    except ValueError as exc:
        raise ToolError(str(exc))
    desc = (inp.get("description") or "").strip()[:120]
    summary = (f"Set a ${amount:,.2f} flat fee for {_name(c)} "
               f"({billing.FLAT_FEE_PLANS[plan].lower()}" + (f", due {due}" if due else "") + ")"
               + (f": {desc}" if desc else ""))
    return c, (amount, plan, due, desc), summary


def _run_flat_fee(attorney, inp):
    c, args, _ = _prep_flat_fee(attorney, inp)
    if args is None:
        billing.clear_flat_fee(c["username"])
        return f"{_name(c)} is billed hourly again."
    amount, plan, due, desc = args
    billing.set_flat_fee(c["username"], amount, plan, due, desc, set_by=attorney)
    return (f"{_name(c)} is now on a ${amount:,.2f} flat fee. Time logged from now on is "
            "tracked privately and not billed.")


def _prep_checklist(attorney, inp):
    c = resolve_client(attorney, inp.get("client"))
    if not felony.is_felony(c):
        raise ToolError(f"{_name(c)} is not a felony case (set Charge Level to Felony first).")
    key = inp.get("item")
    if key not in felony.CHECKLIST_LABELS:
        raise ToolError("item must be one of: " + ", ".join(felony.CHECKLIST_LABELS) + ".")
    done = inp.get("done", True) is not False
    verb = "Check" if done else "Uncheck"
    note = (" This also drafts the Request for Discovery if it isn't drafted yet."
            if done and key == felony.ARRAIGNMENT and not c.get("discovery_draft") else "")
    return c, key, done, f"{verb} \"{felony.CHECKLIST_LABELS[key]}\" for {_name(c)}.{note}"


def _run_checklist(attorney, inp):
    c, key, done, _ = _prep_checklist(attorney, inp)
    felony.set_item(c["username"], key, done, attorney)
    fresh = storage.load_client(c["username"]) or {}
    d = fresh.get("discovery_draft") or {}
    extra = (f" Request for Discovery drafted: {d['category']}/{d['filename']}."
             if d.get("status") == "ready" and not d.get("reviewed") and key == felony.ARRAIGNMENT else "")
    return f"{'Checked' if done else 'Unchecked'} \"{felony.CHECKLIST_LABELS[key]}\" for {_name(c)}." + extra


def _find_admin_item(inp):
    want = str(inp.get("item") or "").strip().lower()
    items = firm_admin.overview()["obligations"]
    hits = [o for o in items if o["id"] == want] or [o for o in items if want and want in o["title"].lower()]
    if len(hits) != 1:
        raise ToolError("Name one firm admin item by id or a unique part of its title. Items: "
                        + "; ".join(f"{o['id']} ({o['title']})" for o in items))
    o = hits[0]
    if not o["next_due"]:
        raise ToolError(f"{o['title']} has nothing due (no due date set, or it is turned off).")
    return o


def _prep_admin_done(attorney, inp):
    o = _find_admin_item(inp)
    on = (inp.get("completed_on") or "").strip()
    if on:
        _parse_date(on, "completed_on")
    bits = [f"Mark \"{o['title']}\" done for the {o['next_due']} due date"]
    if inp.get("amount"):
        bits.append(f"amount {inp['amount']}")
    if inp.get("confirmation"):
        bits.append(f"confirmation {inp['confirmation']}")
    return o, " · ".join(bits) + ". This stops its reminders."


def _run_admin_done(attorney, inp):
    o, _ = _prep_admin_done(attorney, inp)
    try:
        firm_admin.complete(o["id"], o["next_due"], attorney, inp.get("amount", ""),
                            inp.get("confirmation", ""), inp.get("note", ""), inp.get("completed_on", ""))
    except firm_admin.AdminError as exc:
        return f"Not recorded: {exc}"
    return f"Recorded: {o['title']} done for {o['next_due']}. Its reminders have stopped."


# ── Registry ─────────────────────────────────────────────────────────────────

def _schema(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_CLIENT = {"type": "string", "description": "Client username or name (part of a name works if it is unique)."}

DATA_TOOLS = {
    "get_schedule": (get_schedule, "Court dates, case deadlines, meetings and Google Calendar events "
                     "between two dates (inclusive), each with client, county and court.",
                     _schema({"start_date": {"type": "string", "description": "YYYY-MM-DD"},
                              "end_date": {"type": "string", "description": "YYYY-MM-DD"}},
                             ["start_date", "end_date"])),
    "find_clients": (find_clients, "List the attorney's clients, optionally filtered by words matching "
                     "name, case type, county, court, charges or case number. Includes balance due.",
                     _schema({"query": {"type": "string"},
                              "include_archived": {"type": "boolean"}}, [])),
    "get_client_details": (get_client_details, "Everything on one client's file: contact, case info, "
                           "dates, recent portal messages, billing summary and document names.",
                           _schema({"client": _CLIENT}, ["client"])),
    "get_billing_status": (get_billing_status, "One client's billing: amount due, statements issued, "
                           "payments received and unbilled time.",
                           _schema({"client": _CLIENT}, ["client"])),
    "get_billing_report": (get_billing_report, "Firm billing numbers for a calendar month: hours logged, "
                           "their value at the hourly rate, statements issued, payments received, and "
                           "who currently owes money.",
                           _schema({"month": {"type": "string", "description": "YYYY-MM"}}, ["month"])),
    "get_attention_items": (get_attention_items, "What needs the attorney now: court within 7 days, "
                            "clients not contacted in 30+ days, unanswered client messages, unresolved "
                            "conflict checks, and open leads.", _schema({}, [])),
    "get_firm_admin": (get_firm_admin, "The firm's own compliance deadlines (BPR registration, CLE, "
                       "professional privilege tax, estimated taxes, PLLC annual report, insurance...): "
                       "next due dates, overdue items, and records of what was filed or paid.",
                       _schema({}, [])),
    "list_leads": (list_leads, "Open incoming leads (prospective clients), newest first.",
                   _schema({"limit": {"type": "integer"}}, [])),
    "get_signature_status": (get_signature_status, "E-signature requests for one client: who has "
                             "signed, who hasn't, and where the signed copy was saved.",
                             _schema({"client": _CLIENT}, ["client"])),
    "save_draft_document": (save_draft_document, "Save a document you drafted (motion, letter, "
                            "agreement, pleading, notice...) as a Word file in the client's attorney-only "
                            "Drafts folder, which the client cannot see. Always use this for drafted "
                            "documents instead of writing them in chat.",
                            _schema({"client": _CLIENT,
                                     "title": {"type": "string", "description": "e.g. Motion to Suppress"},
                                     "content": {"type": "string", "description": "The complete document as plain "
                                                 "text: one paragraph per line, blank lines between sections, no markdown."}},
                                    ["client", "title", "content"])),
}

# name -> (prepare(attorney, input) -> (..., summary), run(attorney, input) -> str, title, description, schema)
ACTION_TOOLS = {
    "log_time": (_prep_log_time, _run_log_time, "Log time",
                 "Add a time entry (billable hours, can be 0 for a note) to a client's file.",
                 _schema({"client": _CLIENT, "hours": {"type": "number"}, "note": {"type": "string"},
                          "category": {"type": "string", "description": "e.g. Research, Drafting, Court Appearance, Phone/Email, Meeting"},
                          "date": {"type": "string", "description": "YYYY-MM-DD, default today"}},
                         ["client", "hours", "note"])),
    "send_client_message": (_prep_message, _run_message, "Send client message",
                            "Send a message to a client through their client portal.",
                            _schema({"client": _CLIENT, "text": {"type": "string"}}, ["client", "text"])),
    "update_case_info": (_prep_case_update, _run_case_update, "Update case info",
                         "Change case fields on a client's file: " + ", ".join(CASE_FIELDS) + ".",
                         _schema({"client": _CLIENT,
                                  "changes": {"type": "object", "description": "field -> new value",
                                              "additionalProperties": {"type": "string"}}},
                                 ["client", "changes"])),
    "send_for_signature": (_prep_esign, _run_esign, "Send for signature",
                           "Send a PDF or Word document from the client's file for e-signature "
                           "through Dropbox Sign. Signers default to the client (name and email on file).",
                           _schema({"client": _CLIENT,
                                    "document": {"type": "string", "description": "\"Category/file name\" or a unique part of the file name"},
                                    "signers": {"type": "array", "items": _schema(
                                        {"name": {"type": "string"}, "email": {"type": "string"}}, ["name", "email"])},
                                    "subject": {"type": "string"}, "message": {"type": "string"}},
                                   ["client", "document"])),
    "record_payment": (_prep_payment, _run_payment, "Record payment",
                       "Record a payment received outside the portal (check, cash, wire).",
                       _schema({"client": _CLIENT, "amount": {"type": "number"},
                                "method": {"type": "string"}, "reference": {"type": "string"}},
                               ["client", "amount"])),
    "update_felony_checklist": (_prep_checklist, _run_checklist, "Update felony checklist",
                                "Check (done=true) or uncheck an item on a felony client's case "
                                "checklist. Items: " + ", ".join(f"{k} ({v})" for k, v in felony.CHECKLIST)
                                + ". Checking 'arraignment' drafts the Request for Discovery "
                                "automatically if it isn't drafted yet.",
                                _schema({"client": _CLIENT,
                                         "item": {"type": "string", "enum": [k for k, _ in felony.CHECKLIST]},
                                         "done": {"type": "boolean"}},
                                        ["client", "item"])),
    "complete_firm_admin_item": (_prep_admin_done, _run_admin_done, "Mark firm admin item done",
                                 "Record that a firm admin item (from get_firm_admin) was filed or paid "
                                 "for its next due date, with optional amount, confirmation number, note "
                                 "and completed_on (YYYY-MM-DD, default today). Stops its reminders.",
                                 _schema({"item": {"type": "string", "description": "Item id or part of its title"},
                                          "amount": {"type": "string"}, "confirmation": {"type": "string"},
                                          "note": {"type": "string"},
                                          "completed_on": {"type": "string", "description": "YYYY-MM-DD"}},
                                         ["item"])),
    "set_flat_fee": (_prep_flat_fee, _run_flat_fee, "Set flat fee",
                     "Bill a client a flat fee instead of hourly (earned on receipt), or switch "
                     "back to hourly with remove=true. plan: 'full' (paid up front) or 'half' "
                     "(half up front, half by due_date). Time logged under a flat fee is tracked "
                     "privately and never billed.",
                     _schema({"client": _CLIENT, "amount": {"type": "number"},
                              "plan": {"type": "string", "enum": ["full", "half"]},
                              "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                              "description": {"type": "string", "description": "What the fee covers"},
                              "remove": {"type": "boolean"}},
                             ["client"])),
}


def tool_definitions() -> list:
    """Tool list for the Messages API, in a fixed order so the prompt cache holds."""
    defs = [{"name": n, "description": d, "input_schema": s} for n, (_, d, s) in DATA_TOOLS.items()]
    defs += [{"name": n, "description": d + " Needs the attorney's confirmation before it runs.",
              "input_schema": s} for n, (_, _, _, d, s) in ACTION_TOOLS.items()]
    return defs


def is_action(name: str) -> bool:
    return name in ACTION_TOOLS


def run_data_tool(attorney: str, name: str, inp: dict) -> str:
    fn = DATA_TOOLS[name][0]
    return fn(attorney, **(inp or {}))


def prepare_action(attorney: str, name: str, inp: dict) -> dict:
    """Validate a proposed action and describe it for the confirm card."""
    prep, _, title, _, _ = ACTION_TOOLS[name]
    summary = prep(attorney, inp or {})[-1]
    return {"title": title, "summary": summary}


def run_action(attorney: str, name: str, inp: dict) -> str:
    return ACTION_TOOLS[name][1](attorney, inp or {})
