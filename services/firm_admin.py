"""services/firm_admin.py — firm compliance deadlines, reminders and records.

Tracks the firm's own obligations (BPR registration, CLE, professional
privilege tax, estimated taxes, PLLC annual report, malpractice renewal...).
Each obligation repeats yearly on one or more dates (MM-DD) or falls on a
single date. Reminders start 60 days out and step through 45, 30, 15, 10 and
5 days; they stop as soon as that occurrence is marked done, and the
completion is kept as a record (date, amount, confirmation number, note).

Everything lives in FIRM_SETTINGS_DIR/firm-admin.json (gitignored), written
atomically under a module lock.
"""

import re
import threading
import uuid
from datetime import date, datetime, timedelta

import shared
from services import storage

REMINDER_DAYS = (60, 45, 30, 15, 10, 5)
MAX_TITLE = 120
MAX_TEXT = 500
_lock = threading.Lock()
_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


class AdminError(ValueError):
    """A problem to show the attorney."""


def _path():
    return shared.FIRM_SETTINGS_DIR / "firm-admin.json"


def _today() -> date:
    return date.today()


def _defaults(start: str) -> list:
    def ob(key, title, category, dates, notes, active=True, link=""):
        return {"id": key, "title": title, "category": category,
                "schedule": {"repeat": "yearly", "dates": dates},
                "notes": notes, "link": link, "amount": "", "active": active, "start": start}
    return [
        ob("bpr", "BPR annual registration and fee", "Bar & licensing", [],
           "Tennessee Board of Professional Responsibility annual registration. Set the due date "
           "to match your registration notice.", link="https://www.tbpr.org/"),
        ob("iolta", "IOLTA / trust account certification", "Bar & licensing", [],
           "Certified with the BPR annual registration; set the same date."),
        ob("cle", "CLE: 15 hours (incl. 3 ethics / professionalism)", "Bar & licensing", ["12-31"],
           "Calendar-year compliance period. Check the Tennessee CLE Commission for the "
           "reporting deadline.", link="https://www.cletn.com/"),
        ob("privilege_tax", "Professional privilege tax", "Taxes", ["06-01"],
           "Tennessee professional privilege tax for licensed attorneys, filed through TNTAP.",
           link="https://tntap.tn.gov/"),
        ob("estimated_tax", "Quarterly estimated taxes (federal)", "Taxes",
           ["01-15", "04-15", "06-15", "09-15"], "IRS Form 1040-ES payments."),
        ob("pllc_report", "PLLC annual report (Secretary of State)", "Business entity", ["04-01"],
           "Due the 1st day of the 4th month after the fiscal year ends. Turn this on once "
           "MT Legal, PLLC is formed.", active=False, link="https://sos.tn.gov/"),
        ob("malpractice", "Malpractice insurance renewal", "Insurance", [],
           "Set to your policy renewal date."),
    ]


def _load() -> dict:
    data = storage.read_json(_path())
    if not isinstance(data, dict) or not isinstance(data.get("obligations"), list):
        if _path().exists():
            # Never overwrite a damaged file: it holds the records.
            raise AdminError("The firm admin file can't be read; it was left untouched.")
        data ={"obligations": _defaults(_today().isoformat()), "records": [], "reminders_sent": {}}
        storage.write_json(_path(), data)
    data.setdefault("records", [])
    data.setdefault("reminders_sent", {})
    return data


def _update(mutate):
    with _lock:
        data = _load()
        result = mutate(data)
        storage.write_json(_path(), data)
        return result


# ── Dates ────────────────────────────────────────────────────────────────────

def _on(year: int, mmdd: str) -> date:
    m, d = int(mmdd[:2]), int(mmdd[3:])
    while True:
        try:
            return date(year, m, d)
        except ValueError:                      # Feb 29, Apr 31 ... use the month's last day
            d -= 1


def occurrences(ob: dict, until: date) -> list:
    """Due dates from the obligation's start date through `until`, oldest first."""
    sched = ob.get("schedule") or {}
    try:
        start = date.fromisoformat(ob.get("start") or "")
    except ValueError:
        start = _today()
    if sched.get("repeat") == "once":
        try:
            d = date.fromisoformat(sched.get("date") or "")
        except ValueError:
            return []
        return [d] if d <= until else []
    out = []
    for year in range(start.year, until.year + 1):
        out += [_on(year, mmdd) for mmdd in sched.get("dates") or [] if _MMDD.match(mmdd)]
    return sorted(d for d in out if start <= d <= until)


def _done(data: dict, ob_id: str) -> set:
    return {r["due"] for r in data["records"] if r.get("obligation_id") == ob_id}


def next_open(data: dict, ob: dict, today: date):
    """The earliest due date not yet marked done (may be past = overdue), or None."""
    done = _done(data, ob["id"])
    for d in occurrences(ob, today + timedelta(days=800)):
        if d.isoformat() not in done:
            return d
    return None


def stage(days_left: int):
    """Which reminder applies: 'overdue', one of REMINDER_DAYS, or None (not yet)."""
    if days_left < 0:
        return "overdue"
    fits = [t for t in REMINDER_DAYS if days_left <= t]
    return min(fits) if fits else None


def _status(data: dict, ob: dict, today: date) -> dict:
    view = {k: ob.get(k) for k in ("id", "title", "category", "schedule", "notes", "link", "amount", "active")}
    recs = sorted((r for r in data["records"] if r.get("obligation_id") == ob["id"]),
                  key=lambda r: r["due"], reverse=True)
    view["last_record"] = recs[0] if recs else None
    nxt = next_open(data, ob, today) if ob.get("active", True) else None
    view["next_due"] = nxt.isoformat() if nxt else ""
    view["days_left"] = (nxt - today).days if nxt else None
    view["stage"] = stage(view["days_left"]) if nxt else None
    has_dates = bool((ob.get("schedule") or {}).get("dates")) or bool((ob.get("schedule") or {}).get("date"))
    if not ob.get("active", True):
        view["status"] = "off"
    elif not has_dates:
        view["status"] = "needs_date"
    elif view["stage"] == "overdue":
        view["status"] = "overdue"
    elif view["stage"] is not None:
        view["status"] = "due_soon"
    else:
        view["status"] = "ok"
    return view


def overview(today: date | None = None) -> dict:
    today = today or _today()
    with _lock:
        data = _load()
    obs = [_status(data, ob, today) for ob in data["obligations"]]
    order = {"overdue": 0, "due_soon": 1, "needs_date": 2, "ok": 3, "off": 4}
    obs.sort(key=lambda o: (order[o["status"]], o["next_due"] or "9999", o["title"]))
    names = {ob["id"]: ob["title"] for ob in data["obligations"]}
    records = [{**r, "title": names.get(r.get("obligation_id"), "(removed)")}
               for r in sorted(data["records"], key=lambda r: r.get("completed_at", ""), reverse=True)]
    return {"obligations": obs, "records": records, "reminder_days": list(REMINDER_DAYS)}


def reminder_text(o: dict) -> str:
    if o["stage"] == "overdue":
        return f"Overdue since {o['next_due']}"
    days = o["days_left"]
    return f"Due {o['next_due']} ({'today' if days == 0 else f'in {days} day' + ('s' if days != 1 else '')})"


def reminders(today: date | None = None) -> list:
    """Open reminders for the dashboard and the assistant: overdue, or due within 60 days."""
    out = []
    for o in overview(today)["obligations"]:
        if o["status"] in ("overdue", "due_soon"):
            out.append({"id": o["id"], "title": o["title"], "due": o["next_due"],
                        "days_left": o["days_left"], "stage": o["stage"], "text": reminder_text(o)})
    return out


# ── Changes ──────────────────────────────────────────────────────────────────

def _clean(s, limit=MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:limit]


def complete(ob_id: str, due: str, by: str, amount="", confirmation="", note="",
             completed_on: str = "") -> dict:
    """Mark one occurrence done and keep the record. Ends its reminders."""
    try:
        due_d = date.fromisoformat(str(due or ""))
    except ValueError:
        raise AdminError("Due date must be YYYY-MM-DD.")
    when = str(completed_on or "") or _today().isoformat()
    try:
        date.fromisoformat(when)
    except ValueError:
        raise AdminError("Completed date must be YYYY-MM-DD.")

    def mutate(data):
        ob = next((o for o in data["obligations"] if o["id"] == ob_id), None)
        if not ob:
            raise AdminError("Unknown item.")
        if due_d.isoformat() in _done(data, ob_id):
            raise AdminError("That due date is already marked done.")
        rec = {"id": uuid.uuid4().hex[:12], "obligation_id": ob_id, "due": due_d.isoformat(),
               "completed_on": when, "completed_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
               "by": by, "amount": _clean(amount, 40), "confirmation": _clean(confirmation, 80),
               "note": _clean(note)}
        data["records"].append(rec)
        return {**rec, "title": ob["title"]}
    return _update(mutate)


def delete_record(record_id: str) -> None:
    """Undo a completion entered by mistake (its reminders come back)."""
    def mutate(data):
        before = len(data["records"])
        data["records"] = [r for r in data["records"] if r.get("id") != record_id]
        if len(data["records"]) == before:
            raise AdminError("Record not found.")
    _update(mutate)


def save_obligation(fields: dict) -> dict:
    """Add an item (no id) or edit one. Dates: yearly MM-DD list, or a single YYYY-MM-DD."""
    title = _clean(fields.get("title"), MAX_TITLE)
    if not title:
        raise AdminError("Give the item a name.")
    repeat = fields.get("repeat") or "yearly"
    if repeat == "yearly":
        raw = fields.get("dates")
        raw = raw if isinstance(raw, list) else re.split(r"[,\s]+", str(raw or ""))
        dates = sorted({d.strip() for d in raw if str(d).strip()})
        bad = [d for d in dates if not _MMDD.match(d)]
        if bad:
            raise AdminError("Yearly dates must be MM-DD, e.g. 06-01.")
        schedule = {"repeat": "yearly", "dates": dates}
    elif repeat == "once":
        try:
            schedule = {"repeat": "once", "date": date.fromisoformat(str(fields.get("date") or "")).isoformat()}
        except ValueError:
            raise AdminError("Date must be YYYY-MM-DD.")
    else:
        raise AdminError("Repeat must be yearly or once.")
    clean = {"title": title, "category": _clean(fields.get("category"), 60) or "Other",
             "schedule": schedule, "notes": _clean(fields.get("notes")),
             "link": _clean(fields.get("link"), 300), "amount": _clean(fields.get("amount"), 40),
             "active": fields.get("active", True) is not False}
    if clean["link"] and not re.match(r"^https?://", clean["link"]):
        raise AdminError("Link must start with http:// or https://.")

    def mutate(data):
        ob_id = fields.get("id")
        if ob_id:
            ob = next((o for o in data["obligations"] if o["id"] == ob_id), None)
            if not ob:
                raise AdminError("Unknown item.")
            ob.update(clean)
            return ob
        ob = {"id": uuid.uuid4().hex[:10], **clean, "start": _today().isoformat()}
        data["obligations"].append(ob)
        return ob
    return _update(mutate)


def delete_obligation(ob_id: str) -> None:
    """Remove an item. Its past records stay in the history."""
    def mutate(data):
        before = len(data["obligations"])
        data["obligations"] = [o for o in data["obligations"] if o["id"] != ob_id]
        if len(data["obligations"]) == before:
            raise AdminError("Unknown item.")
    _update(mutate)


# ── Email reminders (local app, hourly) ──────────────────────────────────────

def claim_email_reminders(today: date | None = None) -> list:
    """Reminders whose step (60, 45, ... days, or overdue) hasn't been emailed
    yet. Marks them sent, along with any earlier steps the app missed while it
    was off, so each step goes out at most once."""
    today = today or _today()

    def mutate(data):
        due_now = []
        for ob in data["obligations"]:
            if not ob.get("active", True):
                continue
            nxt = next_open(data, ob, today)
            if not nxt:
                continue
            st = stage((nxt - today).days)
            if st is None:
                continue
            key = f"{ob['id']}|{nxt.isoformat()}"
            sent = data["reminders_sent"].setdefault(key, [])
            label = str(st)
            if label in sent:
                continue
            steps = [str(t) for t in REMINDER_DAYS if st == "overdue" or t >= st] + ([label] if st == "overdue" else [])
            sent.extend(s for s in steps if s not in sent)
            o = _status(data, ob, today)
            due_now.append({"title": ob["title"], "due": o["next_due"], "text": reminder_text(o)})
        return due_now
    return _update(mutate)
