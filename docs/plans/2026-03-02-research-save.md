# Research Report Save Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add "Save to Documents" to Legal Issue Analysis and Legal Authority research steps, auto-billing 0.5 hrs and placing a tracker note on each save.

**Architecture:** One new Flask route (`POST /portal/attorney/research/save-report`) mirrors the existing `research_save_draft()` pattern exactly. Frontend adds two save buttons (one per report section) that call a single `saveResearchReport(reportType)` JS function.

**Tech Stack:** Flask, Python pathlib, Jinja2/HTML, vanilla JavaScript — no new dependencies.

---

## Context

The existing `research_save_draft()` route (app.py ~line 2226) already does: save `.txt` file → append billing entry with 0.5 hrs → update `hours_billed` → return billing entry to frontend → frontend calls `populateBillingLog()` and `populateOverview()`. This new route is the same pattern with different label text and filename prefix.

### Key locations
- `app.py` line 2271: end of `research_save_draft()` — insert new route here
- `app.py` line 879: `_log_activity(username, action_type, description)` helper
- `app.py` line 1774: `DOCS_CATEGORIES` list (includes `"Litigation Drafts"`)
- `attorney_portal.html` line 812: `#res-issues-section` div — add save row inside here
- `attorney_portal.html` line 820: `#res-authority-section` div — add save row inside here
- `attorney_portal.html` line 1328: `_resAnalyzedIssues` JS variable (holds issues text)
- `attorney_portal.html` line 1339: `populateResearch()` clear list — add new span IDs here
- `attorney_portal.html` line 1487: end of `saveResearchDraft()` — add new JS function after here

---

## Task 1: Add `research_save_report()` route to app.py

**Files:**
- Modify: `app.py` (insert after line 2271, before the `if __name__ == "__main__":` block)
- Test: `tests/test_research_save_report.py` (create new)

### Step 1: Write the failing test

Create `tests/test_research_save_report.py`:

```python
import json
import sys
import types
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal stubs so app.py imports without optional heavy deps
# ---------------------------------------------------------------------------
for mod in ("anthropic", "google.oauth2.credentials",
            "google_auth_oauthlib.flow", "googleapiclient.discovery",
            "mammoth", "pypdf", "fpdf"):
    if mod not in sys.modules:
        parts = mod.split(".")
        for i in range(1, len(parts) + 1):
            name = ".".join(parts[:i])
            if name not in sys.modules:
                sys.modules[name] = types.ModuleType(name)

import importlib
import app as _app_module

_app = _app_module.app
_app.config["TESTING"] = True
_app.config["SECRET_KEY"] = "test"


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "CLIENT_FILES_DIR",    tmp_path / "files")
    (tmp_path / "accounts").mkdir()
    (tmp_path / "files").mkdir()


@pytest.fixture
def client(patch_dirs):
    with _app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "atty1"
            sess["role"]     = "attorney"
        yield c


@pytest.fixture
def make_client_json(tmp_path, monkeypatch):
    """Create a minimal client JSON for username 'testclient'."""
    accounts_dir = tmp_path / "accounts"
    accounts_dir.mkdir(exist_ok=True)
    record = {
        "username":    "testclient",
        "client_name": "Test Client",
        "billing_log": [],
        "hours_billed": 0,
        "activity_log": [],
    }
    (accounts_dir / "testclient.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    return record


def test_save_report_analysis_creates_file_and_bills(client, make_client_json, tmp_path):
    """Saving an 'analysis' report creates a .txt file and adds a 0.5-hr billing entry."""
    resp = client.post("/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis",
              "text": "ISSUE 1: Fourth Amendment violation."})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["filename"].startswith("legal_issues_")
    assert data["filename"].endswith(".txt")
    assert data["category"] == "Litigation Drafts"
    assert data["billing_entry"]["hours"] == 0.5
    assert "legal issues analysis" in data["billing_entry"]["note"].lower()
    assert data["total_hours"] == 0.5

    # File should exist on disk
    saved = (tmp_path / "files" / "testclient" / "documents" /
             "Litigation Drafts" / data["filename"])
    assert saved.exists()
    assert "Fourth Amendment" in saved.read_text(encoding="utf-8")


def test_save_report_authority_creates_file_and_bills(client, make_client_json, tmp_path):
    """Saving an 'authority' report creates a .txt file and adds a 0.5-hr billing entry."""
    resp = client.post("/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "authority",
              "text": "Terry v. Ohio, 392 U.S. 1 (1968)."})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["filename"].startswith("legal_authority_")
    assert data["billing_entry"]["hours"] == 0.5
    assert "authority memo" in data["billing_entry"]["note"].lower()


def test_save_report_missing_params_returns_400(client):
    """Missing username or text returns 400."""
    resp = client.post("/portal/attorney/research/save-report",
        json={"report_type": "analysis", "text": "some text"})
    assert resp.status_code == 400

    resp2 = client.post("/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis"})
    assert resp2.status_code == 400


def test_save_report_invalid_type_returns_400(client):
    """Invalid report_type returns 400."""
    resp = client.post("/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "bogus",
              "text": "some text"})
    assert resp.status_code == 400


def test_save_report_deduplicates_filename(client, make_client_json, tmp_path):
    """If the filename already exists, a _2 suffix is added."""
    # Pre-create the expected file
    dest_dir = (tmp_path / "files" / "testclient" / "documents" / "Litigation Drafts")
    dest_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d")
    (dest_dir / f"legal_issues_{ts}.txt").write_text("existing", encoding="utf-8")

    resp = client.post("/portal/attorney/research/save-report",
        json={"username": "testclient", "report_type": "analysis",
              "text": "new content"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "_2" in data["filename"]
```

### Step 2: Run test to verify it fails

```bash
cd C:/Users/Endoc/Desktop/law-office-app
python -m pytest tests/test_research_save_report.py -v
```

Expected: FAIL — `404 NOT FOUND` for the route (route doesn't exist yet).

### Step 3: Add the route to app.py

Insert the following **after line 2271** (after `research_save_draft()`, before the `if __name__ == "__main__":` block) in `app.py`:

```python

@app.route("/portal/attorney/research/save-report", methods=["POST"])
@require_attorney
def research_save_report():
    data        = request.get_json() or {}
    username    = data.get("username", "").strip()
    report_type = data.get("report_type", "").strip()   # "analysis" or "authority"
    text        = data.get("text", "").strip()
    if not all([username, report_type, text]):
        return jsonify({"error": "Missing parameters."}), 400
    if report_type not in ("analysis", "authority"):
        return jsonify({"error": "Invalid report_type. Must be 'analysis' or 'authority'."}), 400
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
    billing_entry = None
    client = load_client(username)
    if client:
        entry = {
            "date":  datetime.now().strftime("%Y-%m-%d"),
            "hours": 0.5,
            "note":  f"{label} saved as \"{dest.name}\".",
            "type":  "research_report",
        }
        client.setdefault("billing_log", []).append(entry)
        client["hours_billed"] = round(
            sum(e.get("hours", 0) for e in client["billing_log"]), 2
        )
        save_client(client)
        _log_activity(username, "time_logged",
                      f"0.5 hrs — {label} saved as \"{dest.name}\".")
        billing_entry = entry
    return jsonify({
        "success":       True,
        "filename":      dest.name,
        "category":      category,
        "billing_entry": billing_entry,
        "total_hours":   client["hours_billed"] if client else None,
    })
```

### Step 4: Run tests to verify they pass

```bash
python -m pytest tests/test_research_save_report.py -v
```

Expected: All 5 tests PASS.

### Step 5: Run full test suite

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS (existing 3 + new 5).

### Step 6: Commit

```bash
git add app.py tests/test_research_save_report.py
git commit -m "feat: add research/save-report route with auto-billing"
```

---

## Task 2: Add save buttons and JS to attorney_portal.html

**Files:**
- Modify: `templates/attorney_portal.html`

No new tests needed — this is pure HTML/JS UI wiring on top of the route tested in Task 1.

### Step 1: Add save row to `#res-issues-section` (HTML)

In `attorney_portal.html`, find the `#res-issues-section` block (around line 812). The current content is:

```html
        <div id="res-issues-section" style="display:none">
          <div class="res-section-label">Identified Issues</div>
          <div id="res-issues-content" class="res-issues-block"></div>
          <button class="btn btn-primary" onclick="findAuthority()" id="res-authority-btn" style="margin-top:.2rem">Research Legal Authority →</button>
```

Add a save row **after** `#res-issues-content` and **before** the "Research Legal Authority" button:

```html
        <div id="res-issues-section" style="display:none">
          <div class="res-section-label">Identified Issues</div>
          <div id="res-issues-content" class="res-issues-block"></div>
          <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem">
            <button class="btn btn-primary" onclick="saveResearchReport('analysis')" style="padding:.4rem .85rem;font-size:.84rem">↓ Save to Documents</button>
            <span id="res-analysis-save-result" style="font-family:Arial,sans-serif;font-size:.84rem"></span>
          </div>
          <button class="btn btn-primary" onclick="findAuthority()" id="res-authority-btn" style="margin-top:.2rem">Research Legal Authority →</button>
```

### Step 2: Add save row to `#res-authority-section` (HTML)

Find the `#res-authority-section` block (around line 820). Current content:

```html
        <div id="res-authority-section" style="display:none">
          <div class="res-section-label">Legal Authority</div>
          <div id="res-authority-content" class="res-memo-block"></div>
        </div>
```

Add a save row **after** `#res-authority-content`:

```html
        <div id="res-authority-section" style="display:none">
          <div class="res-section-label">Legal Authority</div>
          <div id="res-authority-content" class="res-memo-block"></div>
          <div style="display:flex;align-items:center;gap:.6rem;margin-top:.6rem">
            <button class="btn btn-primary" onclick="saveResearchReport('authority')" style="padding:.4rem .85rem;font-size:.84rem">↓ Save to Documents</button>
            <span id="res-authority-save-result" style="font-family:Arial,sans-serif;font-size:.84rem"></span>
          </div>
        </div>
```

### Step 3: Add `saveResearchReport()` JS function

In `attorney_portal.html`, find the end of `saveResearchDraft()` (around line 1487):

```javascript
  });
}

// ── Save client info ──────────────────────────────────────
```

Add the new function **between** the closing `}` of `saveResearchDraft()` and the `// ── Save client info` comment:

```javascript
function saveResearchReport(reportType) {
  if (!_currentClient) return;
  const text = reportType === "analysis"
    ? _resAnalyzedIssues
    : document.getElementById("res-authority-content").textContent;
  if (!text.trim()) return;
  const resElId = reportType === "analysis"
    ? "res-analysis-save-result"
    : "res-authority-save-result";
  const resEl = document.getElementById(resElId);
  resEl.style.color = "";
  resEl.textContent = "Saving\u2026";
  fetch("/portal/attorney/research/save-report", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username:    _currentClient.username,
      report_type: reportType,
      text
    })
  }).then(r => r.json()).then(d => {
    if (!d.success) {
      resEl.style.color = "var(--red)";
      resEl.textContent = d.error || "Save failed.";
      return;
    }
    resEl.style.color = "var(--green)";
    resEl.textContent = "Saved as \u201c" + d.filename + "\u201d in " + d.category + ". 0.5 hrs billed.";
    if (d.billing_entry && _currentClient) {
      _currentClient.billing_log = _currentClient.billing_log || [];
      _currentClient.billing_log.push(d.billing_entry);
      if (d.total_hours !== null) _currentClient.hours_billed = d.total_hours;
      populateBillingLog(_currentClient);
      populateOverview(_currentClient);
    }
  }).catch(e => {
    resEl.style.color = "var(--red)";
    resEl.textContent = "Request failed: " + e.message;
  });
}
```

### Step 4: Update `populateResearch()` clear list

Find the `populateResearch()` function (around line 1331). It has this line clearing result spans:

```javascript
  ["res-analyze-err","res-authority-err","res-spot-err","res-draft-err","res-save-result"].forEach(id => {
    document.getElementById(id).textContent = "";
  });
```

Add the two new span IDs to the array:

```javascript
  ["res-analyze-err","res-authority-err","res-spot-err","res-draft-err","res-save-result",
   "res-analysis-save-result","res-authority-save-result"].forEach(id => {
    document.getElementById(id).textContent = "";
  });
```

### Step 5: Verify the page loads without JS errors

Run the Flask app:
```bash
python app.py
```
Open the attorney portal in a browser, navigate to the Research tab, select a client. Verify:
- No console errors on page load
- "Identify Legal Issues →" button still works
- After issues appear, a small "↓ Save to Documents" button is visible below them
- After authority memo appears, a small "↓ Save to Documents" button is visible below it
- Clicking Save shows "Saving…" then green confirmation text
- The billing log updates with the 0.5-hr entry
- The file appears when checking the client's documents

### Step 6: Commit

```bash
git add templates/attorney_portal.html
git commit -m "feat: add save buttons for legal issues and authority research reports"
```

---

## Quick Verification Checklist

After both tasks are done, confirm:
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] New route rejects missing `username` with 400
- [ ] New route rejects invalid `report_type` with 400
- [ ] Analysis save creates `legal_issues_YYYYMMDD.txt` in `Litigation Drafts`
- [ ] Authority save creates `legal_authority_YYYYMMDD.txt` in `Litigation Drafts`
- [ ] Billing log shows 0.5 hrs with correct label text
- [ ] `populateResearch()` clears both save result spans when switching clients
