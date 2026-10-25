# AI Message Assistant Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Auto-reply to every client message with a Claude Haiku AI response, billing 0.1 hrs per reply and logging it in the billing log.

**Architecture:** Modify `client_send_message` to call Claude after saving the client message, append the AI reply to `client["messages"]`, add a billing entry, and return the reply text to the frontend. The frontend appends both messages to the thread. A disclaimer banner sits at the top of the Messages tab.

**Tech Stack:** Python/Flask, `anthropic` SDK (already installed), Jinja2, vanilla JS, CSS in `static/css/style.css`.

**Design doc:** `docs/plans/2026-03-02-ai-message-assistant-design.md`

---

## Task 1: Add `from-ai` CSS class

**Files:**
- Modify: `static/css/style.css`

**Step 1: Read the existing message bubble styles**

Read `static/css/style.css` and find the lines:
```css
.message-bubble.from-client { ... }
.message-bubble.from-attorney { ... }
```
They are around line 1153-1154.

**Step 2: Add the `from-ai` style directly after `from-attorney`**

```css
.message-bubble.from-ai { background: #e8edf2; color: #2c3e50; align-self: flex-end; border-bottom-right-radius: 4px; }
```

This gives AI bubbles a muted blue-gray background — visually distinct from both the client (light gray) and attorney (navy) bubbles.

**Step 3: Verify no syntax errors**

```bash
python -c "from app import app; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add static/css/style.css
git commit -m "style(chat): add from-ai message bubble CSS class"
```
Co-author: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## Task 2: Modify `client_send_message` in app.py — add AI reply + billing

**Files:**
- Modify: `app.py` (around line 1011 — `client_send_message` function)
- Test: `tests/test_ai_chat.py` (create)

**Step 1: Write the failing tests**

Create `tests/test_ai_chat.py`:

```python
import json, sys, types, pytest
from pathlib import Path

# Stub heavy deps
for mod in ("anthropic", "google.oauth2.credentials",
            "google_auth_oauthlib.flow", "googleapiclient.discovery",
            "mammoth", "pypdf", "fpdf", "stripe"):
    if mod not in sys.modules:
        parts = mod.split(".")
        for i in range(1, len(parts) + 1):
            name = ".".join(parts[:i])
            if name not in sys.modules:
                sys.modules[name] = types.ModuleType(name)

import app as _app_module

_app = _app_module.app
_app.config["TESTING"] = True
_app.config["SECRET_KEY"] = "test"


@pytest.fixture(autouse=True)
def patch_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(_app_module, "CLIENT_ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(_app_module, "CLIENT_FILES_DIR",    tmp_path / "files")
    (tmp_path / "accounts").mkdir()
    (tmp_path / "files").mkdir()


@pytest.fixture
def flask_client(patch_dirs):
    with _app.test_client() as c:
        yield c


def make_client(tmp_path, username="testclient"):
    rec = {
        "username":        username,
        "client_name":     "Test Client",
        "case_type":       "Criminal Defense",
        "legal_issue":     "DUI charge",
        "assigned_attorney": "Endocide",
        "hours_billed":    0,
        "billing_log":     [],
        "messages":        [],
    }
    (tmp_path / "accounts").mkdir(exist_ok=True)
    (tmp_path / "accounts" / f"{username}.json").write_text(json.dumps(rec))
    return rec


def _stub_anthropic(monkeypatch, reply_text="I understand your concern."):
    """Stub get_anthropic_client so Claude returns reply_text."""
    fake_content = types.SimpleNamespace(text=reply_text)
    fake_msg     = types.SimpleNamespace(content=[fake_content])
    fake_client  = types.SimpleNamespace(
        messages=types.SimpleNamespace(
            create=lambda **kw: fake_msg
        )
    )
    monkeypatch.setattr(_app_module, "get_anthropic_client", lambda: fake_client)


def test_message_saved_and_ai_reply_returned(flask_client, tmp_path, monkeypatch):
    """Client message is saved; AI reply is returned in response."""
    make_client(tmp_path)
    _stub_anthropic(monkeypatch, reply_text="Thank you for reaching out.")
    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"]     = "client"
    resp = flask_client.post("/portal/client/message",
                             content_type="application/json",
                             json={"text": "What is the status of my case?"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "Thank you for reaching out." in data["ai_reply"]

    client = _app_module.load_client("testclient")
    # Both messages saved
    assert len(client["messages"]) == 2
    assert client["messages"][0]["from"] == "client"
    assert client["messages"][1]["from"] == "ai"


def test_ai_reply_billed_01_hours(flask_client, tmp_path, monkeypatch):
    """Each AI response adds 0.1 hrs to billing log and hours_billed."""
    make_client(tmp_path)
    _stub_anthropic(monkeypatch)
    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"]     = "client"
    flask_client.post("/portal/client/message",
                      content_type="application/json",
                      json={"text": "Hello"})

    client = _app_module.load_client("testclient")
    assert client["hours_billed"] == pytest.approx(0.1)
    ai_entries = [e for e in client["billing_log"] if e.get("type") == "ai_message"]
    assert len(ai_entries) == 1
    assert ai_entries[0]["hours"] == 0.1


def test_anthropic_failure_still_saves_message(flask_client, tmp_path, monkeypatch):
    """If Anthropic API fails, client message is still saved; no billing entry."""
    make_client(tmp_path)
    def _raise():
        raise Exception("API error")
    monkeypatch.setattr(_app_module, "get_anthropic_client", _raise)

    with flask_client.session_transaction() as sess:
        sess["username"] = "testclient"
        sess["role"]     = "client"
    resp = flask_client.post("/portal/client/message",
                             content_type="application/json",
                             json={"text": "Hello"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "ai_reply" not in data

    client = _app_module.load_client("testclient")
    assert len(client["messages"]) == 1          # only client message
    assert client["hours_billed"] == 0           # no billing
    assert client["billing_log"] == []
```

**Step 2: Run to verify all 3 tests fail**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -m pytest tests/test_ai_chat.py -v
```

Expected: all 3 `FAILED` (route doesn't return `ai_reply` yet)

**Step 3: Modify `client_send_message` in app.py**

Read the current function (around line 1011). Replace it entirely with:

```python
@app.route("/portal/client/message", methods=["POST"])
@require_client
def client_send_message():
    data = request.get_json()
    text = (data or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "Message cannot be empty."}), 400
    client = load_client(session["username"])
    if not client:
        return jsonify({"error": "Account not found."}), 404

    # Save client message
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    client.setdefault("messages", []).append({
        "from": "client",
        "date": now,
        "text": text,
    })

    # Generate AI reply
    ai_reply = None
    try:
        attorney_key     = client.get("assigned_attorney", "")
        attorney_display = ATTORNEYS.get(attorney_key, {}).get("display", "your attorney")
        history          = client["messages"][-10:]  # last 10 for context
        system_prompt = (
            f"You are the Endo-Legal Assistant, an AI assistant for Endo-Legal "
            f"Attorneys At Law, PLLC. You are responding on behalf of {attorney_display}.\n\n"
            f"Client: {client.get('client_name', '')}\n"
            f"Case Type: {client.get('case_type', '')}\n"
            f"Legal Issue: {client.get('legal_issue', '')}\n\n"
            "Your role:\n"
            "- Provide helpful, professional responses to client questions\n"
            "- Acknowledge their concerns and keep them informed\n"
            "- Do NOT give specific legal advice or make promises about case outcomes\n"
            "- Always remind clients their messages are saved and reviewed by their attorney\n"
            "- Sign every response as: \u2014 Endo-Legal Assistant\n\n"
            "Keep responses concise (2-4 sentences). Be warm and professional."
        )
        turns = []
        for m in history:
            role = "user" if m["from"] == "client" else "assistant"
            turns.append({"role": role, "content": m["text"]})
        ai = get_anthropic_client()
        response  = ai.messages.create(
            model=MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=turns,
        )
        ai_reply = response.content[0].text
        reply_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        client["messages"].append({
            "from": "ai",
            "date": reply_date,
            "text": ai_reply,
        })
        # Bill 0.1 hrs for AI response
        client["hours_billed"] = round(client.get("hours_billed", 0) + 0.1, 2)
        client.setdefault("billing_log", []).append({
            "date":  date.today().isoformat(),
            "hours": 0.1,
            "note":  "AI assistant response \u2014 " + text[:60] + ("..." if len(text) > 60 else ""),
            "type":  "ai_message",
        })
    except Exception:
        pass  # AI failure is non-fatal; client message already saved above

    client["last_communication"] = date.today().isoformat()
    save_client(client)

    result = {"success": True}
    if ai_reply:
        result["ai_reply"] = ai_reply
    return jsonify(result)
```

**Step 4: Run tests to verify all 3 pass**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -m pytest tests/test_ai_chat.py -v
```

Expected: all 3 `PASSED`

**Step 5: Run full suite for regressions**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -m pytest tests/ -v
```

Expected: all `PASSED`

**Step 6: Commit**

```bash
git add app.py tests/test_ai_chat.py
git commit -m "feat(ai-chat): auto-reply to client messages with Claude, bill 0.1 hrs"
```
Co-author: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## Task 3: Update `sendMessage()` JS + add disclaimer in client_portal.html

**Files:**
- Modify: `templates/client_portal.html`

**Step 1: Read the file first**, focusing on the Messages tab (lines ~90-122) and the `sendMessage()` function (lines ~206-230).

**Step 2: Add the disclaimer banner inside the Messages tab card**

Find the Messages tab card's `portal-section-title` div:
```html
<div class="portal-section-title">Message Thread</div>
```

Insert the disclaimer BEFORE it:

```html
        <div style="background:#f0f4f8;border-left:4px solid #6b8cae;border-radius:4px;padding:.65rem 1rem;margin-bottom:.85rem;font-family:Arial,sans-serif;font-size:.82rem;color:#2c3e50">
          <strong>Endo-Legal Assistant:</strong> You are chatting with an AI assistant. All messages are saved and reviewed by your attorney. Responses are billed at 0.1 hrs per message.
        </div>
```

**Step 3: Replace the `sendMessage()` function**

Find and replace the entire `sendMessage` function (lines ~206-230) with this updated version that handles `ai_reply` and uses safe DOM methods:

```javascript
function sendMessage() {
  var text = document.getElementById("msg-text").value.trim();
  var res  = document.getElementById("msg-result");
  if (!text) {
    res.textContent = "Please enter a message.";
    res.style.color = "var(--red)";
    return;
  }
  res.textContent = "Sending\u2026";
  res.style.color = "var(--gray-3)";
  var btn = document.querySelector("[onclick='sendMessage()']");
  if (btn) btn.disabled = true;

  fetch("/portal/client/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (btn) btn.disabled = false;
    if (d.success) {
      var thread = document.getElementById("message-thread");
      var now = new Date().toLocaleDateString("en-US", { year:"numeric", month:"2-digit", day:"2-digit" });

      // Append client message
      var clientWrap = document.createElement("div");
      var clientBubble = document.createElement("div");
      clientBubble.className = "message-bubble from-client";
      clientBubble.textContent = text;
      var clientMeta = document.createElement("div");
      clientMeta.className = "message-meta";
      clientMeta.textContent = "You \u00B7 " + now;
      clientWrap.appendChild(clientBubble);
      clientWrap.appendChild(clientMeta);
      thread.appendChild(clientWrap);

      // Append AI reply if returned
      if (d.ai_reply) {
        var aiWrap = document.createElement("div");
        var aiBubble = document.createElement("div");
        aiBubble.className = "message-bubble from-ai";
        aiBubble.textContent = d.ai_reply;
        var aiMeta = document.createElement("div");
        aiMeta.className = "message-meta";
        aiMeta.style.textAlign = "right";
        aiMeta.textContent = "Endo-Legal Assistant \u00B7 " + now;
        aiWrap.appendChild(aiBubble);
        aiWrap.appendChild(aiMeta);
        thread.appendChild(aiWrap);
      }

      thread.scrollTop = thread.scrollHeight;
      document.getElementById("msg-text").value = "";
      res.textContent = d.ai_reply ? "" : "Message sent. Your attorney will respond shortly.";
      res.style.color = "var(--green)";
      if (res.textContent) setTimeout(function() { res.textContent = ""; }, 4000);
    } else {
      res.textContent = d.error || "An error occurred.";
      res.style.color = "var(--red)";
    }
  })
  .catch(function() {
    if (btn) btn.disabled = false;
    res.textContent = "Connection error. Please try again.";
    res.style.color = "var(--red)";
  });
}
```

**Step 4: Update Jinja template rendering for `from-ai` messages**

The template renders messages on page load at lines ~102-108:
```html
<div class="message-bubble from-{{ msg.from }}">{{ msg.text }}</div>
<div class="message-meta" style="text-align:{% if msg.from == 'attorney' %}right{% else %}left{% endif %}">
  {{ 'Attorney' if msg.from == 'attorney' else client.client_name }} &middot; {{ msg.date }}
</div>
```

Replace with:
```html
<div class="message-bubble from-{{ msg.from }}">{{ msg.text }}</div>
<div class="message-meta" style="text-align:{% if msg.from in ('attorney', 'ai') %}right{% else %}left{% endif %}">
  {% if msg.from == 'attorney' %}Attorney
  {% elif msg.from == 'ai' %}Endo-Legal Assistant
  {% else %}{{ client.client_name }}{% endif %} &middot; {{ msg.date }}
</div>
```

**Step 5: Verify**

```bash
python -c "from app import app; print('OK')"
```

Expected: `OK`

**Step 6: Commit**

```bash
git add templates/client_portal.html
git commit -m "feat(ai-chat): add AI reply rendering and disclaimer to client message tab"
```
Co-author: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## Task 4: Update attorney portal to label AI messages

**Files:**
- Modify: `templates/attorney_portal.html`

**Step 1: Read `populateMessages` function** (around line 1607-1616)

It currently renders:
```javascript
${m.from === 'attorney' ? 'You' : (c.client_name || c.username)} &middot; ${m.date}
```

**Step 2: Update the sender label logic** to handle `from: "ai"`:

Find this line in `populateMessages`:
```javascript
       ${m.from === 'attorney' ? 'You' : (c.client_name || c.username)} &middot; ${m.date}
```

Replace with:
```javascript
       ${m.from === 'attorney' ? 'You' : m.from === 'ai' ? 'Endo-Legal Assistant' : (c.client_name || c.username)} &middot; ${m.date}
```

**Step 3: Verify**

```bash
python -c "from app import app; print('OK')"
```

**Step 4: Run full test suite**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -m pytest tests/ -v
```

Expected: all `PASSED`

**Step 5: Commit**

```bash
git add templates/attorney_portal.html
git commit -m "feat(ai-chat): label AI messages in attorney portal message thread"
```
Co-author: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## Task 5: Final smoke test

**Step 1: Run full test suite**

```bash
cd C:/Users/Endoc/Desktop/law-office-app && python -m pytest tests/ -v
```

Expected: all `PASSED`

**Step 2: Start app and test manually**

```bash
python app.py
```

1. Log in as a test client (e.g. `AliceM`)
2. Click **Messages** tab
3. Verify the disclaimer banner appears at the top
4. Send a message — you should see your message + an AI reply appear immediately
5. Check the **Billing** tab — `hours_billed` should have increased by 0.1
6. Log in as attorney — open that client, check Messages tab — AI response should appear labeled "Endo-Legal Assistant"
7. Check the client's billing log — an `ai_message` entry should appear

**Step 3: Final commit (if any cleanup needed)**

```bash
git add <any changed files>
git commit -m "feat(ai-chat): complete AI message assistant"
```
Co-author: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`
