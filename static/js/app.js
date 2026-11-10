/* Law Office App — client-side JS */

// ── Utility: show spinner ──────────────────────────────────────────────────
function showSpinner(containerId, message) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `<div class="spinner-wrap"><div class="spinner"></div><span>${message || "Please wait…"}</span></div>`;
  el.style.display = "block";
}

// ── Utility: show error ────────────────────────────────────────────────────
function showError(containerId, message) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `<div class="alert alert-urgent"><span class="alert-icon">⚠</span><div><div class="alert-title">Error</div>${escapeHtml(message)}</div></div>`;
  el.style.display = "block";
}

// ── Utility: escape HTML ───────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");   // also safe inside single-quoted attributes (data-on-*)
}

// ── Utility: render model-generated HTML safely ────────────────────────────
// The research memos come back as HTML by design, but they are produced from
// text a visitor typed, so they are not trusted. Parse them detached from the
// page and keep only a formatting allowlist before anything is inserted.
var SAFE_TAGS = [
  "H1","H2","H3","H4","H5","H6","P","BR","HR","DIV","SPAN",
  "UL","OL","LI","STRONG","B","EM","I","U","SMALL","BLOCKQUOTE",
  "TABLE","THEAD","TBODY","TFOOT","TR","TH","TD","CODE","PRE","A"
];

function _sanitizeNode(node) {
  var children = Array.prototype.slice.call(node.childNodes);
  children.forEach(function (child) {
    if (child.nodeType === 3) return;                 // text is always fine
    if (child.nodeType !== 1) { child.remove(); return; }

    if (SAFE_TAGS.indexOf(child.tagName) === -1) {
      // Drop the tag but keep any readable text inside it.
      var text = document.createTextNode(child.textContent || "");
      child.replaceWith(text);
      return;
    }

    Array.prototype.slice.call(child.attributes).forEach(function (attr) {
      var name  = attr.name.toLowerCase();
      var value = (attr.value || "").trim();
      var isSafeLink =
        child.tagName === "A" && name === "href" && /^(https?:|mailto:)/i.test(value);
      // Inline styles and event handlers are the usual injection routes.
      if (!isSafeLink) child.removeAttribute(attr.name);
    });

    if (child.tagName === "A" && child.getAttribute("href")) {
      child.setAttribute("target", "_blank");
      child.setAttribute("rel", "noopener noreferrer");
    }

    _sanitizeNode(child);
  });
  return node;
}

// Replace an element's contents with sanitized model HTML.
function renderSafeHtml(el, dirtyHtml) {
  if (!el) return;
  var parsed = new DOMParser().parseFromString(String(dirtyHtml || ""), "text/html");
  _sanitizeNode(parsed.body);
  el.replaceChildren.apply(el, Array.prototype.slice.call(parsed.body.childNodes));
}

// ── Print / Save as PDF ────────────────────────────────────────────────────
function printPage() {
  window.print();
}

// ── Copy to Clipboard ──────────────────────────────────────────────────────
function copyToClipboard(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.tagName === "TEXTAREA" ? el.value : el.innerText;
  navigator.clipboard.writeText(text).then(function () {
    const btn = document.querySelector('[data-on-click*="copyToClipboard"]');
    if (btn) {
      const original = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(function () { btn.textContent = original; }, 2000);
    }
  }).catch(function () {
    // Fallback for older browsers
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  });
}

// ── Tool 1: Client Intake ──────────────────────────────────────────────────
function submitIntake(event) {
  event.preventDefault();
  const form = document.getElementById("intake-form");
  const resultEl = document.getElementById("intake-result");

  // Capture e-signature metadata
  var esigTimestampEl = document.getElementById("esig-timestamp");
  var esigConsent     = document.getElementById("esig-consent");
  var esigTimestamp   = esigTimestampEl ? esigTimestampEl.textContent : "";

  const data = {
    full_name:          form.full_name.value.trim(),
    dob:                form.dob ? form.dob.value : "",
    phone:              form.phone.value.trim(),
    email:              form.email.value.trim(),
    case_type:          form.case_type.value,
    matter_description: form.matter_description.value.trim(),
    referral_source:    form.referral_source.value.trim(),
    case_no:            form.case_no ? form.case_no.value.trim() : "",
    county:             form.county ? form.county.value.trim() : "",
    court_name:         form.court_name ? form.court_name.value.trim() : "",
    arrest_date:        form.arrest_date ? form.arrest_date.value : "",
    court_date_1:       form.court_date_1 ? form.court_date_1.value : "",
    esignature: {
      signed:    !!(esigConsent && esigConsent.checked),
      signer:    form.full_name.value.trim(),
      timestamp: esigTimestamp || new Date().toISOString(),
      ip_note:   "Captured via web intake form — IP not logged client-side",
    },
  };

  if (!data.full_name) { showError("intake-result", "Full name is required."); return; }
  if (!data.matter_description) { showError("intake-result", "Matter description is required."); return; }

  showSpinner("intake-result", "Saving intake record… this may take a moment.");

  fetch("/intake/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.error) { showError("intake-result", res.error); return; }
      renderIntakeSummary(res, data, resultEl);
    })
    .catch(function (err) { showError("intake-result", "Network error: " + err.message); });
}

function renderIntakeSummary(res, r, el) {
  // `r` is what the visitor typed; the server returns no account or file details.
  let urgentHtml = "";
  if (res.urgent_dates && res.urgent_dates.length > 0) {
    const items = res.urgent_dates.map(function (d) {
      const days = Number(d.days_away) || 0;
      return `<li><strong>${escapeHtml(d.label)}:</strong> ${escapeHtml(d.date)} (${days} day${days === 1 ? "" : "s"} away)</li>`;
    }).join("");
    urgentHtml = `
      <div class="alert alert-urgent">
        <span class="alert-icon">🚨</span>
        <div>
          <div class="alert-title">Upcoming date: please call us</div>
          <ul style="margin-top:.4rem;padding-left:1.2rem">${items}</ul>
        </div>
      </div>`;
  }

  function dateRow(label, val) {
    if (!val) return "";
    return `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(val)}</td></tr>`;
  }

  el.innerHTML = `
    <div class="card" id="intake-summary-card">
      <h2 style="margin:0 0 1rem">Intake Received</h2>
      ${urgentHtml}
      <div class="alert alert-success" style="margin-bottom:1.25rem">
        <span class="alert-icon">✓</span>
        <div>Thank you. The attorney will review your information and contact you.
          ${res.email_sent ? "A confirmation has been emailed to you." : ""}
          Sending this form does not by itself create an attorney-client relationship.</div>
      </div>
      <table class="summary-table">
        <tr><th>Full Name</th><td>${escapeHtml(r.full_name)}</td></tr>
        <tr><th>Phone</th><td>${escapeHtml(r.phone || "—")}</td></tr>
        <tr><th>Email</th><td>${escapeHtml(r.email || "—")}</td></tr>
        <tr><th>Case Type</th><td>${escapeHtml(r.case_type || "Other")}</td></tr>
        <tr><th>Matter Description</th><td style="white-space:pre-wrap">${escapeHtml(r.matter_description)}</td></tr>
        ${dateRow("Arrest Date", r.arrest_date)}
        ${dateRow("Court Date", r.court_date_1)}
      </table>
      <div class="btn-group no-print">
        <button class="btn btn-print" data-action="print">🖨 Print / Save as PDF</button>
        <button class="btn btn-secondary" data-action="reset-intake">New Intake</button>
      </div>
    </div>`;
  el.querySelector('[data-action="print"]').addEventListener("click", printPage);
  el.querySelector('[data-action="reset-intake"]').addEventListener("click", resetIntake);

  el.style.display = "block";
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetIntake() {
  document.getElementById("intake-form").reset();
  const el = document.getElementById("intake-result");
  el.innerHTML = "";
  el.style.display = "none";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ── Research query panel mobile collapse ──────────────────────────────────
function toggleQueryPanel() {
  var panel = document.getElementById("query-panel");
  var btn   = document.getElementById("query-toggle-btn");
  if (!panel) return;
  var collapsed = panel.classList.toggle("query-panel-collapsed");
  if (btn) btn.textContent = collapsed ? "▲ Expand" : "▼ Collapse";
}

// ── Tool 2: Legal Research ─────────────────────────────────────────────────
function submitResearch(event) {
  event.preventDefault();
  const question = document.getElementById("research-question").value.trim();
  const caseType = document.getElementById("research-case-type").value;
  const resultEl = document.getElementById("research-result");

  if (!question) { showError("research-result", "Please enter a research question."); return; }
  if (_checkUsageGate("research")) return;

  showSpinner("research-result", "Researching… this may take 15–30 seconds.");

  fetch("/research/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: question, case_type: caseType }),
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.error) { showError("research-result", res.error); return; }
      _recordUsage("research");

      resultEl.replaceChildren();

      var memo = document.createElement("div");
      memo.className = "memo-output";
      memo.id = "memo-content";
      renderSafeHtml(memo, res.memo);

      var actions = document.createElement("div");
      actions.className = "btn-group no-print";
      var dlBtn = document.createElement("button");
      dlBtn.className = "btn btn-print";
      dlBtn.textContent = "🖨 Download Research Report";
      dlBtn.addEventListener("click", printPage);
      actions.appendChild(dlBtn);

      resultEl.appendChild(memo);
      resultEl.appendChild(actions);
      resultEl.style.display = "block";
      // On mobile: auto-collapse the query panel so results are front and center
      if (window.innerWidth <= 800) {
        var qp  = document.getElementById("query-panel");
        var btn = document.getElementById("query-toggle-btn");
        if (qp && !qp.classList.contains("query-panel-collapsed")) {
          qp.classList.add("query-panel-collapsed");
          if (btn) btn.textContent = "▲ Expand";
        }
      }
      resultEl.scrollIntoView({ behavior: "smooth", block: "start" });
    })
    .catch(function (err) { showError("research-result", "Network error: " + err.message); });
}

// ── Consultation CTA Modal ─────────────────────────────────────────────────
function showConsultModal(title, body, dismissLabel) {
  document.getElementById("consult-title").textContent = title;
  document.getElementById("consult-body").textContent  = body;
  document.getElementById("consult-dismiss").textContent = dismissLabel || "Continue Reviewing";
  document.getElementById("consultation-modal").style.display = "flex";
}
function closeConsultModal() {
  document.getElementById("consultation-modal").style.display = "none";
}
function handleConsultOverlay(e) {
  if (e.target === document.getElementById("consultation-modal")) closeConsultModal();
}

// ── Tool 4: Google Calendar ────────────────────────────────────────────────
var _scheduleClientData = {};

function openScheduleModalFromBtn(btn) {
  openScheduleModal(btn.dataset.client, btn.dataset.matter, btn.dataset.casetype);
}

function openScheduleModal(clientName, matter, caseType) {
  _scheduleClientData = { client_name: clientName, matter_description: matter, case_type: caseType };
  document.getElementById("modal-client-display").textContent = "Client: " + clientName;
  // Default to today's date and 9:00 AM
  var today = new Date().toISOString().split("T")[0];
  document.getElementById("meeting-date").value = today;
  document.getElementById("meeting-time").value = "09:00";
  document.getElementById("meeting-duration").value = "60";
  document.getElementById("meeting-notes").value = "";
  document.getElementById("calendar-modal-result").innerHTML = "";
  document.getElementById("calendar-modal").style.display = "flex";
}

function closeScheduleModal() {
  document.getElementById("calendar-modal").style.display = "none";
}

function handleModalOverlayClick(event) {
  if (event.target === document.getElementById("calendar-modal")) {
    closeScheduleModal();
  }
}

function submitScheduleMeeting() {
  var resultEl = document.getElementById("calendar-modal-result");
  var date     = document.getElementById("meeting-date").value;
  var time     = document.getElementById("meeting-time").value;
  var duration = document.getElementById("meeting-duration").value;
  var notes    = document.getElementById("meeting-notes").value.trim();

  if (!date || !time) {
    resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.75rem"><span class="alert-icon">⚠</span><div>Please select a date and time.</div></div>';
    return;
  }

  resultEl.innerHTML = '<div class="spinner-wrap" style="margin-top:.75rem"><div class="spinner"></div><span>Creating calendar event…</span></div>';

  fetch("/calendar/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({}, _scheduleClientData, {
      date: date, time: time, duration: parseInt(duration), notes: notes,
    })),
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.error) {
        resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.75rem"><span class="alert-icon">⚠</span><div>' + escapeHtml(res.error) + '</div></div>';
        return;
      }
      resultEl.innerHTML = '<div class="alert alert-success" style="margin-top:.75rem"><span class="alert-icon">✓</span><div><div class="alert-title">Call scheduled!</div>Added to your calendar successfully.</div></div>';
    })
    .catch(function (err) {
      resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.75rem"><span class="alert-icon">⚠</span><div>Network error: ' + escapeHtml(err.message) + '</div></div>';
    });
}

// Dashboard: check calendar auth status on page load
function loadCalendarStatus() {
  var card = document.getElementById("calendar-status-body");
  if (!card) return;
  fetch("/calendar/status")
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.authorized) {
        card.innerHTML = '<div class="alert alert-success" style="margin-bottom:0"><span class="alert-icon">✓</span><div><strong>Connected</strong> — Google Calendar is authorized. Schedule Meeting buttons are ready.</div></div>';
      } else {
        var msg = {
          "libraries_missing":  "Google packages not installed. Run <code>pip install -r requirements.txt</code> then restart the app.",
          "no_credentials_file":"<code>credentials.json</code> not found. See <strong>GOOGLE_CALENDAR_SETUP.md</strong> in the app folder for how to create it.",
          "not_authorized":     "credentials.json found but not yet authorized.",
          "token_invalid":      "Authorization expired.",
        }[res.reason] || "Not connected.";
        card.innerHTML = '<div style="font-family:Arial,sans-serif;font-size:.92rem">' +
          '<p style="color:var(--gray-4);margin-bottom:1rem">' + msg + '</p>' +
          '<a href="/calendar/authorize" class="btn btn-calendar" style="text-decoration:none">Authorize Google Calendar →</a>' +
          '<p style="margin-top:.85rem;font-size:.8rem;color:var(--gray-3)">See <strong>GOOGLE_CALENDAR_SETUP.md</strong> in the app folder for step-by-step instructions.</p>' +
          '</div>';
      }
    })
    .catch(function () {
      card.innerHTML = '<p style="font-family:Arial,sans-serif;color:var(--gray-3);font-size:.9rem">Could not check calendar status.</p>';
    });
}

if (document.getElementById("calendar-status-body")) {
  loadCalendarStatus();
}

// ── Follow-Up Form ─────────────────────────────────────────────────────────
function submitFollowUp(event) {
  event.preventDefault();
  var name     = document.getElementById("fu-name").value.trim();
  var phone    = document.getElementById("fu-phone").value.trim();
  var caseType = document.getElementById("fu-case-type").value;
  var message  = document.getElementById("fu-message").value.trim();
  var resultEl = document.getElementById("follow-up-result");

  if (!name || !phone) {
    resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.5rem"><span class="alert-icon">⚠</span><div>Please provide your name and phone number.</div></div>';
    return;
  }

  resultEl.innerHTML = '<div class="spinner-wrap" style="margin-top:.5rem"><div class="spinner"></div><span>Sending…</span></div>';

  fetch("/follow-up/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name, phone: phone, case_type: caseType, message: message }),
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.error) {
        resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.5rem"><span class="alert-icon">⚠</span><div>' + escapeHtml(res.error) + '</div></div>';
        return;
      }
      resultEl.innerHTML = '<div class="alert alert-success" style="margin-top:.5rem"><span class="alert-icon">✓</span><div><strong>Request received!</strong> Redirecting you to complete your intake…</div></div>';
      document.getElementById("follow-up-form").reset();
      setTimeout(function() { window.location.href = "/intake"; }, 1800);
    })
    .catch(function (err) {
      resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.5rem"><span class="alert-icon">⚠</span><div>Network error: ' + escapeHtml(err.message) + '</div></div>';
    });
}

// ── Forced Intake Gate Modal ───────────────────────────────────────────────
var _forcedIntakeSource = "";
var _forcedIntakeIsGate = false;  // true when gate fired by usage limit (not download btn)

// Returns true (and shows the modal) if the user has hit the 3-use limit.
// Only checks here — the counter is incremented by _recordUsage() once a
// request actually succeeds, so network errors don't burn a visitor's free uses.
function _checkUsageGate(page) {
  if (localStorage.getItem("el_signed_up")) return false;
  var uses = parseInt(localStorage.getItem("el_" + page + "_uses") || "0", 10);
  if (uses >= 3) {
    _forcedIntakeIsGate = true;
    openForcedIntakeModal(page);
    return true;
  }
  return false;
}

function _recordUsage(page) {
  if (localStorage.getItem("el_signed_up")) return;
  var key  = "el_" + page + "_uses";
  var uses = parseInt(localStorage.getItem(key) || "0", 10);
  localStorage.setItem(key, uses + 1);
}

function openForcedIntakeModal(source) {
  _forcedIntakeSource = source || "";
  document.getElementById("fi-name").value = "";
  document.getElementById("fi-phone").value = "";
  document.getElementById("fi-email").value = "";
  document.getElementById("fi-case-type").value = "";
  document.getElementById("forced-intake-result").replaceChildren();
  document.getElementById("forced-intake-modal").style.display = "flex";
}

function closeForcedIntakeModal() {
  _forcedIntakeIsGate = false;
  document.getElementById("forced-intake-modal").style.display = "none";
}

function handleForcedIntakeOverlay(e) {
  if (e.target === document.getElementById("forced-intake-modal")) closeForcedIntakeModal();
}

function submitForcedIntake() {
  var name     = document.getElementById("fi-name").value.trim();
  var phone    = document.getElementById("fi-phone").value.trim();
  var email    = document.getElementById("fi-email").value.trim();
  var caseType = document.getElementById("fi-case-type").value;
  var resultEl = document.getElementById("forced-intake-result");

  if (!name || !phone) {
    resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.5rem"><span class="alert-icon">⚠</span><div>Please provide your name and phone number.</div></div>';
    return;
  }

  resultEl.innerHTML = '<div class="spinner-wrap" style="margin-top:.5rem"><div class="spinner"></div><span>Saving…</span></div>';

  fetch("/capture/lead", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name, phone: phone, email: email, case_type: caseType, source: _forcedIntakeSource }),
  })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (res.error) {
        resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.5rem"><span class="alert-icon">⚠</span><div>' + escapeHtml(res.error) + '</div></div>';
        return;
      }
      localStorage.setItem("el_signed_up", "true");
      document.getElementById("forced-intake-modal").style.display = "none";
      if (_forcedIntakeIsGate) {
        _forcedIntakeIsGate = false;
        // Gate unlocked — user clicks Search/Generate again to continue
      } else {
        window.print();
      }
    })
    .catch(function (err) {
      resultEl.innerHTML = '<div class="alert alert-urgent" style="margin-top:.5rem"><span class="alert-icon">⚠</span><div>Network error: ' + escapeHtml(err.message) + '</div></div>';
    });
}

// ESC closes the intake modal. Trapping visitors in a dialog they cannot
// dismiss loses more prospects than the captured details are worth.
document.addEventListener("keydown", function (e) {
  var modal = document.getElementById("forced-intake-modal");
  if (e.key === "Escape" && modal && modal.style.display !== "none") {
    closeForcedIntakeModal();
  }
});

// ── Tool 3: Document Drafting ──────────────────────────────────────────────
// Map a template name to its field-block id.
// Parentheses are dropped, not hyphenated — "Eviction Notice (Detainer Warrant)"
// has the id "fields-eviction-notice-detainer-warrant".
function templateFieldsId(templateName) {
  return "fields-" + String(templateName)
    .toLowerCase()
    .replace(/[()]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function onTemplateChange() {
  const tmpl = document.getElementById("template-type").value;
  document.querySelectorAll(".template-fields").forEach(function (s) {
    s.style.display = "none";
  });
  if (tmpl) {
    const target = document.getElementById(templateFieldsId(tmpl));
    if (target) target.style.display = "grid";
  }
}

// Save a draft to Google Drive as a Google Doc and open it in a new tab.
// The tab is opened before the request so popup blockers allow it; statusEl
// (optional) shows progress and errors as text.
function openAsGoogleDoc(title, content, username, statusEl) {
  if (!content) return;
  var win = window.open("", "_blank");
  if (win) { win.opener = null; win.document.title = "Creating Google Doc…"; }
  function status(msg, isError) {
    if (!statusEl) return;
    statusEl.style.color = isError ? "var(--red, #c0392b)" : "";
    statusEl.textContent = msg;
  }
  status("Creating Google Doc…", false);
  fetch("/drafting/google-doc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title, content: content, username: username || "" }),
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.success) {
        if (win) win.close();
        status(d.error || "Could not create the Google Doc.", true);
        return;
      }
      if (win) win.location.href = d.url;
      else window.open(d.url, "_blank", "noopener");
      status("Saved to Google Drive as “" + d.title + "”.", false);
    })
    .catch(function (e) {
      if (win) win.close();
      status("Request failed: " + e.message, true);
    });
}

// NOTE: the drafting form's submit handler lives in templates/drafting.html —
// it generates the document, then offers the "Save & Download" claim flow.
// Nothing here should also bind to that form.
