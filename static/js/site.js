// Site-wide page behaviour (banner, scroll boxes, mobile collapse, pop-outs).
// Loaded by base.html on every page, before app.js and the page's own scripts.

// Compact the fixed banner once the visitor scrolls. The body reserves the
// banner's full height (measured while expanded) so nothing below it moves.
(function () {
  var header = document.querySelector(".site-header");
  if (!header) return;
  var root = document.documentElement;
  // Measure the expanded height with transitions paused, so a resize mid-
  // animation can't capture an in-between size.
  function reserve() {
    var compact = header.classList.contains("is-compact");
    header.classList.add("is-measuring");
    header.classList.remove("is-compact");
    root.style.setProperty("--header-h", header.offsetHeight + "px");
    if (compact) header.classList.add("is-compact");
    void header.offsetHeight;
    header.classList.remove("is-measuring");
  }
  var ticking = false;
  function update() {
    ticking = false;
    var y = window.scrollY;
    // Hysteresis so the banner doesn't flicker around the threshold.
    if (y > 60) header.classList.add("is-compact");
    else if (y < 10) header.classList.remove("is-compact");
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  window.addEventListener("resize", reserve);
  window.addEventListener("load", reserve);   // web fonts can change the height
  reserve();
  update();
})();

// Self-scrolling blocks drop their bottom fade once read to the end.
document.querySelectorAll(".ed-scroll").forEach(function (box) {
  function check() {
    box.classList.toggle("is-end", box.scrollTop + box.clientHeight >= box.scrollHeight - 8);
  }
  box.addEventListener("scroll", check, { passive: true });
  window.addEventListener("resize", check);
  check();

  // On first hover, slide the content up a little and back so it's obvious
  // the block scrolls. Skipped once the reader has scrolled it themselves, or
  // when they've asked for reduced motion.
  var nudged = false;
  box.addEventListener("mouseenter", function () {
    if (nudged || box.scrollTop > 0 || box.scrollHeight <= box.clientHeight) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    nudged = true;
    box.classList.add("is-nudging");          // CSS slides the content up and back
    setTimeout(function () { box.classList.remove("is-nudging"); }, 1000);
  });
});

// Phones: bring a box that was just opened to the top of the screen, just
// under the fixed header, so its title is the first thing in view. Waits a
// frame so boxes closing above it have already collapsed.
window.scrollBoxIntoView = function (el) {
  if (!el || !window.matchMedia("(max-width: 700px)").matches) return;
  requestAnimationFrame(function () {
    var header = document.querySelector(".site-header");
    // The header shrinks once the page scrolls past 60px, so measure the
    // height it will have at the destination, not the height it has now.
    function headerAt(y) {
      if (!header) return 0;
      var was = header.classList.contains("is-compact");
      header.classList.add("is-measuring");
      header.classList.toggle("is-compact", y > 60);
      var hgt = header.offsetHeight;
      header.classList.toggle("is-compact", was);
      void header.offsetHeight;
      header.classList.remove("is-measuring");
      return hgt;
    }
    var elTop = el.getBoundingClientRect().top + window.pageYOffset;
    var top = elTop - headerAt(elTop - header.offsetHeight - 10) - 10;
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
  });
};
// Expandable boxes act as an accordion: opening one closes any other open
// box in the same group (same parent), on every page.
document.addEventListener("toggle", function (e) {
  var opened = e.target;
  if (!(opened instanceof HTMLDetailsElement) || !opened.open || !opened.parentElement) return;
  Array.prototype.forEach.call(opened.parentElement.children, function (sib) {
    if (sib !== opened && sib.tagName === "DETAILS" && sib.open) sib.open = false;
  });
  window.scrollBoxIntoView(opened);
}, true);

// A tap on an open box's content closes it too, not just a tap on its
// title. Links, buttons, form fields, and text being selected are left alone.
window.isTapOnControl = function (e) {
  if (e.target.closest("a, button, input, select, textarea, label, summary, [contenteditable]")) return true;
  var sel = window.getSelection && window.getSelection();
  return !!(sel && String(sel).length);
};
// If closing left the box's title above the screen, bring it back into view.
window.revealClosedBox = function (box, title) {
  var header = document.querySelector(".site-header");
  var top = (title || box).getBoundingClientRect().top;
  if (top < (header ? header.getBoundingClientRect().height : 0)) window.scrollBoxIntoView(box);
};
document.addEventListener("click", function (e) {
  var body = e.target.closest("details[open] > .ed-box-body");
  if (!body || window.isTapOnControl(e)) return;
  var box = body.parentElement;
  box.open = false;
  window.revealClosedBox(box, box.querySelector("summary"));
});

// Phones only: always-open blocks ([data-mobile-collapse]) fold down to their
// heading and open on tap, one at a time, so long pages stay short. Wider
// screens keep them permanently open.
(function () {
  var blocks = Array.prototype.slice.call(document.querySelectorAll("[data-mobile-collapse]"));
  if (!blocks.length) return;
  var phone = window.matchMedia("(max-width: 700px)");
  function head(b) { return b.querySelector(".ed-layer-head, .ed-panel-head"); }
  function setOpen(b, open) {
    b.classList.toggle("is-collapsed", !open);
    var h = head(b);
    if (h) h.setAttribute("aria-expanded", open ? "true" : "false");
  }
  function apply() {
    blocks.forEach(function (b) {
      var h = head(b);
      if (!h) return;
      if (phone.matches) {
        b.classList.add("is-collapsible");
        h.setAttribute("role", "button");
        h.setAttribute("tabindex", "0");
        setOpen(b, false);
      } else {
        b.classList.remove("is-collapsible", "is-collapsed");
        h.removeAttribute("role"); h.removeAttribute("tabindex"); h.removeAttribute("aria-expanded");
      }
    });
  }
  function toggle(b) {
    if (!b.classList.contains("is-collapsible")) return;
    var opening = b.classList.contains("is-collapsed");
    if (opening) {
      blocks.forEach(function (o) {
        if (o !== b && o.parentElement === b.parentElement && o.classList.contains("is-collapsible")) setOpen(o, false);
      });
    }
    setOpen(b, opening);
    if (opening) window.scrollBoxIntoView(b);
  }
  blocks.forEach(function (b) {
    var h = head(b);
    if (!h) return;
    h.addEventListener("click", function () { toggle(b); });
    var body = b.querySelector(".ed-layer-body, .ed-panel-body");
    if (body) body.addEventListener("click", function (e) {
      if (!b.classList.contains("is-collapsible") || b.classList.contains("is-collapsed")) return;
      if (window.isTapOnControl(e)) return;
      toggle(b);
      window.revealClosedBox(b, h);
    });
    h.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(b); }
    });
  });
  apply();
  if (phone.addEventListener) phone.addEventListener("change", apply);
})();

// Pop-out boxes (.ed-boxes--pop): on wider screens an opened box's content
// floats beside it (right, else left, else centred below) and a shade dims
// the page. Clicking the shade or pressing Escape closes it.
(function () {
  var groups = document.querySelectorAll(".ed-boxes--pop");
  if (!groups.length) return;
  var shade = document.createElement("div");
  shade.className = "ed-pop-shade";
  shade.setAttribute("aria-hidden", "true");
  document.body.appendChild(shade);
  var wide = window.matchMedia("(min-width: 701px)");
  var boxes = [];
  groups.forEach(function (g) {
    boxes = boxes.concat(Array.prototype.slice.call(g.querySelectorAll(":scope > details")));
  });
  function place(box) {
    box.classList.remove("pops-left", "pops-center");
    var body = box.querySelector(".ed-box-body");
    if (!body) return;
    var r = box.getBoundingClientRect();
    var w = body.offsetWidth + 16;
    var vw = document.documentElement.clientWidth;
    if (r.right + w <= vw) return;
    if (r.left - w >= 0) box.classList.add("pops-left");
    else box.classList.add("pops-center");
  }
  function closeAll() { boxes.forEach(function (b) { b.open = false; }); }
  function sync() {
    var open = boxes.filter(function (b) { return b.open; })[0];
    if (open && wide.matches) place(open);
    shade.classList.toggle("is-on", !!open && wide.matches);
  }
  boxes.forEach(function (b) {
    b.addEventListener("toggle", function () {
      if (b.open) boxes.forEach(function (o) { if (o !== b) o.open = false; });
      sync();
    });
  });
  shade.addEventListener("click", closeAll);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeAll(); });
  window.addEventListener("resize", sync);
})();

// Scroll reveals: sections fade up as they come into view, and the cards in a
// grid arrive one after another. base.html adds .rv-on to <html> before the
// first paint (not for reduced motion); the CSS hides these elements until
// they get .rv-in, and .rv-done hands them back to their normal styles.
(function () {
  var root = document.documentElement;
  if (!root.classList.contains("rv-on")) return;
  window._rvReady = true;
  // Groups whose children arrive one at a time, and the gap between them.
  var STAGGERED = [
    [".ed-hero-text", 160], [".ed-page-head", 120],
    ["#practice .ed-grid", 140],
    [".ed-grid", 90], [".ed-boxes", 90], [".ed-layers", 90],
  ];
  var SINGLE = ".ed-subhead, .ed-overview, .ed-quote, .ed-cta";
  var seen = [];

  // Homepage hero: "what comes next." rolls up into place, then the paragraph
  // below writes itself in word by word.
  var heroText = document.querySelector(".ed-hero--home .ed-hero-text");
  if (heroText) {
    var em = heroText.querySelector("h1 em");
    if (em) em.classList.add("rv-roll");
    var lede = heroText.querySelector(".ed-lede");
    if (lede) {
      seen.push(lede);   // its words animate instead of the whole block
      var WORDS_START = 1200, WORD_STEP = 55;
      var count = splitWords(lede, WORDS_START, WORD_STEP);
      // Once every word is in, put the plain text back. Some phone browsers
      // (iOS Safari) can leave animated words drawn soft until they repaint.
      setTimeout(function () {
        lede.querySelectorAll(".rv-word").forEach(function (w) {
          w.replaceWith(document.createTextNode(w.textContent));
        });
        lede.normalize();
      }, WORDS_START + count * WORD_STEP + 700);
      // Phones show a "Read more" cue; it waits until the first sentence is written.
      var first = lede.querySelector(".ed-lede-first");
      var firstCount = first ? first.querySelectorAll(".rv-word").length : count;
      var cueAt = WORDS_START + firstCount * WORD_STEP;
      lede.style.setProperty("--rv-cue-delay", cueAt + "ms");
      // Once the cue has faded in, let the fold's own show/hide take over again.
      setTimeout(function () { lede.classList.add("rv-lede-done"); }, cueAt + 450);
    }
  }
  // Wrap each word of el's text in a span with its own start time; returns the count.
  function splitWords(el, start, step) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var nodes = [], n = 0;
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var frag = document.createDocumentFragment();
      node.nodeValue.split(/(\s+)/).forEach(function (part) {
        if (!part) return;
        if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
        var span = document.createElement("span");
        span.className = "rv-word";
        span.style.setProperty("--d", (start + n++ * step) + "ms");
        span.textContent = part;
        frag.appendChild(span);
      });
      node.parentNode.replaceChild(frag, node);
    });
    return n;
  }

  function mark(el, delay) {
    if (seen.indexOf(el) !== -1) return;
    seen.push(el);
    el.classList.add("rv");
    el.style.setProperty("--rv-delay", delay + "ms");
  }
  // On a repeat visit only the homepage headline animates; the rest stays put.
  var repeat = root.classList.contains("rv-static");
  if (repeat) { STAGGERED = [[".ed-hero--home .ed-hero-text", 160]]; SINGLE = ""; }
  STAGGERED.forEach(function (g) {
    document.querySelectorAll(g[0]).forEach(function (group) {
      Array.prototype.forEach.call(group.children, function (child, i) {
        mark(child, Math.min(i, 8) * g[1]);
      });
    });
  });
  if (SINGLE) document.querySelectorAll(SINGLE).forEach(function (el) { mark(el, 0); });
  // Remember this page, so the next visit to it stays still.
  try {
    var pages = JSON.parse(localStorage.getItem("mtl-seen-pages") || "[]");
    if (pages.indexOf(location.pathname) === -1) {
      pages.push(location.pathname);
      localStorage.setItem("mtl-seen-pages", JSON.stringify(pages.slice(-200)));
    }
  } catch (e) {}

  function done(el) {
    el.classList.add("rv-done");
    el.style.removeProperty("--rv-delay");
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      var el = e.target;
      io.unobserve(el);
      el.classList.add("rv-in");
      // Hand back to the element's own transitions (hover lifts) once in place.
      var ms = parseFloat(getComputedStyle(el).getPropertyValue("--rv-delay")) || 0;
      setTimeout(function () { done(el); }, ms + 800);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.12 });
  seen.forEach(function (el) { io.observe(el); });
  root.classList.add("rv-ready");
})();
