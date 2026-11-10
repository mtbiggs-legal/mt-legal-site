"""services/felony.py — felony case checklist and the automatic discovery request.

Felony clients get a checklist of case milestones (arraignment, discovery,
body cam, ...). Once a felony case is the firm's in a trial court (Criminal
or Circuit Court with a case number), or the attorney checks "arraigned /
waiver filed", a Request for Discovery under Tenn. R. Crim. P. 16 is drafted
from the client file and saved to the attorney-only Drafts folder, once per
case. The attorney reviews, signs and files it.

after_client_save() runs after every client save (storage calls it outside
the client lock), so the draft appears whichever way the case info changed.
"""

import re
import sys
from datetime import date, datetime

import shared
from services import client_files
from services import storage

DRAFT_CATEGORY = "Drafts"
ARRAIGNMENT = "arraignment"
CHECKLIST = (
    (ARRAIGNMENT, "Arraigned or waiver of arraignment filed"),
    ("discovery_filed", "Discovery request filed"),
    ("discovery_received", "Discovery received from the State"),
    ("bodycam", "Body cam / dash cam video received"),
    ("dispatch", "911 calls / dispatch audio received"),
    ("lab", "Lab reports received (drugs, blood, DNA)"),
    ("reviewed", "Discovery reviewed with the client"),
    ("motions", "Motions deadline calendared"),
)
CHECKLIST_LABELS = dict(CHECKLIST)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def is_felony(client: dict) -> bool:
    return str((client or {}).get("charge_level") or "").strip().lower() == "felony"


def in_trial_court(client: dict) -> bool:
    """Felony cases are arraigned in Criminal Court (or Circuit Court in
    counties without one) after indictment or bind-over."""
    court = str(client.get("court") or "").lower()
    return ("criminal court" in court or "circuit court" in court) and "general sessions" not in court


def checklist_view(client: dict) -> list:
    """The checklist for the portal and the assistant ([] for non-felony clients)."""
    if not is_felony(client):
        return []
    state = client.get("felony_checklist") if isinstance(client.get("felony_checklist"), dict) else {}
    out = []
    for key, label in CHECKLIST:
        item = state.get(key) if isinstance(state.get(key), dict) else {}
        out.append({"key": key, "label": label, "done": bool(item.get("done")),
                    "at": item.get("at", ""), "by": item.get("by", "")})
    return out


def should_draft(client: dict) -> bool:
    if not is_felony(client) or client.get("archived"):
        return False
    if isinstance(client.get("discovery_draft"), dict):
        return False                                # once per case
    arraigned = ((client.get("felony_checklist") or {}).get(ARRAIGNMENT) or {}).get("done")
    return bool(arraigned) or (in_trial_court(client) and bool(str(client.get("case_no") or "").strip()))


def set_item(username: str, key: str, done: bool, by: str):
    """Check or uncheck one checklist item. Returns the saved client, or None."""
    if key not in CHECKLIST_LABELS:
        raise ValueError("Unknown checklist item.")

    def mutate(client):
        if not is_felony(client):
            raise ValueError("The checklist is for felony cases.")
        state = client.get("felony_checklist")
        if not isinstance(state, dict):
            state = client["felony_checklist"] = {}
        state[key] = {"done": bool(done), "at": _now() if done else "", "by": by if done else ""}
        client.setdefault("activity_log", []).append({
            "timestamp": _now(), "action_type": "checklist",
            "description": f"{'Checked' if done else 'Unchecked'}: {CHECKLIST_LABELS[key]}"})
    return storage.update_client_atomic(username, mutate)


# ── The discovery request ────────────────────────────────────────────────────

def _court_parts(client: dict):
    """("CRIMINAL COURT", "DAVIDSON") from "Davidson County Criminal Court"."""
    court = str(client.get("court") or "").strip()
    county = str(client.get("county") or "").strip()
    m = re.match(r"(?i)^\s*(.+?)\s+county\s+(.+)$", court)
    if m:
        county = county or m.group(1)
        kind = m.group(2)
    else:
        kind = court or "Criminal Court"
    county = re.sub(r"(?i)\s+county$", "", county).strip()
    return kind.upper(), (county.upper() or "[COUNTY]")


def discovery_request_text(client: dict) -> str:
    from services.assistant import _signature_block
    kind, county = _court_parts(client)
    name = (client.get("client_name") or client.get("username") or "").strip()
    case_no = str(client.get("case_no") or "").strip() or "[CASE NUMBER]"
    charges = str(client.get("charges") or "").strip()
    today = date.today()
    sig = _signature_block()
    lines = [
        f"IN THE {kind} FOR {county} COUNTY, TENNESSEE",
        "DIVISION [__]",
        "STATE OF TENNESSEE,",
        "v.",
        f"{name.upper()},",
        "Defendant.",
        f"Case No. {case_no}",
        "DEFENDANT'S REQUEST FOR DISCOVERY AND INSPECTION",
        f"The Defendant, {name}, by and through counsel, and pursuant to Rule 16 of the Tennessee "
        "Rules of Criminal Procedure, the Due Process Clause of the Fourteenth Amendment to the "
        "United States Constitution, Article I, Sections 8 and 9 of the Tennessee Constitution, "
        "Brady v. Maryland, 373 U.S. 83 (1963), and Giglio v. United States, 405 U.S. 150 (1972), "
        "requests that the State of Tennessee disclose and permit the Defendant to inspect, copy "
        "or photograph the following materials within the possession, custody or control of the "
        "State, the existence of which is known or by the exercise of due diligence may become "
        "known to the District Attorney General:"
        + (f" The Defendant is charged with {charges}." if charges else ""),
        "1. The substance of any oral statement made by the Defendant, before or after arrest, in "
        "response to interrogation by any person then known to the Defendant to be a law "
        "enforcement officer, that the State intends to offer in evidence at trial. Tenn. R. "
        "Crim. P. 16(a)(1).",
        "2. Any relevant written or recorded statement made by the Defendant, including any "
        "recorded testimony of the Defendant before a grand jury that relates to the offense "
        "charged. Tenn. R. Crim. P. 16(a)(1).",
        "3. A copy of the Defendant's prior criminal record, if any. Tenn. R. Crim. P. 16(a)(1).",
        "4. Books, papers, documents, photographs, tangible objects, buildings or places, or "
        "copies or portions thereof, that are material to the preparation of the defense, that "
        "the State intends to use in its case-in-chief at trial, or that were obtained from or "
        "belong to the Defendant. Tenn. R. Crim. P. 16(a)(1).",
        "5. Results or reports of physical or mental examinations and of scientific tests or "
        "experiments, including all laboratory reports, chain-of-custody records and testing "
        "data. Tenn. R. Crim. P. 16(a)(1).",
        "6. All audio and video recordings relating to this case, including body-worn camera, "
        "in-car (dash) camera, jail and booking recordings, and interview room recordings.",
        "7. All 911 calls, dispatch audio, and computer-aided dispatch (CAD) reports relating to "
        "this case.",
        "8. All search warrants, affidavits, returns and inventories relating to this case.",
        "9. All evidence favorable to the Defendant that is material to guilt or punishment, "
        "including evidence that impeaches the credibility of any State witness, together with "
        "any promises, inducements or agreements made to any witness. Brady v. Maryland; "
        "Giglio v. United States.",
        "10. Notice of any evidence the State intends to offer under Tennessee Rule of Evidence "
        "404(b), and notice under Tenn. R. Crim. P. 12(d) of the State's intention to use "
        "any evidence that the Defendant may be entitled to discover under Rule 16.",
        "The Defendant further requests that this request be treated as continuing, and that the "
        "State promptly disclose any additional material discovered before or during trial. "
        "Tenn. R. Crim. P. 16(c).",
        "Respectfully submitted,",
        *sig.split("\n"),
        f"Counsel for Defendant {name}",
        "CERTIFICATE OF SERVICE",
        f"I hereby certify that a true and exact copy of the foregoing has been served on the "
        f"Office of the District Attorney General for {county.title()} County, [ADDRESS], via "
        f"[METHOD], on this the ___ day of {today:%B}, {today.year}.",
        "______________________________",
        shared.MANAGING_PARTNER["display"],
    ]
    return "\n".join(lines)


def _claim(client: dict) -> None:
    """Run inside update_client_atomic: mark the draft as in progress if one is
    due, so two saves at once can't both draft it."""
    if should_draft(client):
        client["discovery_draft"] = {"status": "drafting", "at": _now()}


def maybe_draft_discovery(username: str):
    """Draft the discovery request if the case calls for it. Returns the saved
    file name, or None."""
    if not username or storage.safe_username(username) != username:
        return None
    client = storage.load_client(username)
    if not client or not should_draft(client):
        return None
    claimed = storage.update_client_atomic(username, _claim)
    if not claimed or (claimed.get("discovery_draft") or {}).get("status") != "drafting":
        return None
    try:
        from services.docx_writer import text_to_docx
        folder = storage._client_docs_dir(username, DRAFT_CATEGORY)
        stem = f"DRAFT_Request_for_Discovery_{date.today():%Y%m%d}"
        dest, n = folder / f"{stem}.docx", 2
        while dest.exists():
            dest, n = folder / f"{stem}_{n}.docx", n + 1
        client_files.write_path(dest, text_to_docx("Request for Discovery", discovery_request_text(claimed),
                                      shared.MANAGING_PARTNER["display"]))
    except Exception as exc:
        storage.update_client_atomic(username, lambda c: c.pop("discovery_draft", None))
        print(f"[felony] discovery draft failed for {username}: {exc!r}", file=sys.stderr)
        return None

    def done(c):
        c["discovery_draft"] = {"status": "ready", "at": _now(), "category": DRAFT_CATEGORY,
                                "filename": dest.name, "reviewed": False}
        c.setdefault("activity_log", []).append({
            "timestamp": _now(), "action_type": "document_generated",
            "description": f"Request for Discovery drafted automatically: {DRAFT_CATEGORY}/{dest.name}"})
    storage.update_client_atomic(username, done)
    return dest.name


def mark_reviewed(username: str):
    def mutate(c):
        d = c.get("discovery_draft")
        if isinstance(d, dict) and d.get("status") == "ready":
            d["reviewed"] = True
    return storage.update_client_atomic(username, mutate)


def pending_reviews(clients) -> list:
    """Discovery drafts the attorney hasn't reviewed yet (for the dashboard)."""
    out = []
    for c in clients:
        d = c.get("discovery_draft")
        if isinstance(d, dict) and d.get("status") == "ready" and not d.get("reviewed"):
            out.append({"username": c.get("username", ""),
                        "client_name": c.get("client_name") or c.get("username", ""),
                        "kind": "discovery_draft",
                        "text": "Request for Discovery drafted — ready to review",
                        "category": d.get("category", DRAFT_CATEGORY),
                        "filename": d.get("filename", ""), "at": d.get("at", "")})
    return out


_running = set()


def after_client_save(username: str) -> None:
    """Called by storage after every client save, outside the client lock."""
    if username in _running:
        return                                       # the draft's own saves
    _running.add(username)
    try:
        maybe_draft_discovery(username)
    except Exception as exc:
        print(f"[felony] after_client_save failed for {username}: {exc!r}", file=sys.stderr)
    finally:
        _running.discard(username)
