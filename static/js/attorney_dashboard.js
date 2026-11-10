// attorney_dashboard.js: The firm dashboard and the Insights panel.
// Split out of attorney_portal.js; loaded right after it (see attorney_portal.html),
// and like it, defines global functions the templates call.

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

function loadDashboard(keepMonth) {
  fetch("/portal/attorney/dashboard")
    .then(r => {
      if (!r.ok || !r.headers.get("content-type")?.includes("application/json")) {
        return Promise.reject(new Error("HTTP " + r.status + " — session may have expired, please reload."));
      }
      return r.json();
    })
    .then(d => {
      renderDashCalendar(d.calendar || [], keepMonth === true);
      renderDashDeadlines(d.deadlines || []);
      renderFollowUps(d.follow_up_needed || []);
      if (window.renderActionItems) renderActionItems(d.action_items || []);
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
            + '<div style="font-family:Arial,sans-serif;font-size:.82rem;color:var(--navy);font-weight:600;cursor:pointer" data-on-click=\'[["selectClient",["' + uAttr + '"]]]\'>'
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
      renderDashStats(d);
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

// Summary tiles across the top of the dashboard.
function renderDashStats(d) {
  function set(id, text) { var el = document.getElementById(id); if (el) el.textContent = text; }
  var deadlines = d.deadlines || [];
  var soon      = deadlines.filter(function(a) { return a.days_until <= 7; })
                           .sort(function(a, b) { return a.days_until - b.days_until; });
  set("dash-stat-court", soon.length);
  set("dash-stat-court-sub", soon.length
    ? "Next: " + (soon[0].client_name || "") + " in " + soon[0].days_until + "d"
    : deadlines.length + " in the next 90 days");
  set("dash-stat-followup", (d.follow_up_needed || []).length);
  set("dash-stat-hours", (d.billing_total || 0) + " hrs");
  var clients = d.billing || [];
  set("dash-stat-clients", clients.length);
  set("dash-stat-clients-sub", clients.filter(function(c) { return c.hours > 0; }).length + " with hours logged");
  set("dash-today", new Date().toLocaleDateString("en-US",
    { weekday: "long", month: "long", day: "numeric", year: "numeric" }));
}

var _calEvents = [];
var _calYear  = new Date().getFullYear();
var _calMonth = new Date().getMonth();

var _calShown = false;

// keepMonth: a live refresh redraws the month the attorney is looking at
// instead of jumping back to the current one.
function renderDashCalendar(events, keepMonth) {
  _calEvents = events;
  if (!keepMonth || !_calShown) {
    _calYear  = new Date().getFullYear();
    _calMonth = new Date().getMonth();
  }
  _calShown = true;
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
        html += '<div class="cal-chip ' + cls + '" title="' + tip + '" data-on-click=\'[["$stop",[]],["selectClientAndTab",["' + uAttr + '","overview"]]]\'>' + escHtml(label) + '</div>';
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
    return '<tr class="dash-row-link ' + rowCls + '" data-on-click=\'[["selectClientAndTab",["' + uAttr + '","overview"]]]\'>'
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
    return '<tr class="dash-row-link dash-deadline-orange" data-on-click=\'[["selectClientAndTab",["' + uAttr + '","messages"]]]\'>'
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
    return '<tr class="dash-row-link" data-on-click=\'[["selectClientAndTab",["' + uAttr + '","documents"]]]\'>'
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
    return '<tr class="dash-row-link" data-on-click=\'[["selectClientAndTab",["' + uAttr + '","time"]]]\'>'
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
      if (window.populateFelony) populateFelony(c);
      if (window.populateEngagement) populateEngagement(c);
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
