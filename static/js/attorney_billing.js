// Attorney portal: billing status card (Time & Notes) and threshold
// settings (Insights). Reuses the globals from attorney_security.js, which
// must load first: _el, _show, _note, _table, _stale, _busy, _postJSON.
// No DOM is built from HTML strings; data only ever becomes text.

function billMoney(n) {
  return Number(n || 0).toLocaleString("en-US", {style: "currency", currency: "USD"});
}

function billNoticeText(statement) {
  const n = statement.notice || {};
  switch (n.status) {
    case "pending": return "Pending";
    case "sending": return "Sending";
    case "sent": return "Sent";
    case "failed": return "Failed" + (n.error ? ": " + n.error : "");
    case "no_email": return "No email";
    case "skipped": return "Skipped";
    default: return n.status || "";
  }
}

function billResult(text, isError) {
  const box = document.getElementById("bill-status-result");
  if (box) _show(box, text ? _note(text, isError) : null);
}

function billRender(username, summary) {
  feeRender(summary);
  const sumBox = document.getElementById("bill-status-summary");
  const listBox = document.getElementById("bill-statements");
  if (!sumBox || !listBox) return;
  if (!summary) {
    _show(sumBox);
    _show(listBox);
    return;
  }
  _show(sumBox, _el("p", {},
    "Unbilled: " + billMoney(summary.unbilled_amount) + " of " + billMoney(summary.threshold) +
    " threshold · Amount due: " + billMoney(summary.amount_due)));
  const statements = summary.statements || [];
  if (!statements.length) {
    _show(listBox, _note("No statements issued yet."));
    return;
  }
  const rows = statements.map(s => {
    const status = (s.notice || {}).status;
    const cells = [
      "#" + s.number,
      (s.issued_at || "").slice(0, 10),
      s.billed_through || "",
      billMoney(s.amount),
      billNoticeText(s),
    ];
    if (status === "failed" || status === "no_email") {
      const btn = _el("button", {type: "button", className: "btn btn-secondary"}, "Resend");
      btn.addEventListener("click", () => billResend(username, s.id, btn));
      cells[4] = [billNoticeText(s), " ", btn];
    }
    return cells;
  });
  _show(listBox, _table(["Statement", "Issued", "Billed through", "Amount", "Email"], rows));
}

// One delayed re-fetch so "Sending" settles to Sent / Failed / No email.
function billFollowUp(username, summary) {
  const open = (summary.statements || []).some(st => {
    const status = (st.notice || {}).status;
    return status === "pending" || status === "sending";
  });
  if (!open) return;
  setTimeout(() => {
    if (_stale(username)) return;
    fetch("/portal/attorney/client/" + encodeURIComponent(username))
      .then(r => r.json())
      .then(c => {
        if (_stale(username) || c.error || !c.billing_summary) return;
        _currentClient.billing_summary = c.billing_summary;
        billRender(username, c.billing_summary);
      })
      .catch(() => {});
  }, 2500);
}

function billResend(username, statementId, btn) {
  _busy(btn, true);
  billResult("");
  _postJSON("/portal/attorney/statement-notice", {username: username, statement_id: statementId})
    .then(d => {
      if (_stale(username)) return;
      if (d.error) {
        _busy(btn, false);
        billResult(d.error, true);
        return;
      }
      if (_currentClient) _currentClient.billing_summary = d.billing_summary;
      billRender(username, d.billing_summary);
      billFollowUp(username, d.billing_summary);
    })
    .catch(() => {
      _busy(btn, false);
      if (!_stale(username)) billResult("Couldn't resend — try again.", true);
    });
}

function populateBilling(c) {
  billResult("");
  _busy(document.getElementById("bill-issue-btn"), false);
  billRender(c.username, c.billing_summary);
  feeFillForm(c.billing_summary);
}

function issueStatementNow() {
  if (!_currentClient) return;
  const username = _currentClient.username;
  const btn = document.getElementById("bill-issue-btn");
  _busy(btn, true);
  billResult("");
  fetch("/portal/attorney/client/" + encodeURIComponent(username))
    .then(r => r.json())
    .then(c => {
      if (_stale(username)) return null;
      if (c.error || !c.billing_summary) {
        _busy(btn, false);
        billResult(c.error || "Couldn't load billing status.", true);
        return null;
      }
      _currentClient.billing_summary = c.billing_summary;
      billRender(username, c.billing_summary);
      const amount = c.billing_summary.unbilled_amount;
      if (!(amount > 0)) {
        _busy(btn, false);
        billResult("No unbilled time to bill.", true);
        return null;
      }
      if (!confirm("Issue a statement for " + billMoney(amount) +
                   " of unbilled time and email the client?")) {
        _busy(btn, false);
        return null;
      }
      return _postJSON("/portal/attorney/issue-statement", {username: username});
    })
    .then(d => {
      if (!d || _stale(username)) return;
      _busy(btn, false);
      if (d.error) {
        billResult(d.error, true);
        return;
      }
      _currentClient.billing_summary = d.billing_summary;
      billRender(username, d.billing_summary);
      billResult("Statement #" + d.statement.number + " issued.", false);
      billFollowUp(username, d.billing_summary);
    })
    .catch(() => {
      _busy(btn, false);
      if (!_stale(username)) billResult("Couldn't issue the statement \u2014 try again.", true);
    });
}

function billSettingsResult(text, isError) {
  const box = document.getElementById("bill-settings-result");
  if (box) _show(box, text ? _note(text, isError) : null);
}

function loadBillingSettings() {
  fetch("/portal/attorney/billing-settings")
    .then(r => r.json().then(d => ({ok: r.ok, d: d})))
    .then(res => {
      if (!res.ok || res.d.error) {
        billSettingsResult(res.d.error || "Couldn't load billing settings.", true);
        return;
      }
      const input = document.getElementById("bill-threshold");
      if (input && res.d.threshold !== undefined) input.value = res.d.threshold;
    })
    .catch(() => billSettingsResult("Couldn't load billing settings.", true));
}

function saveBillingSettings() {
  const btn = document.getElementById("bill-threshold-save");
  const input = document.getElementById("bill-threshold");
  if (!input) return;
  _busy(btn, true);
  billSettingsResult("");
  _postJSON("/portal/attorney/billing-settings",
            {threshold: input.value === "" ? null : Number(input.value)})
    .then(d => {
      _busy(btn, false);
      if (d.error) return billSettingsResult(d.error, true);
      input.value = d.threshold;
      billSettingsResult("Saved.", false);
    })
    .catch(() => {
      _busy(btn, false);
      billSettingsResult("Couldn't save \u2014 try again.", true);
    });
}

document.addEventListener("DOMContentLoaded", () => {
  const issueBtn = document.getElementById("bill-issue-btn");
  if (issueBtn) issueBtn.addEventListener("click", issueStatementNow);
  const saveBtn = document.getElementById("bill-threshold-save");
  if (saveBtn) saveBtn.addEventListener("click", saveBillingSettings);
});

// ── Fee arrangement: flat fee status, flat fee form, manual payments ─────────

const FEE_STATUS_TEXT = {
  paid: "Paid in full", half_paid: "First half paid", partial: "Partly paid", unpaid: "Not paid yet",
};

function feeResult(text, isError) {
  const box = document.getElementById("fee-result");
  if (box) _show(box, text ? _note(text, isError) : null);
}

function feeTile(label, value, sub, tone) {
  return _el("div", {className: "fee-tile" + (tone ? " fee-" + tone : "")},
    _el("div", {className: "fee-tile-label"}, label),
    _el("div", {className: "fee-tile-value"}, value),
    sub ? _el("div", {className: "fee-tile-sub"}, sub) : null);
}

// Read-only status. Called on load and by live refreshes, so it never
// touches the form fields.
function feeRender(summary) {
  const box = document.getElementById("fee-status");
  if (!box || !summary) return;
  const f = summary.flat_fee;
  const label = document.getElementById("ov-hours-label");
  const sub = document.getElementById("ov-fee-sub");
  const editSummary = document.getElementById("fee-edit-summary");
  const removeBtn = document.getElementById("fee-remove-btn");
  if (!f) {
    _show(box, _el("p", {className: "fee-mode"}, "Billed hourly. ",
      _el("span", {className: "sec-note"}, "Amount due: " + billMoney(summary.amount_due))));
    if (label) label.textContent = "Hours Billed";
    if (sub) sub.textContent = "";
    if (editSummary) editSummary.textContent = "Set a flat fee";
    if (removeBtn) removeBtn.style.display = "none";
    return;
  }
  let remainingSub = FEE_STATUS_TEXT[f.status] || "";
  if (f.remaining > 0 && f.due_date) {
    remainingSub = (f.overdue ? "Overdue since " : (f.plan === "half" ? "Second half due " : "Due ")) + f.due_date;
  }
  let trackedSub = "Private, not billed";
  if (f.effective_rate) {
    trackedSub = "Works out to " + billMoney(f.effective_rate) + "/hr (hourly rate " + billMoney(f.hourly_rate) + ")";
  }
  _show(box,
    _el("p", {className: "fee-mode"}, "Flat fee" + (f.description ? " — " + f.description : ""),
      " ", _el("span", {className: "sec-note"}, f.plan_label + (f.set_at ? " · since " + f.set_at.slice(0, 10) : ""))),
    _el("div", {className: "fee-tiles"},
      feeTile("Flat fee", billMoney(f.amount), f.plan === "half" ? "First half " + billMoney(f.first_payment) : ""),
      feeTile("Paid", billMoney(f.paid), "", f.remaining <= 0 ? "good" : ""),
      feeTile("Remaining", billMoney(f.remaining), remainingSub,
              f.overdue ? "bad" : (f.remaining > 0 ? "warn" : "good")),
      feeTile("Time tracked", f.tracked_hours + " hrs", trackedSub)));
  if (label) label.textContent = "Flat Fee";
  const hours = document.getElementById("ov-hours");
  if (hours) hours.textContent = billMoney(f.amount);
  if (sub) sub.textContent = f.remaining > 0
    ? billMoney(f.remaining) + " remaining" + (f.overdue ? " (overdue)" : "") : "Paid in full";
  if (editSummary) editSummary.textContent = "Change flat fee";
  if (removeBtn) removeBtn.style.display = "";
}

function feeDueLabel() {
  const plan = document.getElementById("fee-plan");
  const label = document.getElementById("fee-due-label");
  if (plan && label) label.textContent = plan.value === "half" ? "Second half due by" : "Due by";
}

// Form fields: filled when a client is opened, not on live refreshes.
function feeFillForm(summary) {
  const f = (summary || {}).flat_fee;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  set("fee-amount", f ? f.amount : "");
  set("fee-plan", f ? f.plan : "full");
  set("fee-due", f ? f.due_date : "");
  set("fee-desc", f ? f.description : "");
  set("pay-amount", "");
  set("pay-method", "check");
  set("pay-ref", "");
  ["fee-edit", "pay-edit"].forEach(id => { const d = document.getElementById(id); if (d) d.open = false; });
  feeDueLabel();
  feeResult("");
}

function feeApply(username, d, message) {
  if (_stale(username)) return;
  if (d.error) return feeResult(d.error, true);
  _currentClient.billing_summary = d.billing_summary;
  billRender(username, d.billing_summary);
  feeFillForm(d.billing_summary);
  feeResult(message, false);
}

function feeSave() {
  if (!_currentClient) return;
  const username = _currentClient.username;
  const btn = document.getElementById("fee-save-btn");
  const amount = document.getElementById("fee-amount").value;
  if (!(Number(amount) > 0)) return feeResult("Enter the flat fee amount.", true);
  _busy(btn, true);
  _postJSON("/portal/attorney/flat-fee", {
    username: username, amount: Number(amount),
    plan: document.getElementById("fee-plan").value,
    due_date: document.getElementById("fee-due").value,
    description: document.getElementById("fee-desc").value,
  }).then(d => { _busy(btn, false); feeApply(username, d, "Flat fee saved."); })
    .catch(() => { _busy(btn, false); feeResult("Couldn't save — try again.", true); });
}

function feeRemove() {
  if (!_currentClient) return;
  if (!confirm("Switch this client back to hourly billing? The flat fee comes off the amount due; " +
               "time already logged under it stays private.")) return;
  const username = _currentClient.username;
  const btn = document.getElementById("fee-remove-btn");
  _busy(btn, true);
  _postJSON("/portal/attorney/flat-fee", {username: username, action: "remove"})
    .then(d => { _busy(btn, false); feeApply(username, d, "Back to hourly billing."); })
    .catch(() => { _busy(btn, false); feeResult("Couldn't save — try again.", true); });
}

function paySave() {
  if (!_currentClient) return;
  const username = _currentClient.username;
  const btn = document.getElementById("pay-save-btn");
  const amount = Number(document.getElementById("pay-amount").value);
  if (!(amount > 0)) return feeResult("Enter the payment amount.", true);
  const method = document.getElementById("pay-method").value;
  if (!confirm("Record a " + billMoney(amount) + " " + method + " payment?")) return;
  _busy(btn, true);
  _postJSON("/portal/attorney/record-payment", {
    username: username, amount: amount, method: method,
    reference: document.getElementById("pay-ref").value,
  }).then(d => { _busy(btn, false); feeApply(username, d, billMoney(amount) + " payment recorded."); })
    .catch(() => { _busy(btn, false); feeResult("Couldn't record — try again.", true); });
}

document.addEventListener("DOMContentLoaded", () => {
  const on = (id, ev, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(ev, fn); };
  on("fee-save-btn", "click", feeSave);
  on("fee-remove-btn", "click", feeRemove);
  on("pay-save-btn", "click", paySave);
  on("fee-plan", "change", feeDueLabel);
});
