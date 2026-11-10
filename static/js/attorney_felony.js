// Felony case checklist (Case Overview) and the dashboard's Action Items.
// Reuses the globals from attorney_security.js: _el, _show, _note, _stale,
// _busy, _postJSON. Data only ever becomes text.

function felonyDocUrl(username, d) {
  return "/portal/attorney/document/" + encodeURIComponent(username) + "/" +
    encodeURIComponent(d.category) + "/" + encodeURIComponent(d.filename);
}

function felonyDraftLine(username, d) {
  if (!d || d.status !== "ready") {
    return _note(d && d.status === "drafting" ? "Drafting the discovery request…"
      : "The Request for Discovery is drafted automatically once the case is in Criminal or " +
        "Circuit Court with a case number, or when you check “Arraigned”.");
  }
  const parts = [
    _el("span", {className: "felony-draft-label"}, "Request for Discovery drafted " + (d.at || "").slice(0, 10)),
    " ",
    _el("a", {href: felonyDocUrl(username, d), className: "btn btn-secondary felony-btn"}, "Download draft"),
  ];
  if (!d.reviewed) {
    const btn = _el("button", {type: "button", className: "btn btn-secondary felony-btn"}, "Mark reviewed");
    btn.addEventListener("click", () => felonyReviewed(username, btn));
    parts.push(" ", btn);
  } else {
    parts.push(" ", _el("span", {className: "sec-note"}, "Reviewed"));
  }
  return _el("div", {className: "felony-draft"}, parts);
}

function felonyRender(username, items, draft) {
  const card = document.getElementById("felony-card");
  if (!card) return;
  if (!items || !items.length) {
    card.style.display = "none";
    return;
  }
  card.style.display = "";
  const done = items.filter(i => i.done).length;
  document.getElementById("felony-progress").textContent = done + " of " + items.length + " done";
  const list = items.map(item => {
    const box = _el("input", {type: "checkbox", checked: item.done, id: "fc-" + item.key});
    box.addEventListener("change", () => felonyToggle(username, item.key, box));
    const meta = item.done && item.at
      ? _el("span", {className: "felony-meta"}, item.at.slice(0, 10) + (item.by ? " · " + item.by : ""))
      : null;
    return _el("li", {className: "felony-item" + (item.done ? " is-done" : "")},
      box, _el("label", {htmlFor: "fc-" + item.key}, item.label), meta);
  });
  _show(document.getElementById("felony-list"), list);
  _show(document.getElementById("felony-draft"), felonyDraftLine(username, draft));
}

function populateFelony(c) {
  const res = document.getElementById("felony-result");
  if (res) _show(res);
  felonyRender(c.username, c.felony_checklist, c.discovery_draft);
}

function felonyApply(username, d) {
  if (_stale(username)) return;
  const res = document.getElementById("felony-result");
  if (d.error) {
    _show(res, _note(d.error, true));
    populateFelony(_currentClient);
    return;
  }
  _currentClient.felony_checklist = d.felony_checklist;
  _currentClient.discovery_draft = d.discovery_draft;
  _show(res);
  felonyRender(username, d.felony_checklist, d.discovery_draft);
}

function felonyToggle(username, key, box) {
  _busy(box, true);
  _postJSON("/portal/attorney/felony-checklist", {username: username, key: key, done: box.checked})
    .then(d => felonyApply(username, d))
    .catch(() => {
      box.checked = !box.checked;
      _show(document.getElementById("felony-result"), _note("Couldn't save — try again.", true));
    })
    .finally(() => _busy(box, false));
}

function felonyReviewed(username, btn) {
  _busy(btn, true);
  _postJSON("/portal/attorney/discovery-reviewed", {username: username})
    .then(d => felonyApply(username, d))
    .catch(() => _busy(btn, false));
}

// Dashboard: drafts waiting for review and firm admin deadlines.
function renderActionItems(items) {
  const card = document.getElementById("dash-card-actions");
  const list = document.getElementById("dash-actions-list");
  if (!card || !list) return;
  card.style.display = items && items.length ? "" : "none";
  if (!items || !items.length) return;
  _show(list, items.map(it => {
    if (it.kind === "admin") {
      const open = _el("button", {type: "button", className: "dash-action-client"}, it.client_name);
      open.addEventListener("click", () => showFirmAdmin(document.getElementById("firm-admin-tab-btn")));
      return _el("li", {className: "dash-action dash-action-admin" + (it.stage === "overdue" ? " is-overdue" : "")},
        _el("span", {className: "fa-chip fa-warn"}, "Firm admin"), " ", open, " ",
        _el("span", {}, it.text));
    }
    const name = _el("button", {type: "button", className: "dash-action-client"}, it.client_name);
    name.addEventListener("click", () => selectClient(it.username));
    return _el("li", {className: "dash-action"},
      name, " ", _el("span", {}, it.text), " ",
      _el("a", {href: felonyDocUrl(it.username, it), className: "dash-action-link"}, "Download"));
  }));
}
