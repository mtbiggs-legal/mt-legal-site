# Law Office App — Research Save Design
**Date:** 2026-03-02
**Status:** Approved

---

## Overview

Add "Save to Documents" functionality to the two existing AI research steps in the attorney portal: Legal Issue Analysis and Legal Authority. Both saves auto-bill 0.5 hrs and place a note in the billing tracker — matching the existing pattern used by the motion draft save.

---

## Section 1: Backend Route

Add one new route: `POST /portal/attorney/research/save-report`

- `report_type`: `"analysis"` (legal issues) or `"authority"` (legal authority memo)
- `username`: client username
- `text`: the report content to save

Saves to `client-files/{username}/documents/Litigation Drafts/`:
- Legal issues analysis → `legal_issues_YYYYMMDD.txt`
- Legal authority memo → `legal_authority_YYYYMMDD.txt`
- Auto-deduplicates filename if it already exists (`_2`, `_3`, etc.)

Billing entry appended to `client.billing_log`:
```json
{
  "date": "2026-03-02",
  "hours": 0.5,
  "note": "AI legal issues analysis saved as \"legal_issues_20260302.txt\".",
  "type": "research_report"
}
```

Calls `_log_activity(username, "time_logged", "0.5 hrs — ...")`.

Returns: `{success, filename, category, billing_entry, total_hours}`

---

## Section 2: Frontend HTML

In `#res-issues-section` (attorney_portal.html ~line 814), add a save row between the issues content block and the "Research Legal Authority" button:
```html
<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem">
  <button ... onclick="saveResearchReport('analysis')">↓ Save to Documents</button>
  <span id="res-analysis-save-result" ...></span>
</div>
```

In `#res-authority-section` (~line 822), add a save row after the authority content block:
```html
<div style="display:flex;align-items:center;gap:.6rem;margin-top:.6rem">
  <button ... onclick="saveResearchReport('authority')">↓ Save to Documents</button>
  <span id="res-authority-save-result" ...></span>
</div>
```

---

## Section 3: Frontend JavaScript

One new JS function `saveResearchReport(reportType)`:
- `"analysis"` → reads from `_resAnalyzedIssues` variable
- `"authority"` → reads from `#res-authority-content` element's `textContent`
- Posts to `/portal/attorney/research/save-report`
- On success: shows green "Saved as X in Y. 0.5 hrs billed." and updates billing display via `populateBillingLog()` + `populateOverview()`
- On error: shows red error text

Update `populateResearch()` to clear both new result spans when switching clients.

---

## Files Changed

| File | Change |
|------|--------|
| `app.py` | Add `research_save_report()` route after `research_save_draft()` |
| `templates/attorney_portal.html` | Add save buttons to HTML; add `saveResearchReport()` JS; update `populateResearch()` clear list |

---

## Non-Goals

- No category selector for these saves (always "Litigation Drafts")
- No inline preview of what will be saved
- No undo/delete from this UI
