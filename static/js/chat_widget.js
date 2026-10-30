// Floating legal chat widget and page-visit tracking. Loaded by base.html.
// window._FIRM_NAME is set in base.html's <head>.

(function() {
  var _chatOpen    = false;
  var _chatHistory = [];   // [{role, content}]
  var _chatGreeted = false;

  var GREETING = "Hi there! I'm the " + window._FIRM_NAME + " virtual assistant. How can I help you with your legal question today?";

  // Wiggle the closed pill 5 seconds after the page loads, then every 20
  // seconds while the visitor stays, skipping while the chat is open, the
  // pill is hovered, or the tab is in the background.
  (function () {
    var pill = document.getElementById("chat-toggle");
    if (!pill) return;
    function wiggle() {
      if (document.hidden || pill.matches(":hover")) return;
      if (_chatOpen) return;
      pill.classList.remove("is-wiggling");
      void pill.offsetWidth;
      pill.classList.add("is-wiggling");
      setTimeout(function () { pill.classList.remove("is-wiggling"); }, 1000);
    }
    setTimeout(function () {
      wiggle();
      setInterval(wiggle, 20000);
    }, 5000);
  })();

  window.toggleChat = function() {
    _chatOpen = !_chatOpen;
    var win = document.getElementById("chat-window");
    win.style.display = _chatOpen ? "flex" : "none";
    win.style.flexDirection = "column";
    if (_chatOpen && !_chatGreeted) {
      _chatGreeted = true;
      appendChatBubble("bot", GREETING);
    }
    if (_chatOpen) {
      setTimeout(function() { document.getElementById("chat-input").focus(); }, 80);
    }
  };

  window.sendChatMsg = function() {
    var input = document.getElementById("chat-input");
    var text  = input.value.trim();
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    appendChatBubble("user", text);
    _chatHistory.push({ role: "user", content: text });
    showTyping();
    fetch("/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: _chatHistory.slice(0, -1) })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      hideTyping();
      var reply = d.reply || (d.error ? "Sorry, I hit a snag. Please try again or visit our intake form." : "");
      if (reply) {
        appendChatBubble("bot", reply);
        _chatHistory.push({ role: "assistant", content: reply });
      }
    })
    .catch(function() {
      hideTyping();
      appendChatBubble("bot", "Connection issue. Please complete our intake form and an attorney will reach out shortly.");
    });
  };

  function appendChatBubble(role, text) {
    var msgs = document.getElementById("chat-messages");
    var div  = document.createElement("div");
    div.className = "chat-bubble " + role;
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  var _typingEl = null;
  function showTyping() {
    var msgs = document.getElementById("chat-messages");
    _typingEl = document.createElement("div");
    _typingEl.className = "chat-typing";
    _typingEl.innerHTML = "<span></span><span></span><span></span>";
    msgs.appendChild(_typingEl);
    msgs.scrollTop = msgs.scrollHeight;
  }
  function hideTyping() {
    if (_typingEl && _typingEl.parentNode) _typingEl.parentNode.removeChild(_typingEl);
    _typingEl = null;
  }

  // Hide on attorney/client portal pages
  var path = window.location.pathname;
  if (path.includes("portal") || path.includes("attorney-login") || path.includes("client-portal")) {
    var w = document.getElementById("chat-widget");
    if (w) w.style.display = "none";
  }
})();

/* ── Page visit tracking (once per browser session per page) ── */
(function() {
  var tracked = ["index","meet_the_firm","intake","research","drafting"];
  var page = document.body.dataset.page;
  if (!page || tracked.indexOf(page) === -1) return;
  var key = "pv_" + page;
  if (sessionStorage.getItem(key)) return;
  sessionStorage.setItem(key, "1");
  fetch("/api/track-visit", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({page: page})
  });
})();
