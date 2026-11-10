"""blueprints/drafting.py — Document drafting (attorney tool)."""

import logging

from datetime import datetime
from flask import Blueprint, current_app, render_template, request, jsonify
import anthropic
from services import gcal

from shared import (
    require_auth, require_attorney, DRAFT_HISTORY_DIR, MODEL, get_anthropic_client,
)
from services.accounts import load_client_for_attorney
from services.storage import _log_activity, write_json

log = logging.getLogger(__name__)

drafting_bp = Blueprint("drafting", __name__)

# ── System prompt ─────────────────────────────────────────────────────────────

DRAFTING_SYSTEM_PROMPT = """You are an expert legal document drafter for a solo attorney practice.
Generate professional, complete legal documents based on the template type and variables provided.
Output ONLY the document text — no commentary, no markdown, no explanation.
Use formal legal language appropriate for the document type.
Leave blanks as [TO BE COMPLETED] if a required variable is missing.
For court filings (complaints, answers, petitions, motions, notices, discovery), use Tennessee
format: a caption naming the court, county, parties and docket number; numbered paragraphs;
a signature block for the attorney with "BPR No. [TO BE COMPLETED]"; and a Certificate of Service."""

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

    # ── Civil practice ───────────────────────────────────────────────────────

    "Answer to Complaint": """Draft an Answer to a civil Complaint for Tennessee state court with:
Court: {court_name} | County: {county} | Case No.: {case_no}
Plaintiff: {plaintiff_name} | Defendant (our client): {defendant_name}
Summary of the Complaint's allegations: {complaint_summary}
Admissions / denials / facts our client disputes: {admissions_denials}
Affirmative defenses to assert: {affirmative_defenses}
Counterclaim (if any): {counterclaim} | Jury demand: {jury_demand}
Respond paragraph by paragraph (admit, deny, or deny for lack of knowledge under Tenn. R. Civ. P. 8.02),
include a general denial of anything not expressly admitted, plead affirmative defenses under Rule 8.03
(note Rule 12.08 waiver), plead any counterclaim in numbered counts, and include a prayer for relief
and jury demand if requested.""",

    "Civil Complaint": """Draft a civil Complaint for Tennessee state court with:
Court: {court_name} | County: {county}
Plaintiff (our client): {plaintiff_name} | Defendant: {defendant_name}
Facts: {matter_description}
Causes of action: {causes_of_action}
Damages / relief requested: {relief_requested} | Jury demand: {jury_demand}
Include parties, jurisdiction and venue allegations, numbered factual allegations, one count per cause of
action with its elements, a prayer for relief, and a jury demand if requested.""",

    "General Sessions Civil Warrant": """Draft a Tennessee General Sessions civil warrant and attached statement of claim with:
County: {county} | Plaintiff (our client): {plaintiff_name} | Defendant: {defendant_name}
Defendant's address for service: {property_address}
Amount claimed: {demand_amount} | Basis of the claim: {matter_description}
Keep it within General Sessions civil jurisdiction (T.C.A. § 16-15-501), state the claim plainly,
itemize the amount, and include a sworn-account affidavit if the claim is on an account.""",

    "Motion to Dismiss (Rule 12)": """Draft a Motion to Dismiss under Tenn. R. Civ. P. 12.02 with supporting memorandum:
Court: {court_name} | County: {county} | Case No.: {case_no}
Plaintiff: {plaintiff_name} | Defendant (movant): {defendant_name}
Summary of the Complaint: {complaint_summary}
Grounds for dismissal: {motion_grounds} | Hearing date (if set): {hearing_date}
Apply the Rule 12.02(6) standard (Webb v. Nashville Area Habitat for Humanity, 346 S.W.3d 422 (Tenn. 2011))
where relevant, argue each ground under its own heading, and include a notice of hearing.""",

    "Discovery Requests": """Draft written discovery for Tennessee state court with:
Court: {court_name} | County: {county} | Case No.: {case_no}
Requesting party (our client): {plaintiff_name} | Responding party: {defendant_name}
Sets to include: {discovery_sets}
Topics and documents to target: {discovery_topics}
Include definitions and instructions, Interrogatories under Tenn. R. Civ. P. 33 (no more than 30,
counting subparts), Requests for Production under Rule 34, and Requests for Admission under Rule 36
(note the 30-day deemed-admitted consequence), each numbered and tailored to the topics.""",

    "Settlement Agreement and Release": """Draft a settlement agreement and mutual release with:
Our client: {client_name} | Other party: {opposing_party}
Dispute / claims being settled: {matter_description} | Case No. (if filed): {case_no}
Settlement amount: {settlement_amount} | Payment terms: {payment_terms}
Scope of release: {release_scope} | Governing state: {jurisdiction}
Include recitals, payment terms and default, mutual release, no admission of liability, confidentiality,
non-disparagement, dismissal with prejudice of any pending case, tax responsibility, entire agreement,
and signature blocks.""",

    "Response to Demand Letter": """Draft a response on behalf of our client to a demand letter with:
Our client: {client_name} | Party who sent the demand: {opposing_party}
What the demand claims: {complaint_summary}
Our client's position and key facts: {matter_description}
Proposed resolution or counteroffer: {settlement_amount}
Be firm and professional: address each claim, state factual and legal defenses, include a counteroffer
if provided, reserve all rights, and state that the response is not an admission of liability.""",

    "Engagement Letter": """Draft an attorney-client engagement letter for a Tennessee solo practice with:
Client: {client_name} | Matter: {matter_description}
Scope of representation: {scope_of_representation}
Fee terms: {fee_terms} | Retainer / advance fee: {retainer_amount}
Include scope and exclusions, fees and billing, handling of advance fees in trust (Tenn. Sup. Ct. R. 8,
RPC 1.5 and 1.15), client responsibilities, communication, file retention, termination, no guarantee of
outcome, and signature blocks.""",

    # ── Family practice ──────────────────────────────────────────────────────

    "Answer and Counter-Complaint for Divorce": """Draft an Answer and Counter-Complaint for Divorce for Tennessee court with:
Court: {court_name} | County: {county} | Case No.: {case_no}
Plaintiff/Petitioner: {petitioner_name} | Defendant/Respondent (our client): {respondent_name}
Date of marriage: {date_of_marriage} | Minor children: {minor_children}
Allegations our client disputes: {admissions_denials}
Grounds for the counter-complaint: {grounds_for_divorce}
Relief sought (property, support, parenting): {relief_requested}
Answer each paragraph, then plead the counter-complaint with residency (T.C.A. § 36-4-104), grounds
(§ 36-4-101), children and proposed parenting plan, equitable division (§ 36-4-121), support requests,
and a prayer for relief. Include the statutory injunction notice reference (§ 36-4-106(d)).""",

    "Petition to Modify Parenting Plan": """Draft a Petition to Modify Permanent Parenting Plan for Tennessee court with:
Court: {court_name} | County: {county} | Case No.: {case_no}
Petitioner (our client): {petitioner_name} | Respondent: {respondent_name}
Minor children: {minor_children} | Date of current order: {existing_order_date}
Material change in circumstances: {changed_circumstances}
Requested changes: {requested_changes} | Child support change: {child_support}
Plead a material change under T.C.A. § 36-6-101(a)(2)(B) or (C) as applicable, the best-interest
factors of § 36-6-106(a), attach a proposed parenting plan reference, and request modified support.""",

    "Petition for Civil Contempt": """Draft a Petition for Civil Contempt for Tennessee court with:
Court: {court_name} | County: {county} | Case No.: {case_no}
Petitioner (our client): {petitioner_name} | Respondent: {respondent_name}
Order violated and its date: {existing_order_date}
Specific violations: {violations} | Arrearage (if any): {arrears_amount}
Relief requested: {relief_requested}
Plead the elements of civil contempt (T.C.A. § 29-9-102; Konvalinka v. Chattanooga-Hamilton County
Hospital Authority, 249 S.W.3d 346 (Tenn. 2008)): a lawful, clear order; violation; willfulness; and
ability to comply. Request a purge amount, attorney's fees (T.C.A. § 36-5-103(c)), and a show-cause order.
Note that criminal contempt would require separate notice under Tenn. R. Crim. P. 42(b).""",

    "Notice of Intent to Relocate": """Draft a Tennessee parental relocation notice under T.C.A. § 36-6-108 with:
Relocating parent (our client): {petitioner_name} | Other parent: {respondent_name}
Minor children: {minor_children}
New address / location: {relocation_destination} | Proposed date: {relocation_date}
Reasons for the move: {relocation_reason}
Proposed revised parenting schedule: {proposed_schedule}
Include every statutory element: the new location, date, specific reasons, a proposed revised
parenting schedule, and the required statement that the other parent may file a petition in opposition
within 30 days of receipt. Note the notice must be sent by registered or certified mail at least 60 days
before the move.""",

    "Motion for Temporary Parenting Plan and Support": """Draft a motion for pendente lite (temporary) relief for Tennessee court with:
Court: {court_name} | County: {county} | Case No.: {case_no}
Movant (our client): {petitioner_name} | Other party: {respondent_name}
Minor children: {minor_children}
Proposed temporary schedule: {proposed_schedule}
Temporary child support / spousal support requested: {child_support}
Other temporary relief (residence, vehicles, bills, fees): {temporary_relief}
Request a temporary parenting plan under T.C.A. § 36-6-403, temporary support under the Child Support
Guidelines and § 36-5-121, temporary attorney's fees, and include a notice of hearing.""",
    # ── Motions bank: family, estate planning, basic pleadings ──
    'Marital Dissolution Agreement': "Draft a Tennessee Marital Dissolution Agreement (MDA) for an irreconcilable-differences divorce with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPetitioner (our client): {petitioner_name} | Respondent: {respondent_name}\nDate of marriage: {date_of_marriage} | Date of separation: {date_of_separation}\nMinor children: {minor_children} (parenting plan to be filed separately: {parenting_plan_summary})\nMarital assets and who receives each: {marital_assets}\nMarital debts and who pays each: {marital_debts}\nSeparate property: {separate_property} | Alimony: {spousal_support}\nReal property / marital residence: {property_division}\nInclude: recitals; division of real and personal property, vehicles, bank and retirement accounts (note any QDRO needed); allocation of debts with hold-harmless provisions; alimony (type and term under T.C.A. § 36-5-121, or a mutual waiver); health insurance and COBRA; tax returns and dependency exemptions; attorney's fees; full disclosure and voluntary execution; mutual releases; incorporation into the Final Decree under T.C.A. § 36-4-103; and notarized signature blocks for both parties.",

    'Final Decree of Divorce': 'Draft a proposed Final Decree of Divorce for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPetitioner (our client): {petitioner_name} | Respondent: {respondent_name}\nGrounds: {grounds_for_divorce} | Date of hearing: {hearing_date}\nMinor children: {minor_children} | MDA date: {mda_date} | Parenting plan date: {existing_order_date}\nAdditional terms: {relief_requested}\nInclude findings (jurisdiction, residency under T.C.A. § 36-4-104, the 60/90-day waiting period under § 36-4-101(b), grounds), approval and incorporation of the MDA and permanent parenting plan, child support per the attached worksheet, restoration of a former name if requested, court costs, "ENTER this ___ day of ___" with a judge\'s signature line, and an "Approved for Entry" block for counsel.',

    'Petition to Establish Parentage': 'Draft a Petition to Establish Parentage (paternity), Parenting Plan and Child Support for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPetitioner (our client): {petitioner_name} | Respondent: {respondent_name}\nChild(ren): {minor_children} | Alleged father: {alleged_father}\nFacts (relationship, birth, any voluntary acknowledgment): {matter_description}\nRequested relief: {relief_requested}\nPlead jurisdiction under T.C.A. §§ 36-2-301 et seq., request genetic testing under § 36-2-305 if parentage is disputed, an order of parentage, amendment of the birth certificate, a permanent parenting plan under § 36-6-404, child support under the Guidelines including retroactive support (§ 36-2-311), and allocation of birth-related expenses.',

    'Petition to Modify Child Support': "Draft a Petition to Modify Child Support for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPetitioner (our client): {petitioner_name} | Respondent: {respondent_name}\nMinor children: {minor_children} | Current order date: {existing_order_date} | Current support: {child_support}\nChange in circumstances (income, parenting time, expenses): {changed_circumstances}\nRequested support: {requested_changes}\nPlead a significant variance under T.C.A. § 36-5-101(g) and Tenn. Comp. R. & Regs. 1240-02-04-.05 (15% variance), attach a Child Support Worksheet reference, and request modification effective from the date of filing, plus attorney's fees under § 36-5-103(c).",

    'Motion for Pendente Lite Support': "Draft a Motion for Pendente Lite (temporary) Support for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPetitioner (our client): {petitioner_name} | Respondent: {respondent_name}\nMinor children: {minor_children}\nIncomes: Petitioner {petitioner_income}; Respondent {respondent_income}\nTemporary support requested: {child_support} | Temporary alimony requested: {spousal_support}\nOther temporary relief: {temporary_relief}\nRequest temporary child support under the Guidelines, temporary alimony and suit money under T.C.A. § 36-5-121, interim attorney's fees, maintenance of insurance, and preservation of the status quo; include a notice of hearing.",

    'Petition for Grandparent Visitation': 'Draft a Petition for Grandparent Visitation for Tennessee court under T.C.A. § 36-6-306 with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPetitioner (our client): {petitioner_name} | Respondent: {respondent_name}\nChild(ren): {minor_children} | Relationship of petitioner: {relationship}\nQualifying circumstance (death, divorce, never married, child lived with grandparent, etc.): {qualifying_basis}\nFacts on the relationship and its denial or severe reduction: {matter_description}\nRequested visitation: {proposed_schedule}\nPlead the statutory threshold (opposition by the parent, denial or severe reduction of visitation), a significant existing relationship and substantial harm to the child if severed (§ 36-6-306(b)), and the best-interest factors (§ 36-6-307).',

    'Petition for Name Change': 'Draft a Petition for Change of Name for Tennessee court under T.C.A. §§ 29-8-101 et seq. with:\nCourt: {court_name} | County: {county}\nPetitioner: {petitioner_name} | Current name: {current_name} | Requested name: {new_name}\nDate and place of birth: {birth_info} | Residence: {property_address}\nReason: {matter_description} | For a minor? {minor_children}\nInclude the sworn statements the court requires (not for fraud or to avoid creditors, criminal history disclosure, sex-offender status), consent or notice to both parents if the petitioner is a minor, a verification, and a proposed order.',

    'Durable Power of Attorney (Financial)': 'Draft a Tennessee Durable General Power of Attorney (financial) under the Uniform Durable Power of Attorney Act, T.C.A. §§ 34-6-101 et seq., with:\nPrincipal: {principal_name} | Address: {property_address}\nAgent (attorney-in-fact): {agent_name} | Successor agent: {successor_agent}\nEffective: {effective_when} | Powers granted / excluded: {powers}\nSpecial instructions: {special_instructions}\nInclude the durability language of § 34-6-102, enumerated powers (banking, real estate, tax, retirement, digital assets, gifting limits), compensation and accounting of the agent, revocation, reliance by third parties, nomination of a conservator, and a notarized signature block (required for recording if real estate may be conveyed).',

    'Health Care Power of Attorney': "Draft a Tennessee Appointment of Health Care Agent / Durable Power of Attorney for Health Care under the Tennessee Health Care Decisions Act, T.C.A. §§ 68-11-1801 et seq., with:\nPrincipal: {principal_name} | Agent: {agent_name} | Alternate agent: {successor_agent}\nWishes on life-sustaining treatment, organ donation, and other instructions: {special_instructions}\nInclude the agent's authority and its start on incapacity, HIPAA access, nomination of a guardian, revocation, and execution either before two qualified witnesses or a notary, with the witness statements the Act requires.",

    'Living Will (Advance Directive)': 'Draft a Tennessee Living Will / Advance Care Plan under T.C.A. §§ 68-11-1801 et seq. with:\nDeclarant: {principal_name} | County of residence: {county}\nTreatment preferences (CPR, ventilation, artificial nutrition and hydration, dialysis, comfort care) for terminal condition / permanent unconsciousness / end-stage illness: {special_instructions}\nOrgan donation: {organ_donation}\nUse plain language, include the quality-of-life scenarios, a statement that it revokes prior directives, and execution before two qualified witnesses or a notary with the required statements.',

    'HIPAA Authorization': 'Draft a HIPAA-compliant authorization to release protected health information (45 C.F.R. § 164.508) with:\nIndividual: {principal_name} | Date of birth: {birth_info}\nPersons authorized to receive information: {agent_name}\nScope / purpose: {powers} | Expiration: {effective_when}\nInclude all required core elements and statements (right to revoke, no conditioning of treatment, potential redisclosure), and a signature and date block.',

    'Petition to Probate Will': "Draft a Petition to Admit Will to Probate and for Letters Testamentary for a Tennessee probate court with:\nCourt: {court_name} | County: {county}\nDecedent: {decedent_name} | Date of death: {date_of_death} | Last address: {property_address}\nWill date: {will_date} | Witnesses: {will_witnesses}\nPetitioner / named executor: {executor_name} | Heirs and beneficiaries (names, addresses, relationship): {beneficiaries}\nEstimated estate value: {estate_value} | Bond / inventory waived in will? {bond_waiver}\nPlead venue (T.C.A. § 32-2-101), the will's due execution (self-proving affidavit under § 32-1-104 if present), request letters testamentary, waiver of bond and inventory if the will allows, notice to creditors (§ 30-2-306), and include an oath of executor and proposed order.",

    'Small Estate Affidavit': "Draft a Tennessee Small Estate Affidavit under T.C.A. §§ 30-4-101 et seq. with:\nCourt: {court_name} | County: {county}\nDecedent: {decedent_name} | Date of death: {date_of_death}\nAffiant: {executor_name} | Relationship: {relationship}\nPersonal property and values: {estate_assets} | Debts and funeral expenses: {marital_debts}\nDistributees: {beneficiaries} | Will exists? {will_date}\nConfirm the estate is within the small-estate limit (personal property only, no real property), list each asset, debts paid or to be paid, distribution under the will or intestacy (T.C.A. § 31-2-104), the affiant's sworn statements, and a notary block.",

    'Notice of Appearance': 'Draft a Notice of Appearance of counsel for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nNotes: {matter_description}\nState that the undersigned appears as counsel of record and request that all notices, pleadings and correspondence be served on counsel. Use Tennessee format with a caption, numbered paragraphs where appropriate, the attorney signature block, and a certificate of service.',

    'Motion to Continue': 'Draft a Motion to Continue for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nSetting to be continued: {hearing_date} | Reason: {motion_grounds}\nOpposing position: {opposing_position}\nShow good cause, that the motion is not for delay, prior continuances, and request a new date; include a proposed order. Use Tennessee format with a caption, numbered paragraphs where appropriate, the attorney signature block, and a certificate of service.',

    'Motion for Extension of Time': 'Draft a Motion for Extension of Time for Tennessee court (Tenn. R. Civ. P. 6.02) with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nDeadline and what is due: {deadline_info} | Additional time requested: {extension_requested}\nReason: {motion_grounds} | Opposing position: {opposing_position}\nShow cause (or excusable neglect if the deadline has passed) and include a proposed order. Use Tennessee format with a caption, numbered paragraphs where appropriate, the attorney signature block, and a certificate of service.',

    'Motion to Compel Discovery': "Draft a Motion to Compel Discovery for Tennessee court (Tenn. R. Civ. P. 37.01) with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nDiscovery served and date: {discovery_sets} | Deficiencies: {discovery_topics}\nGood-faith efforts to resolve: {meet_confer}\nRequest an order compelling full responses within a set time, deeming objections waived where untimely, and expenses and attorney's fees under Rule 37.01(4); include the certification of good-faith conference and a notice of hearing. Use Tennessee format with a caption, numbered paragraphs where appropriate, the attorney signature block, and a certificate of service.",

    'Motion for Default Judgment': 'Draft a Motion for Default Judgment for Tennessee court (Tenn. R. Civ. P. 55) with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nDate and method of service: {service_info} | Answer deadline: {deadline_info}\nDamages / relief sought: {relief_requested}\nPlead service, failure to plead or otherwise defend, that the defendant is not a minor, incompetent, or in military service (attach an SCRA affidavit reference), the five-day notice under Rule 55.01 if the defendant appeared, and a proposed order. Use Tennessee format with a caption, numbered paragraphs where appropriate, the attorney signature block, and a certificate of service.',

    'Motion to Withdraw as Counsel': "Draft a Motion to Withdraw as Counsel for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nReason (stated generally, without privileged detail): {motion_grounds}\nUpcoming settings: {hearing_date}\nClient's last known address: {property_address}\nComply with Tenn. Sup. Ct. R. 8, RPC 1.16 (no confidential information; reasonable notice to the client; protect the client's interests) and any local rule; certify service on the client and all counsel; include a proposed order allowing time to retain new counsel. Use Tennessee format with a caption, numbered paragraphs where appropriate, the attorney signature block, and a certificate of service.",

    'Agreed Order': 'Draft an Agreed Order (or proposed order) for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nWhat the parties agreed / what the court ordered: {matter_description}\nHearing date (if any): {hearing_date}\nInclude recitals, numbered ordering paragraphs, "ENTER this ___ day of ___" with a judge\'s signature line, "Approved for Entry" signature blocks for all counsel or parties, and a certificate of service.',

    'Notice of Hearing': 'Draft a Notice of Hearing for Tennessee court with:\nCourt: {court_name} | County: {county} | Case No.: {case_no}\nPlaintiff/Petitioner: {plaintiff_name} | Defendant/Respondent: {defendant_name} | We represent: {client_role}\nMotion or matter to be heard: {matter_description} | Date and time: {hearing_date} {hearing_time}\nCourtroom / judge: {courtroom}\nState the date, time and place and include a certificate of service.',
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
    "court_name": "", "county": "", "case_no": "",
    "plaintiff_name": "", "defendant_name": "",
    "complaint_summary": "", "admissions_denials": "", "affirmative_defenses": "",
    "counterclaim": "", "causes_of_action": "", "relief_requested": "", "jury_demand": "",
    "motion_grounds": "", "hearing_date": "", "discovery_sets": "", "discovery_topics": "",
    "settlement_amount": "", "payment_terms": "", "release_scope": "",
    "scope_of_representation": "", "fee_terms": "", "retainer_amount": "",
    "existing_order_date": "", "changed_circumstances": "", "requested_changes": "",
    "child_support": "", "violations": "", "arrears_amount": "",
    "relocation_destination": "", "relocation_date": "", "relocation_reason": "",
    "proposed_schedule": "", "temporary_relief": "",
    "date_of_separation": "", "parenting_plan_summary": "", "mda_date": "", "alleged_father": "",
    "relationship": "", "qualifying_basis": "", "current_name": "", "new_name": "",
    "birth_info": "", "principal_name": "", "agent_name": "", "successor_agent": "",
    "effective_when": "", "powers": "", "special_instructions": "", "organ_donation": "",
    "decedent_name": "", "date_of_death": "", "will_date": "", "will_witnesses": "",
    "estate_value": "", "bond_waiver": "", "estate_assets": "", "client_role": "",
    "opposing_position": "", "deadline_info": "", "extension_requested": "", "meet_confer": "",
    "service_info": "", "hearing_time": "", "courtroom": "",
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
            write_json(DRAFT_HISTORY_DIR / f"{ts}_{slug}.json",
                       {"timestamp": ts, "template_type": template_type,
                        "variables": all_vars, "draft": draft_text})
        except Exception:
            log.warning("Ignored error in drafting", exc_info=True)
        return jsonify({"success": True, "draft": draft_text})
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Please check your .env file."}), 401
    except anthropic.APIError as e:
        return jsonify({"error": f"API error: {str(e)}"}), 500


MAX_GOOGLE_DOC_CHARS = 500_000


@drafting_bp.route("/drafting/google-doc", methods=["POST"])
@require_auth
@require_attorney
def drafting_google_doc():
    """Save a draft to the firm's Google Drive as a Google Doc and return its link.
    With a username, the client's activity log records it."""
    data     = request.get_json() or {}
    title    = (data.get("title") or "").strip()[:200] or "Draft"
    content  = (data.get("content") or "").strip()
    username = (data.get("username") or "").strip()
    if not content:
        return jsonify({"error": "There is no draft to save."}), 400
    if len(content) > MAX_GOOGLE_DOC_CHARS:
        return jsonify({"error": "The draft is too long to save as a Google Doc."}), 400
    client = None
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        title = f"{title} — {client.get('client_name') or username}"
    title = f"{title} ({datetime.now().strftime('%Y-%m-%d')})"

    try:
        doc = gcal.create_google_doc(title, content)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Google Doc creation failed")
        return jsonify({"error": "Could not create the Google Doc. Check the Google connection and try again."}), 502
    if not (doc.get("url") or "").startswith("https://docs.google.com/"):
        return jsonify({"error": "Google did not return a document link."}), 502

    if client:
        _log_activity(client["username"], "google_doc_created", f"Google Doc created: {title}")
    return jsonify({"success": True, "url": doc["url"], "title": title})
