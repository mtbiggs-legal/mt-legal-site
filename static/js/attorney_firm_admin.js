// Firm Admin tab: deadlines, "mark done" records, add / edit items.
// Reuses the globals from attorney_security.js: _el, _show, _note, _busy,
// _postJSON, _table. Data only ever becomes text.

let _faData = null;

const FA_STATUS = {
  overdue: ["Overdue", "bad"], due_soon: ["Due soon", "warn"], needs_date: ["Needs a due date", "info"],
  ok: ["On track", "good"], off: ["Not tracked", "muted"],
};

function faResult(id, text, isError) {
  const box = document.getElementById(id);
  if (box) _show(box, text ? _note(text, isError) : null);
}

function faWhen(o) {
  if (o.status === "off") return "Reminders off";
  if (o.status === "needs_date") return "Set a due date to get reminders";
  if (!o.next_due) return "Nothing due";
  const d = o.days_left;
  if (d < 0) return "Was due " + o.next_due + " (" + (-d) + " day" + (d === -1 ? "" : "s") + " ago)";
  return "Due " + o.next_due + (d === 0 ? " (today)" : " (in " + d + " day" + (d === 1 ? "" : "s") + ")");
}

function faItem(o) {
  const [label, tone] = FA_STATUS[o.status] || ["", ""];
  const head = _el("div", {className: "fa-item-head"},
    _el("span", {className: "fa-title"}, o.title),
    _el("span", {className: "fa-chip fa-" + tone}, label),
    o.stage && o.stage !== "overdue" ? _el("span", {className: "fa-chip fa-stage"}, o.stage + "-day reminder") : null);
  const meta = _el("div", {className: "fa-meta"},
    _el("span", {}, o.category), " · ", _el("span", {}, faWhen(o)),
    o.amount ? " · " + o.amount : "",
    o.last_record ? " · Last done " + o.last_record.completed_on : "");
  const notes = o.notes ? _el("div", {className: "fa-notes"}, o.notes, " ",
    o.link ? _el("a", {href: o.link, target: "_blank", rel: "noopener"}, "Open site ↗") : null)
    : (o.link ? _el("div", {className: "fa-notes"}, _el("a", {href: o.link, target: "_blank", rel: "noopener"}, "Open site ↗")) : null);

  const actions = _el("div", {className: "fa-item-actions"});
  if (o.next_due && o.status !== "off") {
    const done = _el("button", {type: "button", className: "btn btn-primary fa-small"}, "Mark done");
    done.addEventListener("click", () => faOpenDone(o, wrap));
    actions.append(done);
  }
  const edit = _el("button", {type: "button", className: "btn btn-secondary fa-small"}, "Edit");
  edit.addEventListener("click", () => faOpenEdit(o));
  actions.append(edit);

  const wrap = _el("div", {className: "fa-item fa-item-" + o.status}, head, meta, notes, actions,
    _el("div", {className: "fa-done-form"}));
  return wrap;
}

function faOpenDone(o, wrap) {
  const box = wrap.querySelector(".fa-done-form");
  if (box.childNodes.length) { _show(box); return; }
  const now = new Date();
  const today = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" +
                String(now.getDate()).padStart(2, "0");
  const on = _el("input", {type: "date", value: today});
  const amount = _el("input", {type: "text", maxLength: 40, placeholder: o.amount || "Amount paid"});
  const conf = _el("input", {type: "text", maxLength: 80, placeholder: "Confirmation / receipt no."});
  const note = _el("input", {type: "text", maxLength: 500, placeholder: "Note (optional)"});
  const save = _el("button", {type: "button", className: "btn btn-primary fa-small"}, "Save record");
  save.addEventListener("click", () => {
    _busy(save, true);
    _postJSON("/portal/attorney/firm-admin/complete", {
      id: o.id, due: o.next_due, completed_on: on.value, amount: amount.value,
      confirmation: conf.value, note: note.value,
    }).then(d => {
      _busy(save, false);
      if (d.error) return faResult("fa-result", d.error, true);
      faRender(d);
      faResult("fa-result", o.title + " marked done for " + o.next_due + ". Reminders for it have stopped.");
    }).catch(() => { _busy(save, false); faResult("fa-result", "Couldn't save — try again.", true); });
  });
  _show(box, _el("div", {className: "fa-done-grid"},
    _el("label", {}, "Done on", on), _el("label", {}, "Amount", amount),
    _el("label", {}, "Confirmation", conf), _el("label", {}, "Note", note)), save);
}

function faRender(d) {
  _faData = d;
  const list = document.getElementById("fa-list");
  if (list) _show(list, (d.obligations || []).map(faItem));
  const recs = d.records || [];
  const recBox = document.getElementById("fa-records");
  if (recBox) {
    if (!recs.length) {
      _show(recBox, _note("Nothing marked done yet. Each completion is kept here."));
    } else {
      _show(recBox, _table(["Item", "Due", "Done", "Amount", "Confirmation", "Note", ""], recs.map(r => {
        const undo = _el("button", {type: "button", className: "btn btn-secondary fa-small"}, "Undo");
        undo.addEventListener("click", () => faUndo(r, undo));
        return [r.title, r.due, r.completed_on, r.amount || "—", r.confirmation || "—", r.note || "", undo];
      })));
    }
  }
  faBadge(d);
}

function faBadge(d) {
  const badge = document.getElementById("fa-badge");
  if (!badge) return;
  const n = (d.obligations || []).filter(o => o.status === "overdue" || o.status === "due_soon").length;
  badge.textContent = n;
  badge.style.display = n ? "" : "none";
}

function faUndo(r, btn) {
  if (!confirm("Undo the record for " + r.title + " (due " + r.due + ")? Its reminders come back.")) return;
  _busy(btn, true);
  _postJSON("/portal/attorney/firm-admin/record/delete", {record_id: r.id})
    .then(d => { if (d.error) { _busy(btn, false); return faResult("fa-result", d.error, true); } faRender(d); })
    .catch(() => _busy(btn, false));
}

function loadFirmAdmin() {
  fetch("/portal/attorney/firm-admin")
    .then(r => r.json())
    .then(d => d.error ? faResult("fa-result", d.error, true) : faRender(d))
    .catch(() => faResult("fa-result", "Couldn't load firm admin items.", true));
}

function showFirmAdmin(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-firm-admin").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  faCloseEdit();
  faResult("fa-result", "");
  loadFirmAdmin();
}

// ── Add / edit ──────────────────────────────────────────────────────────────

function faRepeatToggle() {
  const once = document.getElementById("fa-edit-repeat").value === "once";
  document.getElementById("fa-edit-dates-wrap").style.display = once ? "none" : "";
  document.getElementById("fa-edit-date-wrap").style.display = once ? "" : "none";
}

function faOpenEdit(o) {
  const set = (id, v) => { document.getElementById(id).value = v || ""; };
  const sched = (o && o.schedule) || {repeat: "yearly", dates: []};
  set("fa-edit-id", o ? o.id : "");
  set("fa-edit-name", o ? o.title : "");
  set("fa-edit-category", o ? o.category : "");
  set("fa-edit-repeat", sched.repeat || "yearly");
  set("fa-edit-dates", (sched.dates || []).join(", "));
  set("fa-edit-date", sched.date || "");
  set("fa-edit-amount", o ? o.amount : "");
  set("fa-edit-link", o ? o.link : "");
  set("fa-edit-notes", o ? o.notes : "");
  document.getElementById("fa-edit-active").checked = o ? o.active !== false : true;
  document.getElementById("fa-edit-title").textContent = o ? "Edit item" : "Add item";
  document.getElementById("fa-edit-delete").style.display = o ? "" : "none";
  faRepeatToggle();
  faResult("fa-edit-result", "");
  const card = document.getElementById("fa-edit-card");
  card.style.display = "";
  card.scrollIntoView({behavior: "smooth", block: "start"});
}

function faCloseEdit() {
  const card = document.getElementById("fa-edit-card");
  if (card) card.style.display = "none";
}

function faSaveEdit() {
  const btn = document.getElementById("fa-edit-save");
  const val = id => document.getElementById(id).value;
  _busy(btn, true);
  _postJSON("/portal/attorney/firm-admin/item", {
    id: val("fa-edit-id") || undefined, title: val("fa-edit-name"), category: val("fa-edit-category"),
    repeat: val("fa-edit-repeat"), dates: val("fa-edit-dates"), date: val("fa-edit-date"),
    amount: val("fa-edit-amount"), link: val("fa-edit-link"), notes: val("fa-edit-notes"),
    active: document.getElementById("fa-edit-active").checked,
  }).then(d => {
    _busy(btn, false);
    if (d.error) return faResult("fa-edit-result", d.error, true);
    faRender(d);
    faCloseEdit();
    faResult("fa-result", "Saved.");
  }).catch(() => { _busy(btn, false); faResult("fa-edit-result", "Couldn't save — try again.", true); });
}

function faDeleteItem() {
  const id = document.getElementById("fa-edit-id").value;
  if (!id || !confirm("Remove this item? Its past records stay in the history.")) return;
  _postJSON("/portal/attorney/firm-admin/item/delete", {id: id})
    .then(d => {
      if (d.error) return faResult("fa-edit-result", d.error, true);
      faRender(d);
      faCloseEdit();
    });
}

document.addEventListener("DOMContentLoaded", () => {
  const on = (id, ev, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(ev, fn); };
  on("fa-add-btn", "click", () => faOpenEdit(null));
  on("fa-edit-save", "click", faSaveEdit);
  on("fa-edit-cancel", "click", faCloseEdit);
  on("fa-edit-delete", "click", faDeleteItem);
  on("fa-edit-repeat", "change", faRepeatToggle);
  // Sidebar badge on page load.
  fetch("/portal/attorney/firm-admin").then(r => r.json()).then(d => { if (!d.error) faBadge(d); }).catch(() => {});
});
