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
  if (typeof loadIntakeQueue === "function") loadIntakeQueue();

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
          <div class="lead-card-header" data-on-click='[["toggleLead",["$this"]]]'>
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
              data-on-click='[["convertLead",["$this"]]]' data-lead='${safe}'>Convert to Client →</button>
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
      if (window.populateFelony) populateFelony(c);
      if (window.populateEngagement) populateEngagement(c);
      if (window.populateCaseDates) populateCaseDates(c);
      showAttyTab("overview", document.querySelector("#atty-tabs .portal-tab-btn"));
    });
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
  submitLogout();
}
