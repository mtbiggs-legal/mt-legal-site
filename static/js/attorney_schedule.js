// Attorney portal — scheduling-order review panel and the Case dates card.
// Relies on attorney_security.js globals (_el, _show, _note, _stale, _busy, _postJSON),
// attorney_portal.html globals (_currentClient, loadDashboard) and window._CASE_DATE_LABELS.
// XSS rule: every element is built with _el(); untrusted values only ever become
// text nodes or input .value. No HTML strings.

let schedFile = null;
let schedUser = null;

function schedEl(id) { return document.getElementById(id); }

function schedLabels() { return window._CASE_DATE_LABELS || []; }

function schedCurrent(d) {
  return (d && d.current) || (_currentClient && _currentClient.case_dates) || {};
}

function schedFmt(d) { return (d && d.date) ? d.date : "—"; }

function openSchedReview(filename) {
  if (!_currentClient) return;
  const username = _currentClient.username;
  schedFile = filename;
  schedUser = username;
  const panel = schedEl("sched-review");
  panel.style.display = "block";
  schedEl("sched-file").textContent = filename;
  _show(schedEl("sched-rows"));
  _show(schedEl("sched-notes"));
  _show(schedEl("sched-result"));
  _show(schedEl("sched-status"), _note("Reading the order…"));
  _busy(schedEl("sched-save"), true);
  panel.scrollIntoView({behavior: "smooth", block: "nearest"});
  _postJSON("/portal/attorney/scheduling-order/extract", {username, filename})
    .then(d => {
      if (_stale(username) || schedFile !== filename) return;
      schedRender(filename, d);
    })
    .catch(() => {
      if (_stale(username) || schedFile !== filename) return;
      schedRender(filename, {success: false, error: "Request failed."});
    });
}

function schedRender(filename, d) {
  const extracted = (d.success && d.extraction && d.extraction.dates) || {};
  const current = schedCurrent(d);
  if (d.success) {
    _show(schedEl("sched-status"));
  } else {
    _show(schedEl("sched-status"),
          _note((d.error || "Could not read the order.") + " You can enter the dates below.", true));
  }
  _show(schedEl("sched-rows"), schedLabels().map(item => {
    const kind = item.kind;
    const ex = extracted[kind];
    const cur = current[kind];
    const curDate = cur && cur.date ? cur.date : "";
    const input = _el("input", {type: "date", id: "sched-date-" + kind,
                                value: (ex && ex.date) || curDate || ""});
    input.dataset.kind = kind;
    const conf = ex && ex.confidence ? String(ex.confidence).toLowerCase() : "";
    const low = conf === "low";
    const row = _el("div", {className: "sched-row" + (low ? " sched-low" : "")},
      _el("label", {htmlFor: "sched-date-" + kind}, item.label),
      input,
      (curDate && curDate !== input.value)
        ? _el("span", {className: "sched-was"}, "was " + curDate) : null,
      conf ? _el("span", {className: "sched-conf sched-conf-" + (["high", "medium", "low"].includes(conf) ? conf : "low")},
                 conf + " confidence") : null,
      (ex && ex.evidence)
        ? _el("div", {className: "sched-evidence"},
              (ex.page ? "p. " + ex.page + " — " : "") + ex.evidence) : null);
    return row;
  }));
  const notes = d.success && d.extraction && d.extraction.notes;
  _show(schedEl("sched-notes"), notes ? _note(notes) : null);
  _busy(schedEl("sched-save"), false);
}

function schedSave(confirmClear) {
  if (!_currentClient || !schedFile) return;
  const username = _currentClient.username;
  const filename = schedFile;
  const saveBtn = schedEl("sched-save");
  const out = schedEl("sched-result");
  const inputs = schedEl("sched-rows").querySelectorAll("input[type=date]");
  if (inputs.length !== schedLabels().length) return;
  const dates = {};
  inputs.forEach(i => { dates[i.dataset.kind] = i.value; });
  let resubmitted = false;
  const live = () => !_stale(username) && schedFile === filename;
  const body = {username, filename, dates};
  if (confirmClear === true) body.confirm_clear = true;
  _show(out, _note("Saving…"));
  _busy(saveBtn, true);
  _postJSON("/portal/attorney/scheduling-order/confirm", body)
    .then(d => {
      if (!live()) return;
      if (!d.success) {
        if (Array.isArray(d.would_clear) && d.would_clear.length && confirmClear !== true) {
          const names = schedLabels().filter(i => d.would_clear.includes(i.kind)).map(i => i.label);
          if (confirm("This will remove: " + names.join(", ") + ". Continue?")) {
            resubmitted = true;
            return schedSave(true);
          }
          return _show(out, _note("Nothing was changed."));
        }
        return _show(out, _note(d.error || "Save failed.", true));
      }
      _show(out,
        _note(d.unchanged ? "No changes." : "Saved."),
        (d.warnings || []).map(w => _note(w, true)));
      _currentClient.case_dates = d.case_dates;
      if (d.case_dates_history) _currentClient.case_dates_history = d.case_dates_history;
      populateCaseDates(_currentClient);
      const dash = document.getElementById("atty-dashboard");
      if (window.loadDashboard && dash && dash.classList.contains("active")) loadDashboard();
    })
    .catch(() => {
      if (live()) _show(out, _note("Request failed — reload the page and try again.", true));
    })
    .finally(() => { if (live() && !resubmitted) _busy(saveBtn, false); });
}

function populateCaseDates(c) {
  const list = schedEl("case-dates-list");
  const histBtn = schedEl("case-dates-history-btn");
  const hist = schedEl("case-dates-history");
  if (!list) return;
  if (schedUser && schedUser !== c.username) {
    schedFile = null;
    schedUser = null;
    schedEl("sched-review").style.display = "none";
  }
  const cd = c.case_dates || {};
  _show(list, schedLabels().map(item => {
    const e = cd[item.kind];
    return _el("div", {className: "sched-row"},
      _el("strong", {style: "flex:0 0 11rem"}, item.label),
      _el("span", {}, schedFmt(e)),
      (e && e.source) ? _el("span", {className: "sched-was"}, e.source) : null);
  }));
  const history = c.case_dates_history || [];
  hist.style.display = "none";
  _show(hist);
  if (!history.length) {
    histBtn.style.display = "none";
    return;
  }
  histBtn.style.display = "";
  histBtn.textContent = "History (" + history.length + ")";
  _show(hist, history.slice().reverse().map(h => {
    const prev = h.previous || {};
    return _el("div", {className: "sched-row"},
      _el("div", {className: "sec-note", style: "flex:1 1 100%"},
          (h.replaced_at || "") + " · replaced by " + (h.replaced_by || "")),
      schedLabels().filter(item => prev[item.kind]).map(item =>
        _el("span", {}, item.label + ": " + schedFmt(prev[item.kind]))));
  }));
}

document.addEventListener("DOMContentLoaded", () => {
  const cancel = schedEl("sched-cancel");
  if (!cancel) return;
  cancel.addEventListener("click", () => {
    schedFile = null;
    schedEl("sched-review").style.display = "none";
  });
  schedEl("sched-save").addEventListener("click", () => schedSave());
  schedEl("case-dates-history-btn").addEventListener("click", () => {
    const h = schedEl("case-dates-history");
    h.style.display = h.style.display === "none" ? "block" : "none";
  });
});
