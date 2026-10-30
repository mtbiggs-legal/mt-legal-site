"""Hourly background job for the weekly blog.

Each tick emails drafts that haven't gone out, publishes drafts whose review
window has passed, and writes this week's draft if there isn't one yet. Posts
go out under the attorney's name, so a draft publishes only after its review
email was sent and only if it is still a draft when the window closes.
"""
import logging
import os
import threading
import time
from datetime import datetime

from services import blog
from services import blog_writer
import shared

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
TICK_SECONDS = 3600
LOCK_STALE_SECONDS = 600

_thread = None
_thread_guard = threading.Lock()


def _acquire_tick_lock():
    """Return the lock file's path, or None if another tick holds it."""
    lock = shared.BLOG_DIR / ".tick.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
            log.warning("Clearing stale blog tick lock")
            lock.unlink()
    except FileNotFoundError:
        pass
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.close(fd)
    return lock


def _send_review(post, clock) -> None:
    """Email a draft and start its review window once the send has succeeded.

    The window runs from the send, so the clock is read after it returns.
    POST_LOCK is not held during the send, so the post is re-read afterwards: a
    draft pulled meanwhile stays pulled, and edits made meanwhile are kept.
    """
    slug = post["slug"]
    try:
        sent = blog_writer.send_review_email(post)
    except Exception:
        log.exception("Review email failed for blog draft %s", slug)
        return
    if not sent:
        log.warning("Review email not sent for blog draft %s; retrying next tick", slug)
        return
    with blog.POST_LOCK:
        fresh = blog.load_post(slug)
        if not fresh or fresh.get("status") != "draft":
            log.info("Blog draft %s stopped being a draft during its review email", slug)
            return
        sent_at = clock()
        fresh["review_email_sent_at"] = sent_at.isoformat()
        fresh["publish_at"] = (sent_at + blog.REVIEW_WINDOW).isoformat()
        blog.save_post(fresh)


def _is_due(post, now) -> bool:
    publish_at = post.get("publish_at")
    if not publish_at:
        log.warning("Blog draft %s was emailed but has no publish date", post.get("slug"))
        return False
    return datetime.fromisoformat(publish_at) <= now


def _process_draft(slug, clock) -> None:
    with blog.POST_LOCK:
        post = blog.load_post(slug)
        if not post or post.get("status") != "draft":
            return
        if post.get("review_email_sent_at"):
            now = clock()
            if _is_due(post, now):
                blog.publish(slug, now=now)
                log.warning("Auto-published blog post %s", slug)
            return
    _send_review(post, clock)


def _process_drafts(clock) -> None:
    for draft in blog.list_posts("draft"):
        slug = draft.get("slug")
        try:
            _process_draft(slug, clock)
        except Exception:  # one bad record must not hold up the others
            log.exception("Could not process blog draft %s", slug)


def _mark_topic_used(topic_id) -> None:
    with blog.POST_LOCK:
        topics = blog.load_topics()
        for t in topics:
            if isinstance(t, dict) and t.get("id") == topic_id:
                t["used"] = True
        blog.save_topics(topics)


def _weekly_draft(clock) -> None:
    if not shared.BLOG_AUTOGEN:
        return
    now = clock()
    state = blog.load_state()
    wk = blog.iso_week(now)
    if state["week"] == wk:
        return
    # While the email is failing, more drafts would only pile up and then all
    # publish on one tick once it recovers. The week stays open for the retry.
    unsent = [p.get("slug") for p in blog.list_posts("draft") if not p.get("review_email_sent_at")]
    if unsent:
        log.error("No new blog draft for %s: review email still unsent for %s",
                  wk, ", ".join(map(str, unsent)))
        return
    if state.get("attempts_week") != wk:
        state["attempts"] = 0
        state["attempts_week"] = wk

    step = state["step"]
    area = blog.ROTATION[step % len(blog.ROTATION)]
    fmt = blog.FORMATS[step % len(blog.FORMATS)]
    topic = blog_writer.next_topic(area)
    past_titles = [p["title"] for p in blog.list_posts() if p.get("title")]
    try:
        data = blog_writer.generate_post(area, fmt, topic and topic["title"], past_titles)
    except blog_writer.BlogGenerationError as exc:
        state["attempts"] += 1
        log.error("Blog draft for %s failed (attempt %s of %s): %s",
                  wk, state["attempts"], MAX_ATTEMPTS, exc)
        if state["attempts"] >= MAX_ATTEMPTS:
            log.error("Giving up on the blog draft for %s", wk)
            state["step"] = step + 1
            state["week"] = wk
        blog.save_state(state)
        return

    # Claim the week before writing the post, so no failure from here on can
    # lead to a second draft. If the post can't be saved, the week is lost.
    state["step"] = step + 1
    state["week"] = wk
    blog.save_state(state)
    try:
        post = blog.new_post(data["title"], data["summary"], data["body"], area, fmt,
                             topic_id=topic and topic["id"], now=now)
        blog.save_post(post)
    except Exception:
        log.exception("Could not save the blog draft for %s; no post this week", wk)
        return
    if topic:
        try:
            _mark_topic_used(topic["id"])
        except Exception:
            log.exception("Could not mark blog topic %s used", topic["id"])
    _send_review(post, clock)


def tick(app, now: datetime | None = None) -> None:
    """Run one pass. Never raises, so the scheduler thread can't die."""
    # Tests pass a fixed now; otherwise each step reads the real time when it acts.
    clock = (lambda: now) if now else datetime.now
    try:
        lock = _acquire_tick_lock()
        if lock is None:
            return
        try:
            with app.app_context():
                _process_drafts(clock)
                _weekly_draft(clock)
        finally:
            lock.unlink(missing_ok=True)
    except Exception:
        log.exception("Blog tick failed")


def _loop(app) -> None:
    while True:
        try:
            tick(app)
        except Exception:
            log.exception("Blog tick failed")
        time.sleep(TICK_SECONDS)


def start_scheduler(app) -> threading.Thread:
    """Seed the blog folder and start the tick thread, once per process."""
    global _thread
    with _thread_guard:
        if _thread is None:
            try:
                blog.seed_from_repo()
            except Exception:
                log.exception("Could not seed the blog folder")
            _thread = threading.Thread(target=_loop, args=(app,), daemon=True,
                                       name="blog-scheduler")
            _thread.start()
        return _thread
