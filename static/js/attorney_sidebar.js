// Collapsible sidebar sections. Each label with data-collapse="key" opens or
// closes the element its aria-controls names. Sections start closed on every
// page load (the template renders them hidden).

(function () {
  document.querySelectorAll(".sidebar-collapse[data-collapse]").forEach(function (label) {
    var body = document.getElementById(label.getAttribute("aria-controls"));
    function toggle() {
      var open = label.getAttribute("aria-expanded") !== "true";
      if (body) body.hidden = !open;
      label.setAttribute("aria-expanded", open ? "true" : "false");
      label.classList.toggle("is-collapsed", !open);
    }
    label.addEventListener("click", toggle);
    label.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
  });
})();
