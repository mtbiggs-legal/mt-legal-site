// attorney_clients.js: Leads to clients, the New Client tab, and the all-clients list.
// Split out of attorney_portal.js; loaded right after it (see attorney_portal.html),
// and like it, defines global functions the templates call.

// ── Lead helpers ───────────────────────────────────────────────────────────────
function toggleLead(header) {
  const detail  = header.nextElementSibling;
  const chevron = header.querySelector(".lead-chevron");
  const open    = detail.style.display !== "none";
  detail.style.display = open ? "none" : "block";
  chevron.classList.toggle("open", !open);
}

function convertLead(btn) {
  const l = JSON.parse(btn.getAttribute("data-lead").replace(/&#39;/g,"'"));
  // Archive the lead so it disappears from the leads list
  if (l._filename) {
    fetch("/portal/attorney/archive-lead", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({filename: l._filename})
    }).then(() => populateLeads());
  }
  showNewClientTab(null);
  document.getElementById("nc-name").value        = l.name       || "";
  document.getElementById("nc-phone").value       = l.phone      || "";
  document.getElementById("nc-email").value       = l.email      || "";
  document.getElementById("nc-legal-issue").value = l.message || l.notes || "";
  const ct = document.getElementById("nc-case-type");
  if (l.case_type) {
    for (let i = 0; i < ct.options.length; i++) {
      if (ct.options[i].value === l.case_type) { ct.selectedIndex = i; break; }
    }
  }
  document.getElementById("nc-name").focus();
}

// ── New Client tab ─────────────────────────────────────────────────────────────
function showNewClientTab(btn) {
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-new-client").classList.add("active");
  if (btn) btn.classList.add("active");
  else document.getElementById("new-client-tab-btn").classList.add("active");
  _currentClient = null;
}

function confirmNewClient() {
  location.reload();
}

function resetNewClientForm() {
  document.getElementById("nc-success-card").style.display = "none";
  document.getElementById("nc-form-card").style.display    = "block";
  ["nc-name","nc-phone","nc-email","nc-username","nc-legal-issue"].forEach(id => {
    document.getElementById(id).value = "";
  });
  document.getElementById("nc-opposing").value = "";
  document.getElementById("nc-related-list").replaceChildren();
  document.getElementById("nc-form-card").appendChild(document.getElementById("nc-result"));
  document.getElementById("nc-result").innerHTML = "";
}

// ── Create new client ─────────────────────────────────────────────────────────
function createClient() {
  const name     = document.getElementById("nc-name").value.trim();
  const username = document.getElementById("nc-username").value.trim();
  const res      = document.getElementById("nc-result");
  if (!name) {
    res.replaceChildren(_note("Full name is required.", true));
    return;
  }
  res.innerHTML = '<p style="color:var(--gray-3);font-family:Arial,sans-serif;font-size:.88rem">Creating…</p>';
  const createBtn = document.getElementById("nc-create-btn");
  if (createBtn) createBtn.disabled = true;
  fetch("/portal/attorney/create-client", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({
      client_name:          name,
      username,
      case_type:            document.getElementById("nc-case-type").value,
      phone:                document.getElementById("nc-phone").value,
      email:                document.getElementById("nc-email").value,
      legal_issue:          document.getElementById("nc-legal-issue").value,
      opposing_parties:     document.getElementById("nc-opposing").value.split("\n").map(s => s.trim()).filter(Boolean),
      related_parties:      collectRelated(document.getElementById("nc-related-list")),
    })
  }).then(r => r.json()).then(d => {
    if (d.success) {
      // Show credentials card, hide form
      document.getElementById("nc-form-card").style.display    = "none";
      document.getElementById("nc-success-username").textContent = d.username || username;
      document.getElementById("nc-success-invite").textContent = d.invite_sent
        ? "Emailed to the client." : "Not emailed (no address, or email isn't set up).";
      document.getElementById("nc-success-link").value = d.invite_link || "";
      document.getElementById("nc-success-card").style.display  = "block";
      // Surface any conflict-of-interest matches
      if (d.conflict_hits && d.conflict_hits.length) {
        res.replaceChildren(
          _note("⚠ Conflict check matches — review before proceeding.", true),
          hitsTable(d.conflict_hits));
        document.getElementById("nc-success-card").appendChild(res);
      } else {
        res.replaceChildren();
      }
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${escHtml(d.error || 'Unknown error')}</p>`;
    }
  }).catch(() => {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Request failed.</p>';
  }).finally(() => { if (createBtn) createBtn.disabled = false; });
}

// ── All clients master list ───────────────────────────────────────────────────

function showAllClients(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".see-all-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-all-clients").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  // clear any prior filter
  var inp = document.getElementById("all-clients-search");
  if (inp) inp.value = "";
  filterAllClientsTable("");
}

function filterAllClientsTable(q) {
  q = (q || "").toLowerCase().trim();
  document.querySelectorAll("#all-clients-tbody .all-clients-row").forEach(row => {
    var name = row.getAttribute("data-name") || "";
    row.style.display = (!q || name.includes(q)) ? "" : "none";
  });
}

var _acSortCol = null, _acSortDir = "asc";
function sortAllClients(col, th) {
  // toggle direction
  if (_acSortCol === col) {
    _acSortDir = _acSortDir === "asc" ? "desc" : "asc";
  } else {
    _acSortCol = col; _acSortDir = "asc";
  }
  // update header arrows
  document.querySelectorAll(".all-clients-table thead th").forEach(h => {
    h.classList.remove("sort-asc", "sort-desc");
  });
  th.classList.add(_acSortDir === "asc" ? "sort-asc" : "sort-desc");
  // sort rows
  var tbody = document.getElementById("all-clients-tbody");
  var rows = Array.from(tbody.querySelectorAll(".all-clients-row"));
  rows.sort(function(a, b) {
    var av = (a.querySelector('td[data-col="' + col + '"]') || {}).textContent || "";
    var bv = (b.querySelector('td[data-col="' + col + '"]') || {}).textContent || "";
    av = av.trim(); bv = bv.trim();
    // numeric columns
    if (col === "hours" || col === "balance") {
      var an = parseFloat(av) || 0, bn = parseFloat(bv) || 0;
      return _acSortDir === "asc" ? an - bn : bn - an;
    }
    return _acSortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  rows.forEach(r => tbody.appendChild(r));
}
