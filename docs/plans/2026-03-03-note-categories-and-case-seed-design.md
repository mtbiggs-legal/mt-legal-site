# Note Categories + Case Seed Design

## Feature 1: Note Categories in Billing Log

### What
Add a `category` field to every billing log entry. Attorneys select a category when logging time/notes. Auto-generated entries get an appropriate default category.

### Categories
Court Appearance, Research, Drafting, Meeting, Phone/Email, Filing, Negotiation, Travel, Overhead, Witness/Investigation, Other

### Changes
- `templates/attorney_portal.html` (tab-time form): add `<select id="be-category">` between Hours and Note fields
- `logBillingEntry()` JS: include `category` in fetch payload
- `portal_billing_entry()` route: read and store `category` on entry dict
- Billing log table: add Category column (Date | Category | Hours | Note)
- `populateBillingLog()`: render category badge
- Auto-entries default categories:
  - Intake → "Intake"
  - Research save → "Research"
  - Doc upload → "Filing"
  - Research query (AI) → "Research"
  - Drafting → "Drafting"
  - Payment entries → "Overhead"

### Data model
```json
{
  "date": "2026-03-03",
  "hours": 1.5,
  "note": "...",
  "category": "Court Appearance"
}
```

---

## Feature 2: Simulated Open-to-Close Cases

### Script: `seed_cases.py`

Creates **two new full-detail client cases** + **enriches one existing client per attorney** with realistic case histories.

### New Case 1 — Marcus Endo (Endocide)
- **Username:** `RHollister`
- **Client:** Raymond T. Hollister
- **Case type:** Criminal Defense
- **Matter:** Felony DUI (DUI with refusal, .18 BAC, prior DUI 6 yrs ago), Davidson Co.
- **Outcome:** Plea to misdemeanor DUI, 11 months 29 days suspended, fines
- **~22 billing entries** across: Intake, Meeting, Court Appearance, Research, Drafting, Phone/Email, Filing, Negotiation
- **10 client ↔ attorney messages**
- Notes on: opposing counsel (ADA Priya Mehta), Judge (Hon. Calvin Reese), case law (State v. Bishop, State v. Turner), client issues (compliance, anxious)
- **Payments:** $3,500 retainer + $1,750 final = $5,250 collected / 15 hours @ $350

### New Case 2 — Sophia Hargrove (SophiaH)
- **Username:** `LChen`
- **Client:** Linda M. Chen
- **Case type:** Employment Law
- **Matter:** Wrongful termination / hostile work environment (age + gender), NovaTech Solutions, Davidson Co. Circuit Court
- **Outcome:** Mediated settlement — $48,000
- **~22 billing entries** across: Intake, Meeting, Research, Drafting, Filing, Negotiation, Witness/Investigation, Phone/Email, Court Appearance, Travel
- **10 client ↔ attorney messages**
- Notes on: opposing counsel (firm: Whitmore & Associates, atty: Greg Stanton), Judge (Hon. Marianne Okafor), case law (McDonnell Douglas v. Green, THRA § 4-21-401), expert witness (Dr. Susan Park, HR expert)
- **Payments:** $5,000 retainer + $8,750 final = $13,750 collected / ~25 hours @ $350 + contingency portion

### Enriched Existing Clients
- **BobbyT** (Endocide) — add 12 more realistic entries, messages, partial payment
- **DerekW** (SophiaH) — add 12 more realistic entries, messages, partial payment

### Script behavior
- Idempotent: checks if client already has seeded data (looks for `"seeded": true` flag), skips if already done
- Uses `app.save_client()` to write
- Prints a summary of what was created/updated
