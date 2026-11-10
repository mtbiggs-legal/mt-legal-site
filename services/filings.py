"""services/filings.py — court filing packages.

prefill() reads everything the client file already knows (court, county,
case number, our client's side, the parties to serve) so the attorney is only
asked for what's missing. prepare() builds one PDF: the document, then a
certificate of service and signature block. What the attorney fills in is
saved back to the client file, so the next package for the case needs nothing.

Nothing here files with a court. The attorney files through the court's own
system, then mark_filed() stores the file-stamped copy and the hearing date.
The /s/ signature goes on only when the attorney ticks the approval box.
"""

import re
import secrets
from datetime import date, datetime

import shared
from services import client_files
from services import storage

PACKAGE_CATEGORY = "Filing Packages"
SOURCE_EXTS = {".pdf", ".txt"}
SERVICE_METHODS = ("email", "U.S. Mail", "hand delivery", "the Court's electronic filing system")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FilingError(Exception):
    """A problem to show the attorney."""


# ── Pre-fill ─────────────────────────────────────────────────────────────────

def _client_role(client: dict) -> str:
    if client.get("filing_role"):
        return client["filing_role"]
    ct = (client.get("case_type") or "").lower()
    return "Defendant" if "criminal" in ct else ""


def _default_service(client: dict) -> list:
    """Saved service list, else one row per opposing party (address still blank).
    A criminal case is served on the District Attorney General."""
    if client.get("service_list"):
        return [dict(s) for s in client["service_list"]]
    rows = []
    if "criminal" in (client.get("case_type") or "").lower():
        county = client.get("county") or ""
        rows.append({"name": "Office of the District Attorney General" + (f", {county} County" if county else ""),
                     "role": "Counsel for the State of Tennessee", "address": "", "method": "email"})
    for name in client.get("opposing_parties") or []:
        if "criminal" in (client.get("case_type") or "").lower() and name.lower().startswith("state of"):
            continue
        rows.append({"name": name, "role": "Opposing party", "address": "", "method": "email"})
    return rows


def prefill(client: dict) -> dict:
    """Everything the form can fill in from the file, and the list of what's missing."""
    fields = {
        "court":       client.get("court", ""),
        "county":      client.get("county", ""),
        "case_no":     client.get("case_no", ""),
        "client_name": client.get("client_name", ""),
        "client_role": _client_role(client),
        "opposing":    ", ".join(client.get("opposing_parties") or []),
        "service":     _default_service(client),
    }
    missing = [k for k in ("court", "county", "case_no", "client_role") if not fields[k]]
    if not fields["service"]:
        missing.append("service")
    elif any(not (s.get("address") or "").strip() for s in fields["service"]):
        missing.append("service addresses")
    return {"fields": fields, "missing": missing}


# ── Validation ───────────────────────────────────────────────────────────────

def _text(v, limit=300) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def clean_fields(data: dict) -> dict:
    f = {k: _text(data.get(k)) for k in ("court", "county", "case_no", "client_name", "client_role",
                                          "opposing", "title")}
    service = []
    for s in data.get("service") or []:
        row = {"name": _text(s.get("name"), 200), "role": _text(s.get("role"), 120),
               "address": _text(s.get("address"), 300), "method": _text(s.get("method"), 60) or "email"}
        if row["name"]:
            service.append(row)
    f["service"] = service[:12]
    missing = [label for key, label in (("court", "court"), ("county", "county"), ("case_no", "case number"),
                                        ("client_role", "your client's side"))
               if not f[key]]
    if not service:
        missing.append("at least one party to serve")
    elif any(not s["address"] for s in service):
        missing.append("a service address (email or mailing) for every party")
    if missing:
        raise FilingError("Still needed: " + ", ".join(missing) + ".")
    return f


# ── Content ──────────────────────────────────────────────────────────────────

def signature_block(approved: bool, role: str) -> list:
    p = shared.MANAGING_PARTNER
    bpr = shared.ATTORNEY_BPR or "________"
    lines = [f"/s/ {p['name']}" if approved else "______________________________",
             f"{p['name']}, BPR No. {bpr}", shared.FIRM_NAME]
    if shared.FIRM_ADDRESS:
        lines += [part.strip() for part in shared.FIRM_ADDRESS.split(";") if part.strip()]
    phone = shared._env("FIRM_PHONE")
    email = shared._env("FIRM_EMAIL")
    if phone:
        lines.append(f"Phone: {phone}")
    if email:
        lines.append(f"Email: {email}")
    lines.append(f"Counsel for {role or '[Party]'}")
    return lines


def certificate_of_service(f: dict, approved: bool) -> list:
    """Paragraphs of the certificate of service."""
    today = date.today()
    served = []
    for s in f["service"]:
        line = s["name"] + (f", {s['role']}" if s["role"] else "") + f", {s['address']}"
        served.append(f"{line} (via {s['method']})")
    sig = signature_block(approved, f["client_role"])
    return (["CERTIFICATE OF SERVICE",
             f"I hereby certify that a true and exact copy of the foregoing has been served on the "
             f"following on {today:%B} {today.day}, {today.year}:"]
            + served + [""] + sig)


def caption(f: dict) -> list:
    return [f"IN THE {f['court'].upper()}", f"FOR {f['county'].upper()} COUNTY, TENNESSEE",
            f"Case No. {f['case_no']}"]


def checklist(f: dict, source_ext: str) -> list:
    """Things to confirm before filing, tailored to the court. Local rules govern."""
    court = f["court"].lower()
    items = [
        f"Caption shows {f['court']}, {f['county']} County, Case No. {f['case_no']}.",
        "You have read the final document and signed it (Tenn. R. Civ. P. 11 / Tenn. R. Crim. P. 49).",
        "Certificate of service lists every party or counsel of record, with method and date.",
        f"File through the clerk's e-filing system for {f['county']} County, or in person if the court "
        "doesn't accept e-filing for this case type.",
    ]
    if "general sessions" in court:
        items.append("General Sessions: confirm whether the clerk accepts this filing electronically.")
    if "criminal" in court or "criminal" in f.get("client_role", "").lower():
        items.append("Criminal matter: serve the District Attorney General's office assigned to the case.")
    if re.search(r"\bmotion\b", f.get("title", "").lower()):
        items += ["Motion: attach a proposed order if the court's local rules require one.",
                  "Motion: set it for hearing and serve a notice of hearing (check the docket's motion days)."]
    if re.search(r"complaint|petition|civil warrant", f.get("title", "").lower()):
        items += ["New case: pay the filing fee and file a civil cover sheet if required.",
                  "New case: have the clerk issue summons for each defendant/respondent."]
    if source_ext == ".txt":
        items.append("The document was plain text; check its formatting in the package before filing.")
    items.append("After filing, upload the file-stamped copy here and add any hearing date.")
    return items


# ── PDF ──────────────────────────────────────────────────────────────────────

def _latin1(s: str) -> str:
    table = {"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
             "…": "...", " ": " ", "•": "-"}
    s = "".join(table.get(ch, ch) for ch in s)
    return s.encode("latin-1", "replace").decode("latin-1")


def _text_pdf(f: dict, body: str = None, cert: list = None) -> bytes:
    from fpdf import FPDF
    pdf = FPDF(format="Letter")
    pdf.set_margins(25, 22, 25)
    pdf.set_auto_page_break(True, 22)
    if body is not None:
        pdf.add_page()
        pdf.set_font("Times", "B", 12)
        for line in caption(f):
            pdf.cell(0, 6, _latin1(line), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Times", "", 12)
        pdf.multi_cell(0, 6, _latin1(body), new_x="LMARGIN", new_y="NEXT")
    if cert:
        pdf.add_page()
        pdf.set_font("Times", "B", 12)
        pdf.cell(0, 8, _latin1(cert[0]), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Times", "", 12)
        for para in cert[1:]:
            pdf.multi_cell(0, 6, _latin1(para), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
    return bytes(pdf.output())


def render_package(source_path, f: dict, approved: bool) -> bytes:
    """The document followed by the certificate of service, as one PDF."""
    if not shared.FPDF_AVAILABLE:
        raise FilingError("PDF tools aren't installed (fpdf2). Run: pip install -r requirements.txt")
    from services import client_files
    cert = certificate_of_service(f, approved)
    ext = source_path.suffix.lower()
    if ext == ".txt":
        return _text_pdf(f, body=client_files.read_text(source_path), cert=cert)
    if not shared.PYPDF_AVAILABLE:
        raise FilingError("PDF tools aren't installed (pypdf). Run: pip install -r requirements.txt")
    import io
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for src in (PdfReader(io.BytesIO(client_files.read_bytes(source_path))),
                PdfReader(io.BytesIO(_text_pdf(f, cert=cert)))):
        for page in src.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ── Prepare / mark filed ─────────────────────────────────────────────────────

def prepare(username: str, category: str, filename: str, data: dict, prepared_by: str) -> dict:
    from services.documents import resolve_doc_path
    path = resolve_doc_path(username, category, filename)
    if path is None:
        raise FilingError("That document isn't in the client's file.")
    if path.suffix.lower() not in SOURCE_EXTS:
        raise FilingError("Filing packages need the final document as a PDF (or plain text). "
                          "Save or print it to PDF, upload it, and prepare the package from that.")
    f = clean_fields(data)
    f["title"] = f.get("title") or path.stem.replace("_", " ")
    approved = bool(data.get("approve_signature"))
    pdf = render_package(path, f, approved)

    folder = storage._client_docs_dir(username, PACKAGE_CATEGORY)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem)[:70] or "filing"
    dest = folder / f"{stem}_filing_package.pdf"
    n = 2
    while dest.exists():
        dest = folder / f"{stem}_filing_package_{n}.pdf"
        n += 1
    client_files.write_path(dest, pdf)

    entry = {"id": "f_" + secrets.token_hex(5), "title": f["title"], "document": f"{category}/{path.name}",
             "package": f"{PACKAGE_CATEGORY}/{dest.name}", "court": f["court"], "county": f["county"],
             "case_no": f["case_no"], "signature_approved": approved, "status": "prepared",
             "prepared_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "prepared_by": prepared_by,
             "checklist": checklist(f, path.suffix.lower())}

    def mutate(c):
        # Save what the attorney filled in, so the next package is pre-filled.
        for key in ("court", "county", "case_no"):
            if not c.get(key):
                c[key] = f[key]
        c["filing_role"] = f["client_role"]
        c["service_list"] = f["service"]
        c.setdefault("filings", []).append(entry)

    storage.update_client_atomic(username, mutate)
    storage._log_activity(username, "filing_prepared", f"Filing package prepared: {f['title']}")
    return entry


def mark_filed(username: str, filing_id: str, upload, category: str, hearing_date: str,
               hearing_label: str = "") -> dict:
    """Store the file-stamped copy and any hearing date for a prepared filing."""
    from werkzeug.utils import secure_filename
    client = storage.load_client(username) or {}
    entry = next((e for e in client.get("filings") or [] if e["id"] == filing_id), None)
    if not entry:
        raise FilingError("Filing not found.")
    if category not in shared.DOCS_CATEGORIES:
        category = "Court Orders"
    hearing_date = (hearing_date or "").strip()
    if hearing_date and not _DATE_RE.match(hearing_date):
        raise FilingError("Hearing date must be YYYY-MM-DD.")

    stamped = ""
    if upload is not None and getattr(upload, "filename", ""):
        name = secure_filename(upload.filename)
        if not name or "." + name.rsplit(".", 1)[-1].lower() not in shared.ALLOWED_DOC_EXTENSIONS:
            raise FilingError("That file type can't be stored.")
        folder = storage._client_docs_dir(username, category)
        dest = folder / f"FILED_{name}"
        n = 2
        while dest.exists():
            dest = folder / f"FILED_{n}_{name}"
            n += 1
        client_files.write_path(dest, upload.read())
        stamped = f"{category}/{dest.name}"

    label = (hearing_label or "").strip()[:80] or f"Hearing: {entry['title']}"[:80]
    gcal_id = None
    if hearing_date:
        from services.gcal import gcal_create_all_day
        gcal_id = gcal_create_all_day(f"{label} - {client.get('client_name', username)}",
                                      f"{entry['court']}, Case No. {entry['case_no']}", hearing_date)

    def mutate(c):
        for e in c.get("filings") or []:
            if e["id"] == filing_id:
                e["status"] = "filed"
                e["filed_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                if stamped:
                    e["stamped_file"] = stamped
                if hearing_date:
                    e["hearing_date"] = hearing_date
                    e["hearing_label"] = label
                    if gcal_id:
                        e["hearing_gcal_event_id"] = gcal_id
        # The next court date is the earliest upcoming one.
        if hearing_date and hearing_date >= date.today().isoformat():
            cur = c.get("next_court_date") or ""
            if not cur or cur < date.today().isoformat() or hearing_date < cur:
                c["next_court_date"] = hearing_date

    saved = storage.update_client_atomic(username, mutate)
    storage._log_activity(username, "filing_filed",
                          f"Filed: {entry['title']}" + (f"; hearing {hearing_date}" if hearing_date else ""))
    return next(e for e in saved["filings"] if e["id"] == filing_id)


def list_filings(client: dict) -> list:
    return list(reversed(client.get("filings") or []))
