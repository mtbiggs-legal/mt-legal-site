// Move to the top of the page whenever the attorney switches to another page
// of the portal (a sidebar tab, a client, a client tab, a dashboard link), so
// attention goes back to the new page's heading. Loaded after the scripts
// that define these functions. Live refreshes (attorney_live.js, _liveBg) call
// some of them in the background and must not move the page.

(function () {
  var NAV_FUNCTIONS = [
    "showDashboard", "showEmailReview", "showInsights", "showFirmAdmin", "showGlobalResearch", "loadLeads",
    "showNewClientTab", "showConflictCheck", "showAllClients",
    "selectClient", "selectClientAndTab", "showAttyTab", "goToTab",
  ];

  function toTop() {
    if (typeof _liveBg !== "undefined" && _liveBg) return;
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }

  NAV_FUNCTIONS.forEach(function (name) {
    var original = window[name];
    if (typeof original !== "function") return;
    window[name] = function () {
      var result = original.apply(this, arguments);
      toTop();
      return result;
    };
  });
})();
