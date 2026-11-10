// CSP-safe event wiring. The Content-Security-Policy forbids inline handlers
// (onclick="..."), so markup says what to call in a data attribute instead:
//
//   <button data-on-click='[["showTab",["billing","$this"]],["loadBilling",[]]]'>
//
// Each entry is [functionName, args]. The function must be a global. Args are
// JSON values, with these stand-ins:
//   "$this" the element   "$event" the event   "$value" el.value
//   "$text" el.textContent   "$files" el.files   "$checked" el.checked
//   "$id:foo" document.getElementById("foo")   "$$x" the literal string "$x"
// Pseudo-calls: ["$prevent"] preventDefault, ["$stop"] stopPropagation,
// ["$ifSelf"] skip the rest unless the event started on this element.
//
// Like inline handlers, every matching element from the target up to the
// document runs, innermost first, until one stops propagation.
(function () {
  "use strict";
  var TYPES = ["click", "change", "input", "submit", "keydown"];

  function resolve(arg, el, ev) {
    if (typeof arg !== "string" || arg.charAt(0) !== "$") return arg;
    if (arg.slice(0, 2) === "$$") return arg.slice(1);
    if (arg === "$this") return el;
    if (arg === "$event") return ev;
    if (arg === "$value") return el.value;
    if (arg === "$text") return el.textContent;
    if (arg === "$files") return el.files;
    if (arg === "$checked") return el.checked;
    if (arg.slice(0, 4) === "$id:") return document.getElementById(arg.slice(4));
    return arg;
  }

  function runCalls(spec, el, ev) {
    var calls;
    try { calls = JSON.parse(spec); } catch (e) { console.error("Bad data-on spec", spec); return; }
    for (var i = 0; i < calls.length; i++) {
      var name = calls[i][0], args = calls[i][1] || [];
      if (name === "$prevent") { ev.preventDefault(); continue; }
      if (name === "$stop") { ev.stopPropagation(); continue; }
      if (name === "$ifSelf") { if (ev.target !== el) return; continue; }
      var fn = window[name];
      if (typeof fn !== "function") { console.error("No handler named", name); continue; }
      fn.apply(el, args.map(function (a) { return resolve(a, el, ev); }));
    }
  }

  TYPES.forEach(function (type) {
    var attr = "data-on-" + type;
    document.addEventListener(type, function (ev) {
      var el = ev.target && ev.target.nodeType === 1 ? ev.target : ev.target && ev.target.parentElement;
      while (el && el !== document) {
        if (el.hasAttribute && el.hasAttribute(attr)) {
          runCalls(el.getAttribute(attr), el, ev);
          if (ev.cancelBubble) break;
        }
        el = el.parentElement;
      }
    });
  });
})();
