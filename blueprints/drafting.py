"""blueprints/drafting.py — Document drafting (attorney tool + portal claim)."""

import html
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
import anthropic
import billing

from conflicts import record_check
from security import begin_login_attempt, clear_login_failures, lockout_message
from shared import (
    require_auth, require_attorney,
    DRAFT_HISTORY_DIR, MODEL, MIN_PASSWORD_LENGTH,
    get_anthropic_client, load_client, save_client, hash_password, check_password,
    ATTORNEYS, CASE_ATTORNEY_MAP,
    _make_username, base_username, _log_activity, _client_docs_dir, recalc_hours,
)

drafting_bp = Blueprint("drafting", __name__)

# ── System prompt ─────────────────────────────────────────────────────────────

DRAFTING_SYSTEM_PROMPT = """You are an expert legal document drafter for a solo attorney practice.
Generate professional, complete legal documents based on the template type and variables provided.
Output ONLY the document text — no commentary, no markdown, no explanation.
Use formal legal language appropriate for the document type.
Leave blanks as [TO BE COMPLETED] if a required variable is missing."""

# ── Template prompts (trimmed to essentials; full set preserved from app.py) ──

TEMPLATE_PROMPTS = {
    "Demand Letter": """Draft a professional demand letter with:
Client Name (sender): {client_name} | Opposing Party: {opposing_party}
Matter Description: {matter_description} | Demand Amount: {demand_amount}
Response Deadline: {response_deadline}
Include: factual background, legal basis, specific demand, consequences of non-response.""",

    "Landlord-Tenant Notice": """Draft a formal landlord-tenant notice with:
Landlord Name: {landlord_name} | Tenant Name(s): {tenant_name}
Property Address: {property_address} | Notice Type: {notice_type}
Amount Owed (if applicable): {amount_owed} | Cure/Compliance Deadline: {cure_deadline}
Include proper statutory notice language, violation description, cure period, consequences.""",

    "Rental Agreement": """Draft a comprehensive residential rental agreement with:
Landlord: {landlord_name} | Tenant(s): {tenant_name} | Property: {property_address}
Monthly Rent: {monthly_rent} | Security Deposit: {security_deposit} | Lease Term: {lease_term}
Utilities Included: {utilities_included} | Pet Policy: {pet_policy}
Include all standard residential lease provisions.""",

    "LLC Operating Agreement": """Draft an LLC operating agreement with:
LLC Name: {llc_name} | State: {state_of_formation} | Members: {members_and_ownership}
Purpose: {business_purpose} | Registered Agent: {registered_agent}
Management Structure: {management_structure}
Include formation, capital contributions, profit/loss allocation, management, transfer restrictions.""",

    "Last Will and Testament": """Draft a last will and testament with:
Testator: {testator_name} | Executor: {executor_name} | Beneficiaries: {beneficiaries}
Asset Distribution: {asset_distribution} | Specific Bequests: {specific_bequests}
Guardian (if minors): {guardian_name}
Include testamentary intent, executor appointment, bequests, residuary estate, attestation block.""",

    "Divorce Petition": """Draft a divorce petition with:
Petitioner: {petitioner_name} | Respondent: {respondent_name}
Date of Marriage: {date_of_marriage} | Grounds: {grounds_for_divorce}
Minor Children: {minor_children} | Property Overview: {property_division}
Spousal Support: {spousal_support}
Include jurisdictional allegations, grounds, prayer for relief, signature block.""",

    "DeFi Engagement Letter": """Draft a DeFi/cryptocurrency legal engagement letter with:
Client: {client_name} | Matter: {matter_description} | Jurisdiction: {jurisdiction}
Include: scope of representation, fee structure (flat/LaaS/hourly placeholders),
DeFi-specific disclaimers (rapidly evolving law, no guarantee of regulatory outcomes,
recommend Solidity auditor alongside legal review, tax advice requires CPA),
conflict acknowledgment, signature blocks.""",

    "Token Offering Checklist": """Create a token offering compliance checklist with:
Client: {client_name} | Project: {project_name} | Token Type: {token_type}
Description: {matter_description}
Include: Securities Exemption Analysis (Reg D 506b/506c/Reg A+/Reg S/Reg CF),
Required Documents checklist with status fields, Investor Qualification Requirements,
Timeline and Filing Deadlines, Ongoing Compliance Obligations.""",

    "Smart Contract Review Memo": """Draft a smart contract legal review memo with:
Client: {client_name} | Contract: {contract_name} | Context: {matter_description}
Include: Contract Summary, Compliance Issues, Risk Rating (Low/Medium/High) for transfer
restrictions, admin key privileges, upgrade proxy risks, oracle dependencies, reentrancy
liability exposure, Recommended Modifications, Disclaimer (legal analysis only — Solidity
security audit recommended separately).""",

    "DAO Formation Checklist": """Create a DAO formation and legal wrapper checklist with:
Client: {client_name} | DAO Name: {dao_name} | Purpose: {matter_description}
Jurisdiction: {jurisdiction}
Include: Entity Type Recommendation (Wyoming DAO LLC/Cayman Foundation/Marshall Islands/
Swiss Association/BVI), Formation Documents checklist, Token Governance Considerations,
Regulatory Exposure Summary.""",

    "Parenting Plan": """Draft a comprehensive Tennessee Permanent Parenting Plan with:
Petitioner: {petitioner_name} | Respondent: {respondent_name}
Minor Children: {minor_children} | Primary Residence: {primary_residence}
Parenting Schedule: {parenting_schedule} | Holiday Schedule: {holiday_schedule}
Decision-Making Authority: {decision_making}
Format consistent with T.C.A. § 36-6-404. Include relocation restrictions and dispute resolution.""",

    "Child Support Worksheet": """Draft a child support calculation worksheet with:
Petitioner: {petitioner_name} | Respondent: {respondent_name}
Children: {minor_children} | Petitioner Income: {petitioner_income}
Respondent Income: {respondent_income} | Parenting Time: {parenting_time}
Health Insurance: {health_insurance} | Childcare: {childcare_cost}
Include Tennessee Child Support Guidelines analysis and modification threshold note.""",

    "Property Settlement Agreement": """Draft a marital property settlement agreement with:
Petitioner: {petitioner_name} | Respondent: {respondent_name}
Date of Marriage: {date_of_marriage} | Marital Assets: {marital_assets}
Marital Debts: {marital_debts} | Separate Property: {separate_property}
Spousal Support: {spousal_support}
Format for Tennessee court submission. Include QDRO reference if retirement accounts involved.""",

    "Personal Injury Demand Letter": """Draft a personal injury demand letter with:
Client: {client_name} | Defendant: {opposing_party} | Insurer: {insurance_company}
Claim/Policy No.: {claim_number} | Incident: {incident_description}
Injuries: {injuries} | Medical Treatment: {medical_treatment}
Special Damages: {special_damages} | General Damages Demand: {general_damages_demand}
Settlement Demand: {demand_amount} | Deadline: {response_deadline}
Include negligence elements, itemized damages, policy limits request, reservation of rights.""",

    "Employment Separation Agreement": """Draft an employment separation agreement with:
Employee: {client_name} | Employer: {employer_name} | Last Day: {termination_date}
Severance: {severance_terms} | COBRA/Benefits: {benefits_continuation}
Non-Disparagement: {non_disparagement} | Return of Property: {return_of_property}
Governing State: {jurisdiction}
Include general release, ADEA provisions (if 40+), confidentiality, integration clause.""",

    "EEOC Charge Narrative": """Draft an EEOC charge narrative with:
Charging Party: {client_name} | Employer: {employer_name}
Employment Dates: {employment_dates} | Position: {position}
Basis of Discrimination: {discrimination_basis} | Description: {matter_description}
Most Recent Act: {last_act_date} | Prior Complaints: {internal_complaints}
Include basis of charge, chronological narrative, comparator evidence, adverse action, timeliness note.""",

    "Real Estate Purchase Agreement": """Draft a residential real estate purchase agreement with:
Buyer: {buyer_name} | Seller: {seller_name} | Property: {property_address}
Purchase Price: {purchase_price} | Earnest Money: {earnest_money}
Financing Contingency: {financing_terms} | Inspection Period: {inspection_period}
Closing Date: {closing_date} | Personal Property Included: {personal_property}
Include all standard Tennessee real property transaction provisions.""",

    "Eviction Notice (Detainer Warrant)": """Draft an eviction notice with:
Landlord: {landlord_name} | Tenant(s): {tenant_name} | Property: {property_address}
Grounds: {eviction_grounds} | Amount Owed: {amount_owed}
Notice Period: {notice_period} | Prior Notices: {prior_notices}
Include Tennessee statutory citations (T.C.A. § 66-28-505, § 29-18-104),
detainer warrant filing procedure, URLTA applicability note.""",

    "Contract Breach Demand Letter": """Draft a contract breach demand letter with:
Client (non-breaching party): {client_name} | Breaching Party: {opposing_party}
Contract: {contract_description} | Date: {contract_date}
Description of Breach: {matter_description} | Damages: {damages}
Demand: {demand_amount} | Response Deadline: {response_deadline}
Include specific breach, damages quantification, reservation of rights, dispute resolution clause reference.""",
}

_ALL_VARS = {
    "client_name": "", "matter_description": "", "opposing_party": "",
    "demand_amount": "", "response_deadline": "",
    "landlord_name": "", "tenant_name": "", "property_address": "",
    "notice_type": "", "amount_owed": "", "cure_deadline": "",
    "monthly_rent": "", "security_deposit": "", "lease_term": "",
    "utilities_included": "", "pet_policy": "",
    "llc_name": "", "state_of_formation": "", "members_and_ownership": "",
    "business_purpose": "", "registered_agent": "", "management_structure": "",
    "testator_name": "", "executor_name": "", "beneficiaries": "",
    "asset_distribution": "", "specific_bequests": "", "guardian_name": "",
    "petitioner_name": "", "respondent_name": "", "date_of_marriage": "",
    "grounds_for_divorce": "", "minor_children": "", "property_division": "",
    "spousal_support": "",
    "project_name": "", "token_type": "", "contract_name": "",
    "dao_name": "", "jurisdiction": "",
    "primary_residence": "", "parenting_schedule": "", "holiday_schedule": "",
    "decision_making": "",
    "petitioner_income": "", "respondent_income": "", "parenting_time": "",
    "health_insurance": "", "childcare_cost": "",
    "marital_assets": "", "marital_debts": "", "separate_property": "",
    "insurance_company": "", "claim_number": "", "incident_description": "",
    "injuries": "", "medical_treatment": "", "special_damages": "",
    "general_damages_demand": "",
    "employer_name": "", "termination_date": "", "severance_terms": "",
    "benefits_continuation": "", "non_disparagement": "", "return_of_property": "",
    "employment_dates": "", "position": "", "discrimination_basis": "",
    "last_act_date": "", "internal_complaints": "",
    "buyer_name": "", "seller_name": "", "purchase_price": "",
    "earnest_money": "", "financing_terms": "", "inspection_period": "",
    "closing_date": "", "personal_property": "",
    "eviction_grounds": "", "notice_period": "", "prior_notices": "",
    "contract_description": "", "contract_date": "", "damages": "",
}


@drafting_bp.route("/drafting")
@require_auth
@require_attorney
def drafting():
    return render_template("drafting.html")


@drafting_bp.route("/drafting/generate", methods=["POST"])
@require_auth
@require_attorney
def drafting_generate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received."}), 400

    template_type = data.get("template_type", "").strip()
    variables     = data.get("variables", {})

    if template_type not in TEMPLATE_PROMPTS:
        return jsonify({"error": "Invalid template type."}), 400

    try:
        client = get_anthropic_client()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500

    all_vars = dict(_ALL_VARS)
    all_vars.update({k: v for k, v in variables.items() if v})
    user_prompt = TEMPLATE_PROMPTS[template_type].format(**all_vars)

    try:
        message = client.messages.create(
            model=MODEL, max_tokens=4096,
            system=DRAFTING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        draft_text = message.content[0].text
        try:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = template_type.lower().replace(" ", "_")
            with open(DRAFT_HISTORY_DIR / f"{ts}_{slug}.json", "w") as f:
                json.dump({"timestamp": ts, "template_type": template_type,
                           "variables": all_vars, "draft": draft_text}, f, indent=2)
        except Exception:
            pass
        return jsonify({"success": True, "draft": draft_text})
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Please check your .env file."}), 401
    except anthropic.APIError as e:
        return jsonify({"error": f"API error: {str(e)}"}), 500


@drafting_bp.route("/drafting/claim-document", methods=["POST"])
@require_auth
def drafting_claim_document():
    data          = request.get_json() or {}
    full_name     = data.get("full_name", "").strip()
    password      = data.get("password", "").strip()
    email         = data.get("email", "").strip()
    phone         = data.get("phone", "").strip()
    case_type     = data.get("case_type", "Other").strip()
    template_type = data.get("template_type", "Generated Document").strip()
    draft_content = data.get("draft_content", "").strip()

    if not full_name or not password:
        return jsonify({"error": "Full name and password are required."}), 400
    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "error": f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        }), 400
    if not draft_content:
        return jsonify({"error": "No document content to save."}), 400

    atty         = CASE_ATTORNEY_MAP.get(case_type, "Endocide")
    atty_display = ATTORNEYS[atty]["display"]
    now_str      = datetime.now().strftime("%Y-%m-%d")
    now_ts       = datetime.now().strftime("%Y%m%d_%H%M%S")

    # An account may already exist for this name. Adding a document and billable
    # time to it requires that account's password — a name alone is not proof of
    # identity. Otherwise create a fresh, non-colliding account.
    claim_user = base_username(full_name)
    ip         = request.remote_addr or ""
    existing   = load_client(claim_user)
    # Only guessing an existing account's password is throttled; creating a
    # fresh account has nothing to guess.
    wait       = begin_login_attempt("claim", claim_user, ip) if existing else 0
    if wait:
        return jsonify({"error": lockout_message(wait)}), 429
    if existing and not check_password(password, existing.get("password", "")):
        return jsonify({
            "error": "An account already exists for this name. Enter that account's "
                     "password to save the document to it, or log in to your portal."
        }), 403
    if existing:
        clear_login_failures("claim", claim_user, ip)

    if existing:
        username = existing["username"]
        record   = existing
        if email and not record.get("email"):
            record["email"] = email
        if phone and not record.get("phone"):
            record["phone"] = phone
    else:
        username = _make_username(full_name)
        record = {
            "username":           username,
            "password":           hash_password(password),
            "client_name":        full_name,
            "case_type":          case_type,
            "assigned_attorney":  atty,
            "legal_issue":        f"Document generated via drafting tool: {template_type}",
            "next_court_date":    "",
            "hours_billed":       0,
            "last_communication": now_str,
            "phone":              phone,
            "email":              email,
            "google_drive_url":   "",
            "next_meeting":       "",
            "time_logs":          [],
            "notes":              [],
            "billing_log": [{
                "date":     now_str,
                "hours":    0.2,
                "note":     f"Intake Processing — New Client File Opened ({case_type})",
                "type":     "intake",
                "category": "Intake",
            }],
            "activity_log": [],
            "messages": [{
                "from": "attorney",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "text": (
                    f"Welcome to your MT Legal client portal. I'm {atty_display}. "
                    f"Your generated {template_type} has been saved to your Documents folder. "
                    "Please review it and reach out with any questions."
                ),
            }],
        }
        record_check(record, "claim", "public", client_names=[full_name])

    safe_name    = template_type.replace(" ", "_").replace("/", "-")
    doc_filename = f"{now_ts}_{safe_name}.html"
    doc_dir      = _client_docs_dir(username, "Generated Documents")
    (doc_dir / doc_filename).write_text(
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<title>{html.escape(template_type)}</title>"
        f"<style>body{{font-family:Georgia,serif;max-width:860px;margin:2rem auto;"
        f"padding:1.5rem;line-height:1.7;color:#1a1a2e}}"
        f"h1,h2,h3{{color:#1B2A4A}}pre{{white-space:pre-wrap}}</style></head><body>"
        f"<p style='color:#888;font-size:.8rem;margin-bottom:2rem'>"
        f"Generated: {datetime.now().strftime('%B %d, %Y')} &nbsp;|&nbsp; "
        f"Template: {html.escape(template_type)} &nbsp;|&nbsp; "
        f"Client: {html.escape(full_name)}</p>"
        f"{draft_content}</body></html>",
        encoding="utf-8",
    )

    record.setdefault("billing_log", []).append({
        "date":     now_str,
        "hours":    0.5,
        "note":     f"Document Generation — {template_type}",
        "type":     "document",
        "category": "Document Drafting",
        "filename": doc_filename,
    })
    recalc_hours(record)
    # Save before logging: _log_activity re-reads the file from disk, so logging
    # first would be overwritten by this save.
    save_client(record)
    _log_activity(username, "document_generated",
                  f"Document generated and saved: {template_type} ({doc_filename})")

    return jsonify({
        "success":      True,
        "username":     username,
        "attorney":     atty_display,
        "doc_filename": doc_filename,
        "billed_hours": billing.billed_hours(billing.load_ledger(username)),
        "message": (
            f"Your {template_type} has been saved to your client portal. "
            "You can log in to download it anytime."
        ),
    })
