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
