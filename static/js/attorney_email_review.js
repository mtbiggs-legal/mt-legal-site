// Attorney portal — Inbox tab (email reviewer).
// Relies on _el, _note, _show, _postJSON from attorney_security.js, which loads first.
// XSS rule: email fields are untrusted; they only ever become text nodes.

let _erReviews = [];

function showEmailReview(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-email-review").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  erLoadStatus();
  erLoadList();
}

function _erWhen(iso) {
  if (!iso) return "never";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
}

function erLoadStatus() {
  const out = document.getElementById("er-status");
  const connect = document.getElementById("er-connect");
  fetch("/email-review/status").then(r => r.json()).then(s => {
    connect.style.display = s.connected ? "none" : "";
    if (!s.connected) {
      const why = {
        no_credentials_file: "credentials.json is missing (see docs/EMAIL_REVIEW_SETUP.md).",
        libraries_missing: "Google libraries are not installed.",
      }[s.reason] || "Click Connect Gmail and sign in to the firm mailbox.";
      return _show(out, _el("span", {}, "Gmail not connected. " + why));
    }
    const digest = s.digest_hour >= 0 ? `Morning digest after ${s.digest_hour}:00` : "Digest off";
    _show(out, _el("span", {},
      _el("strong", {}, s.account || "Gmail connected"), " · last check ", _erWhen(s.last_check),
      " · ", s.auto ? "checks hourly while the app runs" : "automatic checks off",
      " · ", digest));
  }).catch(() => _show(out, _note("Could not read the Gmail status.", true)));
}

function erLoadList() {
  fetch("/email-review/list").then(r => r.json()).then(data => {
    _erReviews = data.reviews || [];
    const sel = document.getElementById("er-category");
    if (sel.options.length === 1) {
      Object.entries(data.categories || {}).forEach(([k, v]) =>
        sel.appendChild(_el("option", {value: k}, v)));
    }
    erRender();
    erUpdateBadge();
  }).catch(() => _show(document.getElementById("er-list"), _note("Could not load the inbox.", true)));
}

function erUpdateBadge() {
  const badge = document.getElementById("inbox-badge");
  if (!badge) return;
  const n = _erReviews.filter(r => r.urgent && !r.handled).length;
  badge.textContent = n;
  badge.style.display = n ? "" : "none";
}

function _erCard(r) {
  const deadlines = (r.deadlines || []).map(d =>
    _el("li", {}, _el("strong", {}, d.date || "Date unclear"), " — ", d.description || ""));
  const handled = _el("input", {type: "checkbox", checked: !!r.handled,
                                onchange: e => erSetHandled(r.id, e.target.checked, e.target)});
  return _el("div", {className: "er-item" + (r.urgent && !r.handled ? " er-urgent" : "") + (r.handled ? " er-handled" : "")},
    _el("div", {className: "er-item-head"},
      _el("span", {className: "er-cat er-cat-" + (r.category || "other")}, r.category_label || "Other"),
      r.urgent ? _el("span", {className: "conflict-badge"}, "Urgent") : null,
      r.matched_client ? _el("span", {className: "er-tag", title: "The address is on a client record and Gmail authenticated the sending domain (DMARC). That proves the domain, not the person."}, "Client, domain authenticated") : null,
      r.client_unverified ? _el("span", {className: "er-tag er-tag-warn", title: "The address matches a client, but Gmail could not authenticate the sending domain. It may be forged."}, "Client address, not authenticated") : null,
      _el("span", {className: "er-from"}, r.from_name || r.from_email || r.from || ""),
      _el("span", {className: "er-date"}, r.received_ms ? _erWhen(new Date(r.received_ms).toISOString()) : (r.date || ""))),
    _el("div", {className: "er-subject"}, r.subject || "(no subject)"),
    _el("p", {className: "er-summary"}, r.summary || ""),
    r.urgent && r.urgency_reason ? _el("p", {className: "er-reason"}, "Why urgent: " + r.urgency_reason) : null,
    deadlines.length ? _el("ul", {className: "er-deadlines"}, deadlines) : null,
    r.attachments && r.attachments.length ? _el("p", {className: "er-attach"}, "Attachments: " + r.attachments.join(", ")) : null,
    _el("div", {className: "er-item-foot"},
      _el("a", {href: r.gmail_url, target: "_blank", rel: "noopener"}, "Open in Gmail →"),
      _el("label", {className: "er-check"}, handled, " Handled")));
}

function erRender() {
  const list = document.getElementById("er-list");
  const cat = document.getElementById("er-category").value;
  const urgentOnly = document.getElementById("er-urgent-only").checked;
  const showHandled = document.getElementById("er-show-handled").checked;
  const rows = _erReviews.filter(r =>
    (!cat || r.category === cat) && (!urgentOnly || r.urgent) && (showHandled || !r.handled));
  if (!rows.length) {
    return _show(list, _note(_erReviews.length ? "Nothing matches these filters." : "No reviewed mail yet. Click Check now."));
  }
  _show(list, rows.map(_erCard));
}

function erSetHandled(id, handled, box) {
  box.disabled = true;
  _postJSON("/email-review/handled", {id, handled}).then(res => {
    box.disabled = false;
    if (res.error) { box.checked = !handled; return alert(res.error); }
    const r = _erReviews.find(x => x.id === id);
    if (r) r.handled = handled;
    erRender();
    erUpdateBadge();
  }).catch(() => { box.disabled = false; box.checked = !handled; });
}

function erRun() {
  const btn = document.getElementById("er-run");
  const msg = document.getElementById("er-message");
  btn.disabled = true;
  _show(msg, _note("Checking the inbox… this can take a minute."));
  _postJSON("/email-review/run", {}).then(res => {
    btn.disabled = false;
    if (res.error) return _show(msg, _note(res.error, true));
    let text = `Reviewed ${res.reviewed} new email(s), ${res.urgent} urgent.`;
    if (res.failed) text += ` ${res.failed} will be retried next check.`;
    if (res.remaining) text += ` ${res.remaining} more waiting; click Check now again.`;
    _show(msg, _note(text));
    erLoadStatus();
    erLoadList();
  }).catch(() => { btn.disabled = false; _show(msg, _note("The check failed.", true)); });
}

function erDigest() {
  const btn = document.getElementById("er-digest");
  const msg = document.getElementById("er-message");
  btn.disabled = true;
  _postJSON("/email-review/digest", {}).then(res => {
    btn.disabled = false;
    if (res.error) return _show(msg, _note(res.error, true));
    _show(msg, _note(res.sent ? `Digest sent to the firm mailbox: ${res.subject}` : res.reason));
    erLoadStatus();
  }).catch(() => { btn.disabled = false; _show(msg, _note("The digest could not be sent.", true)); });
}

document.addEventListener("DOMContentLoaded", () => {
  if (!document.getElementById("tab-email-review")) return;
  document.getElementById("er-run").addEventListener("click", erRun);
  document.getElementById("er-digest").addEventListener("click", erDigest);
  ["er-category", "er-urgent-only", "er-show-handled"].forEach(id =>
    document.getElementById(id).addEventListener("change", erRender));
  erLoadList();   // fills the sidebar's urgent badge
});
