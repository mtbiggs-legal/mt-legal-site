// Pending intakes (Incoming Leads panel). Submitted on the public site; the
// attorney approves one to open the client account and email an invitation.
// Built with _el()/textContent only: every field here came from a stranger.

function loadIntakeQueue() {
  const wrap = document.getElementById("intake-queue-wrap");
  if (!wrap) return;
  fetch("/portal/attorney/intakes")
    .then(r => r.json())
    .then(d => renderIntakeQueue(wrap, d.intakes || []))
    .catch(() => wrap.replaceChildren(_el("p", {className: "intake-empty"}, "Could not load intakes.")));
}

function renderIntakeQueue(wrap, rows) {
  const badge = document.getElementById("leads-badge");
  if (!rows.length) {
    wrap.replaceChildren();
    return;
  }
  if (badge) { badge.textContent = String(rows.length); badge.style.display = "inline-block"; }
  const head = _el("h2", {className: "intake-heading"}, "Intakes awaiting review (" + rows.length + ")");
  wrap.replaceChildren(head, ...rows.map(intakeCard));
}

function _intakeRow(label, value) {
  if (!value) return null;
  return _el("div", {className: "intake-row"}, _el("span", {className: "intake-label"}, label), String(value));
}

function intakeCard(it) {
  const urgent = (it.urgent_dates || []).map(u =>
    _el("div", {className: "intake-urgent"}, "⚠ " + u.label + ": " + u.date + " (" + u.days_away + " days)"));
  const status = _el("p", {className: "intake-status"});
  const approve = _el("button", {type: "button", className: "btn btn-primary"}, "Approve & invite");
  const decline = _el("button", {type: "button", className: "btn btn-secondary"}, "Decline");
  approve.addEventListener("click", () => decideIntake(it, "approve", approve, decline, status));
  decline.addEventListener("click", () => {
    if (confirm("Decline this intake? No account is opened and nothing is sent. " +
                "You can download a non-engagement letter afterwards.")) {
      decideIntake(it, "decline", approve, decline, status);
    }
  });
  const rows = [
    _intakeRow("Submitted", (it.submitted_at || "").replace("T", " ")),
    _intakeRow("Email", it.email), _intakeRow("Phone", it.phone),
    _intakeRow("Opposing party", it.opposing_party),
    _intakeRow("Court", [it.court_name, it.county].filter(Boolean).join(", ")),
    _intakeRow("Case no.", it.case_no), _intakeRow("Court date", it.court_date_1),
    _intakeRow("Arrest date", it.arrest_date), _intakeRow("Referral", it.referral_source),
  ].filter(Boolean);
  return _el("div", {className: "card intake-card"},
    _el("div", {className: "intake-name"}, it.full_name || "—"),
    _el("div", {className: "intake-type"}, it.case_type || "Other"),
    ...urgent,
    _el("p", {className: "intake-matter"}, it.matter_description || ""),
    ...rows,
    _el("div", {className: "intake-actions"}, approve, decline),
    status);
}

function decideIntake(it, action, approveBtn, declineBtn, status) {
  approveBtn.disabled = declineBtn.disabled = true;
  status.textContent = action === "approve" ? "Opening the account…" : "Declining…";
  fetch("/portal/attorney/intakes/" + action, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id: it.id}),
  }).then(r => r.json()).then(d => {
    if (d.error) {
      status.textContent = d.error;
      approveBtn.disabled = declineBtn.disabled = false;
      return;
    }
    if (action === "approve") {
      status.textContent = "Account " + d.username + " opened. " +
        (d.invite_sent ? "Invitation emailed." : "Invitation not emailed: resend it from Client Info.") +
        (d.conflict_hits ? " Conflict check found " + d.conflict_hits + " match(es): review before proceeding." : "");
    } else {
      const letter = _el("a", {href: "/portal/attorney/intakes/" + encodeURIComponent(it.id) +
        "/non-engagement-letter", className: "btn btn-secondary"}, "Download non-engagement letter");
      status.replaceChildren("Declined. ", letter);
    }
  }).catch(() => {
    status.textContent = "Request failed.";
    approveBtn.disabled = declineBtn.disabled = false;
  });
}

// Client Info: (re)send the portal invitation. A new link replaces the old one.
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("ci-send-invite");
  if (!btn) return;
  btn.addEventListener("click", () => {
    if (!_currentClient) return;
    if (!confirm("Send a new portal invitation? Any earlier link stops working.")) return;
    const out = document.getElementById("ci-invite-result");
    const link = document.getElementById("ci-invite-link");
    btn.disabled = true;
    out.textContent = "Sending…";
    fetch("/portal/attorney/send-invite", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username: _currentClient.username}),
    }).then(r => r.json()).then(d => {
      btn.disabled = false;
      if (d.error) { out.textContent = d.error; return; }
      out.textContent = d.invite_sent ? "Invitation emailed." :
        "Not emailed (no address or email isn't set up). Copy the link below to send it another way.";
      link.value = d.invite_link || "";
      link.style.display = d.invite_link ? "" : "none";
    }).catch(() => { btn.disabled = false; out.textContent = "Request failed."; });
  });
});

// Insights: recent sign-in activity from the audit log.
function loadSignInActivity() {
  const wrap = document.getElementById("sign-in-activity");
  wrap.textContent = "Loading…";
  fetch("/portal/attorney/sign-in-activity").then(r => r.json()).then(d => {
    const rows = (d.events || []).map(e => _el("tr", {},
      _el("td", {}, (e.timestamp || "").replace("T", " ")),
      _el("td", {}, e.action.replace(/_/g, " ")),
      _el("td", {}, e.actor || "—"),
      _el("td", {}, e.detail || ""),
      _el("td", {}, e.ip || "")));
    if (!rows.length) { wrap.textContent = "No sign-in activity yet."; return; }
    wrap.replaceChildren(_el("table", {className: "dash-table"},
      _el("thead", {}, _el("tr", {}, ["When", "Event", "Who", "Detail", "IP"].map(h => _el("th", {}, h)))),
      _el("tbody", {}, rows)));
  }).catch(() => { wrap.textContent = "Could not load activity."; });
}

// ── Matters (Client Info) ────────────────────────────────────────────────────
function loadMatters(username) {
  const wrap = document.getElementById("matters-list");
  if (!wrap || !username) return;
  fetch("/portal/attorney/matters/" + encodeURIComponent(username))
    .then(r => r.json()).then(d => renderMatters(username, d.matters || []));
}

function renderMatters(username, list) {
  const wrap = document.getElementById("matters-list");
  wrap.replaceChildren(...list.slice().reverse().map(m => {
    const actions = [];
    if (!m.current) actions.push(_el("button", {type: "button", className: "doc-btn",
      onclick: () => matterAction(username, "switch", m.id)}, "Make current"));
    actions.push(m.status === "open"
      ? _el("button", {type: "button", className: "doc-btn",
          onclick: () => { if (confirm("Close this matter?")) matterAction(username, "close", m.id); }}, "Close")
      : _el("button", {type: "button", className: "doc-btn",
          onclick: () => matterAction(username, "reopen", m.id)}, "Reopen"));
    return _el("div", {className: "intake-row matter-row"},
      _el("strong", {}, m.title || "Matter"),
      " · " + (m.case_type || "") + (m.case_no ? " · " + m.case_no : "") +
      " · " + m.status + (m.current ? " (current)" : "") +
      " · opened " + (m.opened_at || "").slice(0, 10) + " ",
      ...actions);
  }));
}

function matterAction(username, action, id) {
  fetch("/portal/attorney/matters/" + action, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username: username, id: id}),
  }).then(r => r.json()).then(d => {
    if (d.error) { alert(d.error); return; }
    if (action === "switch") selectClient(username);     // the panels show the new current matter
    else renderMatters(username, d.matters || []);
  });
}

function openMatter() {
  if (!_currentClient) return;
  const val = id => document.getElementById(id).value.trim();
  const out = document.getElementById("mt-result");
  if (!val("mt-title")) { out.textContent = "Give the matter a title."; return; }
  out.textContent = "Opening…";
  fetch("/portal/attorney/matters/open", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({username: _currentClient.username, title: val("mt-title"),
      case_type: val("mt-case-type"), case_no: val("mt-case-no"), county: val("mt-county"),
      legal_issue: val("mt-issue"),
      opposing_parties: val("mt-opposing").split(/\r?\n/).map(s => s.trim()).filter(Boolean)}),
  }).then(r => r.json()).then(d => {
    if (d.error) { out.textContent = d.error; return; }
    out.replaceChildren(document.createTextNode("Matter opened and made current. "));
    if (d.conflict_hits && d.conflict_hits.length && typeof hitsTable === "function") {
      out.appendChild(_note("⚠ Conflict check matches: review before proceeding.", true));
      out.appendChild(hitsTable(d.conflict_hits));
    }
    selectClient(_currentClient.username);
  });
}
