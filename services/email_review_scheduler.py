"""Hourly background check of the firm Inbox, plus the morning digest.

Runs only in the local app (python app.py); the portal is switched off on
Render. Does nothing until Gmail is connected (gmail-token.json exists), and
nothing at all with EMAIL_REVIEW_AUTO=0.
"""
import logging
import threading
import time
from datetime import datetime

import shared
from services import email_review
from services import gmail

log = logging.getLogger(__name__)

TICK_SECONDS = 3600

_thread = None
_thread_guard = threading.Lock()


def tick(now: datetime | None = None) -> None:
    """One pass. Never raises, so the thread can't die."""
    try:
        if not shared.EMAIL_REVIEW_AUTO or not shared.GMAIL_TOKEN_FILE.exists():
            return
        now = now or datetime.now()
        service = gmail.get_service()
        try:
            counts = email_review.run_review(service, now=now)
            log.info("Email review: %s", counts)
        except email_review.ReviewBusy:
            log.info("Email review skipped: a check is already running")
        if email_review.digest_due(email_review.load_state(), now):
            email_review.send_digest(service, now=now)
    except Exception:
        log.exception("Email review tick failed")


def _loop() -> None:
    while True:
        tick()
        time.sleep(TICK_SECONDS)


def start_scheduler() -> threading.Thread:
    """Start the tick thread, once per process."""
    global _thread
    with _thread_guard:
        if _thread is None:
            _thread = threading.Thread(target=_loop, daemon=True, name="email-review")
            _thread.start()
        return _thread
