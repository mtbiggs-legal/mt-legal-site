// Attorney portal behaviour. Page data (window._ALL_CLIENTS_DATA, window._ATTORNEYS,
// window._CASE_DATE_LABELS) is set by attorney_portal.html; window._FIRM_NAME by base.html.
// ── Leads ─────────────────────────────────────────────────────────────────────
function loadLeads(btn) {
  // Deselect client tabs, hide client tab nav
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("tab-leads").classList.add("active");
  if (btn) btn.classList.add("active");

  fetch("/portal/attorney/leads-list")
    .then(r => r.json())
    .then(leads => {
      const wrap = document.getElementById("leads-list-wrap");
      if (!leads.length) {
        wrap.innerHTML = `<div class="card" style="text-align:center;padding:2.5rem;color:var(--gray-3)">
          <div style="font-size:2rem;margin-bottom:.5rem">📬</div>
          <p style="font-family:Arial,sans-serif">No leads yet. Follow-up requests and consultation inquiries will appear here.</p>
        </div>`;
        return;
      }
      // Update badge
      const badge = document.getElementById("leads-badge");
      badge.textContent = leads.length;
      badge.style.display = "inline-block";

      wrap.innerHTML = leads.map((l, i) => {
        const accentColor = l.case_type === 'Civil Litigation' ? 'var(--navy)' : 'var(--gold)';
        const date = (l.timestamp||'').slice(0,8).replace(/(\d{4})(\d{2})(\d{2})/,'$2/$3/$1');
        const msg  = l.message || l.notes || '';
        const preview = msg.length > 60 ? msg.slice(0,60) + '…' : msg;
        const safe = escHtml(JSON.stringify(l)).replace(/'/g,"&#39;");
        return `
        <div class="card lead-card" style="border-left:4px solid ${accentColor}">
          <div class="lead-card-header" onclick="toggleLead(this)">
            <div style="flex:1;min-width:0">
              <div style="font-family:Georgia,serif;font-size:1rem;font-weight:bold;color:var(--navy);margin-bottom:.2rem">${escHtml(l.name||'—')}</div>
              <div style="display:flex;align-items:center;gap:.55rem;flex-wrap:wrap">
                <span style="font-family:Arial,sans-serif;font-size:.72rem;font-weight:bold;text-transform:uppercase;letter-spacing:.06em;color:${accentColor}">${escHtml(l.case_type||'Unspecified')}</span>
                ${l.type === 'follow_up' ? '<span style="font-family:Arial,sans-serif;font-size:.7rem;background:#e8f0fe;color:#1a2d5a;padding:.1rem .45rem;border-radius:10px">Follow-up</span>' : ''}
                ${preview ? `<span style="font-family:Arial,sans-serif;font-size:.78rem;color:var(--gray-3);font-style:italic">"${escHtml(preview)}"</span>` : ''}
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:.4rem;flex-shrink:0;margin-left:.75rem">
              <span style="font-family:Arial,sans-serif;font-size:.75rem;color:var(--gray-3)">${date}</span>
              <span class="lead-chevron">▾</span>
            </div>
          </div>
          <div class="lead-card-detail" style="display:none">
            ${l.phone ? `<div class="lead-detail-row"><div class="lead-detail-lbl">Phone</div><div class="lead-detail-val">📞 ${escHtml(l.phone)}</div></div>` : ''}
            ${l.email ? `<div class="lead-detail-row"><div class="lead-detail-lbl">Email</div><div class="lead-detail-val">✉ ${escHtml(l.email)}</div></div>` : ''}
            ${l.source ? `<div class="lead-detail-row"><div class="lead-detail-lbl">Source</div><div class="lead-detail-val">${escHtml(l.source)}</div></div>` : ''}
            ${msg ? `<div style="margin-top:.5rem"><div class="lead-detail-lbl" style="margin-bottom:.35rem">Message</div><div class="lead-full-msg">${escHtml(msg)}</div></div>` : ''}
            <button class="btn btn-primary" style="font-size:.83rem;padding:.42rem 1rem"
              onclick="convertLead(this)" data-lead='${safe}'>Convert to Client →</button>
          </div>
        </div>`;
      }).join("");
    });
}

// Close modals on Escape
document.addEventListener("keydown", function(e) {
  if (e.key === "Escape") {
    closeDocPreview();
    document.getElementById("meeting-modal").style.display          = "none";
    document.getElementById("dash-add-event-modal").style.display   = "none";
    document.getElementById("dash-log-time-modal").style.display    = "none";
  }
});

// Auto-load leads count + init drop zone on page load
// ── Client search ────────────────────────────────────────────────
function filterClientList(q) {
  q = q.toLowerCase().trim();
  document.querySelectorAll("#client-list .client-list-item, #archived-client-list .client-list-item").forEach(btn => {
    var name = btn.getAttribute("data-name") || btn.textContent.toLowerCase();
    var matches = !q || name.includes(q);
    if (!q) {
      btn.style.display = ""; // let CSS class (sidebar-hidden) take over
    } else {
      btn.style.display = matches ? "block" : "none";
    }
  });
  // auto-expand archived section if a match lives there
  var archivedList = document.getElementById("archived-client-list");
  if (archivedList && q) {
    var hasVisible = Array.from(archivedList.querySelectorAll(".client-list-item")).some(b => b.style.display !== "none");
    if (hasVisible) {
      archivedList.style.display = "";
      var chev = document.getElementById("archived-chevron");
      if (chev) chev.textContent = "▾";
    }
  }
}

// ── Archived clients toggle ───────────────────────────────────────
function toggleArchivedList() {
  var list = document.getElementById("archived-client-list");
  var chev = document.getElementById("archived-chevron");
  if (!list) return;
  var open = list.style.display !== "none";
  list.style.display = open ? "none" : "";
  if (chev) chev.textContent = open ? "▸" : "▾";
}

// ── Archive / Unarchive client ────────────────────────────────────
function archiveClient() {
  if (!_currentClient) return;
  if (!confirm("Archive " + (_currentClient.client_name || _currentClient.username) + "? They will be moved to the Archived section.")) return;
  fetch("/portal/attorney/archive-client", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({username: _currentClient.username})
  }).then(r => r.json()).then(d => {
    if (d.success) location.reload();
    else document.getElementById("ov-archive-result").textContent = d.error || "Error.";
  }).catch(() => { document.getElementById("ov-archive-result").textContent = "Request failed."; });
}

function unarchiveClient() {
  if (!_currentClient) return;
  fetch("/portal/attorney/unarchive-client", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({username: _currentClient.username})
  }).then(r => r.json()).then(d => {
    if (d.success) location.reload();
    else document.getElementById("ov-archive-result").textContent = d.error || "Error.";
  }).catch(() => { document.getElementById("ov-archive-result").textContent = "Request failed."; });
}

window.addEventListener("DOMContentLoaded", function() {
  initDocDropZone();
  loadDashboard();
  fetch("/portal/attorney/leads-list")
    .then(r => r.json())
    .then(leads => {
      if (leads.length) {
        const badge = document.getElementById("leads-badge");
        badge.textContent = leads.length;
        badge.style.display = "inline-block";
      }
    }).catch(() => {});

  // Initialise county + court searchable selects
  _ssCounty = initSearchSelect("ov-county-input", "ss-county-dropdown", TN_COUNTIES, function(county) {
    var courts = TN_COURTS[county] || [];
    _ssCourt.setOptions(courts);
  });
  _ssCourt = initSearchSelect("ov-court-input", "ss-court-dropdown", [], null);
});

var _currentClient = null;

// ── Tennessee county + court data ─────────────────────────────────────────────
var TN_COUNTIES = ["Anderson","Bedford","Benton","Bledsoe","Blount","Bradley","Campbell","Cannon","Carroll","Carter","Cheatham","Chester","Claiborne","Clay","Cocke","Coffee","Crockett","Cumberland","Davidson","Decatur","DeKalb","Dickson","Dyer","Fayette","Fentress","Franklin","Gibson","Giles","Grainger","Greene","Grundy","Hamblen","Hamilton","Hancock","Hardeman","Hardin","Hawkins","Haywood","Henderson","Henry","Hickman","Houston","Humphreys","Jackson","Jefferson","Johnson","Knox","Lake","Lauderdale","Lawrence","Lewis","Lincoln","Loudon","Macon","Madison","Marion","Marshall","Maury","McMinn","McNairy","Meigs","Monroe","Montgomery","Moore","Morgan","Obion","Overton","Perry","Pickett","Polk","Putnam","Rhea","Roane","Robertson","Rutherford","Scott","Sequatchie","Sevier","Shelby","Smith","Stewart","Sullivan","Sumner","Tipton","Trousdale","Unicoi","Union","Van Buren","Warren","Washington","Wayne","Weakley","White","Williamson","Wilson"];

var TN_COURTS = {
  "Anderson":   ["Anderson County Criminal Court","Anderson County Circuit Court","Anderson County General Sessions Court","Anderson County Chancery Court","Anderson County Juvenile Court"],
  "Bedford":    ["Bedford County Circuit Court","Bedford County General Sessions Court","Bedford County Chancery Court","Bedford County Juvenile Court"],
  "Benton":     ["Benton County Circuit Court","Benton County General Sessions Court","Benton County Chancery Court","Benton County Juvenile Court"],
  "Bledsoe":    ["Bledsoe County Circuit Court","Bledsoe County General Sessions Court","Bledsoe County Chancery Court","Bledsoe County Juvenile Court"],
  "Blount":     ["Blount County Criminal Court","Blount County Circuit Court","Blount County General Sessions Court","Blount County Chancery Court","Blount County Juvenile Court"],
  "Bradley":    ["Bradley County Criminal Court","Bradley County Circuit Court","Bradley County General Sessions Court","Bradley County Chancery Court","Bradley County Juvenile Court","Bradley County Drug Court"],
  "Campbell":   ["Campbell County Criminal Court","Campbell County Circuit Court","Campbell County General Sessions Court","Campbell County Chancery Court","Campbell County Juvenile Court"],
  "Cannon":     ["Cannon County Circuit Court","Cannon County General Sessions Court","Cannon County Chancery Court","Cannon County Juvenile Court"],
  "Carroll":    ["Carroll County Circuit Court","Carroll County General Sessions Court","Carroll County Chancery Court","Carroll County Juvenile Court"],
  "Carter":     ["Carter County Criminal Court","Carter County Circuit Court","Carter County General Sessions Court","Carter County Chancery Court","Carter County Juvenile Court"],
  "Cheatham":   ["Cheatham County Circuit Court","Cheatham County General Sessions Court","Cheatham County Chancery Court","Cheatham County Juvenile Court"],
  "Chester":    ["Chester County Circuit Court","Chester County General Sessions Court","Chester County Chancery Court","Chester County Juvenile Court"],
  "Claiborne":  ["Claiborne County Criminal Court","Claiborne County Circuit Court","Claiborne County General Sessions Court","Claiborne County Chancery Court","Claiborne County Juvenile Court"],
  "Clay":       ["Clay County Circuit Court","Clay County General Sessions Court","Clay County Chancery Court","Clay County Juvenile Court"],
  "Cocke":      ["Cocke County Criminal Court","Cocke County Circuit Court","Cocke County General Sessions Court","Cocke County Chancery Court","Cocke County Juvenile Court"],
  "Coffee":     ["Coffee County Criminal Court","Coffee County Circuit Court","Coffee County General Sessions Court","Coffee County Chancery Court","Coffee County Juvenile Court","Coffee County Drug Court"],
  "Crockett":   ["Crockett County Circuit Court","Crockett County General Sessions Court","Crockett County Chancery Court","Crockett County Juvenile Court"],
  "Cumberland": ["Cumberland County Criminal Court","Cumberland County Circuit Court","Cumberland County General Sessions Court","Cumberland County Chancery Court","Cumberland County Juvenile Court"],
  "Davidson":   ["Davidson County Criminal Court — Division I","Davidson County Criminal Court — Division II","Davidson County Criminal Court — Division III","Davidson County Criminal Court — Division IV","Davidson County Circuit Court","Davidson County General Sessions Court — Division I","Davidson County General Sessions Court — Division II","Davidson County General Sessions Court — Division III","Davidson County General Sessions Court — Division IV","Davidson County Chancery Court","Davidson County Juvenile Court","Davidson County Drug Court","Davidson County DUI Court","Davidson County Mental Health Court","Davidson County Veterans Treatment Court","Davidson County Probate Court","Davidson County Environmental Court"],
  "Decatur":    ["Decatur County Circuit Court","Decatur County General Sessions Court","Decatur County Chancery Court","Decatur County Juvenile Court"],
  "DeKalb":     ["DeKalb County Circuit Court","DeKalb County General Sessions Court","DeKalb County Chancery Court","DeKalb County Juvenile Court"],
  "Dickson":    ["Dickson County Criminal Court","Dickson County Circuit Court","Dickson County General Sessions Court","Dickson County Chancery Court","Dickson County Juvenile Court"],
  "Dyer":       ["Dyer County Criminal Court","Dyer County Circuit Court","Dyer County General Sessions Court","Dyer County Chancery Court","Dyer County Juvenile Court"],
  "Fayette":    ["Fayette County Circuit Court","Fayette County General Sessions Court","Fayette County Chancery Court","Fayette County Juvenile Court"],
  "Fentress":   ["Fentress County Criminal Court","Fentress County Circuit Court","Fentress County General Sessions Court","Fentress County Chancery Court","Fentress County Juvenile Court"],
  "Franklin":   ["Franklin County Criminal Court","Franklin County Circuit Court","Franklin County General Sessions Court","Franklin County Chancery Court","Franklin County Juvenile Court"],
  "Gibson":     ["Gibson County Circuit Court","Gibson County General Sessions Court","Gibson County Chancery Court","Gibson County Juvenile Court"],
  "Giles":      ["Giles County Circuit Court","Giles County General Sessions Court","Giles County Chancery Court","Giles County Juvenile Court"],
  "Grainger":   ["Grainger County Circuit Court","Grainger County General Sessions Court","Grainger County Chancery Court","Grainger County Juvenile Court"],
  "Greene":     ["Greene County Criminal Court","Greene County Circuit Court","Greene County General Sessions Court","Greene County Chancery Court","Greene County Juvenile Court"],
  "Grundy":     ["Grundy County Circuit Court","Grundy County General Sessions Court","Grundy County Chancery Court","Grundy County Juvenile Court"],
  "Hamblen":    ["Hamblen County Criminal Court","Hamblen County Circuit Court","Hamblen County General Sessions Court","Hamblen County Chancery Court","Hamblen County Juvenile Court"],
  "Hamilton":   ["Hamilton County Criminal Court — Division I","Hamilton County Criminal Court — Division II","Hamilton County Criminal Court — Division III","Hamilton County Circuit Court","Hamilton County General Sessions Court — Division I","Hamilton County General Sessions Court — Division II","Hamilton County General Sessions Court — Division III","Hamilton County Chancery Court","Hamilton County Juvenile Court","Hamilton County Drug Court","Hamilton County DUI Court","Hamilton County Mental Health Court","Hamilton County Probate Court"],
  "Hancock":    ["Hancock County Circuit Court","Hancock County General Sessions Court","Hancock County Chancery Court","Hancock County Juvenile Court"],
  "Hardeman":   ["Hardeman County Circuit Court","Hardeman County General Sessions Court","Hardeman County Chancery Court","Hardeman County Juvenile Court"],
  "Hardin":     ["Hardin County Circuit Court","Hardin County General Sessions Court","Hardin County Chancery Court","Hardin County Juvenile Court"],
  "Hawkins":    ["Hawkins County Criminal Court","Hawkins County Circuit Court","Hawkins County General Sessions Court","Hawkins County Chancery Court","Hawkins County Juvenile Court"],
  "Haywood":    ["Haywood County Circuit Court","Haywood County General Sessions Court","Haywood County Chancery Court","Haywood County Juvenile Court"],
  "Henderson":  ["Henderson County Circuit Court","Henderson County General Sessions Court","Henderson County Chancery Court","Henderson County Juvenile Court"],
  "Henry":      ["Henry County Circuit Court","Henry County General Sessions Court","Henry County Chancery Court","Henry County Juvenile Court"],
  "Hickman":    ["Hickman County Circuit Court","Hickman County General Sessions Court","Hickman County Chancery Court","Hickman County Juvenile Court"],
  "Houston":    ["Houston County Circuit Court","Houston County General Sessions Court","Houston County Chancery Court","Houston County Juvenile Court"],
  "Humphreys":  ["Humphreys County Circuit Court","Humphreys County General Sessions Court","Humphreys County Chancery Court","Humphreys County Juvenile Court"],
  "Jackson":    ["Jackson County Circuit Court","Jackson County General Sessions Court","Jackson County Chancery Court","Jackson County Juvenile Court"],
  "Jefferson":  ["Jefferson County Criminal Court","Jefferson County Circuit Court","Jefferson County General Sessions Court","Jefferson County Chancery Court","Jefferson County Juvenile Court"],
  "Johnson":    ["Johnson County Circuit Court","Johnson County General Sessions Court","Johnson County Chancery Court","Johnson County Juvenile Court"],
  "Knox":       ["Knox County Criminal Court — Division I","Knox County Criminal Court — Division II","Knox County Criminal Court — Division III","Knox County Criminal Court — Division IV","Knox County Circuit Court","Knox County General Sessions Court","Knox County Chancery Court","Knox County Juvenile Court","Knox County Drug Court","Knox County DUI Court","Knox County Mental Health Court","Knox County Veterans Treatment Court","Knox County Probate Court"],
  "Lake":       ["Lake County Circuit Court","Lake County General Sessions Court","Lake County Chancery Court","Lake County Juvenile Court"],
  "Lauderdale": ["Lauderdale County Circuit Court","Lauderdale County General Sessions Court","Lauderdale County Chancery Court","Lauderdale County Juvenile Court"],
  "Lawrence":   ["Lawrence County Circuit Court","Lawrence County General Sessions Court","Lawrence County Chancery Court","Lawrence County Juvenile Court"],
  "Lewis":      ["Lewis County Circuit Court","Lewis County General Sessions Court","Lewis County Chancery Court","Lewis County Juvenile Court"],
  "Lincoln":    ["Lincoln County Circuit Court","Lincoln County General Sessions Court","Lincoln County Chancery Court","Lincoln County Juvenile Court"],
  "Loudon":     ["Loudon County Circuit Court","Loudon County General Sessions Court","Loudon County Chancery Court","Loudon County Juvenile Court"],
  "Macon":      ["Macon County Circuit Court","Macon County General Sessions Court","Macon County Chancery Court","Macon County Juvenile Court"],
  "Madison":    ["Madison County Criminal Court — Division I","Madison County Criminal Court — Division II","Madison County Circuit Court","Madison County General Sessions Court","Madison County Chancery Court","Madison County Juvenile Court","Madison County Drug Court"],
  "Marion":     ["Marion County Circuit Court","Marion County General Sessions Court","Marion County Chancery Court","Marion County Juvenile Court"],
  "Marshall":   ["Marshall County Circuit Court","Marshall County General Sessions Court","Marshall County Chancery Court","Marshall County Juvenile Court"],
  "Maury":      ["Maury County Criminal Court","Maury County Circuit Court","Maury County General Sessions Court","Maury County Chancery Court","Maury County Juvenile Court","Maury County Drug Court"],
  "McMinn":     ["McMinn County Criminal Court","McMinn County Circuit Court","McMinn County General Sessions Court","McMinn County Chancery Court","McMinn County Juvenile Court"],
  "McNairy":    ["McNairy County Circuit Court","McNairy County General Sessions Court","McNairy County Chancery Court","McNairy County Juvenile Court"],
  "Meigs":      ["Meigs County Circuit Court","Meigs County General Sessions Court","Meigs County Chancery Court","Meigs County Juvenile Court"],
  "Monroe":     ["Monroe County Criminal Court","Monroe County Circuit Court","Monroe County General Sessions Court","Monroe County Chancery Court","Monroe County Juvenile Court"],
  "Montgomery": ["Montgomery County Criminal Court — Division I","Montgomery County Criminal Court — Division II","Montgomery County Circuit Court","Montgomery County General Sessions Court","Montgomery County Chancery Court","Montgomery County Juvenile Court","Montgomery County Drug Court","Montgomery County Veterans Treatment Court"],
  "Moore":      ["Moore County Circuit Court","Moore County General Sessions Court","Moore County Chancery Court","Moore County Juvenile Court"],
  "Morgan":     ["Morgan County Criminal Court","Morgan County Circuit Court","Morgan County General Sessions Court","Morgan County Chancery Court","Morgan County Juvenile Court"],
  "Obion":      ["Obion County Circuit Court","Obion County General Sessions Court","Obion County Chancery Court","Obion County Juvenile Court"],
  "Overton":    ["Overton County Circuit Court","Overton County General Sessions Court","Overton County Chancery Court","Overton County Juvenile Court"],
  "Perry":      ["Perry County Circuit Court","Perry County General Sessions Court","Perry County Chancery Court","Perry County Juvenile Court"],
  "Pickett":    ["Pickett County Circuit Court","Pickett County General Sessions Court","Pickett County Chancery Court","Pickett County Juvenile Court"],
  "Polk":       ["Polk County Criminal Court","Polk County Circuit Court","Polk County General Sessions Court","Polk County Chancery Court","Polk County Juvenile Court"],
  "Putnam":     ["Putnam County Criminal Court","Putnam County Circuit Court","Putnam County General Sessions Court","Putnam County Chancery Court","Putnam County Juvenile Court","Putnam County Drug Court"],
  "Rhea":       ["Rhea County Circuit Court","Rhea County General Sessions Court","Rhea County Chancery Court","Rhea County Juvenile Court"],
  "Roane":      ["Roane County Criminal Court","Roane County Circuit Court","Roane County General Sessions Court","Roane County Chancery Court","Roane County Juvenile Court"],
  "Robertson":  ["Robertson County Criminal Court","Robertson County Circuit Court","Robertson County General Sessions Court","Robertson County Chancery Court","Robertson County Juvenile Court"],
  "Rutherford": ["Rutherford County Criminal Court — Division I","Rutherford County Criminal Court — Division II","Rutherford County Circuit Court","Rutherford County General Sessions Court — Division I","Rutherford County General Sessions Court — Division II","Rutherford County Chancery Court","Rutherford County Juvenile Court","Rutherford County Drug Court","Rutherford County DUI Court"],
  "Scott":      ["Scott County Criminal Court","Scott County Circuit Court","Scott County General Sessions Court","Scott County Chancery Court","Scott County Juvenile Court"],
  "Sequatchie": ["Sequatchie County Circuit Court","Sequatchie County General Sessions Court","Sequatchie County Chancery Court","Sequatchie County Juvenile Court"],
  "Sevier":     ["Sevier County Criminal Court","Sevier County Circuit Court","Sevier County General Sessions Court","Sevier County Chancery Court","Sevier County Juvenile Court"],
  "Shelby":     ["Shelby County Criminal Court — Division 1","Shelby County Criminal Court — Division 2","Shelby County Criminal Court — Division 3","Shelby County Criminal Court — Division 4","Shelby County Criminal Court — Division 5","Shelby County Criminal Court — Division 6","Shelby County Criminal Court — Division 7","Shelby County Criminal Court — Division 8","Shelby County Criminal Court — Division 9","Shelby County Criminal Court — Division 10","Shelby County Circuit Court — Division 1","Shelby County Circuit Court — Division 2","Shelby County Circuit Court — Division 3","Shelby County General Sessions Court","Shelby County Chancery Court — Division I","Shelby County Chancery Court — Division II","Shelby County Chancery Court — Division III","Shelby County Juvenile Court","Shelby County Drug Court","Shelby County DUI Court","Shelby County Mental Health Court","Shelby County Veterans Treatment Court","Shelby County Probate Court"],
  "Smith":      ["Smith County Circuit Court","Smith County General Sessions Court","Smith County Chancery Court","Smith County Juvenile Court"],
  "Stewart":    ["Stewart County Circuit Court","Stewart County General Sessions Court","Stewart County Chancery Court","Stewart County Juvenile Court"],
  "Sullivan":   ["Sullivan County Criminal Court — Division I","Sullivan County Criminal Court — Division II","Sullivan County Circuit Court","Sullivan County General Sessions Court","Sullivan County Chancery Court","Sullivan County Juvenile Court","Sullivan County Drug Court"],
  "Sumner":     ["Sumner County Criminal Court","Sumner County Circuit Court","Sumner County General Sessions Court","Sumner County Chancery Court","Sumner County Juvenile Court","Sumner County Drug Court"],
  "Tipton":     ["Tipton County Criminal Court","Tipton County Circuit Court","Tipton County General Sessions Court","Tipton County Chancery Court","Tipton County Juvenile Court"],
  "Trousdale":  ["Trousdale County Circuit Court","Trousdale County General Sessions Court","Trousdale County Chancery Court","Trousdale County Juvenile Court"],
  "Unicoi":     ["Unicoi County Criminal Court","Unicoi County Circuit Court","Unicoi County General Sessions Court","Unicoi County Chancery Court","Unicoi County Juvenile Court"],
  "Union":      ["Union County Criminal Court","Union County Circuit Court","Union County General Sessions Court","Union County Chancery Court","Union County Juvenile Court"],
  "Van Buren":  ["Van Buren County Circuit Court","Van Buren County General Sessions Court","Van Buren County Chancery Court","Van Buren County Juvenile Court"],
  "Warren":     ["Warren County Criminal Court","Warren County Circuit Court","Warren County General Sessions Court","Warren County Chancery Court","Warren County Juvenile Court","Warren County Drug Court"],
  "Washington": ["Washington County Criminal Court — Division I","Washington County Criminal Court — Division II","Washington County Circuit Court","Washington County General Sessions Court","Washington County Chancery Court","Washington County Juvenile Court","Washington County Drug Court"],
  "Wayne":      ["Wayne County Circuit Court","Wayne County General Sessions Court","Wayne County Chancery Court","Wayne County Juvenile Court"],
  "Weakley":    ["Weakley County Circuit Court","Weakley County General Sessions Court","Weakley County Chancery Court","Weakley County Juvenile Court"],
  "White":      ["White County Circuit Court","White County General Sessions Court","White County Chancery Court","White County Juvenile Court"],
  "Williamson": ["Williamson County Criminal Court","Williamson County Circuit Court","Williamson County General Sessions Court","Williamson County Chancery Court","Williamson County Juvenile Court","Williamson County Drug Court","Williamson County DUI Court"],
  "Wilson":     ["Wilson County Criminal Court","Wilson County Circuit Court","Wilson County General Sessions Court","Wilson County Chancery Court","Wilson County Juvenile Court","Wilson County Drug Court"]
};

// ── Searchable select component ───────────────────────────────────────────────
function initSearchSelect(inputId, dropdownId, options, onSelect) {
  var input    = document.getElementById(inputId);
  var dropdown = document.getElementById(dropdownId);
  var selected = "";

  function render(filter) {
    var q = (filter || "").toLowerCase().trim();
    var hits = q ? options.filter(function(o){ return o.toLowerCase().includes(q); }) : options;
    if (!hits.length) {
      dropdown.innerHTML = '<div class="ss-empty">No results found.</div>';
    } else {
      dropdown.innerHTML = hits.map(function(o) {
        var cls = "ss-option" + (o === selected ? " active" : "");
        return '<div class="' + cls + '" data-val="' + escHtml(o) + '">' + escHtml(o) + '</div>';
      }).join("");
      dropdown.querySelectorAll(".ss-option").forEach(function(el) {
        el.addEventListener("mousedown", function(e) {
          e.preventDefault();
          selected = el.getAttribute("data-val");
          input.value = selected;
          input.classList.add("has-value");
          dropdown.classList.remove("open");
          if (onSelect) onSelect(selected);
        });
      });
    }
    dropdown.classList.add("open");
  }

  input.addEventListener("focus", function()  { render(input.value); });
  input.addEventListener("input", function()  { selected = ""; render(input.value); });
  input.addEventListener("blur",  function()  {
    setTimeout(function() { dropdown.classList.remove("open"); }, 150);
    // if typed text doesn't match selection, clear it
    if (input.value && input.value !== selected) { input.value = selected; }
  });

  return {
    getValue: function()  { return selected; },
    setValue: function(v) {
      selected = v || "";
      input.value = selected;
      input.classList.toggle("has-value", !!selected);
    },
    setOptions: function(opts) {
      options = opts;
      selected = "";
      input.value = "";
      input.classList.remove("has-value");
      input.placeholder = opts.length ? "Type to search court…" : "Select county first…";
    }
  };
}

var _ssCounty, _ssCourt;   // instances initialised after DOM ready

// ── Tab switching ─────────────────────────────────────────────────────────────
function showAttyTab(name, btn) {
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  const panel = document.getElementById("tab-" + name);
  if (panel) panel.classList.add("active");
  if (btn) btn.classList.add("active");
  if (name === "research") {
    loadTokenUsage();
    var picker = document.getElementById("res-client-picker");
    if (picker) picker.style.display = "none";
  }
}

// ── Client selection ──────────────────────────────────────────────────────────
function selectClient(username) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  const btn = document.getElementById("cli-" + username);
  if (btn) btn.classList.add("active");

  fetch("/portal/attorney/client/" + username)
    .then(r => r.json())
    .then(c => {
      _currentClient = c;
      document.getElementById("atty-tabs").style.display = "block";
      populateOverview(c);
      populateClientInfo(c);
      populateBillingLog(c);
      populateMessages(c);
      populateDocuments(c);
      populateResearch(c);
      populateSecurity(c);
      if (window.populateBilling) populateBilling(c);
      if (window.populateCaseDates) populateCaseDates(c);
      showAttyTab("overview", document.querySelector("#atty-tabs .portal-tab-btn"));
    });
}

// ── Populate panels ───────────────────────────────────────────────────────────
function populateOverview(c) {
  document.getElementById("ov-name").textContent      = c.client_name || c.username;
  document.getElementById("ov-case-type").textContent = c.case_type   || "";
  document.getElementById("ov-hours").textContent     = c.hours_billed || 0;
  document.getElementById("ov-court").textContent     = c.next_court_date    || "TBD";
  document.getElementById("ov-lastcomm").textContent  = c.last_communication || "—";
  document.getElementById("ov-meeting").textContent   = c.next_meeting       || "None scheduled";
  document.getElementById("ov-legal-issue").textContent = c.legal_issue_summary || c.legal_issue || "No summary entered yet.";
  // Case detail fields
  document.getElementById("ov-case-no").value      = c.case_no      || "";
  document.getElementById("ov-charges").value      = c.charges      || "";
  document.getElementById("ov-charge-level").value = c.charge_level || "";
  document.getElementById("ov-save-result").innerHTML = "";
  // Last note preview — most recent billing_log entry
  const logs = c.billing_log || [];
  const lastNoteEl = document.getElementById("ov-last-note");
  if (logs.length) {
    const last = logs[logs.length - 1];
    lastNoteEl.innerHTML = `
      <div style="display:flex;gap:.6rem;align-items:flex-start">
        <div style="font-size:1.1rem;flex-shrink:0">📝</div>
        <div>
          <div style="font-size:.76rem;color:var(--gray-3);margin-bottom:.25rem">
            ${escHtml(last.date)}${last.hours ? " &middot; " + last.hours + " hrs" : ""}
          </div>
          <div style="white-space:pre-wrap">${escHtml(last.note)}</div>
        </div>
      </div>`;
  } else {
    lastNoteEl.innerHTML = '<span style="color:var(--gray-3)">No notes yet.</span>';
  }
  // County + court searchable selects
  if (_ssCounty && _ssCourt) {
    var savedCounty = c.county || "";
    _ssCounty.setValue(savedCounty);
    var courtOpts = savedCounty ? (TN_COURTS[savedCounty] || []) : [];
    _ssCourt.setOptions(courtOpts);
    _ssCourt.setValue(c.court || "");
  }
  // Archive / restore button visibility
  var isArchived = !!c.archived;
  document.getElementById("ov-archive-btn").style.display   = isArchived ? "none" : "";
  document.getElementById("ov-unarchive-btn").style.display = isArchived ? "" : "none";
  document.getElementById("ov-archive-result").textContent  = isArchived ? "This client file is archived." : "";
}

// Navigate to a tab by name, activating the correct sidebar button
function goToTab(name) {
  let targetBtn = null;
  document.querySelectorAll("#atty-tabs .portal-tab-btn").forEach(b => {
    if ((b.getAttribute("onclick") || "").includes("'" + name + "'")) targetBtn = b;
  });
  showAttyTab(name, targetBtn);
}

// ── Court date picker ─────────────────────────────────────────────────────────
function openCourtDatePicker() {
  if (!_currentClient) return;
  var inp = document.getElementById("ov-court-date-picker");
  inp.value = _currentClient.next_court_date || "";
  try { inp.showPicker(); } catch(e) { inp.click(); }
}

function saveCourtDateFromPicker(val) {
  if (!_currentClient || !val) return;
  var username = _currentClient.username;
  fetch("/portal/attorney/update-client", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username:        username,
      next_court_date: val,
      client_name:     _currentClient.client_name     || "",
      case_type:       _currentClient.case_type       || "",
      phone:           _currentClient.phone           || "",
      email:           _currentClient.email           || "",
      next_meeting:    _currentClient.next_meeting    || "",
      legal_issue:     _currentClient.legal_issue     || "",
      google_drive_url:_currentClient.google_drive_url|| "",
    }),
  })
  .then(r => r.json())
  .then(d => {
    if (d.success) {
      _currentClient.next_court_date = val;
      document.getElementById("ov-court").textContent = val;
      // also sync the client-info form date field
      var ci = document.getElementById("ci-court-date");
      if (ci) ci.value = val;
      var hint = document.querySelector("#ov-court-card .ov-stat-hint");
      if (hint) {
        hint.textContent = "✓ Saved";
        hint.style.color = "var(--green)";
        setTimeout(() => { hint.textContent = "📅 click to change"; hint.style.color = ""; }, 2500);
      }
    }
  })
  .catch(() => {});
}

// ── Meeting scheduler ────────────────────────────────────────────────────────
function openMeetingModal() {
  if (!_currentClient) return;
  // Pre-fill with today's date and a default time
  const today = new Date().toISOString().split("T")[0];
  document.getElementById("mtg-date").value = today;
  document.getElementById("mtg-time").value = "10:00";
  document.getElementById("mtg-note").value = "";
  document.getElementById("mtg-result").innerHTML = "";
  document.getElementById("meeting-modal").style.display = "flex";
}

function closeMeetingModal(e) {
  if (e && e.target !== document.getElementById("meeting-modal")) return;
  document.getElementById("meeting-modal").style.display = "none";
}

function saveMeeting() {
  if (!_currentClient) return;
  const date = document.getElementById("mtg-date").value;
  const time = document.getElementById("mtg-time").value;
  const note = document.getElementById("mtg-note").value.trim();
  const res  = document.getElementById("mtg-result");
  if (!date || !time) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Please select a date and time.</p>';
    return;
  }
  // Format: "March 10, 2026 at 2:00 PM"
  const dt = new Date(date + "T" + time);
  const dateStr = dt.toLocaleDateString("en-US", {year:"numeric", month:"long", day:"numeric"});
  const timeStr = dt.toLocaleTimeString("en-US", {hour:"numeric", minute:"2-digit"});
  const formatted = dateStr + " at " + timeStr + (note ? " — " + note : "");
  res.innerHTML = '<p style="font-family:Arial,sans-serif;font-size:.88rem;color:var(--gray-3)">Saving…</p>';
  fetch("/portal/attorney/update-client", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      username:         _currentClient.username,
      next_meeting:     formatted,
      client_name:      _currentClient.client_name      || "",
      case_type:        _currentClient.case_type        || "",
      phone:            _currentClient.phone            || "",
      email:            _currentClient.email            || "",
      next_court_date:  _currentClient.next_court_date  || "",
      legal_issue:      _currentClient.legal_issue      || "",
      google_drive_url: _currentClient.google_drive_url || "",
    }),
  }).then(r => r.json()).then(d => {
    if (d.success) {
      _currentClient.next_meeting = formatted;
      populateOverview(_currentClient);
      document.getElementById("ci-next-meeting").value = formatted;
      document.getElementById("meeting-modal").style.display = "none";
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${d.error}</p>`;
    }
  });
}

// ── Save case detail fields (case_no, charges, charge_level) ─────────────────
function saveCaseDetails() {
  if (!_currentClient) return;
  const payload = {
    username:     _currentClient.username,
    case_no:      document.getElementById("ov-case-no").value.trim(),
    charges:      document.getElementById("ov-charges").value.trim(),
    charge_level: document.getElementById("ov-charge-level").value,
    county:       _ssCounty ? _ssCounty.getValue() : (_currentClient.county || ""),
    court:        _ssCourt  ? _ssCourt.getValue()  : (_currentClient.court  || ""),
    // preserve all existing fields
    client_name:      _currentClient.client_name      || "",
    case_type:        _currentClient.case_type        || "",
    phone:            _currentClient.phone            || "",
    email:            _currentClient.email            || "",
    next_court_date:  _currentClient.next_court_date  || "",
    next_meeting:     _currentClient.next_meeting     || "",
    legal_issue:      _currentClient.legal_issue      || "",
    google_drive_url: _currentClient.google_drive_url || "",
  };
  fetch("/portal/attorney/update-client", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    const res = document.getElementById("ov-save-result");
    if (d.success) {
      Object.assign(_currentClient, payload);
      res.innerHTML = '<p style="color:var(--green);font-family:Arial,sans-serif;font-size:.85rem">Case details saved.</p>';
      setTimeout(() => { res.innerHTML = ""; }, 3000);
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.85rem">${d.error}</p>`;
    }
  });
}

function populateClientInfo(c) {
  document.getElementById("ci-name").value         = c.client_name      || "";
  document.getElementById("ci-case-type").value    = c.case_type        || "Criminal Defense";
  document.getElementById("ci-phone").value        = c.phone            || "";
  document.getElementById("ci-email").value        = c.email            || "";
  document.getElementById("ci-court-date").value   = c.next_court_date  || "";
  document.getElementById("ci-next-meeting").value = c.next_meeting     || "";
  document.getElementById("ci-legal-issue").value  = c.legal_issue      || "";
  document.getElementById("ci-drive-url").value    = c.google_drive_url || "";
  document.getElementById("ci-result").innerHTML   = "";
}

function _catClass(cat) {
  var m = {
    "Court Appearance": "court", "Research": "research", "Drafting": "drafting",
    "Meeting": "meeting", "Filing": "filing", "Phone/Email": "phone",
    "Negotiation": "negot", "Travel": "travel", "Overhead": "overhead",
    "Intake": "intake", "Witness/Investigation": "research"
  };
  return m[cat] || "";
}

function populateBillingLog(c) {
  var tbody = document.getElementById("billing-log-tbody");
  var total = document.getElementById("be-total");
  var logs  = c.billing_log || [];
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  if (logs.length) {
    logs.slice().reverse().forEach(function(e) {
      var tr   = document.createElement("tr");
      var tdDt = document.createElement("td"); tdDt.textContent = e.date || "";
      var tdCt = document.createElement("td");
      var cat  = e.category || e.type || "Other";
      var badge = document.createElement("span");
      badge.className = "cat-badge " + _catClass(cat);
      badge.textContent = cat;
      tdCt.appendChild(badge);
      var tdHr = document.createElement("td"); tdHr.textContent = e.hours || 0;
      var tdNt = document.createElement("td");
      tdNt.style.whiteSpace = "pre-wrap";
      tdNt.textContent = e.note || "—";
      tr.appendChild(tdDt); tr.appendChild(tdCt); tr.appendChild(tdHr); tr.appendChild(tdNt);
      tbody.appendChild(tr);
    });
  } else {
    var tr = document.createElement("tr");
    var td = document.createElement("td"); td.colSpan = 4;
    td.style.cssText = "color:var(--gray-3);text-align:center;padding:.75rem";
    td.textContent = "No entries yet.";
    tr.appendChild(td); tbody.appendChild(tr);
  }
  total.textContent = "Total: " + (c.hours_billed || 0) + " hrs";
  document.getElementById("be-date").value     = new Date().toISOString().split("T")[0];
  document.getElementById("be-hours").value    = "";
  document.getElementById("be-note").value     = "";
  document.getElementById("be-category").value = "Meeting";
}

function populateMessages(c) {
  const thread = document.getElementById("atty-message-thread");
  const msgs   = c.messages || [];
  thread.replaceChildren();
  if (!msgs.length) {
    thread.appendChild(_el("p", {
      style: "font-family:Arial,sans-serif;font-size:.9rem;color:var(--gray-3);padding:1rem 0"
    }, "No messages yet."));
    thread.scrollTop = thread.scrollHeight;
    return;
  }
  // m.text is client- or AI-sourced and must never be parsed as HTML — built
  // with _el (DOM nodes + text nodes) rather than innerHTML, same pattern as
  // the rest of this file. See docs/superpowers/specs/2026-10-02-voicemail-summaries-design.md
  // for how this was found (a stored-XSS review ahead of the voicemail feature).
  msgs.forEach(m => {
    const senderLabel = m.from === "attorney" ? "You"
      : m.from === "ai" ? window._FIRM_NAME + " Assistant"
      : (c.client_name || c.username);
    thread.appendChild(_el("div", {},
      _el("div", {className: `message-bubble from-${m.from}`}, m.text),
      _el("div", {
        className: "message-meta",
        style: `text-align:${m.from === "attorney" ? "right" : "left"}`
      }, `${senderLabel} · ${m.date}`)
    ));
  });
  thread.scrollTop = thread.scrollHeight;
}

function populateDocuments(c) {
  // Reset category to first tab
  _docCategory = "Intake";
  document.querySelectorAll(".doc-cat-tab").forEach((b, i) => b.classList.toggle("active", i === 0));
  document.getElementById("doc-drop-label").textContent = "Drop files here for \"Intake\"";
  document.getElementById("doc-list-title").textContent = "Intake";
  loadDocumentList();
}

// ── Research tab ───────────────────────────────────────────────────────────────

var _resAnalyzedIssues = "";   // text from analyzeIssues()
var _resSpottedIssues  = "";   // text from issueSpotDocument()

function populateResearch(c) {
  document.getElementById("res-legal-issue").value = c.legal_issue || "";
  // Clear previous results
  _resAnalyzedIssues = "";
  _resSpottedIssues  = "";
  ["res-issues-section","res-authority-section","res-spot-section","res-draft-section"].forEach(id => {
    document.getElementById(id).style.display = "none";
  });
  ["res-analyze-err","res-authority-err","res-spot-err","res-draft-err","res-save-result",
   "res-analysis-save-result","res-authority-save-result"].forEach(id => {
    document.getElementById(id).textContent = "";
  });
  document.getElementById("res-draft-content").value = "";
  // Load document list for the selector
  loadResearchDocuments();
}

function loadResearchDocuments() {
  if (!_currentClient) return;
  const sel = document.getElementById("res-doc-select");
  sel.innerHTML = '<option value="">— Select a document —</option>';
  fetch("/portal/attorney/documents/" + encodeURIComponent(_currentClient.username))
    .then(r => r.json())
    .then(d => {
      Object.entries(d.files).forEach(([cat, files]) => {
        files.forEach(f => {
          const opt = document.createElement("option");
          opt.value = cat + "||" + f.name;
          opt.textContent = "[" + cat + "] " + f.name;
          sel.appendChild(opt);
        });
      });
    });
}

function loadTokenUsage() {
  document.getElementById("tu-error").style.display = "none";
  ["tu-today-total","tu-total-all","tu-total-in","tu-total-out"].forEach(id => {
    document.getElementById(id).textContent = "…";
  });
  fetch("/portal/attorney/token-usage")
    .then(r => r.json())
    .then(d => {
      var todayTok = (d.today_input || 0) + (d.today_output || 0);
      var allTok   = (d.total_input_tokens || 0) + (d.total_output_tokens || 0);
      document.getElementById("tu-today-total").textContent = todayTok.toLocaleString();
      document.getElementById("tu-total-all").textContent   = allTok.toLocaleString();
      document.getElementById("tu-total-in").textContent    = (d.total_input_tokens || 0).toLocaleString();
      document.getElementById("tu-total-out").textContent   = (d.total_output_tokens || 0).toLocaleString();

      var byLabel = d.by_label || {};
      var labels  = Object.keys(byLabel);
      var tbody   = document.getElementById("tu-breakdown-body");
      while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
      if (labels.length > 0) {
        labels.forEach(function(lbl) {
          var entry = byLabel[lbl];
          var row = document.createElement("tr");
          [lbl,
           entry.calls,
           (entry.input  || 0).toLocaleString(),
           (entry.output || 0).toLocaleString(),
           ((entry.input || 0) + (entry.output || 0)).toLocaleString()
          ].forEach(function(val, i) {
            var td = document.createElement("td");
            td.textContent = val;
            td.style.textAlign = i === 0 ? "left" : "right";
            row.appendChild(td);
          });
          tbody.appendChild(row);
        });
        document.getElementById("tu-breakdown").style.display = "block";
      } else {
        document.getElementById("tu-breakdown").style.display = "none";
      }
    })
    .catch(function() {
      ["tu-today-total","tu-total-all","tu-total-in","tu-total-out"].forEach(id => {
        document.getElementById(id).textContent = "—";
      });
      document.getElementById("tu-error").style.display = "block";
    });
}

function _resSetLoading(spinnerId, btnId, loading) {
  document.getElementById(spinnerId).style.display = loading ? "inline" : "none";
  const btn = document.getElementById(btnId);
  if (btn) btn.disabled = loading;
}

function analyzeIssues() {
  const issue = document.getElementById("res-legal-issue").value.trim();
  if (!issue) { document.getElementById("res-analyze-err").textContent = "Please enter a case summary."; return; }
  document.getElementById("res-analyze-err").textContent = "";
  _resSetLoading("res-analyze-spinner", "res-analyze-btn", true);
  fetch("/portal/attorney/research/analyze", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username: _currentClient.username, legal_issue: issue })
  }).then(r => r.json()).then(d => {
    _resSetLoading("res-analyze-spinner", "res-analyze-btn", false);
    if (!d.success) { document.getElementById("res-analyze-err").textContent = d.error || "Error."; return; }
    _resAnalyzedIssues = d.issues;
    document.getElementById("res-issues-content").textContent = d.issues;
    document.getElementById("res-issues-section").style.display = "block";
    document.getElementById("res-authority-section").style.display = "none";
    loadTokenUsage();
  }).catch(e => {
    _resSetLoading("res-analyze-spinner", "res-analyze-btn", false);
    document.getElementById("res-analyze-err").textContent = "Request failed: " + e.message;
  });
}

function findAuthority() {
  if (!_resAnalyzedIssues) { document.getElementById("res-authority-err").textContent = "Analyze issues first."; return; }
  document.getElementById("res-authority-err").textContent = "";
  _resSetLoading("res-authority-spinner", "res-authority-btn", true);
  fetch("/portal/attorney/research/authority", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ issues: _resAnalyzedIssues, case_type: _currentClient.case_type || "Criminal Defense" })
  }).then(r => r.json()).then(d => {
    _resSetLoading("res-authority-spinner", "res-authority-btn", false);
    if (!d.success) { document.getElementById("res-authority-err").textContent = d.error || "Error."; return; }
    document.getElementById("res-authority-content").textContent = d.memo;
    document.getElementById("res-authority-section").style.display = "block";
    loadTokenUsage();
  }).catch(e => {
    _resSetLoading("res-authority-spinner", "res-authority-btn", false);
    document.getElementById("res-authority-err").textContent = "Request failed: " + e.message;
  });
}

function issueSpotDocument() {
  const val = document.getElementById("res-doc-select").value;
  if (!val) { document.getElementById("res-spot-err").textContent = "Select a document first."; return; }
  const [category, filename] = val.split("||");
  document.getElementById("res-spot-err").textContent = "";
  document.getElementById("res-spot-spinner").style.display = "inline";
  fetch("/portal/attorney/research/issue-spot", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username: _currentClient.username, category, filename })
  }).then(r => r.json()).then(d => {
    document.getElementById("res-spot-spinner").style.display = "none";
    if (!d.success) { document.getElementById("res-spot-err").textContent = d.error || "Error."; return; }
    _resSpottedIssues = d.issues;
    document.getElementById("res-spot-content").textContent = d.issues;
    document.getElementById("res-spot-section").style.display = "block";
    loadTokenUsage();
  }).catch(e => {
    document.getElementById("res-spot-spinner").style.display = "none";
    document.getElementById("res-spot-err").textContent = "Request failed: " + e.message;
  });
}

function draftMotion() {
  const issues = (_resSpottedIssues + "\n" + _resAnalyzedIssues).trim();
  if (!issues) { document.getElementById("res-draft-err").textContent = "Run Issue Spot or Analyze Issues first."; return; }
  const motionType = document.getElementById("res-motion-type").value;
  const caseContext = document.getElementById("res-legal-issue").value.trim();
  document.getElementById("res-draft-err").textContent = "";
  _resSetLoading("res-draft-spinner", null, true);
  document.getElementById("res-draft-spinner").style.display = "inline";
  fetch("/portal/attorney/research/draft", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ motion_type: motionType, issues, case_context: caseContext, username: _currentClient.username })
  }).then(r => r.json()).then(d => {
    document.getElementById("res-draft-spinner").style.display = "none";
    if (!d.success) { document.getElementById("res-draft-err").textContent = d.error || "Error."; return; }
    document.getElementById("res-draft-content").value = d.draft;
    document.getElementById("res-draft-section").style.display = "block";
    document.getElementById("res-save-result").textContent = "";
    loadTokenUsage();
  }).catch(e => {
    document.getElementById("res-draft-spinner").style.display = "none";
    document.getElementById("res-draft-err").textContent = "Request failed: " + e.message;
  });
}

function saveResearchDraft() {
  const draft = document.getElementById("res-draft-content").value.trim();
  if (!draft || !_currentClient) return;
  const motionType = document.getElementById("res-motion-type").value;
  const category   = document.getElementById("res-save-cat").value;
  const ts = new Date().toISOString().slice(0,10).replace(/-/g,"");
  const filename = motionType.toLowerCase().replace(/[^a-z0-9]+/g,"_") + "_" + ts + ".txt";
  const resEl = document.getElementById("res-save-result");
  resEl.textContent = "Saving…";
  fetch("/portal/attorney/research/save-draft", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username: _currentClient.username,
      category, draft, filename, motion_type: motionType
    })
  }).then(r => r.json()).then(d => {
    if (!d.success) { resEl.style.color = "var(--red)"; resEl.textContent = d.error || "Save failed."; return; }
    resEl.style.color = "var(--green)";
    resEl.textContent = "Saved as \"" + d.filename + "\" in " + d.category + ".";
    // Update billing log with auto-entry
    if (d.billing_entry && _currentClient) {
      _currentClient.billing_log = _currentClient.billing_log || [];
      _currentClient.billing_log.push(d.billing_entry);
      if (d.total_hours !== null) _currentClient.hours_billed = d.total_hours;
      populateBillingLog(_currentClient);
      populateOverview(_currentClient);
    }
    // Refresh documents so new file appears
    loadResearchDocuments();
  }).catch(e => {
    resEl.style.color = "var(--red)";
    resEl.textContent = "Request failed: " + e.message;
  });
}

function saveResearchReport(reportType) {
  if (!_currentClient) return;
  const text = reportType === "analysis"
    ? _resAnalyzedIssues
    : document.getElementById("res-authority-content").textContent;
  if (!text.trim()) return;
  const resElId = reportType === "analysis"
    ? "res-analysis-save-result"
    : "res-authority-save-result";
  const resEl = document.getElementById(resElId);
  resEl.style.color = "";
  resEl.textContent = "Saving\u2026";
  fetch("/portal/attorney/research/save-report", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      username:    _currentClient.username,
      report_type: reportType,
      text
    })
  }).then(r => r.json()).then(d => {
    if (!d.success) {
      resEl.style.color = "var(--red)";
      resEl.textContent = d.error || "Save failed.";
      return;
    }
    resEl.style.color = "var(--green)";
    resEl.textContent = "Saved as \u201c" + d.filename + "\u201d in " + d.category + ". 0.5 hrs billed.";
    if (d.billing_entry && _currentClient) {
      _currentClient.billing_log = _currentClient.billing_log || [];
      _currentClient.billing_log.push(d.billing_entry);
      if (d.total_hours !== null) _currentClient.hours_billed = d.total_hours;
      populateBillingLog(_currentClient);
      populateOverview(_currentClient);
    }
  }).catch(e => {
    resEl.style.color = "var(--red)";
    resEl.textContent = "Request failed: " + e.message;
  });
}

// ── Generate AI legal issue summary ───────────────────────────────────────────
function generateLegalSummary() {
  if (!_currentClient) return;
  var btn = document.getElementById("gen-summary-btn");
  var el  = document.getElementById("ov-legal-issue");
  btn.disabled = true;
  btn.textContent = "Generating…";
  fetch("/portal/attorney/generate-summary", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ username: _currentClient.username })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    btn.disabled = false;
    btn.textContent = "⚡ Generate AI Summary";
    if (d.success) {
      el.textContent = d.summary;
      _currentClient.legal_issue_summary = d.summary;
    } else {
      el.textContent = d.error || "Error generating summary.";
    }
  })
  .catch(function() {
    btn.disabled = false;
    btn.textContent = "⚡ Generate AI Summary";
    el.textContent = "Network error.";
  });
}

// ── Save client info ──────────────────────────────────────────────────────────
function saveClientInfo() {
  if (!_currentClient) return;
  const payload = {
    username:        _currentClient.username,
    client_name:     document.getElementById("ci-name").value,
    case_type:       document.getElementById("ci-case-type").value,
    phone:           document.getElementById("ci-phone").value,
    email:           document.getElementById("ci-email").value,
    next_court_date: document.getElementById("ci-court-date").value,
    next_meeting:    document.getElementById("ci-next-meeting").value,
    legal_issue:     document.getElementById("ci-legal-issue").value,
    google_drive_url:document.getElementById("ci-drive-url").value,
  };
  fetch("/portal/attorney/update-client", {
    method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)
  }).then(r => r.json()).then(d => {
    const res = document.getElementById("ci-result");
    if (d.success) {
      Object.assign(_currentClient, payload);
      populateOverview(_currentClient);
      populateDocuments(_currentClient);
      // refresh sidebar label
      const btn = document.getElementById("cli-" + _currentClient.username);
      if (btn) btn.textContent = payload.client_name || _currentClient.username;
      let saveMsg = "Saved.";
      if (d.intake_pdf) saveMsg += ' Intake PDF \u201c' + d.intake_pdf + '\u201d saved to Documents.';
      res.innerHTML = '<p style="color:var(--green);font-family:Arial,sans-serif;font-size:.88rem">' + saveMsg + '</p>';
      setTimeout(() => { res.innerHTML = ""; }, 5000);
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${d.error}</p>`;
    }
  });
}

// ── Log billing entry ─────────────────────────────────────────────────────────
function logBillingEntry() {
  if (!_currentClient) return;
  const note     = document.getElementById("be-note").value.trim();
  const hours    = parseFloat(document.getElementById("be-hours").value) || 0;
  const date     = document.getElementById("be-date").value;
  const category = document.getElementById("be-category").value;
  const res      = document.getElementById("be-result");
  if (!note) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Note / description is required.</p>';
    return;
  }
  fetch("/portal/attorney/billing-entry", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ username: _currentClient.username, note, hours, date, category })
  }).then(r => r.json()).then(d => {
    if (d.success) {
      _currentClient.billing_log = _currentClient.billing_log || [];
      _currentClient.billing_log.push(d.entry);
      _currentClient.hours_billed = d.total_hours;
      populateBillingLog(_currentClient);
      populateOverview(_currentClient);
      if (d.billing_summary) _currentClient.billing_summary = d.billing_summary;
      if (window.populateBilling) populateBilling(_currentClient);
      var p = document.createElement("p"); p.style.cssText = "color:var(--green);font-family:Arial,sans-serif;font-size:.88rem"; p.textContent = "Entry saved \u2014 Total: " + d.total_hours + " hrs"; res.textContent = ""; res.appendChild(p);
      setTimeout(() => { res.textContent = ""; }, 4000);
    } else {
      var ep = document.createElement("p"); ep.style.cssText = "color:var(--red);font-family:Arial,sans-serif;font-size:.88rem"; ep.textContent = d.error || "Error."; res.textContent = ""; res.appendChild(ep);
    }
  });
}

// ── Send reply ────────────────────────────────────────────────────────────────
function sendReply() {
  if (!_currentClient) return;
  const text = document.getElementById("atty-reply-text").value.trim();
  const res  = document.getElementById("atty-reply-result");
  if (!text) { res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Enter a reply.</p>'; return; }
  fetch("/portal/attorney/reply", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ username: _currentClient.username, text })
  }).then(r => r.json()).then(d => {
    if (d.success) {
      const now = new Date().toLocaleDateString("en-US", { year:"numeric", month:"2-digit", day:"2-digit" });
      _currentClient.messages = _currentClient.messages || [];
      _currentClient.messages.push({ from:"attorney", date: now, text });
      populateMessages(_currentClient);
      document.getElementById("atty-reply-text").value = "";
      res.innerHTML = '<p style="color:var(--green);font-family:Arial,sans-serif;font-size:.88rem">Reply sent.</p>';
      setTimeout(() => { res.innerHTML = ""; }, 3000);
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${d.error}</p>`;
    }
  });
}

// ── Document management ───────────────────────────────────────────────────────
var _docCategory = "Intake";

function setDocCategory(cat, btn) {
  _docCategory = cat;
  document.querySelectorAll(".doc-cat-tab").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  document.getElementById("doc-drop-label").textContent = `Drop files here for "${cat}"`;
  document.getElementById("doc-list-title").textContent = cat;
  loadDocumentList();
}

function loadDocumentList() {
  if (!_currentClient) return;
  document.getElementById("doc-file-list").innerHTML =
    '<p class="doc-empty" style="color:var(--gray-3)">Loading…</p>';
  fetch("/portal/attorney/documents/" + encodeURIComponent(_currentClient.username))
    .then(r => r.json())
    .then(d => renderDocList(d.files[_docCategory] || []));
}

function renderDocList(files) {
  const wrap  = document.getElementById("doc-file-list");
  const count = document.getElementById("doc-file-count");
  count.textContent = files.length ? files.length + " file" + (files.length > 1 ? "s" : "") : "";
  if (!files.length) {
    _show(wrap, _el("p", {className: "doc-empty"}, "No files in this category yet. Drag & drop above to upload."));
    return;
  }
  const u   = encodeURIComponent(_currentClient.username);
  const cat = encodeURIComponent(_docCategory);
  _show(wrap, files.map(f => {
    const name = f.name;
    const ext  = (name.split(".").pop() || "").toLowerCase();
    const fn   = encodeURIComponent(name);
    return _el("div", {className: "doc-file-row"},
      _el("div", {className: "doc-file-icon"}, docIcon(name)),
      _el("div", {className: "doc-file-name"}, name),
      _el("div", {className: "doc-file-meta"}, f.modified + " · " + fmtBytes(f.size)),
      _el("div", {className: "doc-file-actions"},
        _el("button", {type: "button", className: "doc-btn", title: "Preview",
                       onclick: () => previewDocument(name, ext)}, "👁 Preview"),
        _el("a", {className: "doc-btn", title: "Download",
                  href: "/portal/attorney/document/" + u + "/" + cat + "/" + fn}, "↓ Download"),
        _docCategory === "Scheduling Orders"
          ? _el("button", {type: "button", className: "doc-btn", title: "Read dates",
                           onclick: () => openSchedReview(name)}, "📅 Read dates")
          : null,
        _el("button", {type: "button", className: "doc-btn doc-btn-del", title: "Delete",
                       onclick: () => deleteDocument(name)}, "🗑 Delete")));
  }));
}

// ── Document preview ──────────────────────────────────────────────────────────
function previewDocument(filename, ext) {
  if (!_currentClient) return;
  const u   = encodeURIComponent(_currentClient.username);
  const cat = encodeURIComponent(_docCategory);
  const fn  = encodeURIComponent(filename);
  const previewUrl  = `/portal/attorney/preview/${u}/${cat}/${fn}`;
  const downloadUrl = `/portal/attorney/document/${u}/${cat}/${fn}`;

  document.getElementById("doc-preview-title").textContent = filename;
  document.getElementById("doc-preview-dl").href = downloadUrl;

  const body   = document.getElementById("doc-preview-body");
  const images = ["jpg","jpeg","png","gif","bmp","webp"];
  const texts  = ["txt","rtf"];

  if (ext === "pdf" || ext === "html") {
    body.innerHTML = `<iframe src="${previewUrl}" title="${escHtml(filename)}"></iframe>`;
  } else if (ext === "docx") {
    const docxUrl = previewUrl.replace("/preview/", "/docx-preview/");
    body.innerHTML = `<iframe src="${docxUrl}" title="${escHtml(filename)}"></iframe>`;
  } else if (images.includes(ext)) {
    body.innerHTML = `<img src="${previewUrl}" alt="${escHtml(filename)}" />`;
  } else if (texts.includes(ext)) {
    body.innerHTML = `<pre style="color:var(--gray-3)">Loading…</pre>`;
    fetch(previewUrl).then(r => r.text()).then(text => {
      body.innerHTML = `<pre>${escHtml(text)}</pre>`;
    });
  } else {
    body.innerHTML = `
      <div class="doc-preview-no-support">
        <div style="font-size:3.5rem;margin-bottom:.75rem">${docIcon(filename)}</div>
        <div style="font-family:Georgia,serif;font-size:1.05rem;font-weight:bold;color:var(--navy);margin-bottom:.5rem">
          ${escHtml(filename)}
        </div>
        <div style="font-family:Arial,sans-serif;font-size:.88rem;color:var(--gray-3);margin-bottom:1.5rem">
          Browser preview is not available for .${ext} files.
        </div>
        <a href="${downloadUrl}" class="btn btn-primary">↓ Download to View</a>
      </div>`;
  }

  document.getElementById("doc-preview-overlay").style.display = "flex";
}

function closeDocPreview(e) {
  if (e && e.target !== document.getElementById("doc-preview-overlay")) return;
  document.getElementById("doc-preview-overlay").style.display = "none";
  // Clear iframe/img src to stop loading
  document.getElementById("doc-preview-body").innerHTML = "";
}

function docIcon(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (ext === "pdf")                             return "📄";
  if (["doc","docx"].includes(ext))              return "📝";
  if (["xls","xlsx"].includes(ext))              return "📊";
  if (["ppt","pptx"].includes(ext))              return "📋";
  if (["jpg","jpeg","png","gif","bmp","webp"].includes(ext)) return "🖼";
  if (ext === "txt" || ext === "rtf")            return "📃";
  if (ext === "html")                            return "🗒";
  return "📎";
}

function fmtBytes(b) {
  if (b < 1024)      return b + " B";
  if (b < 1048576)   return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function deleteDocument(filename) {
  if (!_currentClient) return;
  if (!confirm(`Delete "${filename}"?\n\nThis cannot be undone.`)) return;
  fetch("/portal/attorney/delete-document", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      username: _currentClient.username,
      category: _docCategory,
      filename,
    }),
  }).then(r => r.json()).then(d => {
    if (d.success) loadDocumentList();
    else alert("Error: " + d.error);
  });
}

function initDocDropZone() {
  const zone  = document.getElementById("doc-drop-zone");
  const input = document.getElementById("doc-file-input");
  if (!zone) return;
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", ()  => zone.classList.remove("drag-over"));
  zone.addEventListener("dragend",   ()  => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    if (!_currentClient) { alert("Please select a client first."); return; }
    uploadFiles(e.dataTransfer.files);
  });
  zone.addEventListener("click", e => {
    if (e.target === input) return;
    if (!_currentClient) { alert("Please select a client first."); return; }
    input.value = "";
    input.click();
  });
}

function uploadFiles(files) {
  if (!_currentClient || !files || !files.length) return;
  const progress = document.getElementById("doc-upload-progress");
  const list = Array.from(files);
  let done = 0;
  let lastSchedFile = null;
  const total = list.length;

  function next() {
    if (!list.length) {
      progress.textContent = total === 1
        ? "Upload complete."
        : `${done} file${done > 1 ? "s" : ""} uploaded.`;
      setTimeout(() => { progress.textContent = ""; }, 3000);
      loadDocumentList();
      if (window.openSchedReview && lastSchedFile) openSchedReview(lastSchedFile);
      // Refresh billing log and case overview with auto-billed entries
      if (_currentClient) {
        populateBillingLog(_currentClient);
        populateOverview(_currentClient);
      }
      return;
    }
    const file = list.shift();
    progress.textContent = `Uploading "${file.name}" (${done + 1} of ${total})…`;
    const form = new FormData();
    form.append("username", _currentClient.username);
    form.append("category", _docCategory);
    form.append("file", file);
    fetch("/portal/attorney/upload-document", { method: "POST", body: form })
      .then(r => r.json())
      .then(d => {
        if (!d.success) { alert("Upload failed: " + (d.error || "unknown error")); }
        if (d.success && _docCategory === "Scheduling Orders" && d.file && d.file.name) lastSchedFile = d.file.name;
        // Accumulate auto-billing entries into the in-memory client
        if (d.billing_entry && _currentClient) {
          _currentClient.billing_log = _currentClient.billing_log || [];
          _currentClient.billing_log.push(d.billing_entry);
          if (d.total_hours !== null) _currentClient.hours_billed = d.total_hours;
        }
        done++;
        next();
      })
      .catch(err => { progress.textContent = "Upload error: " + err.message; });
  }
  next();
}

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
  autoFillUsername();
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

function autoFillUsername() {
  const name  = document.getElementById("nc-name").value.trim();
  const parts = name.split(/\s+/);
  if (!parts[0]) { document.getElementById("nc-username").value = ""; return; }
  const first      = parts[0];
  const lastInit   = parts.length > 1 ? parts[parts.length - 1][0].toUpperCase() : "";
  const base       = (first + lastInit).replace(/[^a-zA-Z0-9]/g, "");
  document.getElementById("nc-username").value = base;
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
  document.getElementById("nc-password").value   = "";
  document.getElementById("nc-opposing").value = "";
  document.getElementById("nc-related-list").replaceChildren();
  document.getElementById("nc-form-card").appendChild(document.getElementById("nc-result"));
  document.getElementById("nc-result").innerHTML = "";
}

// ── Create new client ─────────────────────────────────────────────────────────
function createClient() {
  const name     = document.getElementById("nc-name").value.trim();
  const username = document.getElementById("nc-username").value.trim();
  const password = document.getElementById("nc-password").value.trim();
  const res      = document.getElementById("nc-result");
  if (!name || !username) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Full name and username are required.</p>';
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
      password,
      must_change_password: true,
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
      document.getElementById("nc-success-password").textContent = d.temp_password || "";
      const pwNote = document.getElementById("nc-success-pw-note");
      if (pwNote) {
        pwNote.textContent = d.password_replaced
          ? "The password you entered was too weak, so a secure one was generated." : "";
      }
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

// ── Global Attorney Dashboard ─────────────────────────────────────────────────

function showDashboard(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("atty-dashboard").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  loadDashboard();
}

// ── Insights Panel ─────────────────────────────────────────────────────────────

function showInsights(btn) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll("#portal-main .portal-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".portal-tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-insights").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  // Populate year selector if empty
  var sel = document.getElementById("ins-tax-year");
  if (!sel.options.length) {
    var curYear = new Date().getFullYear();
    for (var y = curYear; y >= curYear - 4; y--) {
      var opt = document.createElement("option");
      opt.value = y; opt.textContent = y;
      if (y === curYear) opt.selected = true;
      sel.appendChild(opt);
    }
  }
  loadInsights();
  fetch("/api/page-visits")
    .then(function(r){ return r.json(); })
    .then(function(d){
      ["index","meet_the_firm","intake","research","drafting"].forEach(function(k){
        var el = document.getElementById("pv-" + k);
        if (el) el.textContent = (d[k] || 0).toLocaleString();
      });
    })
    .catch(function(){});
  if (window.loadBillingSettings) loadBillingSettings();
}

function showGlobalResearch(btn) {
  document.querySelectorAll(".client-list-item").forEach(function(b) { b.classList.remove("active"); });
  document.querySelectorAll("#portal-main .portal-panel").forEach(function(p) { p.classList.remove("active"); });
  document.querySelectorAll(".portal-tab-btn").forEach(function(b) { b.classList.remove("active"); });
  document.getElementById("atty-tabs").style.display = "none";
  document.getElementById("tab-research").classList.add("active");
  if (btn) btn.classList.add("active");
  _currentClient = null;
  document.getElementById("res-client-picker").style.display = "block";
  document.getElementById("res-client-badge").style.display = "none";
  document.getElementById("res-client-search").value = "";
  document.getElementById("res-client-dropdown").style.display = "none";
  loadTokenUsage();
}

function filterResClientList(query) {
  var dropdown = document.getElementById("res-client-dropdown");
  var q = query.trim().toLowerCase();
  dropdown.style.display = q ? "block" : "none";
  while (dropdown.firstChild) { dropdown.removeChild(dropdown.firstChild); }
  if (!q) return;
  var matches = (window._ALL_CLIENTS_DATA || []).filter(function(c) {
    return (c.client_name || c.username || "").toLowerCase().indexOf(q) !== -1;
  }).slice(0, 8);
  if (!matches.length) {
    var none = document.createElement("div");
    none.className = "res-client-option";
    none.textContent = "No clients found.";
    dropdown.appendChild(none);
    return;
  }
  matches.forEach(function(c) {
    var opt = document.createElement("div");
    opt.className = "res-client-option";
    opt.textContent = (c.client_name || c.username) + (c.case_type ? " — " + c.case_type : "");
    opt.addEventListener("click", function() { selectResClient(c); });
    dropdown.appendChild(opt);
  });
}

function selectResClient(c) {
  _currentClient = c;
  var badge = document.getElementById("res-client-badge");
  badge.textContent = "Linked: " + (c.client_name || c.username);
  badge.style.display = "inline";
  document.getElementById("res-client-dropdown").style.display = "none";
  document.getElementById("res-client-search").value = "";
  var issueTa = document.getElementById("res-legal-issue");
  if (issueTa && !issueTa.value.trim()) {
    issueTa.value = c.legal_issue_summary || c.legal_issue || "";
  }
}

function loadInsights() {
  var year = document.getElementById("ins-tax-year").value || new Date().getFullYear();
  fetch("/portal/attorney/insights?year=" + year)
    .then(function(r) { return r.json(); })
    .then(function(d) { renderInsights(d); })
    .catch(function(e) { console.error("Insights error:", e); });
}

function _fmt$(n) { return "$" + Number(n).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2}); }
function _fmtN(n) { return Number(n).toLocaleString(); }

function _barRows(obj, total, cssClass) {
  var wrap = document.createElement("div");
  var keys = Object.keys(obj).sort(function(a,b){ return obj[b]-obj[a]; });
  if (!keys.length) { wrap.textContent = "No data."; return wrap; }
  keys.forEach(function(k) {
    var pct = total ? Math.round(obj[k]/total*100) : 0;
    var row = document.createElement("div");
    row.className = "ins-bar-wrap";
    var lbl = document.createElement("span");
    lbl.style.cssText = "min-width:140px;font-size:.8rem;color:#444";
    lbl.textContent = k;
    var track = document.createElement("div");
    track.className = "ins-bar-track";
    var fill = document.createElement("div");
    fill.className = "ins-bar-fill" + (cssClass ? " " + cssClass : "");
    fill.style.width = pct + "%";
    track.appendChild(fill);
    var cnt = document.createElement("span");
    cnt.style.cssText = "font-size:.8rem;color:var(--gray-3);white-space:nowrap";
    cnt.textContent = obj[k] + " (" + pct + "%)";
    row.appendChild(lbl); row.appendChild(track); row.appendChild(cnt);
    wrap.appendChild(row);
  });
  return wrap;
}

function renderInsights(d) {
  var f = d.firm, l = d.leads, attys = d.attorneys, year = d.year;

  // Snapshot stats
  document.getElementById("ins-total-clients").textContent     = _fmtN(f.total_clients);
  document.getElementById("ins-total-hours").textContent       = f.total_hours_billed + " hrs";
  document.getElementById("ins-revenue-billed").textContent    = _fmt$(f.total_revenue_billed);
  document.getElementById("ins-revenue-collected").textContent = _fmt$(f.total_revenue_collected);
  document.getElementById("ins-court-dates").textContent       = _fmtN(f.total_court_dates);
  document.getElementById("ins-meetings").textContent          = _fmtN(f.total_meetings);
  document.getElementById("ins-intakes").textContent           = _fmtN(f.intake_forms);
  document.getElementById("ins-messages").textContent          = _fmtN(f.total_messages);
  document.getElementById("ins-time-logs").textContent         = _fmtN(f.total_time_logs);
  document.getElementById("ins-client-files").textContent      = _fmtN(f.total_client_files);
  document.getElementById("ins-research-sessions").textContent = _fmtN(f.research_sessions);
  document.getElementById("ins-draft-sessions").textContent    = _fmtN(f.draft_sessions);
  document.getElementById("ins-leads-total").textContent       = _fmtN(l.total);
  document.getElementById("ins-conversion").textContent        = l.conversion_rate + "%";
  document.getElementById("ins-leads-active").textContent      = _fmtN(l.active);
  document.getElementById("ins-rate-num").textContent          = l.conversion_rate + "%";

  // Case type bars
  var caseBarsEl = document.getElementById("ins-case-bars");
  while (caseBarsEl.firstChild) caseBarsEl.removeChild(caseBarsEl.firstChild);
  caseBarsEl.appendChild(_barRows(f.case_type_breakdown, f.total_clients, ""));

  // Lead source bars
  var srcEl = document.getElementById("ins-source-bars");
  while (srcEl.firstChild) srcEl.removeChild(srcEl.firstChild);
  srcEl.appendChild(_barRows(l.by_source, l.total, "gold"));

  // Lead case type bars
  var lctEl = document.getElementById("ins-lead-ct-bars");
  while (lctEl.firstChild) lctEl.removeChild(lctEl.firstChild);
  lctEl.appendChild(_barRows(l.by_case_type, l.total, "gold"));

  // Per-attorney cards
  var attyWrap = document.getElementById("ins-atty-breakdown");
  while (attyWrap.firstChild) attyWrap.removeChild(attyWrap.firstChild);
  Object.keys(attys).forEach(function(uname) {
    var a = attys[uname];
    var card = document.createElement("div");
    card.className = "ins-atty-card";
    var nm = document.createElement("div");
    nm.className = "ins-atty-name";
    nm.textContent = a.display;
    var grid = document.createElement("div");
    grid.className = "ins-atty-stats";
    [
      [a.total_clients,                   "Total Clients"],
      [a.total_hours_billed + " hrs",     "Hours Billed"],
      [_fmt$(a.total_revenue_billed),     "Revenue Billed"],
      [_fmt$(a.total_revenue_collected),  "Revenue Collected"],
      [a.clients_with_court_dates,        "Clients w/ Court Dates"],
      [a.clients_with_meetings,           "Meetings Scheduled"],
      [a.total_messages,                  "Messages"],
      [a.total_time_logs,                 "Time Log Entries"],
      [Object.keys(a.case_types).map(function(k){ return k+": "+a.case_types[k]; }).join(" · ") || "—", "Case Types"],
    ].forEach(function(pair) {
      var s = document.createElement("div");
      s.className = "ins-atty-stat";
      var v = document.createElement("div");
      v.className = "ins-atty-stat-val";
      v.style.fontSize = String(pair[0]).length > 8 ? ".82rem" : "1.2rem";
      v.textContent = pair[0];
      var lb = document.createElement("div");
      lb.className = "ins-atty-stat-lbl";
      lb.textContent = pair[1];
      s.appendChild(v); s.appendChild(lb);
      grid.appendChild(s);
    });
    card.appendChild(nm); card.appendChild(grid);
    attyWrap.appendChild(card);
  });

  // Tax table
  var tbody = document.getElementById("ins-tax-tbody");
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  var exportBtns = document.getElementById("ins-atty-export-btns");
  while (exportBtns.firstChild) exportBtns.removeChild(exportBtns.firstChild);

  Object.keys(attys).forEach(function(uname) {
    var a = attys[uname];
    var tr = document.createElement("tr");
    [
      a.display,
      a.total_clients,
      a.year_hours_billed + " hrs",
      _fmt$(a.year_revenue_billed),
      _fmt$(a.year_revenue_collected),
    ].forEach(function(val, i) {
      var td = document.createElement("td");
      td.className = i > 0 ? "num" : "";
      td.textContent = val;
      tr.appendChild(td);
    });
    // Print button cell
    var tdBtn = document.createElement("td");
    var pb = document.createElement("button");
    pb.className = "btn btn-primary";
    pb.style.cssText = "padding:.25rem .6rem;font-size:.78rem";
    pb.textContent = "Print W-2";
    pb.onclick = (function(u, y){ return function(){ exportTax(u, y); }; })(uname, year);
    tdBtn.appendChild(pb);
    tr.appendChild(tdBtn);
    tbody.appendChild(tr);

    // Individual export button row
    var eb = document.createElement("button");
    eb.className = "btn btn-primary";
    eb.style.cssText = "font-size:.84rem";
    eb.textContent = "W-2 Summary — " + a.display.split(",")[0];
    eb.onclick = (function(u, y){ return function(){ exportTax(u, y); }; })(uname, year);
    exportBtns.appendChild(eb);
  });

  // Overhead Reserve snapshot stats
  if (d.overhead) {
    var oh = d.overhead;
    document.getElementById("ins-overhead-reserve").textContent = _fmt$(oh.overhead_reserve);
    var netEl = document.getElementById("ins-net-profit");
    netEl.textContent = _fmt$(oh.est_net_profit);
    netEl.style.color = oh.est_net_profit >= 0 ? "var(--navy)" : "#c0392b";

    // P&L summary
    document.getElementById("ins-pl-collected").textContent = _fmt$(d.firm.total_revenue_collected);
    document.getElementById("ins-pl-overhead").textContent  = _fmt$(oh.overhead_reserve);
    document.getElementById("ins-pl-net").textContent       = _fmt$(oh.est_net_profit);
    document.getElementById("ins-pl-pct").textContent       = Math.round(oh.reserve_pct * 100);
    var plNetEl = document.getElementById("ins-pl-net");
    plNetEl.style.color = oh.est_net_profit >= 0 ? "var(--navy)" : "#c0392b";

    // Overhead line-item table
    var ohTbody = document.getElementById("ins-overhead-tbody");
    while (ohTbody.firstChild) ohTbody.removeChild(ohTbody.firstChild);
    var lines = [
      ["Rent / Lease",             oh.monthly_rent],
      ["Salaries (non-billable)",  oh.monthly_salaries],
      ["Software & Subscriptions", oh.monthly_software],
      ["Insurance & Malpractice",  oh.monthly_insurance],
      ["Marketing & Advertising",  oh.monthly_marketing],
      ["Miscellaneous",            oh.monthly_misc],
    ];
    lines.forEach(function(row) {
      if (row[1] <= 0) return; // skip zero entries
      var tr = document.createElement("tr");
      var tdName = document.createElement("td"); tdName.textContent = row[0];
      var tdMo   = document.createElement("td"); tdMo.className = "num"; tdMo.textContent = _fmt$(row[1]);
      var tdYr   = document.createElement("td"); tdYr.className = "num"; tdYr.textContent = _fmt$(row[1] * 12);
      tr.appendChild(tdName); tr.appendChild(tdMo); tr.appendChild(tdYr);
      ohTbody.appendChild(tr);
    });
    if (!ohTbody.firstChild) {
      var tr = document.createElement("tr");
      var td = document.createElement("td"); td.colSpan = 3;
      td.style.cssText = "color:var(--gray-3);font-size:.82rem;text-align:center;padding:.6rem";
      td.textContent = "No overhead configured. Set MONTHLY_* variables in .env to populate.";
      tr.appendChild(td); ohTbody.appendChild(tr);
    }
    // Totals footer
    var ohTfoot = document.getElementById("ins-overhead-tfoot");
    while (ohTfoot.firstChild) ohTfoot.removeChild(ohTfoot.firstChild);
    var tfr = document.createElement("tr");
    tfr.style.fontWeight = "700";
    var tfd = document.createElement("td"); tfd.textContent = "Total Estimated Overhead";
    var tfm = document.createElement("td"); tfm.className = "num"; tfm.textContent = _fmt$(oh.monthly_total);
    var tfy = document.createElement("td"); tfy.className = "num"; tfy.textContent = _fmt$(oh.annual_total);
    tfr.appendChild(tfd); tfr.appendChild(tfm); tfr.appendChild(tfy);
    ohTfoot.appendChild(tfr);
  }
}

function exportTax(attorney, year) {
  var url = "/portal/attorney/insights/export-tax?year=" + year + (attorney ? "&attorney=" + encodeURIComponent(attorney) : "");
  window.open(url, "_blank", "noopener");
}
function exportTaxAll() {
  var year = document.getElementById("ins-tax-year").value || new Date().getFullYear();
  exportTax("", year);
}

function loadDashboard() {
  fetch("/portal/attorney/dashboard")
    .then(r => {
      if (!r.ok || !r.headers.get("content-type")?.includes("application/json")) {
        return Promise.reject(new Error("HTTP " + r.status + " — session may have expired, please reload."));
      }
      return r.json();
    })
    .then(d => {
      renderDashCalendar(d.calendar || []);
      renderDashDeadlines(d.deadlines || []);
      renderFollowUps(d.follow_up_needed || []);
      // recent activity — all values sanitized via escHtml before innerHTML insertion
      const actList = document.getElementById("dash-activity-list");
      const activity = d.recent_activity || [];
      const ACTION_ICONS = {
        intake: "📋", document_upload: "📄", document_delete: "🗑",
        note_saved: "📝", info_updated: "✏️", message_sent: "💬",
        time_logged: "⏱", meeting_scheduled: "📅"
      };
      if (activity.length) {
        actList.innerHTML = activity.map(function(a) {
          var icon = ACTION_ICONS[a.action_type] || "•";
          var ts   = (a.timestamp || "").replace("T", " ").slice(0, 16);
          var uAttr = escHtml(a.username || "").replace(/'/g, "&#39;");
          return '<div style="display:flex;gap:.55rem;align-items:flex-start;padding:.45rem 0;border-bottom:1px solid var(--gray-1)">' 
            + '<span style="flex-shrink:0;font-size:1rem">' + icon + '</span>'
            + '<div style="flex:1;min-width:0">'
            + '<div style="font-family:Arial,sans-serif;font-size:.82rem;color:var(--navy);font-weight:600;cursor:pointer" onclick="selectClient(\'' + uAttr + '\')">'
            + escHtml(a.client_name) + '</div>'
            + '<div style="font-family:Arial,sans-serif;font-size:.8rem;color:var(--gray-4);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            + escHtml(a.description) + '</div>'
            + '</div>'
            + '<div style="font-family:Arial,sans-serif;font-size:.72rem;color:var(--gray-3);white-space:nowrap;flex-shrink:0">'
            + escHtml(ts) + '</div>'
            + '</div>';
        }).join("");
      } else {
        actList.innerHTML = '<p class="dash-empty">No activity yet.</p>';
      }
      renderDashRecentFiles(d.recent_files || []);
      renderDashBilling(d.billing || [], d.billing_total || 0);
    })
    .catch(err => {
      const msg = (err && err.message) ? err.message : String(err);
      console.error("loadDashboard error:", err);
      const calEl = document.getElementById("month-cal-container");
      if (calEl) calEl.innerHTML = '<p class="dash-empty">Error: ' + escHtml(msg) + '</p>';
      ["dash-deadlines-tbody","dash-followup-tbody","dash-files-tbody","dash-billing-tbody"]
        .forEach(id => {
          const el = document.getElementById(id);
          if (el) el.innerHTML = '<tr><td colspan="5" class="dash-empty">Error: ' + escHtml(msg) + '</td></tr>';
        });
    });
}

var _calEvents = [];
var _calYear  = new Date().getFullYear();
var _calMonth = new Date().getMonth();

function renderDashCalendar(events) {
  _calEvents = events;
  _calYear   = new Date().getFullYear();
  _calMonth  = new Date().getMonth();
  renderMonthCal();
}

function calPrevMonth() {
  _calMonth--;
  if (_calMonth < 0) { _calMonth = 11; _calYear--; }
  renderMonthCal();
}
function calNextMonth() {
  _calMonth++;
  if (_calMonth > 11) { _calMonth = 0; _calYear++; }
  renderMonthCal();
}

function renderMonthCal() {
  var MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];
  var DAYS   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

  var labelEl = document.getElementById("cal-month-label");
  if (labelEl) labelEl.textContent = MONTHS[_calMonth] + " " + _calYear;

  var today = new Date(); today.setHours(0,0,0,0);

  // index events by ISO date
  var byDate = {};
  _calEvents.forEach(function(e) {
    var d = e.date || "";
    if (!d) return;
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(e);
  });

  var firstDow    = new Date(_calYear, _calMonth, 1).getDay();
  var daysInMonth = new Date(_calYear, _calMonth + 1, 0).getDate();
  var totalCells  = Math.ceil((firstDow + daysInMonth) / 7) * 7;

  var html = '<table class="month-cal-grid"><thead><tr>';
  DAYS.forEach(function(d) { html += '<th>' + d + '</th>'; });
  html += '</tr></thead><tbody>';

  var day = 1;
  for (var cell = 0; cell < totalCells; cell++) {
    if (cell % 7 === 0) html += '<tr>';

    if (cell < firstDow || day > daysInMonth) {
      html += '<td class="month-cal-empty"></td>';
    } else {
      var mm     = String(_calMonth + 1).padStart(2, '0');
      var dd     = String(day).padStart(2, '0');
      var dateStr = _calYear + '-' + mm + '-' + dd;
      var isToday = (new Date(_calYear, _calMonth, day).getTime() === today.getTime());
      var evs    = byDate[dateStr] || [];

      html += '<td class="month-cal-day' + (isToday ? ' month-cal-today' : '') + '">';
      html += '<div class="month-cal-day-num' + (isToday ? ' month-cal-today-num' : '') + '">' + day + '</div>';

      evs.slice(0, 3).forEach(function(e) {
        var t   = e.type || "";
        var tl  = t.toLowerCase();
        var cls = "cal-pill-gcal";
        if (tl.includes("court") || tl.includes("hearing") || tl.includes("arraignment")) {
          var daysAway = Math.round((new Date(dateStr + 'T00:00:00') - today) / 86400000);
          if      (daysAway <= 7)  cls = "cal-pill-red";
          else if (daysAway <= 30) cls = "cal-pill-orange";
          else if (daysAway <= 60) cls = "cal-pill-yellow";
          else                     cls = "cal-pill-court";
        } else if (tl.includes("meeting") || tl.includes("consult") || tl.includes("deposition")) {
          cls = "cal-pill-meet";
        }
        var label  = e.client_name || e.matter || t;
        if (e.time) label = e.time + " · " + label;
        var uAttr  = escHtml(e.username || "").replace(/'/g, "&#39;");
        var tip    = escHtml((e.client_name || "") + (e.matter ? " — " + e.matter : "") + (e.time ? " @ " + e.time : ""));
        html += '<div class="cal-chip ' + cls + '" title="' + tip + '" onclick="event.stopPropagation();selectClientAndTab(\'' + uAttr + '\',\'overview\')">' + escHtml(label) + '</div>';
      });
      if (evs.length > 3) {
        html += '<div class="cal-chip-more">+' + (evs.length - 3) + ' more</div>';
      }
      html += '</td>';
      day++;
    }

    if (cell % 7 === 6) html += '</tr>';
  }

  html += '</tbody></table>';
  document.getElementById("month-cal-container").innerHTML = html;
}

function renderDashDeadlines(alerts) {
  const tbody = document.getElementById("dash-deadlines-tbody");
  if (!alerts.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="dash-empty">No upcoming court dates within 90 days.</td></tr>';
    return;
  }
  tbody.innerHTML = alerts.map(a => {
    let rowCls = "", badgeCls = "dash-days-normal";
    if      (a.days_until <= 7)  { rowCls = "dash-deadline-red";    badgeCls = "dash-days-red"; }
    else if (a.days_until <= 30) { rowCls = "dash-deadline-orange"; badgeCls = "dash-days-orange"; }
    else if (a.days_until <= 60) { rowCls = "dash-deadline-yellow"; badgeCls = "dash-days-yellow"; }
    var uAttr = escHtml(a.username || "").replace(/'/g, "&#39;");
    return '<tr class="dash-row-link ' + rowCls + '" onclick="selectClientAndTab(\'' + uAttr + '\',\'overview\')">'
      + '<td>' + escHtml(a.client_name) + '</td><td>' + escHtml(a.charges) + '</td>'
      + '<td>' + escHtml(a.court_date) + '</td>'
      + '<td><span class="dash-days-badge ' + badgeCls + '">' + a.days_until + 'd</span></td>'
      + '</tr>';
  }).join("");
}

function renderFollowUps(items) {
  const tbody = document.getElementById("dash-followup-tbody");
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="dash-empty">All clients contacted within 30 days.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(f => {
    var uAttr = escHtml(f.username || "").replace(/'/g, "&#39;");
    var dayCls = f.days_since >= 60 ? "dash-days-red" : "dash-days-orange";
    return '<tr class="dash-row-link dash-deadline-orange" onclick="selectClientAndTab(\'' + uAttr + '\',\'messages\')">'
      + '<td>' + escHtml(f.client_name) + '</td>'
      + '<td>' + escHtml(f.last_contact) + '</td>'
      + '<td><span class="dash-days-badge ' + dayCls + '">' + f.days_since + 'd</span></td>'
      + '</tr>';
  }).join("");
}

function renderDashRecentFiles(files) {
  const tbody = document.getElementById("dash-files-tbody");
  if (!files.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="dash-empty">No files found.</td></tr>';
    return;
  }
  tbody.innerHTML = files.map(f => {
    var uAttr = escHtml(f.username || "").replace(/'/g, "&#39;");
    return '<tr class="dash-row-link" onclick="selectClientAndTab(\'' + uAttr + '\',\'documents\')">'
      + '<td><span class="dash-filename" title="' + escHtml(f.filename) + '">' + escHtml(f.filename) + '</span></td>'
      + '<td>' + escHtml(f.client_name) + '</td><td>' + escHtml(f.category) + '</td>'
      + '<td>' + escHtml(f.modified) + '</td>'
      + '</tr>';
  }).join("");
}

function renderDashBilling(entries, total) {
  const tbody   = document.getElementById("dash-billing-tbody");
  const totalEl = document.getElementById("dash-billing-total");
  totalEl.textContent = total + " hrs";
  const active = entries.filter(e => e.hours > 0);
  if (!active.length) {
    tbody.innerHTML = '<tr><td colspan="2" class="dash-empty">No billable hours yet.</td></tr>';
    return;
  }
  tbody.innerHTML = active.map(e => {
    var uAttr = escHtml(e.username || "").replace(/'/g, "&#39;");
    return '<tr class="dash-row-link" onclick="selectClientAndTab(\'' + uAttr + '\',\'time\')">'
      + '<td>' + escHtml(e.client_name) + '</td>'
      + '<td style="font-weight:600;color:var(--navy)">' + (e.hours||0) + ' hrs</td>'
      + '</tr>';
  }).join("");
}

function selectClientAndTab(username, tabName) {
  document.querySelectorAll(".client-list-item").forEach(b => b.classList.remove("active"));
  const sideBtn = document.getElementById("cli-" + username);
  if (sideBtn) sideBtn.classList.add("active");
  fetch("/portal/attorney/client/" + encodeURIComponent(username))
    .then(r => r.json())
    .then(c => {
      _currentClient = c;
      document.getElementById("atty-tabs").style.display = "block";
      populateOverview(c); populateClientInfo(c); populateBillingLog(c);
      populateMessages(c); populateDocuments(c); populateResearch(c);
      populateSecurity(c);
      if (window.populateBilling) populateBilling(c);
      if (window.populateCaseDates) populateCaseDates(c);
      goToTab(tabName);
    });
}

function openAddEventModal() {
  document.getElementById("dae-date").value = new Date().toISOString().split("T")[0];
  document.getElementById("dae-time").value = "09:00";
  document.getElementById("dae-note").value = "";
  document.getElementById("dae-result").innerHTML = "";
  document.getElementById("dash-add-event-modal").style.display = "flex";
}
function closeDashAddEventModal(e) {
  if (e && e.target !== document.getElementById("dash-add-event-modal")) return;
  document.getElementById("dash-add-event-modal").style.display = "none";
}
function saveDashEvent() {
  const username = document.getElementById("dae-client").value;
  const type     = document.getElementById("dae-type").value;
  const date     = document.getElementById("dae-date").value;
  const time     = document.getElementById("dae-time").value;
  const note     = document.getElementById("dae-note").value.trim();
  const res      = document.getElementById("dae-result");
  if (!username || !date) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Client and date are required.</p>';
    return;
  }
  res.innerHTML = '<p style="color:var(--gray-3);font-family:Arial,sans-serif;font-size:.88rem">Saving…</p>';
  fetch("/portal/attorney/client/" + encodeURIComponent(username))
    .then(r => r.json())
    .then(client => {
      const payload = {
        username: client.username, client_name: client.client_name||"",
        case_type: client.case_type||"", phone: client.phone||"",
        email: client.email||"", legal_issue: client.legal_issue||"",
        google_drive_url: client.google_drive_url||"",
      };
      if (type === "Court Date") {
        payload.next_court_date = date;
        payload.next_meeting    = client.next_meeting || "";
      } else {
        const dt      = new Date(date + "T" + (time||"09:00"));
        const dateStr = dt.toLocaleDateString("en-US", {year:"numeric",month:"long",day:"numeric"});
        const timeStr = dt.toLocaleTimeString("en-US", {hour:"numeric",minute:"2-digit"});
        payload.next_meeting    = dateStr + " at " + timeStr + (note ? " — " + note : "");
        payload.next_court_date = client.next_court_date || "";
      }
      return fetch("/portal/attorney/update-client", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify(payload),
      });
    })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        document.getElementById("dash-add-event-modal").style.display = "none";
        loadDashboard();
      } else {
        res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${escHtml(d.error||"Error saving.")}</p>`;
      }
    })
    .catch(() => { res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Request failed.</p>'; });
}

function openDashLogTimeModal() {
  document.getElementById("dlt-date").value  = new Date().toISOString().split("T")[0];
  document.getElementById("dlt-hours").value = "";
  document.getElementById("dlt-note").value  = "";
  document.getElementById("dlt-result").innerHTML = "";
  document.getElementById("dash-log-time-modal").style.display = "flex";
}
function closeDashLogTimeModal(e) {
  if (e && e.target !== document.getElementById("dash-log-time-modal")) return;
  document.getElementById("dash-log-time-modal").style.display = "none";
}
function saveDashLogTime() {
  const username = document.getElementById("dlt-client").value;
  const date     = document.getElementById("dlt-date").value;
  const hours    = parseFloat(document.getElementById("dlt-hours").value) || 0;
  const note     = document.getElementById("dlt-note").value.trim();
  const res      = document.getElementById("dlt-result");
  if (!note) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Note is required.</p>';
    return;
  }
  if (!username) {
    res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Select a client.</p>';
    return;
  }
  res.innerHTML = '<p style="color:var(--gray-3);font-family:Arial,sans-serif;font-size:.88rem">Saving…</p>';
  fetch("/portal/attorney/billing-entry", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({username, date, hours, note}),
  }).then(r => r.json()).then(d => {
    if (d.success) {
      document.getElementById("dash-log-time-modal").style.display = "none";
      loadDashboard();
    } else {
      res.innerHTML = `<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">${escHtml(d.error||"Error.")}</p>`;
    }
  }).catch(() => { res.innerHTML = '<p style="color:var(--red);font-family:Arial,sans-serif;font-size:.88rem">Request failed.</p>'; });
}

// ── Back-navigation guard ─────────────────────────────────────────────────────
(function() {
  history.pushState({portalGuard: true}, '');

  window.addEventListener('popstate', function(e) {
    history.pushState({portalGuard: true}, '');
    document.getElementById('nav-guard-modal').style.display = 'flex';
  });

  window.addEventListener('beforeunload', function(e) {
    e.preventDefault();
    e.returnValue = '';
  });
})();

function navGuardStay() {
  document.getElementById('nav-guard-modal').style.display = 'none';
}

function navGuardLogout() {
  window.onbeforeunload = null;
  window.location.href = '/logout';
}
