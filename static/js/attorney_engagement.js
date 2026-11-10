// Engagement letter card (Case Overview). A letter is drafted automatically
// when the client file is opened; here the attorney picks the letter type,
// edits the fee amounts and redrafts it into the Drafts folder.
// Reuses the globals from attorney_security.js: _el, _show, _note, _stale,
// _busy, _postJSON. Data only ever becomes text.

const ENG_FIELDS = {
  flat_fee:       ["flat_full", "flat_split_total", "flat_first", "flat_second", "second_due", "included"],
  hourly:         ["matter", "hourly_rate", "retainer"],
  evergreen:      ["matter", "scope", "hourly_rate", "retainer"],
  limited:        ["matter", "scope", "hourly_rate", "retainer", "flat_full"],
  non_engagement: ["matter"],
};
const ENG_LABELS = {
  flat_full: ["Option A: paid in full ($)", "e.g. 3000"],
  flat_split_total: ["Option B: two-payment total ($)", "e.g. 3500"],
  flat_first: ["Option B: first payment ($)", "e.g. 1750"],
  flat_second: ["Option B: second payment ($)", "e.g. 1750"],
  second_due: ["Second payment due", "e.g. December 15, 2026, or before the first court date"],
  included: ["Also included in the fee (optional)", "e.g. Restricted license petition"],
  matter: ["Matter (as written in the letter)", "e.g. your divorce in Davidson County Circuit Court"],
  scope: ["Scope / tasks", "e.g. reviewing and negotiating the lease"],
  hourly_rate: ["Hourly rate ($)", "e.g. 350"],
  retainer: ["Retainer ($)", "e.g. 2500"],
};
const ENG_WIDE = new Set(["second_due", "included", "matter", "scope"]);

function engDocUrl(username, d) {
  return "/portal/attorney/document/" + encodeURIComponent(username) + "/" +
    encodeURIComponent(d.category) + "/" + encodeURIComponent(d.filename);
}

function engStatus(username, eng) {
  const d = eng.draft;
  if (!d || !d.filename) return _note("No letter drafted yet. Choose the letter type and amounts, then draft it.");
  return _el("div", {className: "eng-status"},
    _el("span", {className: "eng-status-label"}, d.title + " — drafted " + (d.at || "").slice(0, 10) +
      (d.by && d.by !== "auto" ? " by " + d.by : " automatically")),
    _el("a", {href: engDocUrl(username, d), className: "btn btn-secondary eng-btn"}, "Download draft"));
}

function engFields(eng, kind) {
  const values = Object.assign({}, (eng.defaults || {})[kind] || {},
                               kind === eng.kind ? eng.terms || {} : {});
  return (ENG_FIELDS[kind] || []).map(key => {
    const [label, hint] = ENG_LABELS[key];
    const input = _el("input", {type: "text", name: key, placeholder: hint, value: values[key] || ""});
    const id = "eng-" + key;
    input.id = id;
    return _el("div", {className: "form-group" + (ENG_WIDE.has(key) ? " full" : "")},
      _el("label", {htmlFor: id}, label), input);
  });
}

function engagementRender(username, eng) {
  const card = document.getElementById("engagement-card");
  if (!card) return;
  if (!eng) { card.style.display = "none"; return; }
  card.style.display = "";
  const select = _el("select", {id: "eng-kind"},
    ...(eng.kinds || []).map(k => _el("option", {value: k.key, selected: k.key === eng.kind}, k.label)));
  select.value = eng.kind;
  const grid = _el("div", {className: "form-grid eng-grid"});
  const fill = () => _show(grid, engFields(eng, select.value));
  select.addEventListener("change", fill);
  fill();
  const btn = _el("button", {type: "button", className: "btn btn-primary eng-btn"},
    eng.draft ? "Redraft letter" : "Draft letter");
  btn.addEventListener("click", () => engSave(username, select, grid, btn));
  _show(document.getElementById("engagement-status"), engStatus(username, eng));
  _show(document.getElementById("engagement-form"),
    _el("div", {className: "form-group full"}, _el("label", {htmlFor: "eng-kind"}, "Letter type"), select),
    grid, _el("div", {className: "eng-actions"}, btn,
      _el("span", {className: "sec-note"}, "Saved to Drafts (not visible to the client). Redrafting replaces the previous draft.")));
}

function populateEngagement(c) {
  const res = document.getElementById("engagement-result");
  if (res) _show(res);
  engagementRender(c.username, c.engagement);
}

function engSave(username, select, grid, btn) {
  const terms = {};
  grid.querySelectorAll("input[name]").forEach(i => { if (i.value.trim()) terms[i.name] = i.value.trim(); });
  const res = document.getElementById("engagement-result");
  _busy(btn, true);
  _show(res, _note("Drafting…"));
  _postJSON("/portal/attorney/engagement-letter", {username: username, kind: select.value, terms: terms})
    .then(d => {
      if (_stale(username)) return;
      if (d.error) { _show(res, _note(d.error, true)); return; }
      _currentClient.engagement = d.engagement;
      engagementRender(username, d.engagement);
      _show(res, _note("Letter drafted."));
    })
    .catch(() => _show(res, _note("Couldn't draft the letter — try again.", true)))
    .finally(() => _busy(btn, false));
}
