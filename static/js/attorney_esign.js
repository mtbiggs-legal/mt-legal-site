// E-signatures on the Documents tab (templates/attorney/_panel_documents.html).
// Server: blueprints/esign.py. Signer names and emails are typed by the
// attorney or come from the client record; all rendering uses textContent/_el.

var _esign = { configured: false, testMode: true, defaults: {}, doc: null };
var SIGNABLE_EXTS = ["pdf", "doc", "docx"];

function esignSignable(name) {
  return SIGNABLE_EXTS.indexOf((name.split(".").pop() || "").toLowerCase()) >= 0;
}

var ESIGN_STATUS = {
  "sent": ["Waiting", "esign-wait"], "partly signed": ["Partly signed", "esign-wait"],
  "signed": ["Signed", "esign-ok"], "declined": ["Declined", "esign-bad"], "error": ["Problem", "esign-bad"],
};
var SIGNER_STATUS = { awaiting_signature: "waiting", signed: "signed", declined: "declined",
                      on_hold: "waiting for an earlier signer", error: "problem" };

// quiet: a live refresh (no spinner); force: ask Dropbox Sign now.
function loadSignatures(quiet, force) {
  if (!_currentClient) return;
  var list = document.getElementById("esign-list");
  if (!list) return;
  if (!quiet) _show(list, _el("p", { className: "doc-empty" }, "Checking…"));
  fetch("/portal/attorney/esign/" + encodeURIComponent(_currentClient.username) + (force ? "?refresh=1" : ""))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { _show(list, _el("p", { className: "doc-empty" }, d.error)); return; }
      _esign.configured = d.configured;
      _esign.testMode = d.test_mode;
      _esign.defaults = d.defaults || {};
      var mode = document.getElementById("esign-mode");
      mode.style.display = d.configured ? "" : "none";
      mode.textContent = d.test_mode ? "Test mode" : "Live";
      mode.className = "esign-mode " + (d.test_mode ? "esign-wait" : "esign-ok");
      renderSignatures(d.requests || []);
    })
    .catch(function () { if (!quiet) _show(list, _el("p", { className: "doc-empty" }, "Couldn't load signatures.")); });
}

function renderSignatures(reqs) {
  var list = document.getElementById("esign-list");
  if (!reqs.length) {
    _show(list, _el("p", { className: "doc-empty" },
      _esign.configured ? "No documents sent for signature yet."
                        : "E-signing isn't set up yet. Add DROPBOX_SIGN_API_KEY to .env (see docs/ESIGN_SETUP.md)."));
    return;
  }
  _show(list, reqs.map(function (r) {
    var st = ESIGN_STATUS[r.status] || [r.status, "esign-wait"];
    var signers = r.signers.map(function (s) {
      return s.name + " — " + (SIGNER_STATUS[s.status] || s.status) + (s.signed_at ? " " + s.signed_at : "");
    }).join("; ");
    var actions = [];
    if (r.status === "sent" || r.status === "partly signed") {
      actions.push(_el("button", { type: "button", className: "doc-btn", onclick: function () { remindEsign(r.id); } }, "Remind"));
    }
    if (r.signed_file) {
      var parts = r.signed_file.split("/");
      actions.push(_el("a", { className: "doc-btn",
        href: "/portal/attorney/document/" + encodeURIComponent(_currentClient.username) + "/" +
              encodeURIComponent(parts[0]) + "/" + encodeURIComponent(parts.slice(1).join("/")) }, "↓ Signed copy"));
    }
    return _el("div", { className: "esign-row" },
      _el("div", { className: "esign-row-main" },
        _el("div", { className: "esign-title" }, r.title + (r.test_mode ? " (test)" : "")),
        _el("div", { className: "esign-meta" }, "Sent " + (r.sent_at || "").replace("T", " ").slice(0, 16) + " · " + signers)),
      _el("span", { className: "esign-status " + st[1] }, st[0]),
      _el("div", { className: "esign-actions" }, actions));
  }));
}

function _signerRow(name, email) {
  var row = _el("div", { className: "esign-signer" },
    _el("input", { type: "text", placeholder: "Full name", value: name || "", className: "esign-name" }),
    _el("input", { type: "email", placeholder: "email@example.com", value: email || "", className: "esign-email" }),
    _el("button", { type: "button", className: "doc-btn", title: "Remove",
                    onclick: function () { row.remove(); } }, "✕"));
  return row;
}

function addEsignSigner() {
  document.getElementById("esign-signers").appendChild(_signerRow("", ""));
}

function openEsign(filename) {
  if (!_currentClient) return;
  _esign.doc = { category: _docCategory, filename: filename };
  document.getElementById("esign-doc").textContent = _docCategory + " / " + filename;
  var signers = document.getElementById("esign-signers");
  signers.replaceChildren(_signerRow(_currentClient.client_name || "", _currentClient.email || ""));
  document.getElementById("esign-subject").value = "Please sign: " + filename.replace(/\.[^.]+$/, "").replace(/_/g, " ");
  document.getElementById("esign-message").value = "";
  document.getElementById("esign-error").textContent = "";
  document.getElementById("esign-test-note").textContent = !_esign.configured
    ? "E-signing isn't set up yet, so this will be refused. See docs/ESIGN_SETUP.md."
    : (_esign.testMode ? "Test mode: the signer gets a real email, but the signature isn't legally binding." : "");
  document.getElementById("esign-modal").style.display = "flex";
}

function closeEsign() { document.getElementById("esign-modal").style.display = "none"; }

function sendEsign() {
  var signers = Array.prototype.map.call(document.querySelectorAll("#esign-signers .esign-signer"), function (row) {
    return { name: row.querySelector(".esign-name").value.trim(), email: row.querySelector(".esign-email").value.trim() };
  });
  var err = document.getElementById("esign-error");
  var btn = document.getElementById("esign-send-btn");
  err.textContent = "";
  btn.disabled = true;
  btn.textContent = "Sending…";
  fetch("/portal/attorney/esign/send", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: _currentClient.username, category: _esign.doc.category,
                           filename: _esign.doc.filename, signers: signers,
                           subject: document.getElementById("esign-subject").value,
                           message: document.getElementById("esign-message").value }),
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) { err.textContent = d.error; return; }
      closeEsign();
      loadSignatures(true);
    })
    .catch(function (e) { err.textContent = "Request failed: " + e.message; })
    .finally(function () { btn.disabled = false; btn.textContent = "Send for signature"; });
}

function remindEsign(requestId) {
  fetch("/portal/attorney/esign/remind", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: _currentClient.username, request_id: requestId }),
  })
    .then(function (r) { return r.json(); })
    .then(function (d) { alert(d.error || ("Reminder sent to " + d.reminded.join(", ") + ".")); })
    .catch(function () { alert("Couldn't send the reminder."); });
}
