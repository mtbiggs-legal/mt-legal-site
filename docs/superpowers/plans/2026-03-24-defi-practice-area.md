# DeFi / Crypto Law Practice Area — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DeFi / Crypto Law as a fully integrated case type with routing, research prompt, document templates, and chat widget knowledge.

**Architecture:** All changes are inline additions to existing files following established patterns. No new files. Backend changes in `app.py`, frontend changes across 6 HTML templates.

**Tech Stack:** Flask, Anthropic API, vanilla HTML/JS

**Spec:** `docs/superpowers/specs/2026-03-24-defi-practice-area-design.md`

---

## Chunk 1: Routing & Dropdowns

### Task 1: Add DeFi to CASE_ATTORNEY_MAP

**Files:**
- Modify: `app.py:56-67`

- [ ] **Step 1: Add the new entry**

In `app.py`, add `"DeFi / Crypto Law": "Endocide"` to the `CASE_ATTORNEY_MAP` dict. Insert before `"Other"` (which is the catch-all):

```python
# app.py — inside CASE_ATTORNEY_MAP (around line 65)
    "Employment Law":             "SophiaH",
    "DeFi / Crypto Law":          "Endocide",
    "Other":                      "Endocide",
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat(defi): add DeFi / Crypto Law to CASE_ATTORNEY_MAP"
```

---

### Task 2: Add DeFi dropdown option to all case type selects

**Files:**
- Modify: `templates/intake.html:36-50`
- Modify: `templates/base.html:519-526`
- Modify: `templates/client_login.html:55-61`
- Modify: `templates/attorney_portal.html:1116-1129`
- Modify: `templates/attorney_portal.html:1308-1321`

- [ ] **Step 1: Add to intake.html**

In `templates/intake.html`, add the option before `"Other"` (around line 48):

```html
  <option value="Employment Law">Employment Law</option>
  <option value="DeFi / Crypto Law">DeFi / Crypto Law</option>
  <option value="Other">Other</option>
```

- [ ] **Step 2: Add to base.html forced intake modal**

In `templates/base.html`, the modal only has Criminal Defense and Civil Litigation (lines 523-525). Add DeFi:

```html
    <option value="Criminal Defense">Criminal Defense</option>
    <option value="Civil Litigation">Civil Litigation</option>
    <option value="DeFi / Crypto Law">DeFi / Crypto Law</option>
```

- [ ] **Step 3: Add to client_login.html**

In `templates/client_login.html` (lines 58-60), add DeFi:

```html
    <option value="Criminal Defense">Criminal Defense</option>
    <option value="Civil Litigation">Civil Litigation</option>
    <option value="DeFi / Crypto Law">DeFi / Crypto Law</option>
```

- [ ] **Step 4: Add to attorney_portal.html — #ci-case-type**

In `templates/attorney_portal.html` (lines 1126-1128), add before `"Other"`:

```html
  <option value="Employment Law">Employment Law</option>
  <option value="DeFi / Crypto Law">DeFi / Crypto Law</option>
  <option value="Other">Other</option>
```

- [ ] **Step 5: Add to attorney_portal.html — #nc-case-type**

In `templates/attorney_portal.html` (lines 1318-1320), add before `"Other"`:

```html
  <option value="Employment Law">Employment Law</option>
  <option value="DeFi / Crypto Law">DeFi / Crypto Law</option>
  <option value="Other">Other</option>
```

- [ ] **Step 6: Verify app starts**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -c "from app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add templates/intake.html templates/base.html templates/client_login.html templates/attorney_portal.html
git commit -m "feat(defi): add DeFi / Crypto Law option to all case type dropdowns"
```

---

## Chunk 2: Research System Prompt

### Task 3: Add DEFI_SYSTEM_PROMPT constant

**Files:**
- Modify: `app.py:396-411` (insert after CIVIL_SYSTEM_PROMPT)

- [ ] **Step 1: Add the new constant**

Insert `DEFI_SYSTEM_PROMPT` immediately after `CIVIL_SYSTEM_PROMPT` (after line 411) in `app.py`:

```python
DEFI_SYSTEM_PROMPT = """You are an expert DeFi and cryptocurrency legal research assistant.
When given a legal question or issue involving blockchain, digital assets, or decentralized finance,
produce a structured legal research memo.

Format your response as HTML with the following sections:
<h2>Legal Research Memo</h2>
<h3>Issue Presented</h3>
<h3>Brief Answer</h3>
<h3>Regulatory Framework</h3>
<h3>Relevant Case Law &amp; Guidance</h3>
<h3>Risk Assessment</h3>
<h3>Recommended Next Steps</h3>

Focus on:
- Securities law: Howey Test, Reg D (506b/506c), Reg A+, Reg S, Reg CF
- Token standards and classifications: ERC-20, ERC-1400, ERC-3643, ERC-721/1155
- Smart contract legal exposure: admin key risks, upgrade proxy risks, oracle dependencies, reentrancy (liability)
- DAO entity structures: Wyoming DAO LLC, Cayman Islands Foundation, Marshall Islands, Swiss Association, BVI
- Crypto estate planning: crypto wills, multi-sig inheritance vaults, hardware wallet succession, trust amendments
- Regulatory bodies: SEC (token classification, broker-dealer, investment adviser), CFTC (commodity classification, derivatives),
  IRS (crypto as property, capital gains, staking income, FBAR/FATCA), FinCEN (AML/KYC, money transmission, VASP rules)

Important disclaimers to include in every memo:
- This is legal information, not legal advice, until a formal engagement letter is signed.
- DeFi law is rapidly evolving — always verify current SEC/CFTC guidance at the time of review.
- Smart contract code review by a qualified Solidity auditor is recommended alongside legal review.
- Tax advice requires a CPA or tax attorney — this firm can refer.

Be thorough but concise. Use plain English first, then introduce technical terms with brief definitions.
Flag any area where regulatory guidance is unsettled or enforcement is active."""
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat(defi): add DEFI_SYSTEM_PROMPT for research queries"
```

---

### Task 4: Update research_query() routing and research.html dropdown

**Files:**
- Modify: `app.py:432` (system prompt selection line)
- Modify: `templates/research.html:61-65`

- [ ] **Step 1: Update research_query() system prompt selection**

In `app.py` at line 432, replace the ternary:

```python
# BEFORE (line 432):
system_prompt = CRIMINAL_SYSTEM_PROMPT if case_type == "Criminal Defense" else CIVIL_SYSTEM_PROMPT

# AFTER:
if case_type == "Criminal Defense":
    system_prompt = CRIMINAL_SYSTEM_PROMPT
elif case_type == "DeFi / Crypto Law":
    system_prompt = DEFI_SYSTEM_PROMPT
else:
    system_prompt = CIVIL_SYSTEM_PROMPT
```

- [ ] **Step 2: Add DeFi option to research.html dropdown**

In `templates/research.html` (lines 63-64), add the DeFi option:

```html
<select id="research-case-type" name="case_type">
  <option value="Criminal Defense">Criminal Defense</option>
  <option value="Civil Litigation">Civil Litigation</option>
  <option value="DeFi / Crypto Law">DeFi / Crypto Law</option>
</select>
```

- [ ] **Step 3: Verify app starts**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -c "from app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app.py templates/research.html
git commit -m "feat(defi): route DeFi research queries to DEFI_SYSTEM_PROMPT"
```

---

## Chunk 3: Document Templates

### Task 5: Add 4 DeFi template prompts to TEMPLATE_PROMPTS and all_vars

**Files:**
- Modify: `app.py:466-541` (TEMPLATE_PROMPTS dict)
- Modify: `app.py:565-584` (all_vars dict)

- [ ] **Step 1: Add 4 template prompt entries**

In `app.py`, add these 4 entries at the end of the `TEMPLATE_PROMPTS` dict (before the closing `}`), after the `"Divorce Petition"` entry (around line 541):

```python
    "DeFi Engagement Letter": """Draft a professional engagement letter for a DeFi/cryptocurrency legal matter with the following details:
Client Name: {client_name}
Matter Description: {matter_description}
Jurisdiction: {jurisdiction}

Include:
1. Scope of representation — specify whether this is limited to legal information/consultation or full representation
2. Fee structure section with placeholders for: flat fee, Legal-as-a-Service (LaaS) retainer, or hourly rate
3. DeFi-specific disclaimer block:
   - The law governing digital assets, DeFi protocols, and blockchain technology is rapidly evolving
   - No guarantee can be made regarding regulatory outcomes, SEC/CFTC interpretations, or enforcement decisions
   - Smart contract code review by a qualified Solidity auditor is recommended alongside legal review
   - Tax advice requires a CPA or tax attorney — this firm can provide referrals
4. Conflict check acknowledgment
5. Signature blocks for attorney and client
Format as a formal legal engagement letter.""",

    "Token Offering Checklist": """Create a structured token offering compliance checklist with the following details:
Client Name: {client_name}
Project Name: {project_name}
Token Type: {token_type}
Project Description: {matter_description}

Include these sections:
1. Securities Exemption Analysis — which exemption applies (Reg D 506b, 506c, Reg A+, Reg S, Reg CF) and rationale
2. Required Documents checklist with status fields (Not Started / In Progress / Complete):
   - Private Placement Memorandum (PPM)
   - Subscription Agreement
   - Investor Accreditation Verification
   - Transfer Restriction Agreement
   - Form D Filing (if Reg D)
3. Investor Qualification Requirements — accredited vs non-accredited, investor count limits
4. Timeline and Filing Deadlines — key dates and regulatory filing windows
5. Ongoing Compliance Obligations — reporting, lockup periods, resale restrictions
Format as a professional legal checklist document.""",

    "Smart Contract Review Memo": """Draft a legal review memo for a smart contract with the following details:
Client Name: {client_name}
Contract Name / Description: {contract_name}
Context: {matter_description}

Include these sections:
1. Contract Summary — plain-English explanation of what the contract does
2. Compliance Issues Identified — securities implications, regulatory concerns, licensing requirements
3. Risk Rating — assign Low / Medium / High with justification for each identified risk:
   - Transfer restriction adequacy
   - Admin key / owner privileges (centralization risk)
   - Upgrade proxy risks
   - Oracle dependencies
   - Reentrancy or other exploit vectors (legal liability exposure)
4. Recommended Modifications — specific changes to reduce legal and regulatory risk
5. Disclaimer: This memo covers legal and regulatory analysis only. A full Solidity security audit by a qualified smart contract auditor is strongly recommended.
Format as a professional legal memorandum.""",

    "DAO Formation Checklist": """Create a DAO formation and legal wrapper checklist with the following details:
Client Name: {client_name}
DAO Name: {dao_name}
Purpose / Description: {matter_description}
Jurisdiction: {jurisdiction}

Include these sections:
1. Entity Type Recommendation — evaluate and recommend from:
   - Wyoming DAO LLC (US)
   - Cayman Islands Foundation
   - Marshall Islands DAO entity
   - Swiss Association
   - BVI company
   Include rationale based on jurisdiction, member count, and regulatory exposure.
2. Formation Documents Needed (checklist with status fields):
   - Operating Agreement / Constitution
   - Contributor Agreement
   - Token Disclaimer
   - Governance Rules
   - IP Assignment
3. Token Governance Considerations — voting mechanisms, quorum, proposal thresholds, delegation
4. Regulatory Exposure Summary — member liability, tax treatment, governance token classification
Format as a professional legal checklist document.""",
```

- [ ] **Step 2: Add new variable keys to all_vars**

In `app.py`, add these keys to the `all_vars` dict (around line 584, before the closing `}`):

```python
    # DeFi templates
    "project_name": "", "token_type": "", "contract_name": "",
    "dao_name": "", "jurisdiction": "",
```

- [ ] **Step 3: Verify app starts**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -c "from app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(defi): add 4 DeFi document template prompts and variables"
```

---

### Task 6: Add DeFi template UI sections to drafting.html

**Files:**
- Modify: `templates/drafting.html:36-47` (template dropdown)
- Modify: `templates/drafting.html` (add 4 field sections after existing ones)

The `onTemplateChange()` in `app.js` (line 486-494) converts template names to IDs via:
`"fields-" + name.toLowerCase().replace(/ /g, "-")`

So: `"DeFi Engagement Letter"` → `"fields-defi-engagement-letter"`, etc.

- [ ] **Step 1: Add 4 options to the template dropdown**

In `templates/drafting.html` (around line 46), add before the closing `</select>`:

```html
    <option value="Divorce Petition">Divorce Petition</option>
    <option value="DeFi Engagement Letter">DeFi Engagement Letter</option>
    <option value="Token Offering Checklist">Token Offering Checklist</option>
    <option value="Smart Contract Review Memo">Smart Contract Review Memo</option>
    <option value="DAO Formation Checklist">DAO Formation Checklist</option>
  </select>
```

- [ ] **Step 2: Add DeFi Engagement Letter field section**

Add after the last existing template-fields div (the Divorce Petition section), following the exact same pattern as existing sections (e.g., Demand Letter at lines 49-77):

```html
<!-- ── DeFi Engagement Letter ─────────────────────────────────────────── -->
<div id="fields-defi-engagement-letter" class="template-fields form-grid" style="display:none">
  <div class="form-section-title">DeFi Engagement Letter Details</div>

  <div class="form-group">
    <label for="del-client-name">Client Name</label>
    <input type="text" id="del-client-name" name="client_name" placeholder="Jane A. Smith" />
  </div>

  <div class="form-group">
    <label for="del-jurisdiction">Jurisdiction</label>
    <input type="text" id="del-jurisdiction" name="jurisdiction" placeholder="e.g. Tennessee / Delaware" />
  </div>

  <div class="form-group full">
    <label for="del-matter">Matter Description</label>
    <textarea id="del-matter" name="matter_description" rows="4" placeholder="Describe the DeFi/crypto matter…"></textarea>
  </div>
</div>
```

- [ ] **Step 3: Add Token Offering Checklist field section**

```html
<!-- ── Token Offering Checklist ───────────────────────────────────────── -->
<div id="fields-token-offering-checklist" class="template-fields form-grid" style="display:none">
  <div class="form-section-title">Token Offering Checklist Details</div>

  <div class="form-group">
    <label for="toc-client-name">Client Name</label>
    <input type="text" id="toc-client-name" name="client_name" placeholder="Jane A. Smith" />
  </div>

  <div class="form-group">
    <label for="toc-project-name">Project Name</label>
    <input type="text" id="toc-project-name" name="project_name" placeholder="e.g. RealToken, AcmeDAO" />
  </div>

  <div class="form-group">
    <label for="toc-token-type">Token Type</label>
    <input type="text" id="toc-token-type" name="token_type" placeholder="e.g. ERC-20 security token, ERC-721 NFT" />
  </div>

  <div class="form-group full">
    <label for="toc-matter">Project Description</label>
    <textarea id="toc-matter" name="matter_description" rows="4" placeholder="Describe the token offering or project…"></textarea>
  </div>
</div>
```

- [ ] **Step 4: Add Smart Contract Review Memo field section**

```html
<!-- ── Smart Contract Review Memo ─────────────────────────────────────── -->
<div id="fields-smart-contract-review-memo" class="template-fields form-grid" style="display:none">
  <div class="form-section-title">Smart Contract Review Memo Details</div>

  <div class="form-group">
    <label for="scr-client-name">Client Name</label>
    <input type="text" id="scr-client-name" name="client_name" placeholder="Jane A. Smith" />
  </div>

  <div class="form-group">
    <label for="scr-contract-name">Contract Name / Description</label>
    <input type="text" id="scr-contract-name" name="contract_name" placeholder="e.g. StakingVault.sol, TokenSale contract" />
  </div>

  <div class="form-group full">
    <label for="scr-matter">Context</label>
    <textarea id="scr-matter" name="matter_description" rows="4" placeholder="Describe what the smart contract does and what you need reviewed…"></textarea>
  </div>
</div>
```

- [ ] **Step 5: Add DAO Formation Checklist field section**

```html
<!-- ── DAO Formation Checklist ────────────────────────────────────────── -->
<div id="fields-dao-formation-checklist" class="template-fields form-grid" style="display:none">
  <div class="form-section-title">DAO Formation Checklist Details</div>

  <div class="form-group">
    <label for="dfc-client-name">Client Name</label>
    <input type="text" id="dfc-client-name" name="client_name" placeholder="Jane A. Smith" />
  </div>

  <div class="form-group">
    <label for="dfc-dao-name">DAO Name</label>
    <input type="text" id="dfc-dao-name" name="dao_name" placeholder="e.g. MakerDAO, AcmeDAO" />
  </div>

  <div class="form-group">
    <label for="dfc-jurisdiction">Jurisdiction</label>
    <input type="text" id="dfc-jurisdiction" name="jurisdiction" placeholder="e.g. Wyoming / Cayman Islands" />
  </div>

  <div class="form-group full">
    <label for="dfc-matter">DAO Purpose / Description</label>
    <textarea id="dfc-matter" name="matter_description" rows="4" placeholder="Describe the DAO's purpose, membership structure, and goals…"></textarea>
  </div>
</div>
```

- [ ] **Step 6: Verify app starts and page loads**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -c "from app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add templates/drafting.html
git commit -m "feat(defi): add DeFi document template UI sections to drafting page"
```

---

## Chunk 4: Chat Widget & Verification

### Task 7: Update public chat widget system prompt

**Files:**
- Modify: `app.py:2439-2449` (_CHAT_SYSTEM constant)

- [ ] **Step 1: Update _CHAT_SYSTEM**

In `app.py`, replace the `_CHAT_SYSTEM` constant (lines 2439-2449) with an expanded version that adds DeFi knowledge:

```python
_CHAT_SYSTEM = """You are a warm, professional virtual assistant for Endo-Legal Attorneys At Law, PLLC — a Nashville law firm specializing in criminal defense, civil litigation, and DeFi / cryptocurrency law (led by Marcus V. Endo, Esq. and Sophia L. Hargrove, Esq.).

Your role:
- Listen empathetically and help visitors understand their options
- Provide general legal information — never specific legal advice
- Keep replies concise (2–4 sentences). Be conversational, not robotic.
- If someone describes an urgent matter (upcoming court date, recent arrest, active lawsuit, SEC enforcement action), encourage them to call or complete the intake form right away
- Gently guide people toward scheduling a free consultation or completing the intake form at /intake
- Never guess at case outcomes or make promises about results

DeFi / Crypto Law — what the firm handles:
- Tokenization and capital raises (RWA, real estate tokens, security tokens) — Reg D, Reg A+, Reg S, Reg CF
- Smart contract legal review — compliance gaps, admin key risks, regulatory exposure
- DAO formation and legal wrappers — Wyoming DAO LLC, Cayman Foundation, Marshall Islands, Swiss Association
- DeFi disputes and on-chain arbitration — contributor disputes, governance attacks, treasury misuse, rug pull recovery
- Crypto estate planning — crypto wills, multi-sig inheritance, hardware wallet succession, trust amendments for digital assets
- Regulatory and compliance — SEC token classification, CFTC commodity rules, IRS crypto tax treatment, FinCEN AML/KYC
- Construction escrow contracts — milestone-based smart contract escrow with dispute resolution

When discussing DeFi/crypto topics:
- Use plain English first, then introduce technical terms with brief definitions
- Never assume the visitor knows Solidity, blockchain internals, or securities law
- Flag when something is time-sensitive (e.g., active SEC guidance changes, enforcement actions)
- Be direct about what needs referral: Solidity code audits require a qualified smart contract auditor, tax questions require a CPA or tax attorney
- Always note: this is legal information, not legal advice, until a formal engagement letter is signed
- DeFi law is rapidly evolving — encourage verification of current regulatory guidance

Always end with a soft nudge toward the intake form or a reminder that a real attorney is ready to help."""
```

- [ ] **Step 2: Verify app starts**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -c "from app import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(defi): add DeFi knowledge base to public chat widget"
```

---

### Task 8: Smoke test all changes

- [ ] **Step 1: Start the Flask app**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python app.py &
```

- [ ] **Step 2: Verify intake page has DeFi option**

Open `http://127.0.0.1:5000/intake` in browser. Confirm "DeFi / Crypto Law" appears in the Case Type dropdown.

- [ ] **Step 3: Verify research page has DeFi option**

Open `http://127.0.0.1:5000/research`. Confirm "DeFi / Crypto Law" appears in the Case Type dropdown.

- [ ] **Step 4: Verify drafting page has all 4 DeFi templates**

Open `http://127.0.0.1:5000/drafting`. Confirm all 4 DeFi templates appear in the Document Template dropdown. Select each one and verify the correct input fields appear.

- [ ] **Step 5: Verify existing templates still work**

Select "Demand Letter" and "Divorce Petition" from the drafting dropdown — confirm their fields still show correctly.

- [ ] **Step 6: Verify chat widget responds to DeFi questions**

Open `http://127.0.0.1:5000/` and use the chat widget. Ask "Do you handle cryptocurrency legal issues?" — confirm the response mentions DeFi capabilities and nudges toward intake.

- [ ] **Step 7: Stop the Flask app**

```bash
kill %1
```
