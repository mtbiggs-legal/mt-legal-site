"""blueprints/portal_attorney.py — Attorney portal: dashboard, clients, documents, research, insights."""

import json
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import (
    Blueprint, render_template, request, jsonify, session,
    current_app, send_file,
)
from werkzeug.utils import secure_filename

import billing
from shared import (
    require_attorney, require_auth,
    ATTORNEYS, CASE_ATTORNEY_MAP, HOURLY_RATE,
    MONTHLY_RENT, MONTHLY_SALARIES, MONTHLY_SOFTWARE,
    MONTHLY_INSURANCE, MONTHLY_MARKETING, MONTHLY_MISC,
    OVERHEAD_RESERVE_PCT,
    CLIENT_FILES_DIR, CLIENT_ACCOUNTS_DIR,
    LEADS_DIR, RESEARCH_HISTORY_DIR, DRAFT_HISTORY_DIR,
    TOKEN_USAGE_DIR, CASE_SEARCHES_DIR,
    GOOGLE_LIBS, TOKEN_FILE,
    MAMMOTH_AVAILABLE, PYPDF_AVAILABLE, FPDF_AVAILABLE,
    DOCS_CATEGORIES, ALLOWED_DOC_EXTENSIONS,
    MODEL, get_anthropic_client,
    load_client, save_client, all_clients,
    _client_docs_dir, hash_password, safe_username, recalc_hours,
    _log_activity, _log_token_usage,
    acceptable_password, generate_temp_password, log_access_atomic,
    can_access_client, load_client_for_attorney, public_client_view, _log_access,
    update_client_atomic,
    get_calendar_service, _push_court_date_to_gcal, _fetch_gcal_events,
    gcal_create_all_day, gcal_update_all_day, gcal_delete_event, gcal_connected,
)
from scheduling_orders import extract_case_dates, ExtractionError, CASE_DATE_KINDS, CASE_DATE_LABELS
from conflicts import (
    DECISIONS, append_firm_log, clean_names, clean_related, has_unresolved_conflict,
    hit_message, make_check_record, record_check, redact_checks, redact_hits,
    run_conflict_check,
)

portal_attorney_bp = Blueprint("portal_attorney", __name__)


# ── PDF / HTML Generators ──────────────────────────────────────────────────────

def _generate_client_pdf(fields: dict):
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


def _generate_intake_html(data, urgent_dates, portal_username, atty_display):
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

def _resolve_doc_path(username, category, filename):
    """Return the on-disk path of a client document, or None if it is not valid.

    Sanitises both the username and the filename so a crafted value cannot walk
    out of CLIENT_FILES_DIR, and confirms the category is a known one.
    """
    uname     = safe_username(username)
    safe_name = secure_filename(filename or "")
    if not uname or not safe_name or category not in DOCS_CATEGORIES:
        return None
    path = CLIENT_FILES_DIR / uname / "documents" / category / safe_name
    return path if path.is_file() else None


def _extract_document_text(username, category, filename):
    """Extract plain text from a client document for AI analysis.
    Returns (text, error_string) — one of the two will be None."""
    path = _resolve_doc_path(username, category, filename)
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


# ── Research prompts ───────────────────────────────────────────────────────────

_RESEARCH_ANALYZE_PROMPT = """You are a senior criminal defense attorney conducting an initial case analysis.
Given a client's case description, identify 3-6 key legal issues in structured format.
For each issue output EXACTLY this format (no other text before or after):

ISSUE [N]: [Brief Title]
Description: [1-2 sentences explaining the issue]
Defense Significance: [Why this matters and what it may support]

Identify: constitutional violations (4th/5th/6th/14th Amendment), procedural defects, evidentiary issues, viable defense theories.
Output ONLY the numbered issues — no intro, no closing remarks."""

_RESEARCH_AUTHORITY_PROMPT = """You are an expert legal researcher specializing in Tennessee criminal defense.
Given a list of identified legal issues, provide the most relevant legal authority for each.
For each issue include: controlling US Supreme Court cases, Tennessee Supreme Court/Court of Criminal Appeals cases, relevant T.C.A. sections, and applicable constitutional provisions.
Format as a structured legal research memo with a heading per issue.
Focus exclusively on authority supporting defense arguments.
Cite cases as: Case Name, Volume Reporter Page (Court Year)."""

_ISSUESPOT_PROMPTS = {
    "Criminal Defense": """You are a senior criminal defense attorney reviewing a legal document (warrant, affidavit, police report, indictment, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Motion: [Suggested motion — e.g., Motion to Suppress, Motion to Dismiss]
Authority: [Key case or statute]

Identify: Fourth Amendment violations, warrant particularity defects, stale probable cause, Miranda violations, chain of custody issues, credibility problems, and any procedural defects.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Civil Litigation": """You are a senior civil litigation attorney reviewing a legal document (complaint, contract, demand letter, settlement agreement, court order, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., Motion to Dismiss, Affirmative Defense, Counterclaim]
Authority: [Key case, statute, or rule — cite Tennessee law where applicable]

Identify: standing defects, statute of limitations issues, failure to state a claim, improper service, jurisdiction problems, vague or conclusory allegations, damages calculation errors, evidentiary gaps, and procedural defects.
Output ONLY the issue list — no intro, no closing remarks.""",

    "DeFi / Crypto Law": """You are a senior attorney specializing in DeFi, cryptocurrency, and blockchain law reviewing a legal document (regulatory notice, smart contract audit, terms of service, SEC correspondence, enforcement action, whitepaper, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., regulatory filing, compliance remediation, legal defense strategy]
Authority: [Key case, statute, or regulatory guidance — SEC, CFTC, FinCEN, state money transmitter laws, Howey test]

Identify: unregistered securities (Howey test), money transmitter licensing issues, AML/KYC deficiencies, smart contract liability, DAO governance risks, staking/yield regulatory exposure, CFTC jurisdiction issues, state-by-state licensing gaps, and consumer protection violations.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Family Law": """You are a senior family law attorney reviewing a legal document (petition for divorce, parenting plan, child support worksheet, prenuptial agreement, protective order, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., Counter-Petition, Objection, Modification Request]
Authority: [Key statute or case — T.C.A. Title 36, Tennessee case law]

Identify: custody factor omissions (T.C.A. § 36-6-106), child support calculation errors, alimony type misapplication (T.C.A. § 36-5-121), property classification issues (marital vs. separate), parenting schedule gaps, UCCJEA jurisdiction problems, and procedural defects.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Personal Injury": """You are a senior personal injury attorney reviewing a legal document (accident report, medical records, demand letter, insurance correspondence, expert report, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., Supplemental Demand, Expert Rebuttal, Litigation Strategy]
Authority: [Key statute or case — Tennessee comparative fault, T.C.A. § 29-39-102 damages caps]

Identify: comparative fault allocation issues (Tennessee 50% bar rule), statute of limitations concerns, damages cap applicability, HCLA pre-suit notice defects (T.C.A. § 29-26-121), causation gaps, inadequate documentation of special damages, insurance bad faith indicators, and subrogation issues.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Employment Law": """You are a senior employment law attorney reviewing a legal document (employment contract, separation agreement, EEOC charge, termination letter, non-compete agreement, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., EEOC Charge, THRC Complaint, Negotiation Strategy, Litigation]
Authority: [Key statute or case — Title VII, THRA (T.C.A. § 4-21-101), FLSA, FMLA, ADA]

Identify: discrimination indicators, retaliation patterns, ADEA waiver deficiencies (21-day/7-day requirements), non-compete overbreadth (T.C.A. § 47-25-101), wage and hour violations, FMLA interference, ADA accommodation failures, and filing deadline issues (180/300 day EEOC windows).
Output ONLY the issue list — no intro, no closing remarks.""",

    "Real Estate": """You are a senior real estate attorney reviewing a legal document (purchase agreement, lease, deed, title report, HOA documents, foreclosure notice, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., Title Objection, Lease Dispute, Foreclosure Defense]
Authority: [Key statute or case — URLTA (T.C.A. § 66-28-101), T.C.A. Title 66, Tennessee conveyance law]

Identify: title defects, easement conflicts, deed errors, URLTA violations (landlord/tenant), non-judicial foreclosure defects (T.C.A. § 35-5-101), HOA authority issues, zoning conflicts, environmental liability, and financing contingency problems.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Contract Dispute": """You are a senior contract law attorney reviewing a legal document (contract, agreement, breach demand letter, purchase order, licensing agreement, or similar).
Carefully analyze the document and identify all legal issues. For each issue output:

ISSUE [N]: [Title]
Basis: [Quote or cite the specific language from the document supporting this issue]
Response: [Suggested response — e.g., Breach Demand, Rescission, Specific Performance Action]
Authority: [Key statute or case — UCC Article 2, Tennessee contract law, T.C.A. § 28-3-109 SOL]

Identify: ambiguous terms, unconscionable clauses, consideration defects, formation issues, conditions precedent failures, force majeure gaps, limitation of liability overreach, arbitration clause enforceability, non-compete/non-solicitation overbreadth, and statute of limitations issues.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Crypto LLC Formation": """You are a senior attorney specializing in cryptocurrency and blockchain law reviewing a Crypto LLC formation intake questionnaire.
Carefully analyze the intake data and identify key legal and compliance considerations:

ISSUE [N]: [Title]
Risk Level: [Low / Medium / High]
Recommendation: [Specific action or filing required]
Authority: [Relevant statute, SEC guidance, FinCEN rule, state law]

Identify: Howey test implications for token offerings, FinCEN money services registration requirements, state money transmitter licensing, SEC registration obligations, AML/KYC compliance needs, tax classification, operational governance gaps, member agreement deficiencies, and jurisdiction-specific regulatory requirements.
Output ONLY the issue list — no intro, no closing remarks.""",

    "Estate Planning": """You are a senior estate planning attorney reviewing an estate planning intake questionnaire.
Carefully analyze the intake data and identify key planning opportunities and requirements:

ISSUE [N]: [Title]
Planning Opportunity: [Specific strategy or document needed]
Priority: [Urgent / High / Medium / Low]
Authority: [Relevant T.C.A., federal tax code, Tennessee case law]

Identify: federal estate tax exposure, state estate/inheritance tax implications, marital deduction planning needs, bypass trust opportunities, QTIP trust considerations, generation-skipping transfer tax issues, probate avoidance strategies, digital asset disposition gaps, and fiduciary appointment deficiencies.
Output ONLY the issue list — no intro, no closing remarks.""",
}

_DRAFT_PROMPTS = {
    "Criminal Defense": """You are an expert criminal defense attorney drafting a motion for Tennessee state court.
Draft a complete, professional legal motion. Include:
- Proper caption (use [CLIENT NAME] and [CASE NO.] as placeholders)
- Introduction stating the relief sought
- Statement of Facts (incorporate facts from the case context)
- Legal Standard / Standard of Review
- Argument section(s) with headings and citations to cases and statutes
- Conclusion with specific prayer for relief
- Certificate of Service placeholder

Use formal legal language and Tennessee Rules of Criminal Procedure formatting.
Output ONLY the motion text — no markdown, no asterisks, no commentary.""",

    "Civil": """You are an expert civil litigation attorney drafting a legal document for Tennessee state court.
Draft a complete, professional legal document. Include:
- Proper caption (use [CLIENT NAME] and [CASE NO.] as placeholders)
- Introduction stating the relief sought or purpose of the filing
- Statement of Facts
- Legal Standard / Standard of Review (where applicable)
- Argument section(s) with headings and citations to Tennessee cases and statutes
- Conclusion with specific prayer for relief
- Certificate of Service placeholder

Use formal legal language and Tennessee Rules of Civil Procedure formatting.
Output ONLY the document text — no markdown, no asterisks, no commentary.""",

    "DeFi / Crypto Law": """You are an expert attorney specializing in DeFi, cryptocurrency, and blockchain law drafting a legal document.
Draft a complete, professional legal document. Include:
- Proper heading and identification of parties (use [CLIENT NAME] and [ENTITY] as placeholders)
- Clear statement of purpose
- Factual background including relevant blockchain/protocol details
- Legal analysis with citations to SEC guidance, CFTC rules, FinCEN guidance, state law, and relevant case law (SEC v. Ripple, SEC v. Coinbase, Howey, Reves)
- Recommended action items or specific relief sought
- Compliance recommendations where applicable

Use formal legal language appropriate to the document type (regulatory response, opinion letter, compliance memo, or court filing).
Output ONLY the document text — no markdown, no asterisks, no commentary.""",

    "Crypto LLC": """You are an expert attorney specializing in cryptocurrency and blockchain law drafting LLC formation documents.
Draft a complete, professional document. Include:
- Proper heading with LLC name, formation jurisdiction, and date (use [LLC NAME] and [JURISDICTION] as placeholders)
- Clear statement of purpose and business operations
- Member information and ownership structure
- Governance provisions and management structure
- Capital contribution requirements
- Profit and loss distribution terms
- Voting rights and decision-making procedures
- Withdrawal and transfer restrictions
- Indemnification and liability limitations
- Compliance and regulatory acknowledgments (Howey test, SEC, FinCEN, state law)

Use formal legal language appropriate to Delaware/Wyoming/Tennessee LLC law.
Output ONLY the document text — no markdown, no asterisks, no commentary.""",

    "Estate": """You are an expert estate planning attorney drafting an estate planning document.
Draft a complete, professional document. Include:
- Proper caption with client name and effective date (use [CLIENT NAME] and [DATE] as placeholders)
- Statement of intent and family information
- Clear identification of beneficiaries
- Asset disposition provisions
- Fiduciary appointments and successor provisions
- Powers and duties of executor/trustee
- Tax planning provisions where appropriate
- Digital asset and cryptocurrency disposition instructions (if applicable)
- Amendment and revocation provisions

Use formal legal language in compliance with Tennessee probate law (T.C.A. Title 32) and federal tax code.
Output ONLY the document text — no markdown, no asterisks, no commentary.""",
}


def _get_issuespot_prompt(case_type: str) -> str:
    if case_type in _ISSUESPOT_PROMPTS:
        return _ISSUESPOT_PROMPTS[case_type]
    if case_type and case_type.startswith("Family Law"):
        return _ISSUESPOT_PROMPTS["Family Law"]
    return _ISSUESPOT_PROMPTS["Civil Litigation"]


def _get_draft_prompt(case_type: str) -> str:
    if case_type == "Crypto LLC Formation":
        return _DRAFT_PROMPTS.get("Crypto LLC", _DRAFT_PROMPTS["Civil"])
    if case_type == "Estate Planning":
        return _DRAFT_PROMPTS.get("Estate", _DRAFT_PROMPTS["Civil"])
    if case_type in _DRAFT_PROMPTS:
        return _DRAFT_PROMPTS[case_type]
    if case_type and case_type.startswith("Family Law"):
        return _DRAFT_PROMPTS["Civil"]
    if case_type in ("Personal Injury", "Employment Law", "Real Estate", "Contract Dispute"):
        return _DRAFT_PROMPTS["Civil"]
    return _DRAFT_PROMPTS["Civil"]


# ── Case-search helpers ────────────────────────────────────────────────────────

_DAVIDSON_URLS = {
    "criminal": ("https://sci.ccc.nashville.gov/Search/Search",
                 "Criminal Court Clerk — Davidson County"),
    "civil":    ("https://caselink.nashville.gov/public/",
                 "Davidson County Civil Courts (CaseLink)"),
}


def _clerk_url(county: str, case_type: str):
    key = case_type.lower()
    if county.lower() == "davidson":
        return _DAVIDSON_URLS.get(key, _DAVIDSON_URLS["criminal"])
    subdomain = county.lower().replace(" ", "")
    path = "cmCaseList.aspx" if key == "criminal" else "cvCaseList.aspx"
    return (f"https://{subdomain}.tncrtinfo.com/{path}",
            f"{county} County Court Clerk (TNCRTInfo)")


# ── Portal pages ───────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/attorney-portal")
@require_attorney
def attorney_portal():
    atty_user = session["username"]
    atty_info = ATTORNEYS[atty_user]

    def _view(c):
        v = public_client_view(c)
        v["is_co_counsel"] = c.get("assigned_attorney") != atty_user
        v["conflict_unresolved"] = has_unresolved_conflict(c)
        v["amount_due"] = billing.amount_due(c, billing.load_ledger(c["username"]))
        return v

    all_mine = [c for c in all_clients() if can_access_client(atty_user, c)]
    clients          = sorted([_view(c) for c in all_mine if not c.get("archived")],
                              key=lambda c: c.get("last_communication") or "", reverse=True)
    archived_clients = [_view(c) for c in all_mine if c.get("archived")]
    return render_template("attorney_portal.html",
                           clients=clients,
                           archived_clients=archived_clients,
                           attorney=atty_info,
                           attorneys=[{"username": u, "display": i["display"]}
                                      for u, i in ATTORNEYS.items()],
                           viewer=atty_user,
                           case_date_labels=[{"kind": k, "label": CASE_DATE_LABELS[k]} for k in CASE_DATE_KINDS])


@portal_attorney_bp.route("/portal/attorney/dashboard")
@require_attorney
def portal_attorney_dashboard():
    try:
        atty_user  = session["username"]
        today      = date.today()
        my_clients = [c for c in all_clients()
                      if can_access_client(atty_user, c)
                      and not c.get("archived")]

        case_gcal_ids = {(e or {}).get("gcal_event_id")
                         for c in my_clients
                         for _k, e in _case_date_entries(c.get("case_dates"))
                         if e.get("gcal_event_id")}

        calendar_events = []
        for c in my_clients:
            uname  = c.get("username", "")
            cname  = c.get("client_name") or uname
            charge = c.get("charges") or c.get("case_type") or ""

            court_raw = c.get("next_court_date", "")
            if court_raw:
                try:
                    cd = datetime.strptime(court_raw, "%Y-%m-%d").date()
                    calendar_events.append({
                        "date": court_raw,
                        "date_display": cd.strftime("%b %d, %Y"),
                        "time": "",
                        "client_name": cname,
                        "username": uname,
                        "type": "Court Date",
                        "matter": charge,
                    })
                except ValueError:
                    pass

            for kind, entry in _case_date_entries(c.get("case_dates")):
                raw = (entry or {}).get("date")
                try:
                    cd_ = datetime.strptime(raw, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    continue
                calendar_events.append({
                    "date": raw, "date_display": cd_.strftime("%b %d, %Y"), "time": "",
                    "client_name": cname, "username": uname, "type": "Court Date",
                    "matter": CASE_DATE_LABELS.get(kind, kind)})

            meeting_raw = c.get("next_meeting", "")
            if meeting_raw:
                m = re.search(r'(\w+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M)', meeting_raw)
                if m:
                    try:
                        dt = datetime.strptime(m.group(1) + " " + m.group(2), "%B %d, %Y %I:%M %p")
                        sort_key  = dt.strftime("%Y-%m-%d")
                        time_part = dt.strftime("%I:%M %p").lstrip("0")
                        display   = dt.strftime("%b %d, %Y")
                        note_part = meeting_raw.split(" — ", 1)[1].strip() if " — " in meeting_raw else ""
                    except ValueError:
                        sort_key, time_part, display, note_part = "9999-99-99", "", meeting_raw[:30], ""
                else:
                    sort_key, time_part, display, note_part = "9999-99-99", "", meeting_raw[:30], ""
                calendar_events.append({
                    "date": sort_key, "date_display": display, "time": time_part,
                    "client_name": cname, "username": uname,
                    "type": "Meeting", "matter": note_part or charge,
                })

        gcal_raw = _fetch_gcal_events(days_ahead=180)
        for gev in gcal_raw:
            if gev.get("gcal_id") in case_gcal_ids:
                continue
            summary  = gev["summary"]
            date_str = gev["start_date"]
            if not date_str:
                continue
            sl = summary.lower()
            if any(k in sl for k in ("court", "hearing", "arraignment")):
                ev_type = "Court Date (GCal)"
            elif any(k in sl for k in ("meeting", "consult", "deposition")):
                ev_type = "Meeting (GCal)"
            else:
                ev_type = "Event (GCal)"
            time_part = ""
            if gev["start_datetime"]:
                try:
                    raw = gev["start_datetime"]
                    if raw.endswith("Z"):
                        raw = raw[:-1]
                    elif len(raw) > 6 and raw[-6] in ("+", "-"):
                        raw = raw[:-6]
                    dt        = datetime.fromisoformat(raw)
                    time_part = dt.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    pass
            try:
                display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")
            except Exception:
                display = date_str
            calendar_events.append({
                "date":         date_str,
                "date_display": display,
                "time":         time_part,
                "client_name":  summary,
                "username":     "",
                "type":         ev_type,
                "matter":       summary,
            })
        calendar_events.sort(key=lambda x: x["date"])

        deadlines = []
        for c in my_clients:
            court_raw = c.get("next_court_date", "")
            if not court_raw:
                continue
            try:
                cd = datetime.strptime(court_raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            days = (cd - today).days
            if 0 <= days <= 90:
                deadlines.append({
                    "client_name": c.get("client_name") or c.get("username", ""),
                    "username":    c.get("username", ""),
                    "charges":     c.get("charges") or c.get("case_type") or "—",
                    "court_date":  cd.strftime("%b %d, %Y"),
                    "days_until":  days,
                })
        for c in my_clients:
            for kind, entry in _case_date_entries(c.get("case_dates")):
                raw = (entry or {}).get("date")
                try:
                    cd_ = datetime.strptime(raw, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    continue
                days = (cd_ - today).days
                if 0 <= days <= 90:
                    deadlines.append({
                        "client_name": c.get("client_name") or c.get("username", ""),
                        "username":    c.get("username", ""),
                        "charges":     CASE_DATE_LABELS.get(kind, kind),
                        "court_date":  cd_.strftime("%b %d, %Y"),
                        "days_until":  days,
                    })
        # Reuse the 180-day pull above rather than making a second API call —
        # the 90-day window is a subset of it.
        for gev in gcal_raw:
            if gev.get("gcal_id") in case_gcal_ids:
                continue
            summary  = gev["summary"]
            date_str = gev["start_date"]
            if not date_str:
                continue
            try:
                gd = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            days = (gd - today).days
            if not (0 <= days <= 90):
                continue
            sl = summary.lower()
            if any(k in sl for k in ("court", "hearing", "arraignment")):
                ev_type = "Court Date"
            elif any(k in sl for k in ("meeting", "consult", "deposition")):
                ev_type = "Meeting"
            else:
                continue
            already = any(
                d["court_date"] == gd.strftime("%b %d, %Y") and
                (d.get("client_name", "").lower() in gev["summary"].lower() or
                 gev["summary"].lower() in d.get("client_name", "").lower())
                for d in deadlines
            )
            if already:
                continue
            deadlines.append({
                "client_name": summary,
                "username":    "",
                "charges":     ev_type,
                "court_date":  gd.strftime("%b %d, %Y"),
                "days_until":  days,
            })
        deadlines.sort(key=lambda x: x["days_until"])

        follow_up_needed = []
        for c in my_clients:
            lc_raw = c.get("last_communication", "")
            if not lc_raw:
                continue
            try:
                lc_date = datetime.strptime(lc_raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            days_since = (today - lc_date).days
            if days_since >= 30:
                follow_up_needed.append({
                    "client_name":  c.get("client_name") or c.get("username", ""),
                    "username":     c.get("username", ""),
                    "last_contact": lc_date.strftime("%b %d, %Y"),
                    "days_since":   days_since,
                })
        follow_up_needed.sort(key=lambda x: x["days_since"], reverse=True)

        all_files = []
        for c in my_clients:
            base = CLIENT_FILES_DIR / c.get("username", "") / "documents"
            if not base.exists():
                continue
            for cat_dir in base.iterdir():
                if not cat_dir.is_dir():
                    continue
                for f in cat_dir.iterdir():
                    if f.is_file():
                        st = f.stat()
                        all_files.append({
                            "filename":    f.name,
                            "client_name": c.get("client_name") or c.get("username", ""),
                            "username":    c.get("username", ""),
                            "category":    cat_dir.name,
                            "modified":    datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                            "_mtime":      st.st_mtime,
                        })
        all_files.sort(key=lambda x: x["_mtime"], reverse=True)
        recent_files = [{k: v for k, v in f.items() if k != "_mtime"} for f in all_files[:15]]

        all_activity = []
        for c in my_clients:
            cname = c.get("client_name") or c.get("username", "")
            uname = c.get("username", "")
            for entry in c.get("activity_log", []):
                all_activity.append({
                    "timestamp":   entry.get("timestamp", ""),
                    "client_name": cname,
                    "username":    uname,
                    "action_type": entry.get("action_type", ""),
                    "description": entry.get("description", ""),
                })
        all_activity.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        recent_activity = all_activity[:20]

        grand_total   = 0.0
        client_totals = []
        for c in my_clients:
            cname = c.get("client_name") or c.get("username", "")
            uname = c.get("username", "")
            client_hrs = 0.0
            for entry in c.get("billing_log", []):
                hrs = float(entry.get("hours", 0) or 0)
                client_hrs += hrs
                grand_total += hrs
            client_totals.append({
                "client_name": cname,
                "username":    uname,
                "hours":       round(client_hrs, 2),
            })
        client_totals.sort(key=lambda x: x["hours"], reverse=True)

        return jsonify({
            "calendar":         calendar_events,
            "deadlines":        deadlines,
            "follow_up_needed": follow_up_needed,
            "recent_files":     recent_files,
            "billing":          client_totals,
            "billing_total":    round(grand_total, 2),
            "recent_activity":  recent_activity,
        })
    except Exception as exc:
        # Log the full traceback server-side; don't ship it to the browser.
        current_app.logger.exception("Attorney dashboard failed")
        return jsonify({"error": f"Could not build the dashboard: {exc}"}), 500


# ── Client CRUD ────────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/clients")
@require_attorney
def portal_clients_list():
    atty = session["username"]
    return jsonify([public_client_view(c) for c in all_clients() if can_access_client(atty, c)])


@portal_attorney_bp.route("/portal/attorney/client/<username>")
@require_attorney
def portal_client_get(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    log_access_atomic(client["username"], "view_record")
    view = public_client_view(client)
    view["viewer_is_assigned"] = client.get("assigned_attorney") == session["username"]
    view["conflict_checks"] = redact_checks(client.get("conflict_checks"), session["username"])
    view["billing_summary"] = billing.billing_summary(client, billing.load_ledger(client["username"]))
    return jsonify(view)


@portal_attorney_bp.route("/portal/attorney/access-log/<username>")
@require_attorney
def portal_access_log(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    return jsonify(list(reversed(client.get("access_log", []))))


@portal_attorney_bp.route("/portal/attorney/co-counsel", methods=["POST"])
@require_attorney
def portal_co_counsel():
    data   = request.get_json() or {}
    client = load_client_for_attorney(data.get("username", ""), assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    action   = data.get("action")
    attorney = (data.get("attorney") or "").strip()
    if action not in ("add", "remove"):
        return jsonify({"error": "Invalid action."}), 400
    if attorney not in ATTORNEYS or attorney == client.get("assigned_attorney"):
        return jsonify({"error": "Invalid attorney."}), 400
    cc = client.setdefault("co_counsel", [])
    if action == "add" and attorney not in cc:
        cc.append(attorney)
    elif action == "remove" and attorney in cc:
        cc.remove(attorney)
    _log_access(client, "co_counsel_change", f"{action} {attorney}")
    save_client(client)
    return jsonify({"success": True, "co_counsel": cc})


@portal_attorney_bp.route("/portal/attorney/issue-statement", methods=["POST"])
@require_attorney
def portal_issue_statement():
    data   = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username  = client["username"]
    statement = billing.issue_statement(username, reason="manual",
                                        issued_by=session["username"], notify=True)
    if not statement:
        return jsonify({"error": "No unbilled time to bill."}), 400
    log_access_atomic(username, "statement_issued",
                      f"{statement['id']} ${statement['amount']:,.2f}")
    billing.send_pending_notices(username)
    fresh = load_client(username)
    return jsonify({"success": True, "statement": statement,
                    "billing_summary": billing.billing_summary(fresh, billing.load_ledger(username))})


@portal_attorney_bp.route("/portal/attorney/statement-notice", methods=["POST"])
@require_attorney
def portal_statement_notice():
    data   = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username = client["username"]
    if not billing.request_resend(username, str(data.get("statement_id") or "")):
        return jsonify({"error": "Notice can't be resent in its current state."}), 400
    billing.send_pending_notices(username)
    return jsonify({"success": True,
                    "billing_summary": billing.billing_summary(load_client(username),
                                                               billing.load_ledger(username))})


@portal_attorney_bp.route("/portal/attorney/billing-settings", methods=["GET", "POST"])
@require_attorney
def portal_billing_settings():
    atty = session["username"]
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = {}
        try:
            value = billing.set_threshold(atty, data.get("threshold"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "threshold": value})
    return jsonify({"threshold": billing.get_threshold(atty),
                    "default": billing.DEFAULT_STATEMENT_THRESHOLD})


@portal_attorney_bp.route("/portal/attorney/conflict-check", methods=["POST"])
@require_attorney
def portal_conflict_check():
    data   = request.get_json() or {}
    names  = clean_names(data.get("names"))
    viewer = session["username"]
    if not names:
        return jsonify({"error": "Enter at least one name."}), 400
    username = str(data.get("username") or "").strip()
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        rec = record_check(client, "manual", viewer, other_names=names)
        _log_access(client, "conflict_check", ", ".join(names))
        save_client(client)
    else:
        skipped = []
        rec = make_check_record("manual", viewer, names,
                                run_conflict_check(other_names=names, skipped=skipped))
        if skipped:
            rec["incomplete"] = len(skipped)
        append_firm_log(rec)
    return jsonify({"success": True, "check": dict(rec, hits=redact_hits(rec["hits"], viewer))})


@portal_attorney_bp.route("/portal/attorney/conflict-decision", methods=["POST"])
@require_attorney
def portal_conflict_decision():
    data   = request.get_json() or {}
    client = load_client_for_attorney(data.get("username", ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    decision = data.get("decision")
    note     = (data.get("note") or "").strip()[:1000]
    if decision not in DECISIONS:
        return jsonify({"error": "Invalid decision."}), 400
    if decision == "waiver_obtained" and not note:
        return jsonify({"error": "Describe the waiver obtained."}), 400
    for chk in client.get("conflict_checks", []):
        if chk.get("id") == data.get("check_id"):
            if chk.get("decision"):
                chk.setdefault("decision_history", []).append(
                    {k: chk.get(k) for k in ("decision", "decision_note", "decided_by", "decided_at")})
            chk.update(decision=decision, decision_note=note,
                       decided_by=session["username"],
                       decided_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            _log_access(client, "conflict_check", f"{decision} on {chk['id']}")
            save_client(client)
            return jsonify({"success": True,
                            "check": dict(chk, hits=redact_hits(chk["hits"], session["username"]))})
    return jsonify({"error": "Conflict check not found."}), 404


@portal_attorney_bp.route("/portal/attorney/archive-client", methods=["POST"])
@require_attorney
def portal_archive_client():
    username = (request.get_json() or {}).get("username", "")
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    client["archived"] = True
    _log_access(client, "edit_record", "File archived.")
    save_client(client)
    _log_activity(username, "info_updated", "Client file archived.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/unarchive-client", methods=["POST"])
@require_attorney
def portal_unarchive_client():
    username = (request.get_json() or {}).get("username", "")
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    client["archived"] = False
    _log_access(client, "edit_record", "File restored from archive.")
    save_client(client)
    _log_activity(username, "info_updated", "Client file restored from archive.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/create-client", methods=["POST"])
@require_attorney
def portal_create_client():
    data      = request.get_json() or {}
    username  = safe_username(data.get("username", ""))
    case_type = data.get("case_type", "Criminal Defense")
    if not username:
        return jsonify({"error": "Username is required."}), 400
    if (CLIENT_ACCOUNTS_DIR / f"{username}.json").exists():
        return jsonify({"error": f"Username '{username}' already exists. Please choose a different one."}), 409

    assigned_atty = CASE_ATTORNEY_MAP.get(case_type, "Endocide")
    client_folder = CLIENT_FILES_DIR / username
    client_folder.mkdir(exist_ok=True)

    first_note  = data.get("legal_issue", "").strip()
    billing_log = [{
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "hours":    0.2,
        "note":     f"Intake Processing — New Client File Opened ({case_type})",
        "type":     "intake",
        "category": "Intake",
    }]
    if first_note:
        billing_log.append({
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0,
            "note":     f"INTAKE NOTES — {case_type}.\nMatter: {first_note}",
            "type":     "intake",
            "category": "Intake",
        })

    posted_password   = (data.get("password") or "").strip()
    password_ok       = acceptable_password(posted_password, username)
    password_replaced = bool(posted_password) and not password_ok
    temp_password     = posted_password if password_ok else generate_temp_password()
    record = {
        "username":             username,
        "password":             hash_password(temp_password),
        "must_change_password": True,
        "client_name":          data.get("client_name", ""),
        "case_type":            case_type,
        "assigned_attorney":    assigned_atty,
        "opposing_parties":     clean_names(data.get("opposing_parties")
                                            or [data.get("opposing_party", "")]),
        "related_parties":      clean_related(data.get("related_parties")),
        "legal_issue":          first_note[:400],
        "next_court_date":      data.get("next_court_date", ""),
        "hours_billed":         round(sum(e.get("hours", 0) for e in billing_log), 2),
        "last_communication":   datetime.now().strftime("%Y-%m-%d"),
        "phone":                data.get("phone", ""),
        "email":                data.get("email", ""),
        "google_drive_url":     data.get("google_drive_url", ""),
        "next_meeting":         data.get("next_meeting", ""),
        "client_folder":        str(client_folder),
        "billing_log":          billing_log,
        "time_logs":            [],
        "notes":                [],
        "messages":             [],
    }

    if first_note:
        try:
            ai = get_anthropic_client()
            ai_resp = ai.messages.create(
                model=MODEL,
                max_tokens=200,
                system=(
                    "You are a legal intake analyst for a law firm. When given a client's "
                    "description of their legal matter, write a 2-3 sentence professional "
                    "summary that: (1) identifies the core legal issue(s) and any specific "
                    "charges, statutes, or claims involved, (2) notes key facts such as "
                    "prior history, urgency, or aggravating circumstances, and (3) states "
                    "the likely legal strategy or relief sought. Be specific and use proper "
                    "legal terminology. Do not use bullet points."
                ),
                messages=[{"role": "user", "content": f"Case type: {case_type}\n\nClient's description:\n{first_note}"}],
            )
            record["legal_issue_summary"] = ai_resp.content[0].text.strip()
        except Exception:
            pass

    check = record_check(record, "create", session["username"],
                         client_names=[record["client_name"] or username],
                         opposing_names=record["opposing_parties"],
                         related_names=[r["name"] for r in record["related_parties"]])
    visible_hits = redact_hits(check["hits"], session["username"])
    save_client(record)
    _log_activity(username, "intake", f"Client profile created — {case_type}.")

    court_date_val = data.get("next_court_date", "").strip()
    if court_date_val:
        gcal_id = _push_court_date_to_gcal(data.get("client_name", username), court_date_val)
        if gcal_id:
            record["court_date_gcal_event_id"] = gcal_id
            save_client(record)

    try:
        atty_display = ATTORNEYS.get(assigned_atty, {}).get("display", assigned_atty)
        pdf_fields = {
            "client_name":        data.get("client_name", ""),
            "full_name":          data.get("client_name", ""),
            "phone":              data.get("phone", ""),
            "email":              data.get("email", ""),
            "case_type":          case_type,
            "legal_issue":        first_note,
            "matter_description": first_note,
            "portal_username":    username,
            "atty_display":       atty_display,
            "case_no":            record.get("case_no", ""),
        }
        pdf_bytes = _generate_client_pdf(pdf_fields)
        intake_dir = CLIENT_FILES_DIR / username / "documents" / "Intake"
        intake_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if pdf_bytes:
            (intake_dir / f"client_profile_{ts}.pdf").write_bytes(pdf_bytes)
        else:
            intake_html = _generate_intake_html(pdf_fields, [], username, atty_display)
            with open(intake_dir / f"client_profile_{ts}.html", "w", encoding="utf-8") as hf:
                hf.write(intake_html)
    except Exception:
        pass

    return jsonify({"success": True, "username": username, "temp_password": temp_password,
                    "password_replaced": password_replaced,
                    "conflict_warnings": [hit_message(h) for h in visible_hits],
                    "conflict_hits": visible_hits})


@portal_attorney_bp.route("/portal/attorney/update-client", methods=["POST"])
@require_attorney
def portal_update_client():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    client   = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    _prev_court_date = client.get("next_court_date", "")
    _prev_name = client.get("client_name", "")
    for field in ("client_name", "case_type", "legal_issue", "next_court_date",
                  "phone", "email", "google_drive_url", "next_meeting",
                  "case_no", "charges", "charge_level", "county", "court"):
        if field in data:
            client[field] = data[field]
    prev_opp = set(client.get("opposing_parties") or [])
    prev_rel = {r.get("name") for r in client.get("related_parties") or []}
    if "opposing_parties" in data:
        client["opposing_parties"] = clean_names(data["opposing_parties"])
    if "related_parties" in data:
        client["related_parties"] = clean_related(data["related_parties"])
    new_opp = [n for n in client["opposing_parties"] if n not in prev_opp]
    new_rel = [r["name"] for r in client["related_parties"] if r["name"] not in prev_rel]
    conflict_hits = []
    new_client = ([client["client_name"]]
                  if client.get("client_name") and client["client_name"] != _prev_name else [])
    if new_opp or new_rel or new_client:
        chk = record_check(client, "edit", session["username"], client_names=new_client,
                           opposing_names=new_opp, related_names=new_rel)
        conflict_hits = redact_hits(chk["hits"], session["username"])
    client.setdefault("activity_log", []).append({
        "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "action_type": "info_updated",
        "description": "Client info updated.",
    })
    _log_access(client, "edit_record", "Client info updated.")
    save_client(client)

    intake_filename = None
    try:
        atty_disp = ATTORNEYS.get(client.get("assigned_attorney", ""), {}).get("display", "")
        pdf_fields = {
            "client_name":        client.get("client_name", ""),
            "full_name":          client.get("client_name", ""),
            "phone":              client.get("phone", ""),
            "email":              client.get("email", ""),
            "case_type":          client.get("case_type", ""),
            "legal_issue":        client.get("legal_issue", ""),
            "matter_description": client.get("legal_issue", ""),
            "portal_username":    username,
            "atty_display":       atty_disp,
            "case_no":            client.get("case_no", ""),
        }
        pdf_bytes = _generate_client_pdf(pdf_fields)
        if pdf_bytes:
            intake_dir = _client_docs_dir(username, "Intake")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = intake_dir / f"intake_{ts}.pdf"
            pdf_path.write_bytes(pdf_bytes)
            intake_filename = pdf_path.name
    except Exception:
        pass

    new_date = data.get("next_court_date", "").strip()
    if new_date and new_date != _prev_court_date and GOOGLE_LIBS and TOKEN_FILE.exists():
        existing_id = client.get("court_date_gcal_event_id")
        if existing_id:
            try:
                service = get_calendar_service()
                upd = {
                    "summary":     f"Court Date: {client.get('client_name', username)}",
                    "description": f"Court date for client {client.get('client_name', username)} — MT Legal",
                    "start":       {"date": new_date},
                    "end":         {"date": (datetime.strptime(new_date, "%Y-%m-%d").date()
                                             + timedelta(days=1)).isoformat()},
                }
                service.events().update(
                    calendarId="primary", eventId=existing_id, body=upd
                ).execute()
                save_client(client)
            except Exception:
                pass
        else:
            gcal_id = _push_court_date_to_gcal(client.get("client_name", username), new_date)
            if gcal_id:
                client["court_date_gcal_event_id"] = gcal_id
                save_client(client)

    return jsonify({"success": True, "intake_pdf": intake_filename, "conflict_hits": conflict_hits})


@portal_attorney_bp.route("/portal/attorney/generate-summary", methods=["POST"])
@require_attorney
def portal_generate_summary():
    data     = request.get_json(force=True)
    username = data.get("username", "").strip()
    client   = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    legal_issue = (client.get("legal_issue") or "").strip()
    if not legal_issue:
        return jsonify({"error": "No legal issue on file to summarize."}), 400
    case_type = client.get("case_type", "General")
    try:
        ai = get_anthropic_client()
        ai_resp = ai.messages.create(
            model=MODEL,
            max_tokens=200,
            system=(
                "You are a legal intake analyst for a law firm. When given a client's "
                "description of their legal matter, write a 2-3 sentence professional "
                "summary that: (1) identifies the core legal issue(s) and any specific "
                "charges, statutes, or claims involved, (2) notes key facts such as "
                "prior history, urgency, or aggravating circumstances, and (3) states "
                "the likely legal strategy or relief sought. Be specific and use proper "
                "legal terminology. Do not use bullet points."
            ),
            messages=[{"role": "user", "content": f"Case type: {case_type}\n\nClient's description:\n{legal_issue}"}],
        )
        summary = ai_resp.content[0].text.strip()
    except Exception as exc:
        return jsonify({"error": f"AI unavailable: {exc}"}), 503
    client["legal_issue_summary"] = summary
    _log_access(client, "edit_record", "AI summary regenerated.")
    save_client(client)
    return jsonify({"success": True, "summary": summary})


@portal_attorney_bp.route("/portal/attorney/billing-entry", methods=["POST"])
@require_attorney
def portal_billing_entry():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    client   = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    note = data.get("note", "").strip()
    if not note:
        return jsonify({"error": "Note cannot be empty."}), 400
    hours    = round(float(data.get("hours", 0) or 0), 2)
    category = (data.get("category") or "Other").strip() or "Other"
    entry = {
        "date":     data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "hours":    hours,
        "note":     note,
        "category": category,
    }
    client.setdefault("billing_log", []).append(entry)
    recalc_hours(client)
    client["last_communication"] = datetime.now().strftime("%Y-%m-%d")
    _log_access(client, "billing_entry", f"{hours} hrs — {note[:80]}")
    save_client(client)
    _log_activity(username, "time_logged",
                  str(hours) + " hrs — " + note[:80] + ("..." if len(note) > 80 else ""))
    fresh = load_client(username) or client
    return jsonify({"success": True, "total_hours": client["hours_billed"], "entry": entry,
                    "billing_summary": billing.billing_summary(fresh, billing.load_ledger(username))})


_SCHED_CATEGORY = "Scheduling Orders"
_CASE_DATES_HISTORY_MAX = 20


def _case_date_entries(case_dates):
    """Yield (kind, entry) for well-formed case-date entries only."""
    if not isinstance(case_dates, dict):
        return
    for kind, entry in case_dates.items():
        if isinstance(kind, str) and isinstance(entry, dict):
            yield kind, entry


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@portal_attorney_bp.route("/portal/attorney/scheduling-order/extract", methods=["POST"])
@require_attorney
def portal_sched_extract():
    data   = _json_body()
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    path = _resolve_doc_path(client["username"], _SCHED_CATEGORY, str(data.get("filename") or ""))
    if path is None:
        return jsonify({"error": "File not found."}), 404
    log_access_atomic(client["username"], "scheduling_order_read", path.name)
    current = dict(_case_date_entries(client.get("case_dates")))
    try:
        extraction = extract_case_dates(path)
    except ExtractionError as exc:
        return jsonify({"success": False, "error": str(exc), "current": current})
    except Exception as exc:
        print(f"scheduling-order extraction failed: {exc!r}", file=sys.stderr)
        return jsonify({"success": False, "current": current,
                        "error": "The AI reader is unavailable right now; enter the dates manually."})
    usage = extraction.pop("usage", None)
    if usage is not None:
        _log_token_usage(session["username"], "Scheduling Order Extraction", usage)
    return jsonify({"success": True, "extraction": extraction, "current": current})


def _snapshot(case_dates) -> dict:
    return {k: (v.get("date"), v.get("gcal_event_id"))
            for k, v in _case_date_entries(case_dates)}


@portal_attorney_bp.route("/portal/attorney/scheduling-order/confirm", methods=["POST"])
@require_attorney
def portal_sched_confirm():
    data   = _json_body()
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username = client["username"]
    dates = data.get("dates")
    if not isinstance(dates, dict):
        return jsonify({"error": "Dates are required."}), 400
    new = {}
    for kind in dates:
        if kind not in CASE_DATE_KINDS:
            return jsonify({"error": f"Unknown date type: {str(kind)[:40]}."}), 400
    if any(k not in dates for k in CASE_DATE_KINDS):
        return jsonify({"error": "All five dates must be sent."}), 400
    for kind, value in dates.items():
        value = str(value or "").strip()
        if not value:
            continue
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
            if not (datetime(2000, 1, 1) <= parsed <= datetime(2100, 12, 31)):
                raise ValueError
        except ValueError:
            return jsonify({"error": f"Invalid date for {CASE_DATE_LABELS[kind]}."}), 400
        new[kind] = parsed.date().isoformat()
    path = _resolve_doc_path(username, _SCHED_CATEGORY, str(data.get("filename") or ""))
    if path is None:
        return jsonify({"error": "File not found."}), 404
    source = path.name

    old_entries = dict(_case_date_entries(client.get("case_dates")))
    first_snapshot = _snapshot(old_entries)
    old = {k: v.get("date") for k, v in old_entries.items()}
    if old == new:
        return jsonify({"success": True, "case_dates": old_entries, "warnings": [], "unchanged": True,
                        "case_dates_history": client.get("case_dates_history") or []})
    would_clear = [k for k in CASE_DATE_KINDS if old.get(k) and not new.get(k)]
    if would_clear and data.get("confirm_clear") is not True:
        labels = ", ".join(CASE_DATE_LABELS[k] for k in would_clear)
        return jsonify({"error": f"This would remove existing dates: {labels}. Confirm to remove them.",
                        "would_clear": would_clear}), 400

    # Google first, outside any client lock (these calls can take seconds).
    cname    = client.get("client_name") or username
    connected = gcal_connected()
    warnings  = [] if connected else ["Google Calendar not connected — dates saved in the app only; "
                                  "update or remove any existing calendar events manually."]
    created   = []
    event_ids = {}
    for kind in CASE_DATE_KINDS:
        before, after = old.get(kind), new.get(kind)
        if before == after:
            continue
        old_id = (old_entries.get(kind) or {}).get("gcal_event_id")
        label  = CASE_DATE_LABELS[kind]
        summary = f"{label}: {cname}"
        desc    = f"{label} for {cname} — from {source} — MT Legal"
        if not connected:
            event_ids[kind] = old_id if after else None
            continue
        if after and old_id:
            outcome = gcal_update_all_day(old_id, summary, desc, after)
            if outcome == "ok":
                event_ids[kind] = old_id
            elif outcome == "gone":
                new_id = gcal_create_all_day(summary, desc, after)
                if new_id:
                    created.append(new_id)
                else:
                    warnings.append(f"Google Calendar event for {label} could not be created.")
                event_ids[kind] = new_id
            else:
                event_ids[kind] = old_id
                warnings.append(f"Google Calendar event for {label} could not be moved — "
                                "update it manually.")
        elif after:
            new_id = gcal_create_all_day(summary, desc, after)
            if new_id:
                created.append(new_id)
            else:
                warnings.append(f"Google Calendar event for {label} could not be created.")
            event_ids[kind] = new_id
        elif old_id:
            if gcal_delete_event(old_id) == "error":
                warnings.append(f"Google Calendar event for {label} ({before}) may be left behind "
                                "— delete it manually.")

    # Re-load and verify nobody else confirmed in between.
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if _snapshot(client.get("case_dates") or {}) != first_snapshot:
        for event_id in created:
            gcal_delete_event(event_id)
        return jsonify({"error": "These dates were just changed by someone else. Reload and "
                                 "try again (check Google Calendar if any events were moved)."}), 409

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    current = dict(_case_date_entries(client.get("case_dates")))
    if current:
        history = client.setdefault("case_dates_history", [])
        history.append({"replaced_at": now, "replaced_by": session["username"],
                        "previous": json.loads(json.dumps(current))})
        del history[:-_CASE_DATES_HISTORY_MAX]
    updated = dict(current)
    for kind in CASE_DATE_KINDS:
        if old.get(kind) == new.get(kind):
            continue
        if new.get(kind):
            updated[kind] = {"date": new[kind], "gcal_event_id": event_ids.get(kind),
                             "source": source, "confirmed_by": session["username"],
                             "confirmed_at": now}
        else:
            updated.pop(kind, None)
    client["case_dates"] = updated
    if any(new.get(k) and new.get(k) != old.get(k) for k in CASE_DATE_KINDS):
        client.setdefault("billing_log", []).append({
            "date": date.today().isoformat(), "hours": 0.2,
            "note": f"Scheduling order review — {source}",
            "category": "Filing", "type": "scheduling_order"})
        recalc_hours(client)
    _log_access(client, "case_dates_confirmed", source)
    save_client(client)
    _log_activity(username, "case_dates_updated", f"Case dates updated from {source}.")
    return jsonify({"success": True, "case_dates": updated, "warnings": warnings,
                    "case_dates_history": client.get("case_dates_history") or []})


@portal_attorney_bp.route("/portal/attorney/leads-list")
@require_attorney
def portal_leads_list():
    atty_user = session.get("attorney") or session.get("username", "")
    leads = []
    for p in sorted(LEADS_DIR.glob("*.json"), reverse=True):
        try:
            with open(p) as f:
                lead = json.load(f)
            if lead.get("assigned_attorney") == atty_user and not lead.get("archived"):
                lead["_filename"] = p.name
                leads.append(lead)
        except Exception:
            pass
    return jsonify(leads)


@portal_attorney_bp.route("/portal/attorney/archive-lead", methods=["POST"])
@require_attorney
def portal_archive_lead():
    data     = request.get_json() or {}
    filename = data.get("filename", "").strip()
    if not filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename."}), 400
    lead_path = LEADS_DIR / filename
    if not lead_path.exists():
        return jsonify({"error": "Lead not found."}), 404
    try:
        with open(lead_path) as f:
            lead = json.load(f)
        if lead.get("assigned_attorney") != session["username"]:
            return jsonify({"error": "Lead not found."}), 404
        lead["archived"] = True
        with open(lead_path, "w") as f:
            json.dump(lead, f, indent=2)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@portal_attorney_bp.route("/portal/attorney/reply", methods=["POST"])
@require_attorney
def portal_attorney_reply():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    # load_client_for_attorney is only for the access check here: it confirms
    # this attorney may write to this client. The actual write goes through
    # update_client_atomic below on a freshly re-read copy, not this one —
    # a plain load/save would silently drop a message or billing entry the
    # client's own (slower, AI-calling) send route wrote in between.
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Reply cannot be empty."}), 400
    username = client["username"]

    def _add_reply(c):
        c.setdefault("messages", []).append({
            "from": "attorney",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "text": text,
        })
        c["last_communication"] = datetime.now().strftime("%Y-%m-%d")
        _log_access(c, "message_sent", text[:80])

    if not update_client_atomic(username, _add_reply):
        return jsonify({"error": "Client not found."}), 404
    _log_activity(username, "message_sent",
                  "Attorney message: " + text[:80] + ("..." if len(text) > 80 else ""))
    return jsonify({"success": True})


# ── Document management ────────────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/documents/<username>")
@require_attorney
def list_documents(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    log_access_atomic(client["username"], "view_documents")
    uname  = client["username"]
    result = {}
    for cat in DOCS_CATEGORIES:
        cat_dir = CLIENT_FILES_DIR / uname / "documents" / cat
        files   = []
        if uname and cat_dir.exists():
            for f in sorted(cat_dir.iterdir()):
                if f.is_file():
                    st = f.stat()
                    files.append({
                        "name":     f.name,
                        "size":     st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                        "category": cat,
                    })
        result[cat] = files
    return jsonify({"categories": DOCS_CATEGORIES, "files": result})


@portal_attorney_bp.route("/portal/attorney/upload-document", methods=["POST"])
@require_attorney
def upload_document():
    username = safe_username(request.form.get("username", ""))
    category = request.form.get("category", "Other").strip()
    if category not in DOCS_CATEGORIES:
        category = "Other"
    if not username:
        return jsonify({"error": "Username required."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        return jsonify({"error": f"File type '{ext}' not allowed."}), 400
    safe_name = secure_filename(file.filename)
    dest_dir  = _client_docs_dir(username, category)
    dest      = dest_dir / safe_name
    stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}{suffix}"
        n += 1
    file.save(str(dest))
    st = dest.stat()

    client = load_client(client["username"])
    if client is None:
        return jsonify({"error": "Client not found."}), 404
    entry = {
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "hours":    0.1,
        "note":     f"{category} — \"{dest.name}\" uploaded.",
        "type":     "document_upload",
        "category": "Filing",
    }
    client.setdefault("billing_log", []).append(entry)
    recalc_hours(client)
    _log_access(client, "document_upload", f"{category}/{dest.name}")
    save_client(client)
    _log_activity(username, "document_upload", f"{category} — \"{dest.name}\" uploaded.")
    billing_entry = entry
    total_hours   = client["hours_billed"]

    return jsonify({
        "success": True,
        "file": {
            "name":     dest.name,
            "size":     st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
            "category": category,
        },
        "billing_entry": billing_entry,
        "total_hours":   total_hours,
    })


@portal_attorney_bp.route("/portal/attorney/delete-document", methods=["POST"])
@require_attorney
def delete_document():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    category = data.get("category", "").strip()
    filename = data.get("filename", "").strip()
    if not all([username, category, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    path = _resolve_doc_path(client["username"], category, filename)
    if path is None:
        return jsonify({"error": "File not found."}), 404
    safe_name = path.name
    path.unlink()
    _log_access(client, "document_delete", f"{category}/{safe_name}")
    save_client(client)
    _log_activity(username, "document_delete", f"{category} — \"{safe_name}\" deleted.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/document/<username>/<category>/<filename>")
@require_attorney
def serve_document(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    path = _resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "download_document", f"{category}/{path.name}")
    return send_file(str(path), as_attachment=True, download_name=path.name)


@portal_attorney_bp.route("/portal/attorney/preview/<username>/<category>/<filename>")
@require_attorney
def preview_document(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    path = _resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "view_document_preview", f"{category}/{path.name}")
    return send_file(str(path), as_attachment=False)


@portal_attorney_bp.route("/portal/attorney/docx-preview/<username>/<category>/<filename>")
@require_attorney
def docx_preview(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    if not MAMMOTH_AVAILABLE:
        return "mammoth not installed — run: python -m pip install mammoth", 503
    path = _resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "view_document_preview", f"{category}/{path.name}")
    safe_name = path.name
    try:
        import mammoth
        with open(path, "rb") as f:
            result = mammoth.convert_to_html(f)
        body_html = result.value
        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{safe_name}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem 2.5rem; color: #222;
           line-height: 1.65; font-size: .93rem; max-width: 820px; }}
    h1,h2,h3 {{ font-family: Georgia, serif; color: #1a2d5a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    td, th {{ border: 1px solid #ccc; padding: .4rem .65rem; }}
    p {{ margin: .45rem 0; }}
    strong {{ color: #111; }}
  </style>
</head>
<body>{body_html}</body>
</html>"""
        return page, 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as exc:
        return f"Could not convert document: {str(exc)}", 500


# ── Research routes ────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/research/analyze", methods=["POST"])
@require_attorney
def research_analyze():
    data        = request.get_json() or {}
    legal_issue = data.get("legal_issue", "").strip()
    if not legal_issue:
        return jsonify({"error": "No case summary provided."}), 400
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=1500,
            system=_RESEARCH_ANALYZE_PROMPT,
            messages=[{"role": "user", "content": f"Case summary:\n{legal_issue}"}],
        )
        _log_token_usage(session.get("username", "unknown"), "Legal Issue Analysis", msg.usage)
        return jsonify({"success": True, "issues": msg.content[0].text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@portal_attorney_bp.route("/portal/attorney/research/authority", methods=["POST"])
@require_attorney
def research_authority():
    data        = request.get_json() or {}
    issues_text = data.get("issues", "").strip()
    case_type   = data.get("case_type", "Criminal Defense")
    if not issues_text:
        return jsonify({"error": "No issues provided."}), 400
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=3000,
            system=_RESEARCH_AUTHORITY_PROMPT,
            messages=[{"role": "user", "content": f"Case Type: {case_type}\n\nIdentified Issues:\n{issues_text}"}],
        )
        _log_token_usage(session.get("username", "unknown"), "Legal Authority Research", msg.usage)
        return jsonify({"success": True, "memo": msg.content[0].text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@portal_attorney_bp.route("/portal/attorney/research/issue-spot", methods=["POST"])
@require_attorney
def research_issue_spot():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    category = data.get("category", "").strip()
    filename = data.get("filename", "").strip()
    if not all([username, category, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    case_type = client.get("case_type", "Civil Litigation")
    text, err = _extract_document_text(username, category, filename)
    if err and not text:
        return jsonify({"error": err}), 400
    if not text or not text.strip():
        return jsonify({"error": "Could not extract text from this document."}), 400
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=2000,
            system=_get_issuespot_prompt(case_type),
            messages=[{"role": "user", "content": f"Document: {filename}\nCase Type: {case_type}\n\n{text[:8000]}"}],
        )
        _log_token_usage(session.get("username", "unknown"), "Document Issue Spotting", msg.usage)
        return jsonify({"success": True, "issues": msg.content[0].text, "filename": filename})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@portal_attorney_bp.route("/portal/attorney/research/draft", methods=["POST"])
@require_attorney
def research_draft():
    data         = request.get_json() or {}
    motion_type  = data.get("motion_type", "Motion to Suppress").strip()
    issues_text  = data.get("issues", "").strip()
    case_context = data.get("case_context", "").strip()
    username     = data.get("username", "").strip()
    if not issues_text:
        return jsonify({"error": "No issues to draft from."}), 400
    case_type = "Civil Litigation"
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        case_type = client.get("case_type", "Civil Litigation")
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    user_msg = (
        f"Motion/Document Type: {motion_type}\n\n"
        f"Practice Area: {case_type}\n\n"
        f"Case Context:\n{case_context}\n\n"
        f"Identified Issues:\n{issues_text}"
    )
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=4096,
            system=_get_draft_prompt(case_type),
            messages=[{"role": "user", "content": user_msg}],
        )
        _log_token_usage(session.get("username", "unknown"), "Motion Draft Generation", msg.usage)
        return jsonify({"success": True, "draft": msg.content[0].text, "motion_type": motion_type})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@portal_attorney_bp.route("/portal/attorney/research/save-draft", methods=["POST"])
@require_attorney
def research_save_draft():
    data        = request.get_json() or {}
    username    = data.get("username", "").strip()
    category    = data.get("category", "Motions").strip()
    draft_text  = data.get("draft", "").strip()
    filename    = data.get("filename", "").strip()
    motion_type = data.get("motion_type", "motion").strip()
    if not all([username, draft_text, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if category not in DOCS_CATEGORIES:
        category = "Motions"
    dest_dir  = _client_docs_dir(username, category)
    safe_name = secure_filename(filename)
    if not safe_name.lower().endswith(".txt"):
        safe_name += ".txt"
    dest = dest_dir / safe_name
    stem, n = Path(safe_name).stem, 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}.txt"
        n += 1
    dest.write_text(draft_text, encoding="utf-8")

    today     = datetime.now().strftime("%Y-%m-%d")
    entry_ai  = {"date": today, "hours": 0.2,
                 "note": f"AI Research — {motion_type} ({dest.name})", "type": "research_ai",
                 "category": "Research"}
    entry_rev = {"date": today, "hours": 0.2,
                 "note": f"Attorney Review — {motion_type} ({dest.name})", "type": "research_review",
                 "category": "Drafting"}
    client.setdefault("billing_log", []).extend([entry_ai, entry_rev])
    recalc_hours(client)
    save_client(client)
    billing_entry = entry_ai

    return jsonify({
        "success":        True,
        "filename":       dest.name,
        "category":       category,
        "billing_entry":  billing_entry,
        "billing_entry2": entry_rev,
        "total_hours":    client["hours_billed"],
    })


@portal_attorney_bp.route("/portal/attorney/research/save-report", methods=["POST"])
@require_attorney
def research_save_report():
    data        = request.get_json() or {}
    username    = safe_username(data.get("username", ""))
    report_type = data.get("report_type", "").strip()
    text        = data.get("text", "").strip()
    if not all([username, report_type, text]):
        return jsonify({"error": "Missing parameters."}), 400
    if report_type not in ("analysis", "authority"):
        return jsonify({"error": "Invalid report_type. Must be 'analysis' or 'authority'."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    category = "Litigation Drafts"
    if report_type == "analysis":
        label  = "AI legal issues analysis"
        prefix = "legal_issues"
    else:
        label  = "AI legal authority memo"
        prefix = "legal_authority"
    ts        = datetime.now().strftime("%Y%m%d")
    dest_dir  = _client_docs_dir(username, category)
    safe_name = f"{prefix}_{ts}.txt"
    dest      = dest_dir / safe_name
    stem, n   = Path(safe_name).stem, 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}.txt"
        n += 1
    dest.write_text(text, encoding="utf-8")
    today     = datetime.now().strftime("%Y-%m-%d")
    entry_ai  = {"date": today, "hours": 0.2,
                 "note": f"AI Research — {label} ({dest.name})", "type": "research_ai",
                 "category": "Research"}
    entry_rev = {"date": today, "hours": 0.2,
                 "note": f"Attorney Review — {label} ({dest.name})", "type": "research_review",
                 "category": "Drafting"}
    client.setdefault("billing_log", []).extend([entry_ai, entry_rev])
    recalc_hours(client)
    client.setdefault("activity_log", []).append({
        "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "action_type": "time_logged",
        "description": f"0.4 hrs — {label} saved as \"{dest.name}\".",
    })
    save_client(client)
    return jsonify({
        "success":        True,
        "filename":       dest.name,
        "category":       category,
        "billing_entry":  entry_ai,
        "billing_entry2": entry_rev,
        "total_hours":    client["hours_billed"],
    })


# ── Token usage ────────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/token-usage")
@require_attorney
def attorney_token_usage():
    username = session.get("username", "")
    path     = TOKEN_USAGE_DIR / f"{username}.json"
    if not path.exists():
        return jsonify({
            "total_input_tokens": 0, "total_output_tokens": 0,
            "today_input": 0, "today_output": 0,
            "log": [], "by_label": {}
        })
    data  = json.loads(path.read_text(encoding="utf-8"))
    today = datetime.now().strftime("%Y-%m-%d")
    today_in = today_out = 0
    by_label: dict = {}
    for entry in data.get("log", []):
        lbl = entry.get("label", "Other")
        by_label.setdefault(lbl, {"input": 0, "output": 0, "calls": 0})
        by_label[lbl]["input"]  += entry.get("input_tokens", 0)
        by_label[lbl]["output"] += entry.get("output_tokens", 0)
        by_label[lbl]["calls"]  += 1
        if entry.get("timestamp", "").startswith(today):
            today_in  += entry.get("input_tokens", 0)
            today_out += entry.get("output_tokens", 0)
    return jsonify({
        "total_input_tokens":  data.get("total_input_tokens", 0),
        "total_output_tokens": data.get("total_output_tokens", 0),
        "today_input":         today_in,
        "today_output":        today_out,
        "by_label":            by_label,
    })


# ── Firm Insights & Tax Export ─────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/insights")
@require_attorney
def attorney_insights():
    try:
        year = int(request.args.get("year", datetime.now().year))
    except ValueError:
        year = datetime.now().year

    clients_list = all_clients()

    all_leads = []
    for p in LEADS_DIR.glob("*.json"):
        try:
            all_leads.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass

    intake_count       = len(list(CLIENT_FILES_DIR.rglob("intake_*.pdf")))
    total_client_files = sum(1 for p in CLIENT_FILES_DIR.rglob("*") if p.is_file())
    research_sessions  = len(list(RESEARCH_HISTORY_DIR.glob("*.json")))
    draft_sessions     = len(list(DRAFT_HISTORY_DIR.glob("*.json")))

    atty_stats: dict = {}
    for uname, info in ATTORNEYS.items():
        atty_stats[uname] = {
            "display":                  info["display"],
            "total_clients":            0,
            "total_hours_billed":       0.0,
            "total_hours_paid":         0.0,
            "total_revenue_billed":     0.0,
            "total_revenue_collected":  0.0,
            "year_hours_billed":        0.0,
            "year_revenue_billed":      0.0,
            "year_revenue_collected":   0.0,
            "clients_with_court_dates": 0,
            "clients_with_meetings":    0,
            "total_messages":           0,
            "total_time_logs":          0,
            "case_types":               {},
        }

    total_court_dates   = 0
    total_meetings      = 0
    total_messages      = 0
    total_time_logs     = 0
    total_payments_sum  = 0.0
    case_type_breakdown: dict = {}

    for c in clients_list:
        atty = c.get("assigned_attorney", "")
        if atty not in atty_stats:
            continue
        s = atty_stats[atty]
        s["total_clients"] += 1

        hrs      = float(c.get("hours_billed", 0) or 0)
        hrs_paid = float(c.get("hours_paid",   0) or 0)
        s["total_hours_billed"]     += hrs
        s["total_hours_paid"]       += hrs_paid
        s["total_revenue_billed"]   += hrs * HOURLY_RATE

        pmt_sum = sum(float(p.get("amount", 0) or 0) for p in c.get("payments", []))
        s["total_revenue_collected"] += pmt_sum
        total_payments_sum           += pmt_sum

        ct = c.get("case_type", "Other")
        s["case_types"][ct] = s["case_types"].get(ct, 0) + 1
        case_type_breakdown[ct] = case_type_breakdown.get(ct, 0) + 1

        if c.get("next_court_date"):
            total_court_dates += 1
            s["clients_with_court_dates"] += 1
        if c.get("next_meeting"):
            total_meetings += 1
            s["clients_with_meetings"] += 1

        msgs  = len(c.get("messages", []))
        tlogs = len(c.get("time_logs", []))
        total_messages  += msgs
        total_time_logs += tlogs
        s["total_messages"]  += msgs
        s["total_time_logs"] += tlogs

        for entry in c.get("billing_log", []):
            if str(entry.get("date", "")).startswith(str(year)):
                e_hrs = float(entry.get("hours", 0) or 0)
                s["year_hours_billed"]   += e_hrs
                s["year_revenue_billed"] += e_hrs * HOURLY_RATE

        for pmt in c.get("payments", []):
            if str(pmt.get("date", "")).startswith(str(year)):
                s["year_revenue_collected"] += float(pmt.get("amount", 0) or 0)

    for s in atty_stats.values():
        for k in ("total_hours_billed", "total_hours_paid", "total_revenue_billed",
                  "total_revenue_collected", "year_hours_billed",
                  "year_revenue_billed", "year_revenue_collected"):
            s[k] = round(s[k], 2)

    total_leads     = len(all_leads)
    active_leads    = sum(1 for l in all_leads if not l.get("archived"))
    archived_leads  = sum(1 for l in all_leads if l.get("archived"))
    total_clients   = len(clients_list)
    # Share of everyone who ever contacted the firm (every lead, plus clients who
    # came in through intake without a lead record) that became a client.
    denom           = max(total_leads, total_clients)
    conversion_rate = round(total_clients / denom * 100, 1) if denom else 0

    leads_by_source:    dict = {}
    leads_by_case_type: dict = {}
    for l in all_leads:
        src = l.get("source", "Direct")
        leads_by_source[src] = leads_by_source.get(src, 0) + 1
        lct = l.get("case_type", "Unknown")
        leads_by_case_type[lct] = leads_by_case_type.get(lct, 0) + 1

    total_hours      = sum(float(c.get("hours_billed", 0) or 0) for c in clients_list)
    _raw_monthly     = (MONTHLY_RENT + MONTHLY_SALARIES + MONTHLY_SOFTWARE +
                        MONTHLY_INSURANCE + MONTHLY_MARKETING + MONTHLY_MISC)
    monthly_overhead = round(_raw_monthly, 2)
    annual_overhead  = round(_raw_monthly * 12, 2)
    overhead_reserve = round(total_payments_sum * OVERHEAD_RESERVE_PCT, 2)
    est_net_profit   = round(total_payments_sum - overhead_reserve, 2)

    return jsonify({
        "year": year,
        "firm": {
            "total_clients":           total_clients,
            "total_hours_billed":      round(total_hours, 2),
            "total_revenue_billed":    round(total_hours * HOURLY_RATE, 2),
            "total_revenue_collected": round(total_payments_sum, 2),
            "total_court_dates":       total_court_dates,
            "total_meetings":          total_meetings,
            "total_messages":          total_messages,
            "total_time_logs":         total_time_logs,
            "total_client_files":      total_client_files,
            "research_sessions":       research_sessions,
            "draft_sessions":          draft_sessions,
            "intake_forms":            intake_count,
            "hourly_rate":             HOURLY_RATE,
            "case_type_breakdown":     case_type_breakdown,
        },
        "leads": {
            "total":           total_leads,
            "active":          active_leads,
            "archived":        archived_leads,
            "conversion_rate": conversion_rate,
            "by_source":       leads_by_source,
            "by_case_type":    leads_by_case_type,
        },
        "overhead": {
            "monthly_rent":      MONTHLY_RENT,
            "monthly_salaries":  MONTHLY_SALARIES,
            "monthly_software":  MONTHLY_SOFTWARE,
            "monthly_insurance": MONTHLY_INSURANCE,
            "monthly_marketing": MONTHLY_MARKETING,
            "monthly_misc":      MONTHLY_MISC,
            "monthly_total":     monthly_overhead,
            "annual_total":      annual_overhead,
            "reserve_pct":       OVERHEAD_RESERVE_PCT,
            "overhead_reserve":  overhead_reserve,
            "est_net_profit":    est_net_profit,
        },
        "attorneys": atty_stats,
    })


@portal_attorney_bp.route("/portal/attorney/insights/export-tax")
@require_attorney
def insights_export_tax():
    try:
        year = int(request.args.get("year", datetime.now().year))
    except ValueError:
        year = datetime.now().year
    atty_filter  = request.args.get("attorney", "")
    clients_list = all_clients()
    summaries    = []

    for uname, info in ATTORNEYS.items():
        if atty_filter and uname != atty_filter:
            continue
        s = {
            "username":       uname,
            "display":        info["display"],
            "year_hours":     0.0,
            "year_revenue":   0.0,
            "year_collected": 0.0,
            "cases":          0,
            "case_list":      [],
        }
        for c in clients_list:
            if c.get("assigned_attorney") != uname:
                continue
            s["cases"] += 1
            for entry in c.get("billing_log", []):
                if str(entry.get("date", "")).startswith(str(year)):
                    e_hrs = float(entry.get("hours", 0) or 0)
                    s["year_hours"]   += e_hrs
                    s["year_revenue"] += e_hrs * HOURLY_RATE
            for pmt in c.get("payments", []):
                if str(pmt.get("date", "")).startswith(str(year)):
                    s["year_collected"] += float(pmt.get("amount", 0) or 0)
            s["case_list"].append({
                "name": c.get("client_name", ""),
                "type": c.get("case_type",   ""),
                "hrs":  round(float(c.get("hours_billed", 0) or 0), 2),
            })
        s["year_hours"]     = round(s["year_hours"],     2)
        s["year_revenue"]   = round(s["year_revenue"],   2)
        s["year_collected"] = round(s["year_collected"], 2)
        summaries.append(s)

    return render_template(
        "tax_summary.html",
        year=year,
        summaries=summaries,
        hourly_rate=HOURLY_RATE,
    )


# ── Case search ────────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/api/case-search", methods=["POST"])
@require_auth
def api_case_search():
    data      = request.get_json(force=True) or {}
    county    = (data.get("county") or "").strip()
    case_type = (data.get("case_type") or "").strip().lower()
    if not county or case_type not in ("criminal", "civil"):
        return jsonify({"error": "Please select a county and case type."}), 400
    url, court_name = _clerk_url(county, case_type)
    record = {
        "timestamp":   datetime.now().isoformat(),
        "county":      county,
        "case_type":   case_type,
        "ip":          request.remote_addr,
        "destination": url,
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    (CASE_SEARCHES_DIR / f"search_{ts}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return jsonify({"url": url, "court_name": court_name})
