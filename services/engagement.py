"""services/engagement.py — engagement and non-engagement letters filled from the client file.

The firm's reviewed letter wording lives here, so the portal, the assistant and
the blank templates in business/engagement-letters all print the same text:

- flat_fee        flat-fee criminal letter (DUI and most misdemeanors), nonrefundable
                  under Tenn. RPC 1.5(f), paid in full or in two payments
- hourly          hourly with a retainer held in trust
- evergreen       ongoing advisory work with an evergreen retainer
- limited         limited scope (RPC 1.2(c)), hourly or flat
- non_engagement  declining the matter

A letter is drafted automatically when a client file is opened (create-client
or an approved intake), as a Word document on the letterhead in the
attorney-only Drafts folder. The attorney can change the letter type and the
fee amounts and redraft it from Case Overview, or ask the assistant to. The
text is filled in directly, not written by the AI, so the fee wording never
drifts. A declined intake gets a non-engagement letter built from the intake.
"""

import re
import sys
from datetime import date, datetime

import shared
from services import client_files, storage

DRAFT_CATEGORY = "Drafts"
BLANK = "[_____]"

KINDS = {
    "flat_fee":       "Flat-Fee Engagement Letter (Criminal)",
    "hourly":         "Standard Engagement Letter (Hourly)",
    "evergreen":      "Evergreen Advisory Engagement Letter",
    "limited":        "Limited-Scope Engagement Letter",
    "non_engagement": "Non-Engagement Letter",
}
# Fee terms a letter can carry. Amounts are dollars ("3000", "$3,000.00").
AMOUNT_TERMS = ("flat_full", "flat_split_total", "flat_first", "flat_second", "hourly_rate", "retainer")
TEXT_TERMS = ("matter", "second_due", "included", "scope")
MAX_TEXT = 600
MAX_AMOUNT = 1_000_000


class LetterError(ValueError):
    pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def money(value) -> str:
    """'3000' -> '$3,000'; '1750.5' -> '$1,750.50'; blank -> the blank line."""
    s = str(value or "").strip().replace("$", "").replace(",", "")
    if not s:
        return BLANK
    n = float(s)
    return f"${n:,.2f}" if n != int(n) else f"${int(n):,}"


def clean_terms(raw) -> dict:
    """Validated fee terms (amounts as plain numbers, text trimmed). Raises LetterError."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k in AMOUNT_TERMS:
        s = str(raw.get(k) or "").strip().replace("$", "").replace(",", "")
        if not s:
            continue
        if not re.fullmatch(r"\d{1,7}(\.\d{1,2})?", s) or not 0 < float(s) <= MAX_AMOUNT:
            raise LetterError(f"{k.replace('_', ' ')} must be a dollar amount.")
        out[k] = s
    for k in TEXT_TERMS:
        s = " ".join(str(raw.get(k) or "").split())[:MAX_TEXT]
        if s:
            out[k] = s
    return out


def default_kind(client: dict) -> str:
    return "flat_fee" if str(client.get("case_type") or "").startswith("Criminal") else "hourly"


def default_terms(client: dict, kind: str) -> dict:
    """Amounts to start from: the client's flat fee if one is set, else the firm rate."""
    terms = {}
    fee = client.get("flat_fee") if isinstance(client.get("flat_fee"), dict) else {}
    if kind in ("flat_fee", "limited") and fee.get("amount"):
        terms["flat_full"] = str(fee["amount"])
    if kind in ("hourly", "evergreen", "limited"):
        rate = float(shared.HOURLY_RATE)
        terms["hourly_rate"] = str(int(rate)) if rate == int(rate) else f"{rate:.2f}"
    return terms


# ── Letter text ──────────────────────────────────────────────────────────────

def _ctx(client: dict, terms: dict) -> dict:
    c = client or {}
    court = str(c.get("court") or "").strip()
    county = re.sub(r"(?i)\s+county$", "", str(c.get("county") or "").strip())
    case_type = str(c.get("case_type") or "").strip()
    matter = (terms.get("matter") or str(c.get("matter") or "").strip()
              or (f"your {case_type} matter" if case_type else ""))
    return {
        "date": f"{date.today():%B} {date.today().day}, {date.today().year}",
        "name": str(c.get("client_name") or "").strip() or "[Client name]",
        "email": str(c.get("email") or "").strip() or "[Client email]",
        "charges": str(c.get("charges") or "").strip() or "[charge(s)]",
        "court": court or (f"{county} County [General Sessions / Criminal / Circuit] Court" if county
                           else "[County] County [General Sessions / Criminal / Circuit] Court"),
        "case_no": str(c.get("case_no") or "").strip() or "[Case/Warrant No.]",
        "matter": matter.rstrip(".") or "[describe the matter]",
        "re_matter": _re_matter(matter.rstrip(".")) or "[Matter]",
        **{k: money(terms.get(k)) for k in AMOUNT_TERMS},
        "second_due": terms.get("second_due") or "[date] or before the [first court setting], whichever comes first",
        "included": terms.get("included") or "",
        "scope": terms.get("scope") or "[describe the specific tasks]",
        "bpr": shared.ATTORNEY_BPR or BLANK,
    }


def _re_matter(matter: str) -> str:
    """"your Criminal Defense matter" -> "Criminal Defense matter" for the Re: line."""
    m = re.sub(r"(?i)^your\s+", "", matter or "").strip()
    return m[:1].upper() + m[1:]


def _head(x: dict, re_line: str) -> list:
    return [x["date"], "VIA E-MAIL", x["name"], x["email"], f"Re: {re_line}", f"Dear {x['name']}:"]


def _sign(x: dict, ask: str = "please sign and date below and return it to me",
          questions: str = "If you have any questions about this letter, please contact me before signing.",
          accept: str = "ACCEPTED AND AGREED:") -> list:
    return [f"If this letter accurately reflects your understanding of the terms of our engagement, {ask}. {questions}",
            "Sincerely,", "/s/ Madison T. Biggs", "Madison T. Biggs", "Attorney at Law", shared.FIRM_NAME,
            f"BPR No. {x['bpr']}", accept, "______________________________", x["name"], "Date: ________________"]


NO_GUARANTEE = ("MT Legal will take reasonable steps to protect your rights and will make good-faith efforts to "
                "achieve your goals. However, I cannot promise or guarantee any particular outcome. Any statements "
                "about possible outcomes are my professional opinion only. You agree to cooperate with me, to be "
                "truthful, and to provide requested information and documents promptly so that I can represent "
                "you effectively.")

TERMINATION_HOURLY = ("You may end this engagement at any time. MT Legal may withdraw as permitted by the Tennessee "
                      "Rules of Professional Conduct and, where required, with the court's permission, including if "
                      "you fail to cooperate, fail to meet your obligations under this agreement (including payment "
                      "and replenishment of the retainer), or if continued representation becomes otherwise "
                      "inappropriate. If the engagement ends, you agree to pay for services performed and costs "
                      "incurred through the date it ends, including reasonable time needed to transfer the file and, "
                      "where necessary, to seek the court's permission to withdraw.")

FILE_RETENTION = ("Your file will be kept for five (5) years after the representation ends. After that, it may be "
                  "destroyed without further notice to you, except for materials MT Legal elects or is required to "
                  "keep longer. You may request a copy of your file at any time before then.")

# The nonrefundable-fee paragraphs (Tenn. RPC 1.5(f)): reviewed wording, used as is.
NONREFUNDABLE = (
    "You and MT Legal agree that the flat fee, and each installment of it, is nonrefundable and is earned by MT "
    "Legal when paid. Because the fee is earned when paid, it is the firm's property on receipt. It will be "
    "deposited into the firm's operating account and will not be held in a client trust account. This agreement "
    "is made under Rule 1.5(f) of the Tennessee Rules of Professional Conduct, which permits a nonrefundable fee "
    "only when it is agreed to in a writing signed by the client that explains the intent of the parties as to "
    "the nature and amount of the fee.",
    "The flat fee is charged for my commitment to your Case and my availability to handle it, not for a "
    "particular number of hours. The fee does not change if your Case resolves quickly or takes longer than "
    "expected within the scope above. MT Legal keeps internal records of the time spent on your Case for its own "
    "purposes; you will not be billed by the hour.",
    "Even though the fee is nonrefundable, the Tennessee Rules of Professional Conduct require every fee to be "
    "reasonable. If the representation ends before the work described above is complete, whether because you "
    "discharge MT Legal or because MT Legal withdraws, you may be entitled to a refund of any part of the fee that "
    "it would be unreasonable for MT Legal to keep in light of the work performed. The fee is not refundable "
    "simply because of the outcome of the Case, including if charges are dismissed early.",
)


def _flat_fee(x: dict) -> list:
    included = (f"Also included in this fee: {x['included']}." if x["included"] else
                "Also included in this fee (check any that apply): ___ Bench trial in General Sessions  "
                "___ Petition for restricted driver's license  ___ Expungement petition if the Case is dismissed  "
                "___ Other: ____________________")
    return _head(x, f"Flat-Fee Engagement: {x['charges']}, {x['court']}, {x['case_no']}") + [
        "Thank you for choosing MT Legal to represent you. This letter sets out the terms of our engagement, "
        "including the flat fee you have agreed to pay. Please read it carefully, especially the section titled "
        "\"Nonrefundable Flat Fee.\"",
        "SCOPE OF REPRESENTATION",
        f"MT Legal will represent you on the charge(s) of {x['charges']} pending in the {x['court']}, "
        f"{x['case_no']} (the \"Case\"). The flat fee covers the following work in the Case: review of the warrant, "
        "citation, and available discovery; investigation reasonably necessary to evaluate your defenses; "
        "communications and negotiations with the prosecution; court appearances through disposition in the court "
        "named above, including any preliminary hearing, motion hearings, and a plea or dismissal; and advising you "
        "about your options at each stage.",
        "Unless included below or agreed in a later signed writing, the flat fee does not include: (a) a jury or "
        "bench trial; (b) representation in Criminal or Circuit Court after the Case is bound over to the grand jury "
        "or indicted; (c) any appeal; (d) probation violation proceedings; (e) a petition for expungement; (f) a "
        "petition for a restricted driver's license; (g) any separate administrative, civil, forfeiture, or "
        "immigration proceeding; and (h) any other charge or case. If you would like me to handle any of that work, "
        "I will tell you the additional fee in writing before I begin.",
        included,
        "FLAT FEE AND PAYMENT OPTION",
        "The fee for the representation described above is a flat fee, not an hourly fee. You will not receive "
        "hourly invoices. Please initial ONE payment option:",
        f"____ Option A, Paid in Full: A flat fee of {x['flat_full']}, paid in full before work begins.",
        f"____ Option B, Two Payments: A flat fee of {x['flat_split_total']}, paid in two installments: "
        f"{x['flat_first']} before work begins, and {x['flat_second']} due on or before {x['second_due']}. "
        "Option B costs more than Option A because the firm carries part of the fee while your case is underway.",
        "If you choose Option B and the second installment is not paid when due, MT Legal may stop all work except "
        "what is needed to protect your interests and may ask the court for permission to withdraw. Any installment "
        "paid is subject to the same nonrefundable terms below.",
        "NONREFUNDABLE FLAT FEE",
        *NONREFUNDABLE,
        "COSTS AND EXPENSES",
        "The flat fee does not include costs. You agree to pay reasonable costs incurred in the Case, such as court "
        "costs, fines, and fees assessed by the court; filing and service fees; subpoena fees; transcript and "
        "recording charges; investigator fees; independent testing of blood or other evidence; and expert witness "
        "fees. I will consult with you before incurring any cost over $100 and will not incur it without your "
        "approval. Court costs, fines, and fees assessed in the disposition of your Case are your responsibility and "
        "are separate from this agreement.",
        "YOUR OBLIGATIONS IN A CRIMINAL CASE",
        "You agree to appear at every court date unless I tell you in writing that your appearance has been excused; "
        "to comply with all conditions of your bond or release; to keep me informed of any change in your phone "
        "number, email, or address; and not to discuss the facts of the Case with anyone other than me, including on "
        "social media. Missing a court date can result in a warrant for your arrest and forfeiture of your bond.",
        "If you are not a United States citizen, please tell me. A criminal charge or plea can have serious "
        "immigration consequences, and I need that information to advise you.",
        NO_GUARANTEE,
        "ENDING THE REPRESENTATION",
        "You may discharge MT Legal at any time. MT Legal may withdraw as permitted by the Tennessee Rules of "
        "Professional Conduct, including if you fail to cooperate, fail to make a required payment, or if continued "
        "representation becomes otherwise inappropriate. Once I have appeared in the Case, withdrawal may require "
        "the court's permission. Any refund after early termination will be determined as described under "
        "\"Nonrefundable Flat Fee.\" The representation will otherwise end when the Case is resolved in the court "
        "named above or when the work described in the scope above is complete.",
        FILE_RETENTION,
    ] + _sign(x, ask="please initial your payment option above, sign and date below, and return it to me",
              accept="ACCEPTED AND AGREED. I have read this agreement, including the section titled \"Nonrefundable "
                     "Flat Fee,\" and I understand that the flat fee is earned when paid and is nonrefundable except "
                     "as stated above.")


def _retainer_text(x: dict) -> str:
    return (f"The retainer is an advance deposit against fees and costs. It remains your property until earned and "
            f"will be held in MT Legal's client trust (IOLTA) account.")


def _hourly(x: dict) -> list:
    return _head(x, f"Engagement: {x['re_matter']}") + [
        f"Thank you for choosing MT Legal to represent you regarding {x['matter']}. This letter confirms the terms "
        "of our engagement.",
        NO_GUARANTEE,
        "HOURLY FEES",
        f"You agree to pay for MT Legal's services based on the time spent working on your matter. My hourly rate is "
        f"{x['hourly_rate']}. Time is recorded in tenths of an hour. You will be billed for all time reasonably spent "
        "on your matter, including legal research, drafting, document review, case preparation, court appearances, "
        "conferences, written and oral communications, travel time, and time spent waiting for court appearances or "
        "other proceedings. If I ever ask another lawyer or staff member to work on your matter, you will be told "
        "their rate in writing before you are billed for their time.",
        "COSTS",
        "You also agree to pay reasonable costs incurred in your matter, including filing fees, service and subpoena "
        "fees, court reporter and transcript charges, postage and delivery charges, travel expenses, and other "
        "reasonably necessary expenses. I will consult with you before incurring any significant expense when "
        "reasonably practicable.",
        "RETAINER",
        f"You agree to pay an initial retainer of {x['retainer']} before work begins. " + _retainer_text(x) +
        " Fees and costs will be paid from the retainer as they are billed. If the representation ends before the "
        "retainer is used, any unearned balance will be refunded to you. If the retainer is used up before the "
        "representation ends, you agree to replenish it within seven (7) days of my request, or sooner if needed "
        "because of an upcoming deadline, hearing, or mediation. MT Legal may require an additional deposit before "
        "substantial work such as contested hearings, mediation, extensive discovery, expert work, or trial "
        "preparation.",
        "Legal matters, particularly contested ones, can be time-intensive and expensive. Total fees and costs may "
        "exceed the initial retainer depending on the issues involved, the conduct of other parties, discovery, "
        "motion practice, hearings, and trial.",
        "INVOICES",
        "You will receive an invoice showing the work performed, the time spent, and how the retainer was applied. "
        "Invoices are due on receipt. Please raise any question about an invoice in writing within fifteen (15) days "
        "of receiving it so that we can address it promptly. MT Legal may suspend work, to the extent permitted by "
        "the Rules of Professional Conduct and court rules, if invoices remain unpaid or the retainer is not "
        "replenished.",
        "ENDING THE REPRESENTATION",
        TERMINATION_HOURLY,
        FILE_RETENTION,
    ] + _sign(x)


def _evergreen(x: dict) -> list:
    return _head(x, f"Advisory Engagement: {x['re_matter']}") + [
        f"Thank you for choosing MT Legal to advise you regarding {x['matter']}. This letter confirms the terms of "
        "our engagement.",
        "SCOPE OF REPRESENTATION",
        f"MT Legal will provide ongoing legal advice and guidance about your legal options and developments in this "
        f"matter, including {x['scope']}. The engagement is limited to advisory representation and consultation. "
        "Litigation, court filings, hearings, contested proceedings, or other substantial legal work beyond advisory "
        "services will require a new or amended written engagement agreement and may require an additional "
        "retainer.",
        NO_GUARANTEE,
        "HOURLY FEES AND COSTS",
        f"You agree to pay for MT Legal's services based on the time spent on the matter at my hourly rate of "
        f"{x['hourly_rate']}, recorded in tenths of an hour, including legal research, drafting, document review, "
        "strategy discussions, factual investigation, and written or oral communications. You also agree to pay "
        "reasonable costs incurred in the matter, such as filing fees, postage, records charges, and travel expenses. "
        "I will consult with you before incurring any significant expense.",
        "EVERGREEN RETAINER",
        f"You agree to pay an evergreen retainer of {x['retainer']} before work begins. " + _retainer_text(x) +
        " Fees and costs will be paid from the retainer as they are billed, and you agree to replenish the retainer "
        "to its full amount within seven (7) days of each request, or sooner if needed because of an emergency, "
        "deadline, or hearing. At the end of the representation, any unearned balance will be refunded to you. "
        "Please raise any question about an invoice in writing within fifteen (15) days of receiving it.",
        "ENDING THE REPRESENTATION",
        TERMINATION_HOURLY,
        FILE_RETENTION,
    ] + _sign(x)


def _limited(x: dict) -> list:
    flat = x["flat_full"] != BLANK
    hourly = x["hourly_rate"] != BLANK and not flat
    fee_lines = []
    if hourly or not flat:
        fee_lines.append(
            f"{'' if hourly else '____ '}Hourly: You agree to pay for MT Legal's services at my hourly rate of "
            f"{x['hourly_rate']}, recorded in tenths of an hour, for the work described above. You agree to pay a "
            f"retainer of {x['retainer']} before work begins. " + _retainer_text(x) +
            " Any unearned balance will be refunded when the engagement ends, and you agree to replenish the retainer "
            "within seven (7) days of a request.")
    if flat or not hourly:
        fee_lines.append(
            f"{'' if flat else '____ '}Flat fee: You agree to pay a flat fee of {x['flat_full']} for the work "
            "described above, paid before work begins. The flat fee is nonrefundable and earned by MT Legal when "
            "paid, will be deposited into the firm's operating account, and will not be held in trust, as permitted "
            "by Rule 1.5(f) of the Tennessee Rules of Professional Conduct. If the engagement ends before the work "
            "described above is complete, you may be entitled to a refund of any part of the fee that it would be "
            "unreasonable for MT Legal to keep in light of the work performed.")
    return _head(x, f"Limited-Scope Engagement: {x['re_matter']}") + [
        f"Thank you for choosing MT Legal to provide limited-scope representation in connection with {x['matter']}. "
        "This letter confirms the terms and the limited scope of our engagement, as permitted by Rule 1.2(c) of the "
        "Tennessee Rules of Professional Conduct.",
        "SCOPE OF REPRESENTATION",
        f"MT Legal's representation is limited to the following: {x['scope']}.",
        "MT Legal does not represent you in any other matter or proceeding and will not be responsible for "
        "monitoring deadlines, preparing pleadings or discovery, or advising you in any other matter. Any contested "
        "proceeding, motion, hearing, or appeal arising from this work is outside the scope of this engagement "
        "unless we agree in writing to expand it. MT Legal may require an additional fee before taking on expanded "
        "work and is not obligated to accept it.",
        NO_GUARANTEE,
        "FEES" if (flat or hourly) else "FEES (initial ONE)",
        *fee_lines,
        "COSTS",
        "You also agree to pay reasonable costs incurred within the scope of this engagement, such as filing fees, "
        "service and subpoena fees, records charges, and postage. I will consult with you before incurring any "
        "significant expense. Please raise any question about an invoice in writing within fifteen (15) days of "
        "receiving it.",
        "ENDING THE REPRESENTATION",
        "You may end this engagement at any time. MT Legal may withdraw as permitted by the Tennessee Rules of "
        "Professional Conduct. Unless otherwise agreed in writing, the representation will end when the services "
        "described above are complete, or when further work would fall outside the agreed scope and we have not "
        "agreed in writing to expand it.",
        FILE_RETENTION,
    ] + _sign(x, questions="If you have any questions about this letter, including the limited scope of "
                           "representation, please contact me before signing.")


def _non_engagement(x: dict) -> list:
    return _head(x, f"Non-Engagement: {x['re_matter']}") + [
        f"Thank you for contacting MT Legal about {x['matter']}. I appreciate the opportunity to consider your "
        "matter. After review, MT Legal has decided not to represent you in this matter. This letter confirms that "
        "decision so that there is no misunderstanding.",
        "NO ATTORNEY-CLIENT RELATIONSHIP",
        "MT Legal does not represent you, has not agreed to represent you, and will not take any action on your "
        "behalf in this matter, including filing anything, contacting any other party, or monitoring any deadline. "
        "No attorney-client relationship has been formed. Our decision is not a judgment about the merits of your "
        "matter, and you should not rely on anything said during our communications as legal advice about it.",
        "DEADLINES MAY APPLY",
        "Your matter may be subject to strict deadlines, including statutes of limitations, court dates, and other "
        "time limits, which may already be running. If those deadlines pass, you may lose rights or claims "
        "permanently. If you wish to pursue this matter, I strongly encourage you to consult another attorney right "
        "away. If you need help finding one, the Nashville Bar Association lawyer referral service and the Tennessee "
        "Bar Association can assist you.",
        "YOUR INFORMATION AND DOCUMENTS",
        "Information you shared with MT Legal about your matter will be kept confidential as required by the "
        "Tennessee Rules of Professional Conduct. If you provided any original documents, they are enclosed or "
        "available for you to pick up. MT Legal has not kept copies except as needed to record this decision and "
        "check for conflicts of interest.",
        "No fee is owed to MT Legal for our review of your matter. Thank you again for considering MT Legal, and I "
        "wish you the best in resolving this matter.",
        "Sincerely,", "/s/ Madison T. Biggs", "Madison T. Biggs", "Attorney at Law", shared.FIRM_NAME,
        f"BPR No. {x['bpr']}",
    ]


_BUILDERS = {"flat_fee": _flat_fee, "hourly": _hourly, "evergreen": _evergreen,
             "limited": _limited, "non_engagement": _non_engagement}


def letter_text(kind: str, client: dict, terms: dict | None = None) -> str:
    """The letter as plain text (one paragraph per line), filled from `client`."""
    if kind not in _BUILDERS:
        raise LetterError("Unknown letter type.")
    return "\n".join(_BUILDERS[kind](_ctx(client, terms or {})))


def letter_docx(kind: str, client: dict, terms: dict | None = None) -> bytes:
    from services.docx_writer import text_to_docx
    return text_to_docx(KINDS[kind], letter_text(kind, client, terms), shared.MANAGING_PARTNER["display"])


# ── Drafts in the client file ────────────────────────────────────────────────

def draft(username: str, kind: str | None = None, terms=None, by: str = "") -> dict:
    """Draft (or redraft) the client's letter into Drafts. Returns the saved
    client's letter record. Raises LetterError."""
    client = storage.load_client(username)
    if not client:
        raise LetterError("Client not found.")
    kind = kind or default_kind(client)
    if kind not in KINDS:
        raise LetterError("Unknown letter type.")
    terms = clean_terms(terms) if terms is not None else default_terms(client, kind)
    data = letter_docx(kind, client, terms)
    folder = storage._client_docs_dir(username, DRAFT_CATEGORY)
    stem = "DRAFT_" + re.sub(r"[^A-Za-z0-9]+", "_", KINDS[kind]).strip("_") + f"_{date.today():%Y%m%d}"
    dest, n = folder / f"{stem}.docx", 2
    while dest.exists():
        dest, n = folder / f"{stem}_{n}.docx", n + 1
    client_files.write_path(dest, data)
    old = client.get("engagement_letter") if isinstance(client.get("engagement_letter"), dict) else {}
    record = {"kind": kind, "title": KINDS[kind], "terms": terms, "category": DRAFT_CATEGORY,
              "filename": dest.name, "at": _now(), "by": by or "auto"}

    def save(c):
        c["engagement_letter"] = record
        c.setdefault("activity_log", []).append({
            "timestamp": _now(), "action_type": "document_generated",
            "description": f"{KINDS[kind]} {'redrafted' if old else 'drafted'}: {DRAFT_CATEGORY}/{dest.name}"})
    storage.update_client_atomic(username, save)
    # The previous draft of this letter is replaced, so Drafts holds one copy.
    prev = old.get("filename")
    if prev and prev != dest.name and old.get("category") == DRAFT_CATEGORY:
        try:
            (folder / prev).unlink(missing_ok=True)
        except OSError:
            pass
    return record


def auto_draft(username: str) -> None:
    """Draft the engagement letter for a newly opened client file (never raises)."""
    try:
        client = storage.load_client(username)
        if client and not client.get("engagement_letter"):
            draft(username)
    except Exception as exc:
        print(f"[engagement] auto draft failed for {username}: {exc!r}", file=sys.stderr)


def view(client: dict) -> dict:
    """The letter card for Case Overview: the current draft and the fee terms
    to edit, with defaults for a client that has none yet."""
    rec = client.get("engagement_letter") if isinstance(client.get("engagement_letter"), dict) else {}
    kind = rec.get("kind") or default_kind(client)
    return {"draft": rec or None, "kind": kind, "terms": rec.get("terms") or default_terms(client, kind),
            "defaults": {k: default_terms(client, k) for k in KINDS},
            "kinds": [{"key": k, "label": v} for k, v in KINDS.items()]}


def intake_client(fields: dict) -> dict:
    """A client-shaped dict from intake fields, for a declined intake's letter."""
    f = fields or {}
    return {"client_name": f.get("full_name", ""), "email": f.get("email", ""),
            "case_type": f.get("case_type", ""), "court": f.get("court_name", ""),
            "county": f.get("county", ""), "case_no": f.get("case_no", ""),
            "matter": f"your {f['case_type']} matter" if f.get("case_type") else "your legal matter"}
