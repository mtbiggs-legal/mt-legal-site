// Live updates for the attorney portal.
//
// Polls /portal/attorney/live (blueprints/live.py) every few seconds while the
// tab is visible, and right after any change this page makes. When a client's
// revision changes, the views showing that client are redrawn in place: the
// open client file, the sidebar, the All Clients table, the dashboard and the
// leads badge. Form fields are only updated when the attorney hasn't edited
// them, so nothing being typed is overwritten.

var LIVE_INTERVAL_MS = 8000;
var _live = { token: "", clients: null, leads: null, timer: null, inflight: false, again: false, stopped: false };

function livePoll() {
  if (_live.stopped) return;
  if (_live.inflight) { _live.again = true; return; }
  _live.inflight = true;
  _liveOriginalFetch("/portal/attorney/live?since=" + encodeURIComponent(_live.token))
    .then(function (r) {
      if (r.status === 401 || r.redirected) { _live.stopped = true; return null; }
      return r.ok ? r.json() : null;
    })
    .then(function (d) { if (d && d.changed) _liveApply(d); if (d) _live.token = d.token; })
    .catch(function () {})
    .finally(function () {
      _live.inflight = false;
      if (_live.again) { _live.again = false; livePoll(); }
    });
}

// Run a poll soon after this page changes something (a save, an upload, an
// assistant confirmation). Several changes in a row collapse into one poll.
var _liveKickTimer = null;
function liveKick() {
  clearTimeout(_liveKickTimer);
  _liveKickTimer = setTimeout(livePoll, 300);
}

function _liveApply(d) {
  var prev = _live.clients;
  var changed = [];
  Object.keys(d.clients).forEach(function (u) {
    if (!prev || !prev[u] || prev[u].rev !== d.clients[u].rev) changed.push(u);
  });
  var removed = prev ? Object.keys(prev).filter(function (u) { return !d.clients[u]; }) : [];
  var leadsChanged = _live.leads !== null && _live.leads !== d.leads;
  var first = prev === null;
  _live.clients = d.clients;
  _live.leads = d.leads;
  if (first) return;                       // the page has just loaded this data itself

  changed.forEach(function (u) { _liveSidebar(d.clients[u]); _liveAllClientsRow(d.clients[u]); });
  removed.forEach(function (u) {
    var b = document.getElementById("cli-" + u);
    if (b) b.remove();
  });
  if (typeof _currentClient !== "undefined" && _currentClient && changed.indexOf(_currentClient.username) >= 0) {
    _liveRefreshClient(_currentClient.username);
  }
  if (changed.length || removed.length) {
    var dash = document.getElementById("atty-dashboard");
    if (dash && dash.classList.contains("active")) _liveBackground(function () { loadDashboard(true); });
  }
  if (leadsChanged) _liveLeads();
}

// ── Open client file ─────────────────────────────────────────────────────────

// Set a form field to the new server value only if the attorney hasn't changed
// it from the old one and isn't typing in it.
function _liveField(id, oldVal, newVal) {
  var el = document.getElementById(id);
  if (!el || el === document.activeElement) return;
  if ((el.value || "") === (oldVal || "")) el.value = newVal || "";
}

function _liveRefreshClient(username) {
  _liveOriginalFetch("/portal/attorney/client/" + encodeURIComponent(username))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (c) {
      if (!c || !_currentClient || _currentClient.username !== username) return;
      var old = _currentClient;
      _currentClient = c;

      renderOverviewStats(c);
      _liveField("ov-case-no", old.case_no, c.case_no);
      _liveField("ov-charges", old.charges, c.charges);
      _liveField("ov-charge-level", old.charge_level, c.charge_level);
      if (typeof _ssCounty !== "undefined" && _ssCounty && _ssCourt &&
          (old.county || "") !== (c.county || "") && _ssCounty.getValue() === (old.county || "")) {
        _ssCounty.setValue(c.county || "");
        _ssCourt.setOptions(c.county ? (TN_COURTS[c.county] || []) : []);
        _ssCourt.setValue(c.court || "");
      }
      if ((old.archived || false) !== (c.archived || false)) {
        var assigned = c.viewer_is_assigned !== false;
        document.getElementById("ov-archive-btn").style.display   = (assigned && !c.archived) ? "" : "none";
        document.getElementById("ov-unarchive-btn").style.display = (assigned && c.archived) ? "" : "none";
        document.getElementById("ov-archive-result").textContent  = c.archived ? "This client file is archived." : "";
      }

      [["ci-name", "client_name"], ["ci-case-type", "case_type"], ["ci-phone", "phone"],
       ["ci-email", "email"], ["ci-court-date", "next_court_date"], ["ci-next-meeting", "next_meeting"],
       ["ci-legal-issue", "legal_issue"], ["ci-drive-url", "google_drive_url"]].forEach(function (p) {
        _liveField(p[0], old[p[1]], c[p[1]]);
      });

      var oldLog = old.billing_log || [], newLog = c.billing_log || [];
      // Compare the entries, not just their count: approving an automatic
      // entry changes it in place.
      if (oldLog.length !== newLog.length || old.hours_billed !== c.hours_billed ||
          JSON.stringify(oldLog) !== JSON.stringify(newLog)) renderBillingLogTable(c);

      var oldMsgs = old.messages || [], newMsgs = c.messages || [];
      if (oldMsgs.length !== newMsgs.length ||
          JSON.stringify(oldMsgs[oldMsgs.length - 1]) !== JSON.stringify(newMsgs[newMsgs.length - 1])) {
        populateMessages(c);
      }

      if (typeof billRender === "function") billRender(c.username, c.billing_summary);
      if (window.felonyRender) felonyRender(c.username, c.felony_checklist, c.discovery_draft);
      if (window.populateCaseDates) populateCaseDates(c);
      var sec = document.getElementById("tab-security");
      if (window.populateSecurity && !(sec && sec.classList.contains("active"))) populateSecurity(c);

      _liveDocuments(username);
      if (window.loadSignatures && JSON.stringify(old.esign_requests || []) !== JSON.stringify(c.esign_requests || [])) {
        _liveBackground(function () { loadSignatures(true); });
      }
      if (window.loadFilings && JSON.stringify(old.filings || []) !== JSON.stringify(c.filings || [])) {
        _liveBackground(function () { loadFilings(true); });
      }
    })
    .catch(function () {});
}

function _liveDocuments(username) {
  if (typeof _docCategory === "undefined") return;
  _liveOriginalFetch("/portal/attorney/documents/" + encodeURIComponent(username))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (d && _currentClient && _currentClient.username === username) {
        renderDocList((d.files || {})[_docCategory] || []);
      }
    })
    .catch(function () {});
}

// ── Lists ────────────────────────────────────────────────────────────────────

function _liveSidebar(s) {
  var btn = document.getElementById("cli-" + s.username);
  if (btn) {
    var label = btn.firstChild;
    if (label && label.nodeType === 3 && label.textContent.trim() !== s.client_name) {
      label.textContent = s.client_name + " ";
      btn.setAttribute("data-name", s.client_name.toLowerCase());
    }
    var flag = btn.querySelector(".conflict-badge");
    if (s.conflict_unresolved && !flag) {
      btn.appendChild(_el("span", { className: "conflict-badge", title: "Unresolved conflict check" }, "Conflict"));
    } else if (!s.conflict_unresolved && flag) {
      flag.remove();
    }
    return;
  }
  if (s.archived) return;
  var list = document.getElementById("client-list");
  if (!list) return;
  var nb = _el("button", { className: "client-list-item", id: "cli-" + s.username }, s.client_name + " ");
  nb.setAttribute("data-name", s.client_name.toLowerCase());
  nb.addEventListener("click", function () { selectClient(s.username); });
  list.insertBefore(nb, list.firstChild);
  if (Array.isArray(window._ALL_CLIENTS_DATA) &&
      !window._ALL_CLIENTS_DATA.some(function (c) { return c.username === s.username; })) {
    window._ALL_CLIENTS_DATA.push({ username: s.username, client_name: s.client_name });
  }
}

function _liveAllClientsRow(s) {
  var row = document.querySelector('#all-clients-tbody .all-clients-row[data-username="' + s.username + '"]');
  if (!row) return;
  function cell(col) { return row.querySelector('td[data-col="' + col + '"]'); }
  var court = s.next_court_date || "";
  var m = court.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  cell("case").textContent    = s.case_no || "—";
  cell("court").textContent   = m ? m[2] + "-" + m[3] + "-" + m[1] : (court || "—");
  cell("hours").textContent   = s.hours_billed || 0;
  cell("balance").textContent = Number(s.amount_due || 0).toFixed(2);
  cell("balance").style.color = s.amount_due > 0 ? "#c0392b" : "var(--navy)";
  cell("contact").textContent = s.last_communication || "—";
  var tds = row.querySelectorAll("td");
  if (tds[6]) tds[6].textContent = s.phone || "—";
  if (tds[7]) tds[7].textContent = s.email || "—";
}

function _liveLeads() {
  _liveOriginalFetch("/portal/attorney/leads-list")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (leads) {
      if (!Array.isArray(leads)) return;
      var badge = document.getElementById("leads-badge");
      if (badge) {
        badge.textContent = leads.length;
        badge.style.display = leads.length ? "inline-block" : "none";
      }
      var panel = document.getElementById("tab-leads");
      if (panel && panel.classList.contains("active")) {
        _liveBackground(function () { loadLeads(document.getElementById("leads-tab-btn")); });
      }
    })
    .catch(function () {});
}

// ── Wiring ───────────────────────────────────────────────────────────────────

// Every request the live code makes on its own is marked X-Live-Refresh, so
// the server doesn't count it as activity for the idle timeout. _liveBg is set
// while calling page functions (loadDashboard, loadLeads) whose fetches start
// synchronously, so theirs are marked too.
var _liveBaseFetch = window.fetch.bind(window);
var _liveBg = false;

function _liveMark(opts) {
  var o = Object.assign({}, opts || {});
  var h = new Headers(o.headers || {});
  h.set("X-Live-Refresh", "1");
  o.headers = h;
  return o;
}

function _liveOriginalFetch(input, opts) { return _liveBaseFetch(input, _liveMark(opts)); }

function _liveBackground(fn) {
  _liveBg = true;
  try { fn(); } finally { _liveBg = false; }
}

// Any change made from this page (POST/PUT/DELETE to our own server) triggers
// an immediate poll, so every other view catches up straight away.
window.fetch = function (input, opts) {
  if (_liveBg) opts = _liveMark(opts);
  var p = _liveBaseFetch(input, opts);
  var method = ((opts && opts.method) || (input && input.method) || "GET").toUpperCase();
  var url = typeof input === "string" ? input : (input && input.url) || "";
  var same = new URL(url, location.href).origin === location.origin;
  if (same && method !== "GET" && method !== "HEAD") {
    p.then(function (r) { if (r.ok) liveKick(); }).catch(function () {});
  }
  return p;
};

function _liveSchedule() {
  clearInterval(_live.timer);
  _live.timer = document.hidden ? null : setInterval(livePoll, LIVE_INTERVAL_MS);
}

document.addEventListener("visibilitychange", function () {
  _liveSchedule();
  if (!document.hidden) livePoll();          // catch up as soon as the tab is back
});

document.addEventListener("DOMContentLoaded", function () {
  livePoll();
  _liveSchedule();
});
