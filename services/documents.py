"""services/documents.py — client intake PDF/HTML and document text extraction."""

from datetime import datetime

from werkzeug.utils import secure_filename

import shared
from shared import DOCS_CATEGORIES, FPDF_AVAILABLE, MAMMOTH_AVAILABLE, PYPDF_AVAILABLE
from services.storage import safe_username


# ── PDF / HTML Generators ──────────────────────────────────────────────────────

def generate_client_pdf(fields: dict):
    """Generate a professional intake/profile PDF. Returns bytes or None if fpdf2 unavailable."""
    if not FPDF_AVAILABLE:
        return None

    from fpdf import FPDF

    NAVY  = (26,  45,  90)
    GOLD  = (201, 168, 76)
    GRAY  = (120, 120, 120)
    BLACK = (30,  30,  30)
    LGRAY = (245, 246, 250)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 38, 'F')
    pdf.set_y(9)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(201, 168, 76)
    pdf.cell(0, 8, "MT LEGAL", align="C", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(200, 200, 200)
    pdf.cell(0, 5, "Client Intake & Profile Record  --  Confidential / Attorney-Client Privilege", align="C", ln=True)
    pdf.set_y(44)

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", align="R", ln=True)
    pdf.ln(2)

    def section(title):
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 7, f"  {title}", ln=True, fill=True)
        pdf.ln(2)

    def row(label, value, full=False):
        if not value:
            return
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(40, 6, label + ":", ln=False)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*BLACK)
        if full:
            pdf.multi_cell(0, 6, str(value))
        else:
            pdf.cell(0, 6, str(value), ln=True)

    def full_row(label, value):
        if not value:
            return
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 6, label + ":", ln=True)
        pdf.set_fill_color(*LGRAY)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*BLACK)
        pdf.multi_cell(0, 6, str(value), fill=True, border=0)
        pdf.ln(2)

    section("CLIENT INFORMATION")
    row("Full Name",      fields.get("full_name") or fields.get("client_name", ""))
    row("Case Number",    fields.get("case_no", ""))
    row("Date of Birth",  fields.get("dob", ""))
    row("Phone",          fields.get("phone", ""))
    row("Email",          fields.get("email", ""))
    row("Case Type",      fields.get("case_type", ""))
    row("Referral",       fields.get("referral_source", ""))
    pdf.ln(3)

    section("PORTAL ACCOUNT")
    row("Username",          fields.get("portal_username", fields.get("username", "")))
    row("Assigned Attorney", fields.get("atty_display", fields.get("assigned_attorney", "")))
    pdf.ln(3)

    matter = fields.get("matter_description") or fields.get("legal_issue", "")
    if matter:
        section("MATTER DESCRIPTION")
        full_row("", matter)
        pdf.ln(1)

    arrest = fields.get("arrest_date", "")
    court  = fields.get("court_date_1", "")
    if arrest or court:
        section("KEY DATES")
        if arrest: row("Arrest Date", arrest)
        if court:  row("Court Date",  court)
        pdf.ln(3)

    urgent = fields.get("urgent_dates", [])
    if urgent:
        pdf.set_fill_color(255, 235, 235)
        pdf.set_draw_color(200, 50, 50)
        pdf.rect(18, pdf.get_y(), 174, 8 + len(urgent) * 6, 'DF')
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 8, "  URGENT DEADLINES", ln=True)
        pdf.set_font("Helvetica", "", 8)
        for d in urgent:
            pdf.cell(0, 6, f"    !  {d['label']}: {d['date']}  ({d['days_away']} days away)", ln=True)
        pdf.ln(4)

    pdf.set_y(-22)
    pdf.set_draw_color(*GOLD)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 5, "All information contained herein is protected by attorney-client privilege.  "
                   "MT Legal  --  Strictly Confidential", align="C")

    return bytes(pdf.output())


def generate_intake_html(data, urgent_dates, portal_username, atty_display):
    """Return a styled HTML string representing the submitted intake form."""
    def e(v):
        return str(v or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    urgent_section = ""
    if urgent_dates:
        items = "".join(
            f'<div class="urgent-item">&#9888; {e(d["label"])}: {e(d["date"])} '
            f'({e(d["days_away"])} days away)</div>'
            for d in urgent_dates
        )
        urgent_section = (
            f'<div class="urgent-box">'
            f'<div class="urgent-title">URGENT DEADLINES</div>{items}</div>'
        )

    submitted = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    matter = e(data.get("matter_description", "")).replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Client Intake &mdash; {e(data.get('full_name',''))}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 2rem; background: #f4f6fa; color: #333; }}
    .doc {{ max-width: 720px; margin: 0 auto; background: #fff; border-radius: 8px; padding: 2.5rem 3rem; box-shadow: 0 2px 14px rgba(0,0,0,.1); }}
    .hdr {{ text-align: center; border-bottom: 2px solid #1a2d5a; padding-bottom: 1.25rem; margin-bottom: 1.75rem; }}
    .firm {{ font-size: 1.45rem; font-weight: bold; color: #1a2d5a; font-family: Georgia, serif; letter-spacing: .02em; }}
    .sub  {{ font-size: .9rem; color: #888; margin-top: .3rem; }}
    .sec  {{ font-family: Georgia, serif; font-size: .95rem; color: #1a2d5a; font-weight: bold;
             border-bottom: 1px solid #dde2ee; padding-bottom: .35rem; margin: 1.5rem 0 .8rem; }}
    .row  {{ display: flex; margin-bottom: .55rem; gap: .5rem; }}
    .lbl  {{ font-weight: bold; min-width: 170px; font-size: .85rem; color: #666; flex-shrink: 0; }}
    .val  {{ font-size: .85rem; color: #222; }}
    .matter {{ background: #f7f8fc; border-left: 3px solid #1a2d5a; border-radius: 0 4px 4px 0;
               padding: .75rem 1rem; font-size: .88rem; line-height: 1.65; margin-top: .2rem; }}
    .urgent {{ background: #fff5f5; border: 1px solid #e53935; border-radius: 4px; padding: .75rem 1rem; margin-top: 1rem; }}
    .urgent-title {{ color: #c62828; font-weight: bold; font-size: .85rem; margin-bottom: .4rem; }}
    .urgent-item  {{ font-size: .83rem; color: #b71c1c; margin-bottom: .2rem; }}
    .atty {{ background: #f0f4ff; border-radius: 4px; padding: .7rem 1rem; font-size: .84rem; color: #1a2d5a; margin-top: .25rem; }}
    .ftr  {{ text-align: center; font-size: .73rem; color: #bbb; margin-top: 2rem;
             border-top: 1px solid #eee; padding-top: 1rem; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="doc">
    <div class="hdr">
      <div class="firm">MT Legal</div>
      <div class="sub">Client Intake Form &mdash; {e(submitted)}</div>
    </div>

    <div class="sec">Client Information</div>
    <div class="row"><div class="lbl">Full Name</div><div class="val">{e(data.get('full_name',''))}</div></div>
    <div class="row"><div class="lbl">Date of Birth</div><div class="val">{e(data.get('dob',''))}</div></div>
    <div class="row"><div class="lbl">Phone</div><div class="val">{e(data.get('phone',''))}</div></div>
    <div class="row"><div class="lbl">Email</div><div class="val">{e(data.get('email',''))}</div></div>
    <div class="row"><div class="lbl">Case Type</div><div class="val">{e(data.get('case_type',''))}</div></div>
    <div class="row"><div class="lbl">Referral Source</div><div class="val">{e(data.get('referral_source',''))}</div></div>

    <div class="sec">Matter Description</div>
    <div class="matter">{matter}</div>

    <div class="sec">Key Dates</div>
    <div class="row"><div class="lbl">Arrest Date</div><div class="val">{e(data.get('arrest_date',''))}</div></div>
    <div class="row"><div class="lbl">Court Date</div><div class="val">{e(data.get('court_date_1',''))}</div></div>
    {urgent_section}

    <div class="sec">Portal Account</div>
    <div class="row"><div class="lbl">Username</div><div class="val">{e(portal_username)}</div></div>
    <div class="row"><div class="lbl">Assigned Attorney</div><div class="atty">{e(atty_display)}</div></div>

    <div class="ftr">
      All information contained herein is protected by attorney&ndash;client privilege.<br>
      MT Legal &mdash; Strictly Confidential
    </div>
  </div>
</body>
</html>"""


# ── Document text extraction ───────────────────────────────────────────────────

def resolve_doc_path(username, category, filename):
    """Return the on-disk path of a client document, or None if it is not valid.

    Sanitises both the username and the filename so a crafted value cannot walk
    out of CLIENT_FILES_DIR, and confirms the category is a known one.
    """
    uname     = safe_username(username)
    safe_name = secure_filename(filename or "")
    if not uname or not safe_name or category not in DOCS_CATEGORIES:
        return None
    path = shared.CLIENT_FILES_DIR / uname / "documents" / category / safe_name
    return path if path.is_file() else None


def extract_document_text(username, category, filename):
    """Extract plain text from a client document for AI analysis.
    Returns (text, error_string) — one of the two will be None."""
    path = resolve_doc_path(username, category, filename)
    if path is None:
        return None, "File not found."
    ext = path.suffix.lower()
    try:
        if ext in (".txt", ".rtf", ".html"):
            return path.read_text(encoding="utf-8", errors="replace"), None
        elif ext == ".docx" and MAMMOTH_AVAILABLE:
            import mammoth
            with open(path, "rb") as f:
                result = mammoth.extract_raw_text(f)
            return result.value, None
        elif ext == ".pdf" and PYPDF_AVAILABLE:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if text.strip():
                return text, None
            return None, "PDF contains no extractable text (may be scanned)."
        else:
            return None, f"Text extraction not available for {ext} files."
    except Exception as exc:
        return None, f"Could not read file: {str(exc)}"
