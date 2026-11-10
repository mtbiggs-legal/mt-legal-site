// attorney_client_panels.js: Selected-client panels: overview, client info, court dates, meetings, case details, research, AI summary, time entries, messages.
// Split out of attorney_portal.js; loaded right after it (see attorney_portal.html),
// and like it, defines global functions the templates call.

// ── Populate panels ───────────────────────────────────────────────────────────
function populateOverview(c) {
  renderOverviewStats(c);
  // Case detail fields
  document.getElementById("ov-case-no").value      = c.case_no      || "";
  document.getElementById("ov-charges").value      = c.charges      || "";
  document.getElementById("ov-charge-level").value = c.charge_level || "";
  document.getElementById("ov-save-result").innerHTML = "";
  // County + court searchable selects
  if (_ssCounty && _ssCourt) {
    var savedCounty = c.county || "";
    _ssCounty.setValue(savedCounty);
    var courtOpts = savedCounty ? (TN_COURTS[savedCounty] || []) : [];
    _ssCourt.setOptions(courtOpts);
    _ssCourt.setValue(c.court || "");
  }
  // Archive / restore button visibility
  var isArchived = !!c.archived;
  document.getElementById("ov-archive-btn").style.display   = isArchived ? "none" : "";
  document.getElementById("ov-unarchive-btn").style.display = isArchived ? "" : "none";
  document.getElementById("ov-archive-result").textContent  = isArchived ? "This client file is archived." : "";
}

// The read-only parts of Case Overview (stats, summary, last note). Live
// updates call this on its own so form fields being edited are left alone.
function renderOverviewStats(c) {
  document.getElementById("ov-name").textContent      = c.client_name || c.username;
  document.getElementById("ov-case-type").textContent = c.case_type   || "";
  document.getElementById("ov-hours").textContent     = c.hours_billed || 0;
  document.getElementById("ov-court").textContent     = c.next_court_date    || "TBD";
  document.getElementById("ov-lastcomm").textContent  = c.last_communication || "—";
  document.getElementById("ov-meeting").textContent   = c.next_meeting       || "None scheduled";
  document.getElementById("ov-legal-issue").textContent = c.legal_issue_summary || c.legal_issue || "No summary entered yet.";
  // Last note preview — most recent billing_log entry
  const logs = c.billing_log || [];
  const lastNoteEl = document.getElementById("ov-last-note");
  if (logs.length) {
    const last = logs[logs.length - 1];
    lastNoteEl.innerHTML = `
      <div style="display:flex;gap:.6rem;align-items:flex-start">
        <div style="font-size:1.1rem;flex-shrink:0">📝</div>
        <div>
          <div style="font-size:.76rem;color:var(--gray-3);margin-bottom:.25rem">
            ${escHtml(last.date)}${last.hours ? " &middot; " + last.hours + " hrs" : ""}
          </div>
          <div style="white-space:pre-wrap">${escHtml(last.note)}</div>
        </div>
      </div>`;
  } else {
    lastNoteEl.innerHTML = '<span style="color:var(--gray-3)">No notes yet.</span>';
  }
}

// Navigate to a tab by name, activating the correct sidebar button
function goToTab(name) {
  let targetBtn = null;
  document.querySelectorAll("#atty-tabs .portal-tab-btn").forEach(b => {
    if ((b.getAttribute("data-on-click") || "").includes('"' + name + '"')) targetBtn = b;
  });
  showAttyTab(name, targetBtn);
}

// ── Court date picker ─────────────────────────────────────────────────────────
function openCourtDatePicker() {
  if (!_currentClient) return;
  var inp = document.getElementById("ov-court-date-picker");
  inp.value = _currentClient.next_court_date || "";
  try { inp.showPicker(); } catch(e) { inp.click(); }
}

function saveCourtDateFromPicker(val) {
  if (!_currentClient || !val) return;
  var username = _currentClient.username;
  fetch("/portal/attorney/update-client", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username:        username,
      next_court_date: val,
      client_name:     _currentClient.client_name     || "",
      case_type:       _currentClient.case_type       || "",
      phone:           _currentClient.phone           || "",
      email:           _currentClient.email           || "",
      next_meeting:    _currentClient.next_meeting    || "",
      legal_issue:     _currentClient.legal_issue     || "",
      google_drive_url:_currentClient.google_drive_url|| "",
    }),
  })
  .then(r => r.json())
  .then(d => {
    if (d.success) {
      _currentClient.next_court_date = val;
      document.getElementById("ov-court").textContent = val;
      // also sync the client-info form date field
      var ci = document.getElementById("ci-court-date");
      if (ci) ci.value = val;
      var hint = document.querySelector("#ov-court-card .ov-stat-hint");
      if (hint) {
        hint.textContent = "✓ Saved";
        hint.style.color = "var(--green)";
        setTimeout(() => { hint.textContent = "📅 click to change"; hint.style.color = ""; }, 2500);
      }
    }
  })
  .catch(() => {});
}

// ── Meeting scheduler ────────────────────────────────────────────────────────
function openMeetingModal() {
  if (!_currentClient) return;
  // Pre-fill with today's date and a default time
  const today = new Date().toISOString().split("T")[0];
  document.getElementById("mtg-date").value = today;
  document.getElementById("mtg-time").value = "10:00";
  document.getElementById("mtg-note").value = "";
  document.getElementById("mtg-result").innerHTML = "";
  document.getElementById("meeting-modal").style.display = "flex";
}

function closeMeetingModal(e) {
  if (e && e.target !== document.getElementById("meeting-modal")) return;
  document.getElementById("meeting-modal").style.display = "none";
}

function saveMeeting() {
  if (!_currentClient) return;
  const date = document.getElementById("mtg-date").value;
  const time = document.getElementById("mtg-time").value;
  const note = document.getElementById("mtg-note").value.trim();
  const res  = document.getElementById("mtg-result");
  if (!date || !time) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Please select a date and time.</p>';
    return;
  }
  // Format: "March 10, 2026 at 2:00 PM"
  const dt = new Date(date + "T" + time);
  const dateStr = dt.toLocaleDateString("en-US", {year:"numeric", month:"long", day:"numeric"});
  const timeStr = dt.toLocaleTimeString("en-US", {hour:"numeric", minute:"2-digit"});
  const formatted = dateStr + " at " + timeStr + (note ? " — " + note : "");
  res.innerHTML = '<p style="font-family:Arial,sans-serif;font-size:.88rem;color:var(--gray-3)">Saving…</p>';
  fetch("/portal/attorney/update-client", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      username:         _currentClient.username,
      next_meeting:     formatted,
      client_name:      _currentClient.client_name      || "",
      case_type:        _currentClient.case_type        || "",
      phone:            _currentClient.phone            || "",
      email:            _currentClient.email            || "",
      next_court_date:  _currentClient.next_court_date  || "",
      legal_issue:      _currentClient.legal_issue      || "",
      google_drive_url: _currentClient.google_drive_url || "",
    }),
  }).then(r => r.json()).then(d => {
    if (d.success) {
      _currentClient.next_meeting = formatted;
      populateOverview(_currentClient);
      document.getElementById("ci-next-meeting").value = formatted;
      document.getElementById("meeting-modal").style.display = "none";
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${d.error}</p>`;
    }
  });
}

// ── Save case detail fields (case_no, charges, charge_level) ─────────────────
function saveCaseDetails() {
  if (!_currentClient) return;
  const payload = {
    username:     _currentClient.username,
    case_no:      document.getElementById("ov-case-no").value.trim(),
    charges:      document.getElementById("ov-charges").value.trim(),
    charge_level: document.getElementById("ov-charge-level").value,
    county:       _ssCounty ? _ssCounty.getValue() : (_currentClient.county || ""),
    court:        _ssCourt  ? _ssCourt.getValue()  : (_currentClient.court  || ""),
    // preserve all existing fields
    client_name:      _currentClient.client_name      || "",
    case_type:        _currentClient.case_type        || "",
    phone:            _currentClient.phone            || "",
    email:            _currentClient.email            || "",
    next_court_date:  _currentClient.next_court_date  || "",
    next_meeting:     _currentClient.next_meeting     || "",
    legal_issue:      _currentClient.legal_issue      || "",
    google_drive_url: _currentClient.google_drive_url || "",
  };
  fetch("/portal/attorney/update-client", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    const res = document.getElementById("ov-save-result");
    if (d.success) {
      Object.assign(_currentClient, payload);
      res.innerHTML = '<p style="color:var(--green);font-family:Arial,sans-serif;font-size:.85rem">Case details saved.</p>';
      setTimeout(() => { res.innerHTML = ""; }, 3000);
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.85rem">${d.error}</p>`;
    }
  });
}

function populateClientInfo(c) {
  if (typeof loadMatters === "function") loadMatters(c.username);
  document.getElementById("ci-name").value         = c.client_name      || "";
  document.getElementById("ci-case-type").value    = c.case_type        || "Criminal Defense";
  document.getElementById("ci-phone").value        = c.phone            || "";
  document.getElementById("ci-email").value        = c.email            || "";
  document.getElementById("ci-court-date").value   = c.next_court_date  || "";
  document.getElementById("ci-next-meeting").value = c.next_meeting     || "";
  document.getElementById("ci-legal-issue").value  = c.legal_issue      || "";
  document.getElementById("ci-drive-url").value    = c.google_drive_url || "";
  document.getElementById("ci-result").innerHTML   = "";
}

function _catClass(cat) {
  var m = {
    "Court Appearance": "court", "Research": "research", "Drafting": "drafting",
    "Meeting": "meeting", "Filing": "filing", "Phone/Email": "phone",
    "Negotiation": "negot", "Travel": "travel", "Overhead": "overhead",
    "Intake": "intake", "Witness/Investigation": "research"
  };
  return m[cat] || "";
}

function populateBillingLog(c) {
  renderBillingLogTable(c);
  document.getElementById("be-date").value     = new Date().toISOString().split("T")[0];
  document.getElementById("be-hours").value    = "";
  document.getElementById("be-note").value     = "";
  document.getElementById("be-category").value = "Meeting";
}

// The time-entry table and total, without touching the new-entry form.
function renderBillingLogTable(c) {
  var tbody = document.getElementById("billing-log-tbody");
  var total = document.getElementById("be-total");
  var logs  = c.billing_log || [];
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  if (logs.length) {
    logs.slice().reverse().forEach(function(e) {
      var tr   = document.createElement("tr");
      var tdDt = document.createElement("td"); tdDt.textContent = e.date || "";
      var tdCt = document.createElement("td");
      var cat  = e.category || e.type || "Other";
      var badge = document.createElement("span");
      badge.className = "cat-badge " + _catClass(cat);
      badge.textContent = cat;
      tdCt.appendChild(badge);
      var tdHr = document.createElement("td"); tdHr.textContent = e.hours || 0;
      if (e.pending_review) {
        // Logged automatically: not billed until approved here.
        tdCt.appendChild(document.createTextNode(" "));
        tdCt.appendChild(_el("span", {className: "cat-badge review-badge",
          title: "Logged automatically. Not billed unless you approve it."}, "Needs review"));
        tdCt.appendChild(_el("div", {className: "review-actions"},
          _el("button", {type: "button", className: "doc-btn",
                         onclick: () => reviewTimeEntry(c.username, e.id, true)}, "Approve"),
          _el("button", {type: "button", className: "doc-btn",
                         onclick: () => reviewTimeEntry(c.username, e.id, false)}, "Don't bill")));
      } else if (e.rejected) {
        tdCt.appendChild(document.createTextNode(" "));
        tdCt.appendChild(_el("span", {className: "cat-badge private-badge",
          title: "Logged automatically; you chose not to bill it"}, "Not billed"));
      } else if (e.billable === false) {
        var priv = document.createElement("span");
        priv.className = "cat-badge private-badge";
        priv.title = "Logged under a flat fee: tracked for you, not billed";
        priv.textContent = "Flat fee";
        tdCt.appendChild(document.createTextNode(" "));
        tdCt.appendChild(priv);
      }
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
}

function reviewTimeEntry(username, id, approve) {
  fetch("/portal/attorney/time-entry/review", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username: username, id: id, approve: approve}),
  }).then(r => r.json()).then(d => {
    if (d.error) { alert(d.error); return; }
    if (typeof _liveRefreshClient === "function") _liveRefreshClient(username);
    else selectClient(username);
  });
}

function populateMessages(c) {
  const thread = document.getElementById("atty-message-thread");
  const msgs   = c.messages || [];
  thread.replaceChildren();
  if (!msgs.length) {
    thread.appendChild(_el("p", {
      style: "font-family:Arial,sans-serif;font-size:.9rem;color:var(--gray-3);padding:1rem 0"
    }, "No messages yet."));
    thread.scrollTop = thread.scrollHeight;
    return;
  }
  // m.text is client- or AI-sourced and must never be parsed as HTML — built
  // with _el (DOM nodes + text nodes) rather than innerHTML, same pattern as
  // the rest of this file. See docs/superpowers/specs/2026-10-02-voicemail-summaries-design.md
  // for how this was found (a stored-XSS review ahead of the voicemail feature).
  msgs.forEach(m => {
    const senderLabel = m.from === "attorney" ? "You"
      : m.from === "ai" ? window._FIRM_NAME + " Assistant"
      : (c.client_name || c.username);
    thread.appendChild(_el("div", {},
      _el("div", {className: `message-bubble from-${m.from}`}, m.text),
      _el("div", {
        className: "message-meta",
        style: `text-align:${m.from === "attorney" ? "right" : "left"}`
      }, `${senderLabel} · ${m.date}`)
    ));
  });
  thread.scrollTop = thread.scrollHeight;
}

function populateDocuments(c) {
  // Reset category to first tab
  _docCategory = "Intake";
  document.querySelectorAll(".doc-cat-tab").forEach((b, i) => b.classList.toggle("active", i === 0));
  document.getElementById("doc-drop-label").textContent = "Drop files here for \"Intake\"";
  document.getElementById("doc-list-title").textContent = "Intake";
  loadDocumentList();
  if (window.loadSignatures) loadSignatures();
  if (window.loadFilings) loadFilings();
}

// ── Research tab ───────────────────────────────────────────────────────────────

var _resAnalyzedIssues = "";   // text from analyzeIssues()
var _resSpottedIssues  = "";   // text from issueSpotDocument()

function populateResearch(c) {
  document.getElementById("res-legal-issue").value = c.legal_issue || "";
  // Clear previous results
  _resAnalyzedIssues = "";
  _resSpottedIssues  = "";
  ["res-issues-section","res-authority-section","res-spot-section","res-draft-section"].forEach(id => {
    document.getElementById(id).style.display = "none";
  });
  ["res-analyze-err","res-authority-err","res-spot-err","res-draft-err","res-save-result",
   "res-analysis-save-result","res-authority-save-result"].forEach(id => {
    document.getElementById(id).textContent = "";
  });
  document.getElementById("res-draft-content").value = "";
  // Load document list for the selector
  loadResearchDocuments();
}

function loadResearchDocuments() {
  if (!_currentClient) return;
  const sel = document.getElementById("res-doc-select");
  sel.innerHTML = '<option value="">— Select a document —</option>';
  fetch("/portal/attorney/documents/" + encodeURIComponent(_currentClient.username))
    .then(r => r.json())
    .then(d => {
      Object.entries(d.files).forEach(([cat, files]) => {
        files.forEach(f => {
          const opt = document.createElement("option");
          opt.value = cat + "||" + f.name;
          opt.textContent = "[" + cat + "] " + f.name;
          sel.appendChild(opt);
        });
      });
    });
}

function loadTokenUsage() {
  document.getElementById("tu-error").style.display = "none";
  ["tu-today-total","tu-total-all","tu-total-in","tu-total-out"].forEach(id => {
    document.getElementById(id).textContent = "…";
  });
  fetch("/portal/attorney/token-usage")
    .then(r => r.json())
    .then(d => {
      var todayTok = (d.today_input || 0) + (d.today_output || 0);
      var allTok   = (d.total_input_tokens || 0) + (d.total_output_tokens || 0);
      document.getElementById("tu-today-total").textContent = todayTok.toLocaleString();
      document.getElementById("tu-total-all").textContent   = allTok.toLocaleString();
      document.getElementById("tu-total-in").textContent    = (d.total_input_tokens || 0).toLocaleString();
      document.getElementById("tu-total-out").textContent   = (d.total_output_tokens || 0).toLocaleString();

      var byLabel = d.by_label || {};
      var labels  = Object.keys(byLabel);
      var tbody   = document.getElementById("tu-breakdown-body");
      while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
      if (labels.length > 0) {
        labels.forEach(function(lbl) {
          var entry = byLabel[lbl];
          var row = document.createElement("tr");
          [lbl,
           entry.calls,
           (entry.input  || 0).toLocaleString(),
           (entry.output || 0).toLocaleString(),
           ((entry.input || 0) + (entry.output || 0)).toLocaleString()
          ].forEach(function(val, i) {
            var td = document.createElement("td");
            td.textContent = val;
            td.style.textAlign = i === 0 ? "left" : "right";
            row.appendChild(td);
          });
          tbody.appendChild(row);
        });
        document.getElementById("tu-breakdown").style.display = "block";
      } else {
        document.getElementById("tu-breakdown").style.display = "none";
      }
    })
    .catch(function() {
      ["tu-today-total","tu-total-all","tu-total-in","tu-total-out"].forEach(id => {
        document.getElementById(id).textContent = "—";
      });
      document.getElementById("tu-error").style.display = "block";
    });
}

function _resSetLoading(spinnerId, btnId, loading) {
  document.getElementById(spinnerId).style.display = loading ? "inline" : "none";
  const btn = document.getElementById(btnId);
  if (btn) btn.disabled = loading;
}

function analyzeIssues() {
  const issue = document.getElementById("res-legal-issue").value.trim();
  if (!issue) { document.getElementById("res-analyze-err").textContent = "Please enter a case summary."; return; }
  document.getElementById("res-analyze-err").textContent = "";
  _resSetLoading("res-analyze-spinner", "res-analyze-btn", true);
  fetch("/portal/attorney/research/analyze", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username: _currentClient.username, legal_issue: issue })
  }).then(r => r.json()).then(d => {
    _resSetLoading("res-analyze-spinner", "res-analyze-btn", false);
    if (!d.success) { document.getElementById("res-analyze-err").textContent = d.error || "Error."; return; }
    _resAnalyzedIssues = d.issues;
    document.getElementById("res-issues-content").textContent = d.issues;
    document.getElementById("res-issues-section").style.display = "block";
    document.getElementById("res-authority-section").style.display = "none";
    loadTokenUsage();
  }).catch(e => {
    _resSetLoading("res-analyze-spinner", "res-analyze-btn", false);
    document.getElementById("res-analyze-err").textContent = "Request failed: " + e.message;
  });
}

function findAuthority() {
  if (!_resAnalyzedIssues) { document.getElementById("res-authority-err").textContent = "Analyze issues first."; return; }
  document.getElementById("res-authority-err").textContent = "";
  _resSetLoading("res-authority-spinner", "res-authority-btn", true);
  fetch("/portal/attorney/research/authority", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ issues: _resAnalyzedIssues, case_type: _currentClient.case_type || "Criminal Defense" })
  }).then(r => r.json()).then(d => {
    _resSetLoading("res-authority-spinner", "res-authority-btn", false);
    if (!d.success) { document.getElementById("res-authority-err").textContent = d.error || "Error."; return; }
    document.getElementById("res-authority-content").textContent = d.memo;
    document.getElementById("res-authority-section").style.display = "block";
    loadTokenUsage();
  }).catch(e => {
    _resSetLoading("res-authority-spinner", "res-authority-btn", false);
    document.getElementById("res-authority-err").textContent = "Request failed: " + e.message;
  });
}

function issueSpotDocument() {
  const val = document.getElementById("res-doc-select").value;
  if (!val) { document.getElementById("res-spot-err").textContent = "Select a document first."; return; }
  const [category, filename] = val.split("||");
  document.getElementById("res-spot-err").textContent = "";
  document.getElementById("res-spot-spinner").style.display = "inline";
  fetch("/portal/attorney/research/issue-spot", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username: _currentClient.username, category, filename })
  }).then(r => r.json()).then(d => {
    document.getElementById("res-spot-spinner").style.display = "none";
    if (!d.success) { document.getElementById("res-spot-err").textContent = d.error || "Error."; return; }
    _resSpottedIssues = d.issues;
    document.getElementById("res-spot-content").textContent = d.issues;
    document.getElementById("res-spot-section").style.display = "block";
    loadTokenUsage();
  }).catch(e => {
    document.getElementById("res-spot-spinner").style.display = "none";
    document.getElementById("res-spot-err").textContent = "Request failed: " + e.message;
  });
}

function draftMotion() {
  const issues = (_resSpottedIssues + "\n" + _resAnalyzedIssues).trim();
  if (!issues) { document.getElementById("res-draft-err").textContent = "Run Issue Spot or Analyze Issues first."; return; }
  const motionType = document.getElementById("res-motion-type").value;
  const caseContext = document.getElementById("res-legal-issue").value.trim();
  document.getElementById("res-draft-err").textContent = "";
  _resSetLoading("res-draft-spinner", null, true);
  document.getElementById("res-draft-spinner").style.display = "inline";
  fetch("/portal/attorney/research/draft", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ motion_type: motionType, issues, case_context: caseContext, username: _currentClient.username })
  }).then(r => r.json()).then(d => {
    document.getElementById("res-draft-spinner").style.display = "none";
    if (!d.success) { document.getElementById("res-draft-err").textContent = d.error || "Error."; return; }
    document.getElementById("res-draft-content").value = d.draft;
    document.getElementById("res-draft-section").style.display = "block";
    document.getElementById("res-save-result").textContent = "";
    loadTokenUsage();
  }).catch(e => {
    document.getElementById("res-draft-spinner").style.display = "none";
    document.getElementById("res-draft-err").textContent = "Request failed: " + e.message;
  });
}

function saveResearchDraft() {
  const draft = document.getElementById("res-draft-content").value.trim();
  if (!draft || !_currentClient) return;
  const motionType = document.getElementById("res-motion-type").value;
  const category   = document.getElementById("res-save-cat").value;
  const ts = new Date().toISOString().slice(0,10).replace(/-/g,"");
  const filename = motionType.toLowerCase().replace(/[^a-z0-9]+/g,"_") + "_" + ts + ".txt";
  const resEl = document.getElementById("res-save-result");
  resEl.textContent = "Saving…";
  fetch("/portal/attorney/research/save-draft", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username: _currentClient.username,
      category, draft, filename, motion_type: motionType
    })
  }).then(r => r.json()).then(d => {
    if (!d.success) { resEl.style.color = "var(--red)"; resEl.textContent = d.error || "Save failed."; return; }
    resEl.style.color = "var(--green)";
    resEl.textContent = "Saved as \"" + d.filename + "\" in " + d.category + ".";
    // Update billing log with auto-entry
    if (d.billing_entry && _currentClient) {
      _currentClient.billing_log = _currentClient.billing_log || [];
      _currentClient.billing_log.push(d.billing_entry);
      if (d.total_hours !== null) _currentClient.hours_billed = d.total_hours;
      populateBillingLog(_currentClient);
      populateOverview(_currentClient);
    }
    // Refresh documents so new file appears
    loadResearchDocuments();
  }).catch(e => {
    resEl.style.color = "var(--red)";
    resEl.textContent = "Request failed: " + e.message;
  });
}

function openResearchDraftAsGoogleDoc() {
  const draft = document.getElementById("res-draft-content").value.trim();
  if (!draft || !_currentClient) return;
  openAsGoogleDoc(document.getElementById("res-motion-type").value, draft,
                  _currentClient.username, document.getElementById("res-save-result"));
}

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

// ── Generate AI legal issue summary ───────────────────────────────────────────
function generateLegalSummary() {
  if (!_currentClient) return;
  var btn = document.getElementById("gen-summary-btn");
  var el  = document.getElementById("ov-legal-issue");
  btn.disabled = true;
  btn.textContent = "Generating…";
  fetch("/portal/attorney/generate-summary", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username: _currentClient.username })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    btn.disabled = false;
    btn.textContent = "⚡ Generate AI Summary";
    if (d.success) {
      el.textContent = d.summary;
      _currentClient.legal_issue_summary = d.summary;
    } else {
      el.textContent = d.error || "Error generating summary.";
    }
  })
  .catch(function() {
    btn.disabled = false;
    btn.textContent = "⚡ Generate AI Summary";
    el.textContent = "Network error.";
  });
}

// ── Save client info ──────────────────────────────────────────────────────────
function saveClientInfo() {
  if (!_currentClient) return;
  const payload = {
    username:        _currentClient.username,
    client_name:     document.getElementById("ci-name").value,
    case_type:       document.getElementById("ci-case-type").value,
    phone:           document.getElementById("ci-phone").value,
    email:           document.getElementById("ci-email").value,
    next_court_date: document.getElementById("ci-court-date").value,
    next_meeting:    document.getElementById("ci-next-meeting").value,
    legal_issue:     document.getElementById("ci-legal-issue").value,
    google_drive_url:document.getElementById("ci-drive-url").value,
  };
  fetch("/portal/attorney/update-client", {
    method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)
  }).then(r => r.json()).then(d => {
    const res = document.getElementById("ci-result");
    if (d.success) {
      Object.assign(_currentClient, payload);
      populateOverview(_currentClient);
      populateDocuments(_currentClient);
      // refresh sidebar label
      const btn = document.getElementById("cli-" + _currentClient.username);
      if (btn) btn.textContent = payload.client_name || _currentClient.username;
      let saveMsg = "Saved.";
      if (d.intake_pdf) saveMsg += ' Intake PDF \u201c' + d.intake_pdf + '\u201d saved to Documents.';
      res.innerHTML = '<p style="color:var(--green);font-family:Arial,sans-serif;font-size:.88rem">' + saveMsg + '</p>';
      setTimeout(() => { res.innerHTML = ""; }, 5000);
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${d.error}</p>`;
    }
  });
}

// ── Log billing entry ─────────────────────────────────────────────────────────
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
  }).then(r => r.json()).then(d => {
    if (d.success) {
      _currentClient.billing_log = _currentClient.billing_log || [];
      _currentClient.billing_log.push(d.entry);
      _currentClient.hours_billed = d.total_hours;
      populateBillingLog(_currentClient);
      populateOverview(_currentClient);
      if (d.billing_summary) _currentClient.billing_summary = d.billing_summary;
      if (window.populateBilling) populateBilling(_currentClient);
      var p = document.createElement("p"); p.style.cssText = "color:var(--green);font-family:Arial,sans-serif;font-size:.88rem"; p.textContent = "Entry saved \u2014 Total: " + d.total_hours + " hrs"; res.textContent = ""; res.appendChild(p);
      setTimeout(() => { res.textContent = ""; }, 4000);
    } else {
      var ep = document.createElement("p"); ep.style.cssText = "color:var(--red);font-family:Arial,sans-serif;font-size:.88rem"; ep.textContent = d.error || "Error."; res.textContent = ""; res.appendChild(ep);
    }
  });
}

// ── Send reply ────────────────────────────────────────────────────────────────
function sendReply() {
  if (!_currentClient) return;
  const text = document.getElementById("atty-reply-text").value.trim();
  const res  = document.getElementById("atty-reply-result");
  if (!text) { res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Enter a reply.</p>'; return; }
  fetch("/portal/attorney/reply", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ username: _currentClient.username, text })
  }).then(r => r.json()).then(d => {
    if (d.success) {
      const now = new Date().toLocaleDateString("en-US", { year:"numeric", month:"2-digit", day:"2-digit" });
      _currentClient.messages = _currentClient.messages || [];
      _currentClient.messages.push({ from:"attorney", date: now, text });
      populateMessages(_currentClient);
      document.getElementById("atty-reply-text").value = "";
      res.innerHTML = '<p style="color:var(--green);font-family:Arial,sans-serif;font-size:.88rem">Reply sent.</p>';
      setTimeout(() => { res.innerHTML = ""; }, 3000);
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${d.error}</p>`;
    }
  });
}
