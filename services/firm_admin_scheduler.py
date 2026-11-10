"""Hourly check that emails firm admin reminders (60, 45, 30, 15, 10 and 5
days before a due date, and once when overdue) to the firm inbox.

Runs only in the local app (python app.py), like the Inbox reviewer: the
portal is switched off on Render. Does nothing until SendGrid is configured,
so no reminder step is used up without being sent.
"""
import logging
import threading
import time
from html import escape

from services import firm_admin

log = logging.getLogger(__name__)

TICK_SECONDS = 3600
_thread = None
_thread_guard = threading.Lock()


def _email(items: list) -> None:
    from blueprints import email_service
    lines = [f"- {i['title']}: {i['text']}" for i in items]
    text = "Firm admin reminders\n\n" + "\n".join(lines) + "\n\nMark each one done in the attorney portal (Firm Admin) to stop its reminders."
    rows = "".join(f"<li><strong>{escape(i['title'])}</strong>: {escape(i['text'])}</li>" for i in items)
    html = email_service._html_wrapper(
        f"<h2>Firm admin reminders</h2><ul>{rows}</ul>"
        "<p>Mark each one done in the attorney portal (Firm Admin) to stop its reminders.</p>")
    subject = f"Firm admin: {items[0]['title']}" + (f" and {len(items) - 1} more" if len(items) > 1 else "")
    email_service._send_firm_alert(subject, html, text)


def tick() -> None:
    """One pass. Never raises, so the thread can't die."""
    try:
        from blueprints import email_service
        if not email_service._api_key():
            return
        items = firm_admin.claim_email_reminders()
        if items:
            _email(items)
            log.info("Firm admin reminders emailed: %d", len(items))
    except Exception:
        log.exception("Firm admin reminder tick failed")


def _loop() -> None:
    while True:
        tick()
        time.sleep(TICK_SECONDS)


def start_scheduler() -> threading.Thread:
    global _thread
    with _thread_guard:
        if _thread is None:
            _thread = threading.Thread(target=_loop, daemon=True, name="firm-admin")
            _thread.start()
        return _thread
