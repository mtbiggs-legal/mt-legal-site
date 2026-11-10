// Portal assistant chat drawer (templates/attorney/_assistant.html).
// The server keeps the conversation; this file only renders it. Everything the
// model or a client wrote goes in through textContent, never innerHTML.

var _asstBusy = false;
var _asstLoaded = false;

function openAssistant() {
  var d = document.getElementById("asst-drawer");
  d.classList.add("open");
  d.setAttribute("aria-hidden", "false");
  document.getElementById("asst-launcher").style.display = "none";
  if (!_asstLoaded) { _asstLoaded = true; loadAssistantHistory(); }
  setTimeout(function () { document.getElementById("asst-input").focus(); }, 50);
}

function closeAssistant() {
  var d = document.getElementById("asst-drawer");
  d.classList.remove("open");
  d.setAttribute("aria-hidden", "true");
  document.getElementById("asst-launcher").style.display = "";
}

function _asstLog() { return document.getElementById("asst-log"); }

function _asstScroll() { var l = _asstLog(); l.scrollTop = l.scrollHeight; }

function _asstBubble(role, text) {
  document.getElementById("asst-empty").style.display = "none";
  var b = document.createElement("div");
  b.className = "asst-msg asst-" + role;
  b.textContent = text;
  _asstLog().appendChild(b);
  _asstScroll();
  return b;
}

function _asstNote(text, isError) {
  var n = document.createElement("div");
  n.className = "asst-note" + (isError ? " asst-error" : "");
  n.textContent = text;
  _asstLog().appendChild(n);
  _asstScroll();
}

function _asstThinking(on) {
  var t = document.getElementById("asst-thinking");
  if (on && !t) {
    t = document.createElement("div");
    t.id = "asst-thinking";
    t.className = "asst-msg asst-assistant asst-typing";
    for (var i = 0; i < 3; i++) t.appendChild(document.createElement("span"));
    _asstLog().appendChild(t);
    _asstScroll();
  } else if (!on && t) {
    t.remove();
  }
}

function _asstSetBusy(busy) {
  _asstBusy = busy;
  document.getElementById("asst-send").disabled = busy;
  document.querySelectorAll(".asst-action-btn").forEach(function (b) { b.disabled = busy; });
}

// One card per proposed change; the attorney decides each, then the batch is sent.
function _asstPendingCards(pending) {
  if (!pending || !pending.length) return;
  var wrap = document.createElement("div");
  wrap.className = "asst-pending";
  var decisions = {};

  pending.forEach(function (p) {
    var card = document.createElement("div");
    card.className = "asst-card";
    var title = document.createElement("div");
    title.className = "asst-card-title";
    title.textContent = "Confirm: " + p.title;
    var body = document.createElement("div");
    body.className = "asst-card-body";
    body.textContent = p.summary;
    var row = document.createElement("div");
    row.className = "asst-card-actions";
    var yes = document.createElement("button");
    yes.className = "asst-action-btn asst-yes";
    yes.textContent = "Confirm";
    var no = document.createElement("button");
    no.className = "asst-action-btn asst-no";
    no.textContent = "Decline";
    function decide(val) {
      decisions[p.id] = val;
      card.classList.toggle("asst-card-yes", val === true);
      card.classList.toggle("asst-card-no", val === false);
      yes.disabled = no.disabled = true;
      var status = document.createElement("div");
      status.className = "asst-card-status";
      status.textContent = val ? "Confirmed" : "Declined";
      row.replaceChildren(status);
      if (Object.keys(decisions).length === pending.length) _asstSendDecisions(decisions);
    }
    yes.onclick = function () { decide(true); };
    no.onclick = function () { decide(false); };
    row.appendChild(yes);
    row.appendChild(no);
    card.appendChild(title);
    card.appendChild(body);
    card.appendChild(row);
    wrap.appendChild(card);
  });
  _asstLog().appendChild(wrap);
  _asstScroll();
}

// A card for each draft the assistant saved: open it, download it, or go to
// the client's Documents tab.
function _asstDocCards(docs) {
  (docs || []).forEach(function (doc) {
    var path = encodeURIComponent(doc.username) + "/" + encodeURIComponent(doc.category) + "/" +
               encodeURIComponent(doc.filename);
    var card = document.createElement("div");
    card.className = "asst-doc";
    var icon = document.createElement("span");
    icon.className = "asst-doc-ico";
    icon.textContent = "📄";
    var info = document.createElement("div");
    info.className = "asst-doc-info";
    var title = document.createElement("div");
    title.className = "asst-doc-title";
    title.textContent = doc.title;
    var where = document.createElement("div");
    where.className = "asst-doc-where";
    where.textContent = doc.category + " / " + doc.filename;
    info.appendChild(title);
    info.appendChild(where);
    var actions = document.createElement("div");
    actions.className = "asst-doc-actions";
    var open = document.createElement("a");
    open.className = "asst-action-btn asst-yes";
    open.href = "/portal/attorney/docx-preview/" + path;
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = "Open";
    var dl = document.createElement("a");
    dl.className = "asst-action-btn asst-no";
    dl.href = "/portal/attorney/document/" + path;
    dl.textContent = "Download .docx";
    var go = document.createElement("button");
    go.type = "button";
    go.className = "asst-action-btn asst-no";
    go.textContent = "Go to file";
    go.onclick = function () {
      if (typeof selectClientAndTab === "function") selectClientAndTab(doc.username, "documents");
    };
    actions.appendChild(open);
    actions.appendChild(dl);
    actions.appendChild(go);
    card.appendChild(icon);
    card.appendChild(info);
    card.appendChild(actions);
    _asstLog().appendChild(card);
  });
  _asstScroll();
}

function _asstHandle(d) {
  _asstThinking(false);
  _asstSetBusy(false);
  if (d.error) { _asstNote(d.error, true); return; }
  if (d.reply) _asstBubble("assistant", d.reply);
  _asstDocCards(d.documents);
  _asstPendingCards(d.pending);
}

function _asstPost(url, body) {
  _asstSetBusy(true);
  _asstThinking(true);
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then(function (r) { return r.json().catch(function () { return { error: "Server error (" + r.status + ")." }; }); })
    .then(_asstHandle)
    .catch(function (e) { _asstHandle({ error: "Request failed: " + e.message }); });
}

function _asstSendDecisions(decisions) {
  _asstPost("/portal/attorney/assistant/confirm", { decisions: decisions });
}

function sendAssistant() {
  var input = document.getElementById("asst-input");
  var text = input.value.trim();
  if (!text || _asstBusy) return;
  input.value = "";
  // A new message declines any change still waiting for a decision.
  document.querySelectorAll(".asst-pending .asst-action-btn").forEach(function (b) { b.disabled = true; });
  _asstBubble("user", text);
  _asstPost("/portal/attorney/assistant/message", { text: text });
}

function askAssistant(text) {
  document.getElementById("asst-input").value = text;
  sendAssistant();
}

function resetAssistant() {
  if (_asstBusy) return;
  fetch("/portal/attorney/assistant/reset", { method: "POST" }).finally(function () {
    var log = _asstLog();
    Array.prototype.slice.call(log.children).forEach(function (c) {
      if (c.id !== "asst-empty") c.remove();
    });
    document.getElementById("asst-empty").style.display = "";
    document.getElementById("asst-input").focus();
  });
}

function loadAssistantHistory() {
  fetch("/portal/attorney/assistant/history")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      (d.messages || []).forEach(function (m) { _asstBubble(m.role, m.text); });
      _asstPendingCards(d.pending);
    })
    .catch(function () {});
}

document.addEventListener("DOMContentLoaded", function () {
  var input = document.getElementById("asst-input");
  if (!input) return;
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAssistant(); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.getElementById("asst-drawer").classList.contains("open")) closeAssistant();
  });
});
