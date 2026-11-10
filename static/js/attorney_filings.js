// Filing packages on the Documents tab (templates/attorney/_panel_documents.html).
// Server: blueprints/filings.py. Form fields are pre-filled from the client
// file; each label says whether its value came from the file or is still needed.

var _filing = { doc: null, methods: [], filedId: null };

function _docHref(path) {
  var parts = path.split("/");
  return "/portal/attorney/document/" + encodeURIComponent(_currentClient.username) + "/" +
         encodeURIComponent(parts[0]) + "/" + encodeURIComponent(parts.slice(1).join("/"));
}

function loadFilings(quiet) {
  if (!_currentClient) return Promise.resolve(null);
  return fetch("/portal/attorney/filing/" + encodeURIComponent(_currentClient.username))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) return null;
      _filing.methods = d.methods || [];
      renderFilings(d.filings || []);
      return d;
    })
    .catch(function () { return null; });
}

function renderFilings(items) {
  var list = document.getElementById("filings-list");
  if (!list) return;
  if (!items.length) {
    _show(list, _el("p", { className: "doc-empty" }, "No filing packages yet. Use \"Prepare filing\" on a document."));
    return;
  }
  _show(list, items.map(function (f) {
    var filed = f.status === "filed";
    var actions = [_el("a", { className: "doc-btn", href: _docHref(f.package) }, "↓ Package")];
    if (f.stamped_file) actions.push(_el("a", { className: "doc-btn", href: _docHref(f.stamped_file) }, "↓ Filed copy"));
    if (!filed) actions.push(_el("button", { type: "button", className: "doc-btn",
                                             onclick: function () { openFiled(f); } }, "Mark filed"));
    var meta = f.court + " · Case No. " + f.case_no + " · prepared " + (f.prepared_at || "").slice(0, 10) +
               (f.signature_approved ? " · signed /s/" : " · signature line blank") +
               (f.hearing_date ? " · hearing " + f.hearing_date : "");
    var details = _el("details", { className: "filing-details" },
      _el("summary", {}, "Checklist before filing"),
      _el("ul", { className: "filing-checklist" }, (f.checklist || []).map(function (c) { return _el("li", {}, c); })));
    return _el("div", { className: "esign-row", style: "align-items:flex-start" },
      _el("div", { className: "esign-row-main" },
        _el("div", { className: "esign-title" }, f.title),
        _el("div", { className: "esign-meta" }, meta),
        filed ? null : details),
      _el("span", { className: "esign-status " + (filed ? "esign-ok" : "esign-wait") }, filed ? "Filed" : "Ready to file"),
      _el("div", { className: "esign-actions" }, actions));
  }));
}

function _partyRow(p) {
  p = p || {};
  var method = _el("select", { className: "filing-method" },
    (_filing.methods.length ? _filing.methods : ["email"]).map(function (m) {
      return _el("option", { value: m, selected: m === (p.method || "email") }, m);
    }));
  var row = _el("div", { className: "filing-party" },
    _el("input", { type: "text", className: "filing-pname", placeholder: "Name (person or office)", value: p.name || "" }),
    _el("input", { type: "text", className: "filing-paddr", placeholder: "Email or mailing address", value: p.address || "" }),
    method,
    _el("button", { type: "button", className: "doc-btn", title: "Remove", onclick: function () { row.remove(); } }, "✕"));
  row.dataset.role = p.role || "";
  return row;
}

function addFilingParty() {
  document.getElementById("filing-service").appendChild(_partyRow({}));
}

function _mark(key, prefilled) {
  var span = document.querySelector('#filing-modal [data-for="' + key + '"]');
  if (!span) return;
  span.className = prefilled ? "filing-prefilled" : "filing-missing";
  span.textContent = prefilled ? "✓ from file" : "needed";
}

function openFiling(filename) {
  if (!_currentClient) return;
  _filing.doc = { category: _docCategory, filename: filename };
  document.getElementById("filing-doc").textContent = _docCategory + " / " + filename;
  document.getElementById("filing-error").textContent = "";
  document.getElementById("filing-approve").checked = false;
  document.getElementById("filing-title").value = filename.replace(/\.[^.]+$/, "").replace(/_/g, " ");
  loadFilings().then(function (d) {
    if (!d) return;
    var f = d.fields, missing = d.missing || [];
    document.getElementById("filing-court").value = f.court || "";
    document.getElementById("filing-county").value = f.county || "";
    document.getElementById("filing-case-no").value = f.case_no || "";
    document.getElementById("filing-role").value = f.client_role || "";
    ["court", "county", "case_no", "client_role"].forEach(function (k) { _mark(k, missing.indexOf(k) < 0); });
    _mark("service", missing.indexOf("service") < 0 && missing.indexOf("service addresses") < 0);
    var svc = document.getElementById("filing-service");
    svc.replaceChildren.apply(svc, (f.service && f.service.length ? f.service : [{}]).map(_partyRow));
    var labels = { court: "court", county: "county", case_no: "case number", client_role: "your client's side",
                   service: "parties to serve", "service addresses": "service addresses" };
    var needed = missing.map(function (k) { return labels[k] || k; }).join(", ");
    var anyFilled = ["court", "county", "case_no", "client_role"].some(function (k) { return f[k]; }) ||
                    (f.service || []).length > 0;
    document.getElementById("filing-summary").textContent = !missing.length
      ? "Everything is filled in from the client file. Review and build."
      : (anyFilled ? "Filled in from the client file where possible. Still needed: " + needed + "."
                   : "Nothing for this case is on file yet. Needed: " + needed +
                     ". What you enter is saved to the file for next time.");
    document.getElementById("filing-modal").style.display = "flex";
  });
}

function closeFiling() { document.getElementById("filing-modal").style.display = "none"; }

function buildFiling() {
  var service = Array.prototype.map.call(document.querySelectorAll("#filing-service .filing-party"), function (row) {
    return { name: row.querySelector(".filing-pname").value.trim(), address: row.querySelector(".filing-paddr").value.trim(),
             method: row.querySelector(".filing-method").value, role: row.dataset.role || "" };
  });
  var btn = document.getElementById("filing-build-btn");
  var err = document.getElementById("filing-error");
  err.textContent = "";
  btn.disabled = true;
  btn.textContent = "Building…";
  fetch("/portal/attorney/filing/prepare", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: _currentClient.username, category: _filing.doc.category, filename: _filing.doc.filename,
      court: document.getElementById("filing-court").value, county: document.getElementById("filing-county").value,
      case_no: document.getElementById("filing-case-no").value, client_role: document.getElementById("filing-role").value,
      client_name: _currentClient.client_name || "", title: document.getElementById("filing-title").value,
      service: service, approve_signature: document.getElementById("filing-approve").checked,
    }),
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { err.textContent = d.error; return; }
      closeFiling();
      loadFilings();
      if (typeof loadDocumentList === "function") loadDocumentList();
    })
    .catch(function (e) { err.textContent = "Request failed: " + e.message; })
    .finally(function () { btn.disabled = false; btn.textContent = "Build package"; });
}

function openFiled(f) {
  _filing.filedId = f.id;
  document.getElementById("filed-title").textContent = f.title + " · " + f.court + " · Case No. " + f.case_no;
  document.getElementById("filed-file").value = "";
  document.getElementById("filed-hearing").value = "";
  document.getElementById("filed-label").value = "";
  document.getElementById("filed-error").textContent = "";
  document.getElementById("filed-modal").style.display = "flex";
}

function closeFiled() { document.getElementById("filed-modal").style.display = "none"; }

function saveFiled() {
  var form = new FormData();
  form.append("username", _currentClient.username);
  form.append("filing_id", _filing.filedId);
  form.append("category", document.getElementById("filed-category").value);
  form.append("hearing_date", document.getElementById("filed-hearing").value);
  form.append("hearing_label", document.getElementById("filed-label").value);
  var file = document.getElementById("filed-file").files[0];
  if (file) form.append("file", file);
  var btn = document.getElementById("filed-save-btn");
  var err = document.getElementById("filed-error");
  btn.disabled = true;
  fetch("/portal/attorney/filing/mark-filed", { method: "POST", body: form })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { err.textContent = d.error; return; }
      closeFiled();
      loadFilings();
    })
    .catch(function (e) { err.textContent = "Request failed: " + e.message; })
    .finally(function () { btn.disabled = false; });
}
