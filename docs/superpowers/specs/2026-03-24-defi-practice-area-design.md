# DeFi / Crypto Law Practice Area — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Approach:** Inline (match existing patterns, no new files)

---

## Overview

Add DeFi / Crypto Law as a new case type (the 11th in `CASE_ATTORNEY_MAP`) and the third practice-area-specific research prompt to the law office app, following the same patterns used by existing case types. All changes are inline additions to existing files.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Implementation approach | Match existing patterns (dropdowns, prompts, templates) | No chatbot intake or keyword classifier exists today |
| Attorney assignment | Endocide (Marcus V. Endo) | User decision |
| Document templates | Top 4: Engagement Letter, Token Offering Checklist, Smart Contract Review Memo, DAO Formation Checklist | Practical core set; more can be added later |
| Chat widget | Full DeFi knowledge base injected | Lets visitors get informed responses on crypto topics |
| Module separation | None — all inline in app.py + templates | Consistent with how every other practice area works |

---

## Section 1: Routing & Intake

### CASE_ATTORNEY_MAP

Add one entry:

```python
"DeFi / Crypto Law": "Endocide"
```

### Dropdown Options

Add `<option value="DeFi / Crypto Law">DeFi / Crypto Law</option>` to all case type dropdowns:

1. **`templates/intake.html`** — case type `<select>` dropdown
2. **`templates/research.html`** — research case type `<select>` dropdown
3. **`templates/base.html`** — forced intake modal case type `<select>` (currently only has Criminal Defense and Civil Litigation; add DeFi alongside)
4. **`templates/client_login.html`** — client self-registration case type `<select>` dropdown
5. **`templates/attorney_portal.html`** — two dropdowns:
   - `#ci-case-type` (Client Info editor, used when attorneys update a client's case type)
   - `#nc-case-type` (New Client form, used when attorneys convert a lead to a client)

### Intake Form

No new form fields. The existing form (name, case type, matter description, county, court dates) is sufficient. Clients describe their crypto matter in `matter_description`.

---

## Section 2: Research System Prompt

### New Constant: `DEFI_SYSTEM_PROMPT`

Placed alongside `CRIMINAL_SYSTEM_PROMPT` and `CIVIL_SYSTEM_PROMPT` in `app.py`.

**Role:** "You are an expert DeFi and cryptocurrency legal research assistant."

**HTML output format with sections:**
- Issue Presented
- Brief Answer
- Regulatory Framework
- Relevant Case Law & Guidance
- Risk Assessment
- Recommended Next Steps

**Focus areas** (drawn from RTF knowledge base):
- Securities law: Howey Test, Reg D (506b/506c), Reg A+, Reg S, Reg CF
- Token standards: ERC-20, ERC-1400, ERC-3643, ERC-721/1155
- Smart contract legal exposure: admin key risks, upgrade proxy risks, oracle dependencies
- DAO entity structures: Wyoming DAO LLC, Cayman Foundation, Marshall Islands, Swiss Association
- Crypto estate planning: crypto wills, multi-sig inheritance, hardware wallet succession
- Regulatory bodies: SEC, CFTC, IRS, FinCEN
- AML/KYC, money transmission, VASP rules

**Disclaimers included in prompt:**
- This is legal information, not legal advice, until engagement letter is signed
- DeFi law is rapidly evolving — always verify current SEC/CFTC guidance
- Smart contract code review by a qualified Solidity auditor is recommended alongside legal review
- Tax advice requires a CPA or tax attorney

### Route Update: `research_query()`

Extend the system prompt selection logic:

```python
if case_type == "Criminal Defense":
    system_prompt = CRIMINAL_SYSTEM_PROMPT
elif case_type == "DeFi / Crypto Law":
    system_prompt = DEFI_SYSTEM_PROMPT
else:
    system_prompt = CIVIL_SYSTEM_PROMPT
```

---

## Section 3: Document Templates

### 4 New Entries in `TEMPLATE_PROMPTS`

Each follows the existing pattern: a prompt string with `{variable}` placeholders.

#### 1. DeFi Engagement Letter

- Matter description from intake
- Scope of representation (legal information vs full representation)
- Fee structure placeholder (flat fee / LaaS / hourly)
- DeFi-specific disclaimer block (rapidly evolving law, no guarantee on regulatory outcomes)
- Conflict check acknowledgment
- Signature block

**Variables:** `{client_name}`, `{matter_description}`, `{jurisdiction}`

#### 2. Token Offering Checklist

- Securities exemption selected and rationale
- Required documents list with status fields
- Investor qualification requirements
- Timeline and filing deadlines
- Ongoing compliance obligations

**Variables:** `{client_name}`, `{project_name}`, `{token_type}`, `{matter_description}`

#### 3. Smart Contract Review Memo

- Contract summary (plain English)
- Compliance issues identified
- Risk rating (Low / Medium / High)
- Recommended modifications
- Disclaimer re: code audit

**Variables:** `{client_name}`, `{contract_name}`, `{matter_description}`

#### 4. DAO Formation Checklist

- Entity type recommendation
- Formation documents needed
- Token governance considerations
- Regulatory exposure summary

**Variables:** `{client_name}`, `{dao_name}`, `{matter_description}`, `{jurisdiction}`

### UI Changes: `templates/drafting.html`

The drafting page uses a single `<select>` dropdown with hidden `<div class="template-fields">` sections shown/hidden via `onTemplateChange()` in `app.js`. Add:

- 4 new `<option>` elements to the template type dropdown
- 4 corresponding `<div id="fields-{slug}" class="template-fields form-grid">` sections with input fields for each template's variables
- Slug convention: lowercase, hyphen-separated (e.g., `fields-defi-engagement-letter`)

### Variable Defaults: `all_vars` dict

Add new keys with empty string defaults:
- `project_name`
- `token_type`
- `contract_name`
- `dao_name`
- `jurisdiction`

---

## Section 4: Public Chat Widget

### Update `_CHAT_SYSTEM` in `app.py`

**Additions:**
- List DeFi / Crypto Law as a firm practice area
- Inject condensed DeFi knowledge base covering: tokenization/RWA, smart contract review, DAO formation, DeFi disputes, crypto estate planning, regulatory/compliance, construction escrow
- Tone guidance: plain English first, don't assume blockchain knowledge, flag time-sensitive enforcement issues, be direct about referral needs (Solidity audits, tax advice)
- Disclaimer language: legal information not advice until engagement letter signed, DeFi law is rapidly evolving

**Preserved behavior:**
- Existing personality and conversational style
- Nudge-toward-intake call to action
- Criminal defense and civil litigation knowledge unchanged

---

## Files Modified

| File | Changes |
|------|---------|
| `app.py` | Add `CASE_ATTORNEY_MAP` entry, `DEFI_SYSTEM_PROMPT` constant, 4 `TEMPLATE_PROMPTS` entries, new keys in `all_vars`, update `research_query()` routing, update `_CHAT_SYSTEM` prompt |
| `templates/intake.html` | Add dropdown option |
| `templates/research.html` | Add dropdown option |
| `templates/base.html` | Add dropdown option in forced intake modal |
| `templates/drafting.html` | Add 4 template options with hidden field sections |
| `templates/client_login.html` | Add dropdown option in self-registration form |
| `templates/attorney_portal.html` | Add dropdown option in 2 places: `#ci-case-type` and `#nc-case-type` |

## Files NOT Modified

- `static/js/app.js` — no changes needed; existing `submitIntake()`, `onTemplateChange()`, and drafting JS handle new values generically
- `static/css/style.css` — existing styles apply to new template field sections
- No new files created

## Deferred (v1 acceptable as-is)

- **`_RESEARCH_AUTHORITY_PROMPT`** — Attorney portal research authority tool is hardcoded for Tennessee criminal defense. DeFi cases using this tool will get criminal-focused results. Acceptable for v1 since this is an attorney-facing power tool, not client-facing. Can be enhanced later with case-type routing.
- **`_CLIENT_RESEARCH_PROMPT`** — Client portal research Q&A uses a generic prompt without case-type awareness. DeFi clients get generic responses. Acceptable for v1.
- **Lead accent colors** — Lead card accent color logic is binary (Civil = navy, everything else = gold). DeFi leads get gold. Acceptable for v1; can add a third color later.

## Testing

- [ ] "DeFi / Crypto Law" appears in intake dropdown and submits successfully
- [ ] Client record saved with `case_type: "DeFi / Crypto Law"` and assigned to Endocide
- [ ] Research page shows DeFi option and returns DeFi-focused research memos
- [ ] All 4 DeFi document templates generate successfully from drafting page
- [ ] `onTemplateChange()` correctly shows/hides DeFi template field sections
- [ ] Chat widget can answer basic DeFi/crypto questions and nudge toward intake
- [ ] Client self-registration (client_login.html) shows DeFi option and creates account correctly
- [ ] Attorney portal: editing a client's case type to DeFi works (`#ci-case-type`)
- [ ] Attorney portal: creating a new client with DeFi type works (`#nc-case-type`)
- [ ] Forced intake modal in base.html includes DeFi option
- [ ] Existing Criminal Defense, Civil Litigation, and other case types still work identically — no regression
