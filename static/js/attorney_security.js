// Attorney portal — parties, conflict checks, co-counsel, access history,
// and the firm-wide Conflict Check tool.
// Relies on attorney_portal.html globals: _currentClient, _ALL_CLIENTS_DATA, _ATTORNEYS.
// XSS rule: every element is built with _el(); untrusted values only ever
// become text nodes or input .value. No HTML strings, no inline handlers.

// props are always literals written in this file — never pass data as props
// (any "on*" key becomes an event listener).
function _el(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([k, v]) => {
    if (k === "style") node.style.cssText = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node[k] = v;
  });
  children.flat(Infinity).forEach(c => {
    if (c === null || c === undefined || c === false) return;
    node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  });
  return node;
}

function _postJSON(url, body) {
  return fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  }).then(r => r.json());
}

function _note(text, isError) {
  return _el("p", {className: "sec-note" + (isError ? " error" : "")}, text);
}

function _show(container, ...nodes) {
  container.replaceChildren(...nodes.flat(Infinity).filter(n => n !== null && n !== undefined && n !== false));
}

function _stale(u) {
  return !_currentClient || _currentClient.username !== u;
}

function _busy(btns, on) {
  [].concat(btns).forEach(b => { if (b) b.disabled = on; });
}

function _badge(text) {
  return _el("span", {className: "conflict-badge"}, text);
}

function _table(headers, rows) {
  return _el("div", {style: "overflow-x:auto"},
    _el("table", {className: "sec-table"},
      _el("thead", {}, _el("tr", {}, headers.map(h => _el("th", {}, h)))),
      _el("tbody", {}, rows.map(cells => _el("tr", {}, cells.map(c => _el("td", {}, c)))))));
}

function hitsTable(hits) {
  if (!hits || !hits.length) return _note("No matches.");
  return _table(
    ["Level", "Searched", "Matched", "Source", "Matter", "Attorney"],
    hits.map(h => [
      [h.level === "likely" ? _el("strong", {}, "Likely") : "Possible",
       h.adverse ? [" ", _badge("Adverse")] : null],
      h.searched_name || "",
      (h.matched_name || "") + (h.relationship ? ` (${h.relationship})` : ""),
      (h.source || "").replace(/_/g, " "),
      h.matter || "",
      h.assigned_attorney_display || "",
    ]));
}

// ── Related-party rows (Parties panel and New Client form) ────────────────────
function addRelatedRow(container, name, relationship) {
  const row = _el("div", {className: "sec-related-row", style: "display:flex;gap:.5rem;margin-bottom:.4rem"});
  row.append(
    _el("input", {type: "text", className: "sec-rel-name", placeholder: "Name",
                  ariaLabel: "Related party name",
                  style: "flex:2", value: name || ""}),
    _el("input", {type: "text", className: "sec-rel-rel", placeholder: "Relationship",
                  ariaLabel: "Relationship",
                  style: "flex:1", value: relationship || ""}),
    _el("button", {type: "button", className: "btn btn-secondary", title: "Remove",
                   ariaLabel: "Remove related party",
                   onclick: () => row.remove()}, "✕"));
  row.querySelector(".sec-rel-rel").setAttribute("list", "sec-rel-options");
  container.appendChild(row);
}

function collectRelated(container) {
  return Array.from(container.querySelectorAll(".sec-related-row")).map(r => ({
    name: r.querySelector(".sec-rel-name").value.trim(),
    relationship: r.querySelector(".sec-rel-rel").value.trim(),
  })).filter(r => r.name);
}

// ── Refresh just this panel (does not switch tabs or clear result boxes) ──────
function refreshSecurity() {
  if (!_currentClient) return Promise.resolve();
  const username = _currentClient.username;
  return fetch("/portal/attorney/client/" + encodeURIComponent(username))
    .then(r => r.json())
    .then(c => {
      if (_stale(username)) return;
      if (c.error) return _refreshFailed();
      _currentClient = c;
      _fillParties(c);
      _renderChecks(c.conflict_checks);
      _renderCoCounsel(c);
    })
    .catch(() => { if (!_stale(username)) _refreshFailed(); });
}

function _refreshFailed() {
  _show(document.getElementById("sec-checks"),
        _note("Couldn't refresh — reload the page.", true));
}

// ── Parties ───────────────────────────────────────────────────────────────────
function _fillParties(c) {
  document.getElementById("sec-opposing").value = (c.opposing_parties || []).join("\n");
  const list = document.getElementById("sec-related-list");
  list.replaceChildren();
  (c.related_parties || []).forEach(r => addRelatedRow(list, r.name, r.relationship));
}

function saveParties() {
  if (!_currentClient) return;
  const u = _currentClient.username;
  const saveBtn = document.getElementById("sec-save-parties");
  const out = document.getElementById("sec-parties-result");
  const opposing = document.getElementById("sec-opposing").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  const related = collectRelated(document.getElementById("sec-related-list"));
  _show(out, _note("Saving…"));
  _busy(saveBtn, true);
  _postJSON("/portal/attorney/update-client", {
    username: u, opposing_parties: opposing, related_parties: related,
  }).then(d => {
    if (_stale(u)) return;
    if (!d.success) return _show(out, _note(d.error || "Save failed.", true));
    if (d.conflict_hits && d.conflict_hits.length) {
      _show(out, _el("p", {className: "sec-note"},
                     _el("strong", {}, "New parties matched existing records:")),
            hitsTable(d.conflict_hits));
    } else {
      _show(out, _note("Saved. No conflicts found for new parties."));
    }
    refreshSecurity();
  }).catch(() => {
    if (!_stale(u)) _show(out, _note("Request failed — reload the page and try again.", true));
  }).finally(() => _busy(saveBtn, false));
}

// ── Conflict checks on this client ────────────────────────────────────────────
function _decisionControls(check) {
  const note = _el("input", {type: "text", placeholder: "Note (required for waiver)",
                             ariaLabel: "Decision note",
                             style: "flex:1;min-width:12rem"});
  const controls = [note];
  const btn = (label, decision) => {
    const b = _el("button", {
      type: "button", className: "btn btn-secondary",
      onclick: () => decideConflict(check.id, decision, note.value.trim(), controls),
    }, label);
    controls.push(b);
    return b;
  };
  return _el("div", {style: "display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.4rem"},
    note, btn("Cleared", "cleared"), btn("Waiver obtained", "waiver_obtained"),
    btn("Declined", "declined"));
}

function _renderChecks(checks) {
  const el = document.getElementById("sec-checks");
  if (!checks || !checks.length) return _show(el, _note("No conflict checks recorded."));
  _show(el, ...checks.slice().reverse().map(c => {
    const unresolved = c.hits && c.hits.length && !c.decision;
    const meta = _el("div", {className: "sec-note"},
      `${c.timestamp} · ${c.trigger} · run by ${c.run_by} · names: ${(c.names || []).join(", ")}`,
      unresolved ? [" ", _badge("Unresolved")] : null,
      c.incomplete ? [" ", _el("strong", {},
        `⚠ ${c.incomplete} record(s) could not be read; check incomplete`)] : null);
    const decided = c.decision
      ? _el("div", {className: "sec-note"}, "Decision: ",
            _el("strong", {}, c.decision.replace(/_/g, " ")),
            ` by ${c.decided_by || ""} ${c.decided_at || ""}`,
            c.decision_note ? ` — ${c.decision_note}` : "")
      : (unresolved ? _decisionControls(c) : null);
    return _el("div", {style: "border-top:1px solid var(--rule);padding:.6rem 0"},
               meta, hitsTable(c.hits), decided);
  }));
}

function decideConflict(checkId, decision, note, controls) {
  if (!_currentClient) return;
  const u = _currentClient.username;
  _busy(controls, true);
  _postJSON("/portal/attorney/conflict-decision", {
    username: u, check_id: checkId, decision, note,
  }).then(d => {
    if (_stale(u)) return;
    if (!d.success) return alert(d.error || "Could not record decision.");
    refreshSecurity();
  }).catch(() => {
    if (!_stale(u)) alert("Request failed — reload the page and try again.");
  }).finally(() => _busy(controls, false));
}

// ── Co-counsel ────────────────────────────────────────────────────────────────
function _renderCoCounsel(c) {
  const list = document.getElementById("sec-cocounsel-list");
  const add  = document.getElementById("sec-cocounsel-add");
  const sel  = document.getElementById("sec-cocounsel-select");
  const attorneys = window._ATTORNEYS || [];
  const byUser = Object.fromEntries(attorneys.map(a => [a.username, a.display]));
  const cc = c.co_counsel || [];

  if (!cc.length) {
    _show(list, _note("None."));
  } else {
    _show(list, ...cc.map(u => _el("span", {
        style: "display:inline-flex;gap:.3rem;align-items:center;margin-right:.6rem;font-family:Arial,sans-serif;font-size:.88rem"},
      byUser[u] || u,
      c.viewer_is_assigned
        ? _el("button", {type: "button", className: "btn btn-secondary",
                         style: "padding:.1rem .45rem",
                         ariaLabel: `Remove co-counsel ${byUser[u] || u}`,
                         onclick: ev => changeCoCounsel("remove", u, ev.currentTarget)}, "✕")
        : null)));
  }

  _show(sel, ...attorneys
    .filter(a => a.username !== c.assigned_attorney && !cc.includes(a.username))
    .map(a => _el("option", {value: a.username}, a.display)));
  add.style.display = c.viewer_is_assigned && sel.options.length ? "flex" : "none";
}

function changeCoCounsel(action, attorney, btn) {
  if (!attorney || !_currentClient) return;
  const u = _currentClient.username;
  _busy(btn, true);
  _postJSON("/portal/attorney/co-counsel", {username: u, action, attorney})
    .then(d => {
      if (_stale(u)) return;
      if (!d.success) return alert(d.error || "Could not update co-counsel.");
      refreshSecurity();
    })
    .catch(() => {
      if (!_stale(u)) alert("Request failed — reload the page and try again.");
    })
    .finally(() => _busy(btn, false));
}

// ── Access history ────────────────────────────────────────────────────────────
function loadAccessLog() {
  if (!_currentClient) return;
  const u = _currentClient.username;
  const el = document.getElementById("sec-access-log");
  const loadBtn = document.getElementById("sec-load-access");
  _show(el, _note("Loading…"));
  _busy(loadBtn, true);
  fetch("/portal/attorney/access-log/" + encodeURIComponent(u))
    .then(r => r.json())
    .then(rows => {
      if (_stale(u)) return;
      if (!Array.isArray(rows)) return _show(el, _note(rows.error || "Could not load.", true));
      if (!rows.length) return _show(el, _note("No access recorded yet."));
      _show(el, _table(["When", "Attorney", "Action", "Detail", "IP"],
        rows.map(r => [r.timestamp || "", r.attorney || "",
                       (r.action || "").replace(/_/g, " "), r.detail || "", r.ip || ""])));
    })
    .catch(() => {
      if (!_stale(u)) _show(el, _note("Request failed — reload the page and try again.", true));
    })
    .finally(() => _busy(loadBtn, false));
}

// ── Populate on client select (called from selectClient and selectClientAndTab) ─
function populateSecurity(c) {
  _fillParties(c);
  document.getElementById("sec-parties-result").replaceChildren();
  document.getElementById("sec-access-log").replaceChildren();
  _renderChecks(c.conflict_checks);
  _renderCoCounsel(c);
  // Archiving is assigned-attorney only (spec A3); runs after populateOverview.
  if (!c.viewer_is_assigned) {
    document.getElementById("ov-archive-btn").style.display   = "none";
    document.getElementById("ov-unarchive-btn").style.display = "none";
  }
}

// ── Firm-wide Conflict Check tab ──────────────────────────────────────────────
// The attach list holds active clients only (from _ALL_CLIENTS_DATA); checks on
// an archived client's matter are rare and can be run unattached.
function showConflictCheck(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-conflict-check").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  const sel = document.getElementById("cc-attach");
  const keep = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  (window._ALL_CLIENTS_DATA || []).forEach(c =>
    sel.appendChild(_el("option", {value: c.username}, c.client_name || c.username)));
  sel.value = keep;
}

function runManualConflictCheck() {
  const out   = document.getElementById("cc-results");
  const names = document.getElementById("cc-names").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  if (!names.length) return _show(out, _note("Enter at least one name.", true));
  const body   = {names};
  const attach = document.getElementById("cc-attach").value;
  if (attach) body.username = attach;
  _show(out, _note("Checking…"));
  const runBtn = document.getElementById("cc-run");
  _busy(runBtn, true);
  _postJSON("/portal/attorney/conflict-check", body).then(d => {
    if (!d.success) return _show(out, _note(d.error || "Check failed.", true));
    _show(out,
      _note(`Recorded as ${d.check.id}${attach ? " on the selected client" : " in the firm log"}.`),
      d.check.incomplete
        ? _note(`⚠ ${d.check.incomplete} record(s) could not be read; check incomplete`, true) : null,
      hitsTable(d.check.hits));
  }).catch(() => _show(out, _note("Request failed — reload the page and try again.", true)))
    .finally(() => _busy(runBtn, false));
}

// ── Static button wiring ──────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("sec-add-related").addEventListener("click", () =>
    addRelatedRow(document.getElementById("sec-related-list")));
  document.getElementById("nc-add-related").addEventListener("click", () =>
    addRelatedRow(document.getElementById("nc-related-list")));
  document.getElementById("sec-save-parties").addEventListener("click", saveParties);
  document.getElementById("sec-load-access").addEventListener("click", loadAccessLog);
  document.getElementById("sec-cocounsel-add-btn").addEventListener("click", () =>
    changeCoCounsel("add", document.getElementById("sec-cocounsel-select").value,
                      document.getElementById("sec-cocounsel-add-btn")));
  document.getElementById("cc-run").addEventListener("click", runManualConflictCheck);
});
