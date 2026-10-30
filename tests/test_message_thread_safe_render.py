"""The attorney portal's message thread must never parse message text as HTML.

Regression test for a stored-XSS bug (found during the voicemail-summaries
design review, see docs/superpowers/specs/2026-10-02-voicemail-summaries-design.md):
populateMessages() used to build the thread with
    thread.innerHTML = msgs.map(m => `...${m.text}...`).join("")
so a client who typed e.g. <img src=x onerror=...> into their own message box
got it executed in the attorney's authenticated session the next time that
attorney opened the client's tab — which also defeats CSRF, since the
injected script can read the page's own CSRF token.

A live browser-execution test isn't available to this pytest suite (no JS
runtime here), so this is a source-level guard: it fails if populateMessages
goes back to assigning raw message text into .innerHTML, and requires the
safe DOM-building helper (_el, already used elsewhere in this file) to be
used instead.
"""

import re
from pathlib import Path

PORTAL_JS = Path(__file__).parent.parent / "static" / "js" / "attorney_portal.js"


def _populate_messages_body() -> str:
    text = PORTAL_JS.read_text(encoding="utf-8")
    m = re.search(r"function populateMessages\(c\) \{(.*?)\n\}", text, re.S)
    assert m, "populateMessages() not found in static/js/attorney_portal.js"
    return m.group(1)


def test_message_text_is_not_assigned_to_innerHTML():
    body = _populate_messages_body()
    # The bug was specifically m.text (and friends) reaching .innerHTML via a
    # template literal. Catch the general shape, not just the exact old code.
    assert not re.search(r"\.innerHTML\s*=.*\$\{m\.(text|from|date)\}", body, re.S), (
        "populateMessages() appears to put message content into innerHTML "
        "again — it must build the thread with _el()/text nodes instead."
    )


def test_message_thread_uses_safe_dom_builder():
    body = _populate_messages_body()
    assert "_el(" in body, (
        "populateMessages() should build the thread with the _el() DOM helper "
        "(static/js/attorney_security.js), not string concatenation into innerHTML."
    )


def test_message_bubble_text_is_a_child_not_markup():
    body = _populate_messages_body()
    # m.text must be passed as an _el() child (becomes a text node), never
    # interpolated into a string that is itself passed as markup.
    assert re.search(r'_el\("div",\s*\{[^}]*className:\s*`message-bubble[^`]*`\s*\},\s*m\.text\)', body), (
        "expected the message bubble to be built as _el(\"div\", {...}, m.text) "
        "so m.text becomes a text node, not parsed HTML."
    )
