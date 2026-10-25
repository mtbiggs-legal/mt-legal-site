# Note Categories + Case Seed Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Category field to every billing log entry, and seed two fully-realized open-to-close client cases (one per attorney) plus enrich two existing clients with rich case histories so Firm Insights reflects real data.

**Architecture:** Feature 1 touches the Time & Notes form HTML, the JS functions `logBillingEntry()` and `populateBillingLog()`, the `portal_billing_entry()` Flask route, and all auto-generated billing entry sites in app.py. Feature 2 is a standalone `seed_cases.py` script that writes directly to client JSON files using `app.save_client()`.

**Tech Stack:** Flask, vanilla JS, HTML/CSS, Python JSON file storage

---

### Task 1: Add Category select to Time & Notes form (HTML)

**Files:**
- Modify: `templates/attorney_portal.html` (~line 1157, the Time & Notes form)

**Step 1: Locate the form-grid inside `tab-time` and add a Category select**

Find this exact block:
```html
          <div class="form-group">
            <label for="be-date">Date</label>
            <input type="date" id="be-date" />
          </div>
          <div class="form-group">
            <label for="be-hours">Billable Hours</label>
            <input type="number" id="be-hours" step="0.25" min="0" placeholder="e.g. 1.5" />
          </div>
          <div class="form-group full">
            <label for="be-note">Note / Description *</label>
            <textarea id="be-note" rows="4" placeholder="Describe work performed, case notes, observations, strategy…"></textarea>
          </div>
```

Replace with:
```html
          <div class="form-group">
            <label for="be-date">Date</label>
            <input type="date" id="be-date" />
          </div>
          <div class="form-group">
            <label for="be-hours">Billable Hours</label>
            <input type="number" id="be-hours" step="0.25" min="0" placeholder="e.g. 1.5" />
          </div>
          <div class="form-group full">
            <label for="be-category">Category</label>
            <select id="be-category">
              <option value="Meeting">Meeting</option>
              <option value="Court Appearance">Court Appearance</option>
              <option value="Research">Research</option>
              <option value="Drafting">Drafting</option>
              <option value="Filing">Filing</option>
              <option value="Phone/Email">Phone / Email</option>
              <option value="Negotiation">Negotiation</option>
              <option value="Witness/Investigation">Witness / Investigation</option>
              <option value="Travel">Travel</option>
              <option value="Overhead">Overhead</option>
              <option value="Other">Other</option>
            </select>
          </div>
          <div class="form-group full">
            <label for="be-note">Note / Description *</label>
            <textarea id="be-note" rows="4" placeholder="Describe work performed, case notes, observations, strategy…"></textarea>
          </div>
```

**Step 2: Commit**
```bash
git add templates/attorney_portal.html
git commit -m "feat(notes): add Category select to Time & Notes entry form"
```

---

### Task 2: Add Category column to billing log table header + CSS badge

**Files:**
- Modify: `templates/attorney_portal.html` (~line 1179, the billing log table)
- Modify: `static/css/style.css` (add `.cat-badge` style)

**Step 1: Update the table header**

Find:
```html
        <table class="time-log-table">
          <thead><tr><th>Date</th><th>Hours</th><th>Note</th></tr></thead>
          <tbody id="billing-log-tbody"></tbody>
        </table>
```

Replace with:
```html
        <table class="time-log-table">
          <thead><tr><th>Date</th><th>Category</th><th>Hours</th><th>Note</th></tr></thead>
          <tbody id="billing-log-tbody"></tbody>
        </table>
```

**Step 2: Add `.cat-badge` CSS to `static/css/style.css`**

Find the `.time-log-table tr:last-child td` rule (near line 1384):
```css
.time-log-table tr:last-child td { border-bottom: none; }
```

Add after it:
```css
.cat-badge { display:inline-block; font-size:.7rem; font-weight:600; padding:.15rem .45rem; border-radius:3px; background:var(--gray-2); color:var(--navy); white-space:nowrap; text-transform:uppercase; letter-spacing:.04em; }
.cat-badge.court   { background:#e8f0fb; color:#1e3a5f; }
.cat-badge.research{ background:#f0f7ee; color:#2e6b3e; }
.cat-badge.drafting{ background:#fef9e7; color:#7d6008; }
.cat-badge.meeting { background:#fdf2fb; color:#6c3483; }
.cat-badge.filing  { background:#fef5e7; color:#9c6000; }
.cat-badge.phone   { background:#eaf4fb; color:#1a5276; }
.cat-badge.negot   { background:#fef5e7; color:#6e2f12; }
.cat-badge.travel  { background:#f5eef8; color:#6c3483; }
.cat-badge.overhead{ background:#f9ebea; color:#922b21; }
.cat-badge.intake  { background:#e8f8f5; color:#1a5f4a; }
```

**Step 3: Commit**
```bash
git add templates/attorney_portal.html static/css/style.css
git commit -m "feat(notes): add Category column to billing log table with colored badges"
```

---

### Task 3: Update `populateBillingLog()` to show category + reset select

**Files:**
- Modify: `templates/attorney_portal.html` — `populateBillingLog()` function (~line 2158)

**Step 1: Add a helper function to map category to CSS class**

Find `function populateBillingLog(c) {`. Add a helper function immediately before it:

```javascript
function _catClass(cat) {
  var m = {
    "Court Appearance": "court", "Research": "research", "Drafting": "drafting",
    "Meeting": "meeting", "Filing": "filing", "Phone/Email": "phone",
    "Negotiation": "negot", "Travel": "travel", "Overhead": "overhead",
    "Intake": "intake", "Witness/Investigation": "research"
  };
  return m[cat] || "";
}
```

**Step 2: Replace the entire `populateBillingLog()` function body**

Find the current function:
```javascript
function populateBillingLog(c) {
  const tbody = document.getElementById("billing-log-tbody");
  const total = document.getElementById("be-total");
  const logs  = c.billing_log || [];
  tbody.innerHTML = logs.length
    ? [...logs].reverse().map(e =>
        `<tr><td>${e.date}</td><td>${e.hours || 0}</td><td>${e.note || "—"}</td></tr>`
      ).join("")
    : `<tr><td colspan="3" style="color:var(--gray-3);text-align:center;padding:.75rem">No entries yet.</td></tr>`;
  total.textContent = "Total: " + (c.hours_billed || 0) + " hrs";
  // reset entry form
  document.getElementById("be-date").value  = new Date().toISOString().split("T")[0];
  document.getElementById("be-hours").value = "";
  document.getElementById("be-note").value  = "";
}
```

Replace with (uses DOM methods to avoid innerHTML with user content):
```javascript
function populateBillingLog(c) {
  var tbody = document.getElementById("billing-log-tbody");
  var total = document.getElementById("be-total");
  var logs  = c.billing_log || [];
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  if (logs.length) {
    var reversed = logs.slice().reverse();
    reversed.forEach(function(e) {
      var tr   = document.createElement("tr");
      var tdDt = document.createElement("td"); tdDt.textContent = e.date || "";
      var tdCt = document.createElement("td");
      var cat  = e.category || e.type || "Other";
      var badge = document.createElement("span");
      badge.className = "cat-badge " + _catClass(cat);
      badge.textContent = cat;
      tdCt.appendChild(badge);
      var tdHr = document.createElement("td"); tdHr.textContent = e.hours || 0;
      var tdNt = document.createElement("td");
      tdNt.style.whiteSpace = "pre-wrap";
      tdNt.textContent = e.note || "—";
      tr.appendChild(tdDt); tr.appendChild(tdCt); tr.appendChild(tdHr); tr.appendChild(tdNt);
      tbody.appendChild(tr);
    });
  } else {
    var tr = document.createElement("tr");
    var td = document.createElement("td"); td.colSpan = 4;
    td.style.cssText = "color:var(--gray-3);text-align:center;padding:.75rem";
    td.textContent = "No entries yet.";
    tr.appendChild(td); tbody.appendChild(tr);
  }
  total.textContent = "Total: " + (c.hours_billed || 0) + " hrs";
  document.getElementById("be-date").value     = new Date().toISOString().split("T")[0];
  document.getElementById("be-hours").value    = "";
  document.getElementById("be-note").value     = "";
  document.getElementById("be-category").value = "Meeting";
}
```

**Step 3: Commit**
```bash
git add templates/attorney_portal.html
git commit -m "feat(notes): render category badge in billing log rows using DOM methods"
```

---

### Task 4: Update `logBillingEntry()` to send category

**Files:**
- Modify: `templates/attorney_portal.html` — `logBillingEntry()` function (~line 2489)

**Step 1: Find the function and add category read + send**

Find:
```javascript
function logBillingEntry() {
  if (!_currentClient) return;
  const note  = document.getElementById("be-note").value.trim();
  const hours = parseFloat(document.getElementById("be-hours").value) || 0;
  const date  = document.getElementById("be-date").value;
  const res   = document.getElementById("be-result");
  if (!note) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Note / description is required.</p>';
    return;
  }
  fetch("/portal/attorney/billing-entry", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ username: _currentClient.username, note, hours, date })
  })
```

Replace with:
```javascript
function logBillingEntry() {
  if (!_currentClient) return;
  const note     = document.getElementById("be-note").value.trim();
  const hours    = parseFloat(document.getElementById("be-hours").value) || 0;
  const date     = document.getElementById("be-date").value;
  const category = document.getElementById("be-category").value;
  const res      = document.getElementById("be-result");
  if (!note) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Note / description is required.</p>';
    return;
  }
  fetch("/portal/attorney/billing-entry", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ username: _currentClient.username, note, hours, date, category })
  })
```

**Step 2: Commit**
```bash
git add templates/attorney_portal.html
git commit -m "feat(notes): send category in logBillingEntry() fetch payload"
```

---

### Task 5: Update `portal_billing_entry()` backend to store category

**Files:**
- Modify: `app.py` (~line 1825, `portal_billing_entry()`)

**Step 1: Find the route and add category to the entry dict**

Find:
```python
    note  = data.get("note", "").strip()
    if not note:
        return jsonify({"error": "Note cannot be empty."}), 400
    hours = round(float(data.get("hours", 0) or 0), 2)
    entry = {
        "date":  data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "hours": hours,
        "note":  note,
    }
```

Replace with:
```python
    note     = data.get("note", "").strip()
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
```

**Step 2: Verify**
```bash
python -c "import app; print('OK')"
```

**Step 3: Commit**
```bash
git add app.py
git commit -m "feat(notes): store category field in portal_billing_entry route"
```

---

### Task 6: Add `category` to all auto-generated billing entries in app.py

**Files:**
- Modify: `app.py` — 7 specific sites where billing entries are auto-created

Read app.py carefully and apply each change.

**Change 1 — Intake billing_log on new client via public intake form (~line 265-272)**

Find:
```python
            "billing_log": [
                {
                    "date":  datetime.now().strftime("%Y-%m-%d"),
                    "hours": 0,
                    "note":  intake_note,
                    "type":  "intake",
                }
            ],
```
Replace with:
```python
            "billing_log": [
                {
                    "date":     datetime.now().strftime("%Y-%m-%d"),
                    "hours":    0,
                    "note":     intake_note,
                    "type":     "intake",
                    "category": "Intake",
                }
            ],
```

**Change 2 — Portal intake auto-bill .1 hr (~line 340-345)**

Find:
```python
        portal_record.setdefault("billing_log", []).append({
            "date":  datetime.now().strftime("%Y-%m-%d"),
            "hours": 0.1,
            "note":  "Intake Processing",
            "type":  "intake",
        })
```
Replace with:
```python
        portal_record.setdefault("billing_log", []).append({
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0.1,
            "note":     "Intake Processing",
            "type":     "intake",
            "category": "Intake",
        })
```

**Change 3 — `portal_create_client` intake billing (~line 1639-1644)**

Find:
```python
        billing_log.append({
            "date":  datetime.now().strftime("%Y-%m-%d"),
            "hours": 0,
            "note":  f"INTAKE — {case_type}.\nMatter: {first_note}",
            "type":  "intake",
        })
```
Replace with:
```python
        billing_log.append({
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0,
            "note":     f"INTAKE — {case_type}.\nMatter: {first_note}",
            "type":     "intake",
            "category": "Intake",
        })
```

**Change 4 — AI message auto-billing (~line 1131-1137)**

Find:
```python
        client.setdefault("billing_log", []).append({
            "date":  date.today().isoformat(),
            "hours": 0.1,
            "note":  "AI assistant response \u2014 " + text[:60] + ("..." if len(text) > 60 else ""),
            "type":  "ai_message",
        })
```
Replace with:
```python
        client.setdefault("billing_log", []).append({
            "date":     date.today().isoformat(),
            "hours":    0.1,
            "note":     "AI assistant response \u2014 " + text[:60] + ("..." if len(text) > 60 else ""),
            "type":     "ai_message",
            "category": "Phone/Email",
        })
```

**Change 5 — Payment billing entry (~line 1222-1227)**

Find:
```python
    client.setdefault("billing_log", []).append({
        "date":  today,
        "hours": 0,
        "note":  payment_entry["note"],
        "type":  "payment",
    })
```
Replace with:
```python
    client.setdefault("billing_log", []).append({
        "date":     today,
        "hours":    0,
        "note":     payment_entry["note"],
        "type":     "payment",
        "category": "Overhead",
    })
```

**Change 6 — Document upload auto-billing (~line 2271-2280)**

Find:
```python
        entry = {
            "date":  datetime.now().strftime("%Y-%m-%d"),
            "hours": 0.1,
            "note":  f"{category} — \"{dest.name}\" uploaded.",
            "type":  "document_upload",
        }
```
Replace with:
```python
        entry = {
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0.1,
            "note":     f"{category} — \"{dest.name}\" uploaded.",
            "type":     "document_upload",
            "category": "Filing",
        }
```

**Change 7 — Research save-draft AI + review entries (~line 2722-2724)**

Find:
```python
        entry_ai  = {"date": today, "hours": 0.2,
                     "note": f"AI Research — {motion_type} ({dest.name})", "type": "research_ai"}
        entry_rev = {"date": today, "hours": 0.2,
                     "note": f"Attorney Review — {motion_type} ({dest.name})", "type": "research_review"}
```
Replace with:
```python
        entry_ai  = {"date": today, "hours": 0.2,
                     "note": f"AI Research — {motion_type} ({dest.name})",
                     "type": "research_ai", "category": "Research"}
        entry_rev = {"date": today, "hours": 0.2,
                     "note": f"Attorney Review — {motion_type} ({dest.name})",
                     "type": "research_review", "category": "Drafting"}
```

**Step after all 7 changes — verify**
```bash
python -c "import app; print('OK')"
```

**Commit:**
```bash
git add app.py
git commit -m "feat(notes): add category field to all auto-generated billing entries"
```

---

### Task 7: Create `seed_cases.py` with full case histories

**Files:**
- Create: `seed_cases.py`

**Overview of script structure:**
- Defines helpers: `E(date, hours, category, note)` for billing entries, `M(from_, date, text)` for messages, `P(amount, method, date, note)` for payments
- Defines all case data as module-level lists (HOLLISTER_BILLING, HOLLISTER_MESSAGES, etc.)
- `seed_new_client(username, data)` — writes a brand-new client JSON; skips if `"seeded": True` already present (unless `--force`)
- `enrich_existing_client(username, extra_billing, extra_messages, extra_payments)` — appends to existing client; skips if `"enriched": True` (unless `--force`)
- `apply_payments(client, payments)` — adds payments list entries and updates hours_paid + appends Overhead billing entries

**Case 1: RHollister — Raymond T. Hollister — Criminal Defense (Endocide)**
- Case: Felony DUI w/ refusal, prior conviction, Davidson Co. Cr. Case No. 2026-CR-44821
- ~18 billing entries spanning: Intake, Meeting, Research, Filing, Phone/Email, Court Appearance, Drafting, Negotiation, Overhead
- 12 messages (6 client / 6 attorney)
- Notes on: ADA Priya Mehta (opposing counsel), Judge Calvin Reese, case law State v. Bishop + State v. Turner + State v. Sensing
- Outcome: Breathalyzer suppressed, plea to misdemeanor DUI, case closed
- Payments: $3,500 retainer + $1,750 final = $5,250

**Case 2: LChen — Linda M. Chen — Employment Law (SophiaH)**
- Case: Wrongful termination / age+gender discrimination at NovaTech Solutions, Davidson Co. Circuit Ct. 26C1140
- ~19 billing entries spanning: Intake, Meeting, Research, Filing, Phone/Email, Witness/Investigation, Drafting, Court Appearance, Negotiation, Travel, Overhead
- 10 messages (5 client / 5 attorney)
- Notes on: Greg Stanton of Whitmore & Associates (opposing counsel), Judge Marianne Okafor, McDonnell Douglas framework, THRA § 4-21-401, expert Dr. Susan Park
- Outcome: Mediation scheduled, strong settlement position
- Payments: $5,000 retainer + $8,750 contingency partial = $13,750

**BobbyT enrichment (Endocide):** 12 more entries (Research, Filing, Negotiation, Court Appearance), 8 messages, 1 payment ($1,050). Case resolves to reckless driving plea.

**DerekW enrichment (SophiaH):** 12 more entries (Research, Phone/Email, Filing, Witness/Investigation, Negotiation), 8 messages, 1 payment ($20,295 contingency). Case resolves to $61,500 settlement.

**Write the complete script to `seed_cases.py`.**

The script structure:

```python
#!/usr/bin/env python3
"""
seed_cases.py
Usage: python seed_cases.py [--force]
"""
import sys, os, pathlib
os.chdir(pathlib.Path(__file__).parent)
import app

FORCE = "--force" in sys.argv

def E(date, hours, category, note):
    return {"date": date, "hours": hours, "category": category, "note": note}
def M(from_, date, text):
    return {"from": from_, "date": date, "text": text}
def P(amount, method, date, note):
    return {"amount": amount, "method": method, "date": date, "note": note}
def hours_from_log(log):
    return round(sum(float(e.get("hours", 0) or 0) for e in log), 2)
def apply_payments(client, payments):
    for p in payments:
        hrs = round(p["amount"] / app.HOURLY_RATE, 2)
        client.setdefault("payments", []).append(p)
        client["hours_paid"] = round(client.get("hours_paid", 0) + hrs, 2)
        client.setdefault("billing_log", []).append(
            E(p["date"], 0, "Overhead", "PAYMENT RECEIVED — " + p["note"])
        )

# --- ALL CASE DATA DEFINED HERE (see full list below) ---

# --- seeding functions ---
def seed_new_client(username, data):
    if not FORCE:
        existing = app.load_client(username)
        if existing and existing.get("seeded"):
            print(f"  [SKIP] {username} already seeded")
            return
    data["seeded"] = True
    data["hours_billed"] = hours_from_log(data.get("billing_log", []))
    app.save_client(data)
    print(f"  [OK] Created {username}: {data['client_name']} — {len(data['billing_log'])} log entries, {len(data['messages'])} messages")

def enrich_existing_client(username, extra_billing, extra_messages, extra_payments):
    c = app.load_client(username)
    if not c:
        print(f"  [WARN] {username} not found"); return
    if not FORCE and c.get("enriched"):
        print(f"  [SKIP] {username} already enriched"); return
    c.setdefault("billing_log", []).extend(extra_billing)
    c["hours_billed"] = hours_from_log(c["billing_log"])
    c.setdefault("messages", []).extend(extra_messages)
    apply_payments(c, extra_payments)
    c["enriched"] = True
    app.save_client(c)
    print(f"  [OK] Enriched {username}: +{len(extra_billing)} entries, +{len(extra_messages)} msgs, +{len(extra_payments)} payments")

if __name__ == "__main__":
    print("=== Endo-Legal Case Seeder ===")
    print(f"HOURLY_RATE = ${app.HOURLY_RATE:.0f}/hr\n")
    print("Creating new clients...")
    # build hollister dict, apply_payments, seed_new_client("RHollister", hollister)
    # build chen dict, apply_payments, seed_new_client("LChen", chen)
    print("\nEnriching existing clients...")
    enrich_existing_client("BobbyT", BOBBYT_EXTRA_BILLING, BOBBYT_EXTRA_MESSAGES, BOBBYT_EXTRA_PAYMENTS)
    enrich_existing_client("DerekW", DEREKW_EXTRA_BILLING, DEREKW_EXTRA_MESSAGES, DEREKW_EXTRA_PAYMENTS)
    print("\nDone.")
```

Write the complete script with ALL billing entries, messages, and case data fully filled in. Include:

**HOLLISTER_BILLING** (18 entries, one per step of DUI case):
- 2026-01-10: Intake note (0 hrs, Intake)
- 2026-01-10: Initial consultation / retainer (0.5 hrs, Meeting)
- 2026-01-12: TCA research + discovery request (1.0 hr, Research)
- 2026-01-15: Filed motion for discovery (0.5 hr, Filing)
- 2026-01-20: Call re license suspension (0.3 hr, Phone/Email)
- 2026-01-28: Officer cert gap found in discovery (1.0 hr, Research)
- 2026-02-03: Drafted Motion to Suppress FSTs (0.5 hr, Drafting)
- 2026-02-10: Email with ADA Mehta + found breathalyzer calibration issue (0.5 hr, Phone/Email)
- 2026-02-14: First suppression hearing, Judge Reese reserved ruling (2.0 hr, Court Appearance)
- 2026-02-18: Confirmed calibration defect - 47 days vs 45 day max (0.5 hr, Research)
- 2026-02-20: Supplemental motion re breathalyzer suppression (0.5 hr, Drafting)
- 2026-02-24: Second suppression hearing - breathalyzer SUPPRESSED (1.5 hr, Court Appearance)
- 2026-02-25: Called client re big win (0.3 hr, Phone/Email)
- 2026-02-27: Plea negotiation call with ADA Mehta (0.5 hr, Negotiation)
- 2026-03-01: State agreed to misdemeanor DUI terms (0.3 hr, Negotiation)
- 2026-03-01: Presented plea offer to client (0.3 hr, Phone/Email)
- 2026-03-03: Drafted plea paperwork, client prep (0.5 hr, Drafting)
- 2026-03-03: Plea hearing - case closed (1.0 hr, Court Appearance)

**HOLLISTER_MESSAGES** (12 messages, alternating client/attorney):
- 2026-01-10: Client shocked after release; Attorney reassures, notes issues found
- 2026-01-12: Client asks about license; Attorney explains DMV hearing filed
- 2026-01-28: Client asks about discovery; Attorney reports cert gap found
- 2026-02-14: Client asks how hearing went; Attorney explains reserved ruling + new breathalyzer issue
- 2026-02-25: Client thrilled about breathalyzer suppression; Attorney explains leverage
- 2026-03-01: Client accepts plea terms; Attorney confirms plea hearing details

**HOLLISTER_PAYMENTS**: $3,500 on 2026-01-10, $1,750 on 2026-03-03

**CHEN_BILLING** (19 entries, employment discrimination case):
- 2026-01-15: Intake (0 hr, Intake)
- 2026-01-15: Initial consultation (1.0 hr, Meeting)
- 2026-01-17: McDonnell Douglas research (1.5 hr, Research)
- 2026-01-20: EEOC + THRA filings (0.5 hr, Filing)
- 2026-01-22: Call re evidence preservation (0.5 hr, Phone/Email)
- 2026-01-28: Witness interviews - 3 former colleagues (2.0 hr, Witness/Investigation)
- 2026-02-01: Drafted demand letter $125k (1.0 hr, Drafting)
- 2026-02-10: Received denial from Stanton / Whitmore (0.3 hr, Phone/Email)
- 2026-02-12: Drafted complaint - Davidson Circuit Ct (1.5 hr, Drafting)
- 2026-02-12: Filed complaint, Case No. 26C1140, Judge Okafor (0.3 hr, Filing)
- 2026-02-18: Research on Judge Okafor's rulings (0.5 hr, Research)
- 2026-02-20: Email re discovery schedule with Stanton (0.5 hr, Phone/Email)
- 2026-02-25: Deposition of HR Director David Park - key admissions (3.0 hr, Witness/Investigation)
- 2026-03-01: Retained Dr. Susan Park, expert witness (1.0 hr, Research)
- 2026-03-01: Expert disclosure filing per TRCP 26.02(4) (0.5 hr, Drafting)
- 2026-03-03: Travel to Circuit Court (0.5 hr, Travel)
- 2026-03-03: Scheduling conference, Judge Okafor ordered mediation (1.5 hr, Court Appearance)
- 2026-03-03: Post-hearing settlement call with Stanton (0.5 hr, Negotiation)

**CHEN_MESSAGES** (10 messages):
- 2026-01-15: Client emotional about termination; Attorney confirms strong case
- 2026-01-20: Client asks about expense reimbursement; Attorney warns don't engage + confirms EEOC filed
- 2026-02-01: Client asks about demand letter; Attorney explains strategy
- 2026-02-25: Client anxious about deposition; Attorney reports excellent result
- 2026-03-03: Client heard NovaTech is worried; Attorney confirms mediation scheduled, pushes for $75k

**CHEN_PAYMENTS**: $5,000 on 2026-01-15, $8,750 on 2026-03-03

**BOBBYT_EXTRA_BILLING** (12 entries, DUI resolves to reckless driving):
- Research Miranda violation
- Phone/Email confirming client asked for attorney 3x
- Filed Motion to Suppress statements
- Drafting letter to ADA Briggs
- Phone/Email - ADA interested in plea, officer has prior complaint
- Court Appearance - arraignment, not guilty plea
- Negotiation - ADA offers reckless driving
- Phone/Email - client accepts
- Drafting - plea paperwork
- Court Appearance - plea entered, reckless driving, $250 fine
- Filing - order of disposition
- Overhead - payment received

**BOBBYT_EXTRA_MESSAGES** (8 messages): stress update, Miranda discovery, confirm asked for attorney, plea offer delivered, acceptance, hearing confirmation

**BOBBYT_EXTRA_PAYMENTS**: $1,050 on 2026-03-10

**DEREKW_EXTRA_BILLING** (12 entries, rear-end injury settles $61,500):
- Research on rear-end liability, MRI confirms L4-L5 herniation
- Phone/Email re medical treatment + missed work
- Filing notice of representation with State Farm
- Drafting demand $84,600 (medical $21,200 + wages $4,200 + property $14,200 + pain/suffering $45,000)
- Phone/Email - State Farm 21-day delay
- Witness/Investigation - retained accident reconstruction expert Robert Dyer PE
- Phone/Email - property damage check issued
- Negotiation - State Farm offers $28k, countered $72k
- Phone/Email - Dyer report confirmed 35 mph impact
- Negotiation - SF escalated to $52k, filed litigation hold notice
- Phone/Email - final offer $61,500, client accepts
- Overhead - payment received

**DEREKW_EXTRA_MESSAGES** (8 messages): PT update, warned not to talk to SF, rejected $28k offer, Dyer report update, client accepts $61,500

**DEREKW_EXTRA_PAYMENTS**: $20,295 on 2026-03-20 (33% contingency on $61,500)

**Full client dicts for RHollister and LChen must include all fields:**
username, password (="password"), must_change_password (=False), client_name, full_name, case_type, assigned_attorney, legal_issue (summary of outcome), next_court_date ("" for closed cases), phone, email, google_drive_url (""), next_meeting, client_folder (str(app.CLIENT_FILES_DIR / username)), billing_log, time_logs ([]), notes ([]), messages, hours_paid (0 before apply_payments), payments ([]), case_no, charges, charge_level, county ("Davidson"), court (full court name), activity_log ([]), case_number ("EL-SEED-001" and "EL-SEED-002"), archived (False)

**Step 2: Run script**
```bash
python seed_cases.py
```
Expected: 4 lines of [OK] output.

**Step 3: Verify**
```bash
python -c "
import app
for un in ['RHollister', 'LChen', 'BobbyT', 'DerekW']:
    c = app.load_client(un)
    print(un, '| hrs:', c.get('hours_billed'), '| pmts:', len(c.get('payments',[])), '| msgs:', len(c.get('messages',[])), '| entries:', len(c.get('billing_log',[])))
"
```

**Step 4: Commit**
```bash
git add seed_cases.py
git commit -m "feat: add seed_cases.py with two full open-to-close case histories + enriched clients"
```

---

### Task 8: Smoke test in browser

**Step 1: Start Flask**
```bash
python app.py
```

**Step 2: Test Time & Notes tab**
- Attorney portal → open any client → Time & Notes tab
- Confirm Category dropdown is visible
- Log an entry with Category = "Court Appearance"
- Confirm 4-column billing log shows with colored badge

**Step 3: Check seeded clients**
- RHollister should appear in Marcus Endo's sidebar
- Open → Time & Notes: 20+ entries with category badges
- Open → Messages: 12 messages
- LChen in Sophia Hargrove's sidebar — same check

**Step 4: Check Firm Insights**
- Revenue Collected should now show real numbers
- Both attorneys should have hours and revenue in the breakdown

**Step 5: Commit any fixes**
```bash
git add -p
git commit -m "fix: smoke test corrections"
```
