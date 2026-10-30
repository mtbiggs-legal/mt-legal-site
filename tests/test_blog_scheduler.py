import contextlib
import os
import runpy
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import blog
from services import blog_scheduler
from services import blog_writer
import shared
from conftest import flask_app

NOW = datetime(2026, 11, 2, 9, 0)  # a Monday
WEEK = timedelta(days=7)
APP_PY = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def writer(monkeypatch):
    """Fake Claude and SendGrid, with autogen on."""
    fake = SimpleNamespace(calls=[], sent=[], send_result=True, generate_error=None,
                           on_generate=None, on_send=None)

    def generate(area, fmt, topic, past_titles):
        fake.calls.append(SimpleNamespace(area=area, fmt=fmt, topic=topic, past=past_titles))
        if fake.on_generate:
            fake.on_generate()
        if fake.generate_error:
            raise fake.generate_error
        return {"title": f"Post {len(fake.calls)}", "summary": "Sum.", "body": "Body."}

    def send(post):
        fake.sent.append(post["slug"])
        if fake.on_send:
            fake.on_send(post)
        return fake.send_result

    monkeypatch.setattr(blog_writer, "generate_post", generate)
    monkeypatch.setattr(blog_writer, "send_review_email", send)
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", True)
    return fake


def tick(now=NOW):
    blog_scheduler.tick(flask_app, now=now)


def only_post():
    posts = blog.list_posts()
    assert len(posts) == 1
    return posts[0]


def make_draft(title="Draft", **kw):
    p = blog.new_post(title, "Sum.", "Body.", "civil-rights", "article", now=NOW)
    p.update(kw)
    blog.save_post(p)
    return p


def sent_draft(title="Sent draft", publish_at=NOW):
    return make_draft(title, review_email_sent_at=(NOW - timedelta(hours=48)).isoformat(),
                      publish_at=publish_at.isoformat())


def in_other_thread(fn, timeout=5):
    """Run fn on another thread and return its result. Fails if it can't finish,
    which is what happens when this code is wrongly holding a lock fn needs."""
    out = []
    t = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), "blocked: a lock was held across a slow call"
    return out[0]


def post_lock_is_free():
    def probe():
        got = blog.POST_LOCK.acquire(blocking=False)
        if got:
            blog.POST_LOCK.release()
        return got
    return in_other_thread(probe)


# ── Weekly draft ──────────────────────────────────────────────────────────────

def test_monday_tick_creates_one_draft_and_emails(writer):
    tick()
    p = only_post()
    assert p["status"] == "draft"
    assert p["review_email_sent_at"] == NOW.isoformat()
    assert p["publish_at"] == (NOW + timedelta(hours=48)).isoformat()
    assert writer.sent == [p["slug"]]
    state = blog.load_state()
    assert state["step"] == 1 and state["week"] == blog.iso_week(NOW)


def test_second_tick_same_week_does_nothing(writer):
    tick()
    tick(NOW + timedelta(hours=1))
    tick(NOW + timedelta(days=1))
    assert len(blog.list_posts()) == 1
    assert len(writer.calls) == 1 and len(writer.sent) == 1
    assert blog.load_state()["step"] == 1


def test_rotation_order_over_eight_weeks(writer):
    for i in range(8):
        tick(NOW + WEEK * i)
    assert tuple(c.area for c in writer.calls) == blog.ROTATION
    assert [c.fmt for c in writer.calls] == ["article", "qa", "tips"] * 2 + ["article", "qa"]
    assert blog.load_state()["step"] == 8
    assert len(blog.list_posts()) == 8


def test_failing_email_stops_new_drafts_piling_up(writer, caplog):
    writer.send_result = False
    for i in range(3):
        tick(NOW + WEEK * i)
    p = only_post()
    assert len(writer.calls) == 1
    assert p["review_email_sent_at"] is None and p["status"] == "draft"
    state = blog.load_state()
    assert state["step"] == 1 and state["week"] == blog.iso_week(NOW)
    assert state["attempts"] == 0
    assert any(r.levelname == "ERROR" and p["slug"] in r.getMessage() for r in caplog.records)


def test_drafts_resume_in_the_same_tick_once_the_email_works(writer):
    writer.send_result = False
    tick()
    writer.send_result = True
    tick(NOW + WEEK)
    assert len(writer.calls) == 2
    assert writer.calls[1].area == blog.ROTATION[1]
    assert len(blog.list_posts("draft")) == 2
    assert all(p["review_email_sent_at"] for p in blog.list_posts("draft"))


def test_three_failures_give_up_week_and_advance(writer):
    writer.generate_error = blog_writer.BlogGenerationError("bad output")
    tick()
    tick(NOW + timedelta(hours=1))
    state = blog.load_state()
    assert state["week"] is None and state["step"] == 0 and state["attempts"] == 2
    tick(NOW + timedelta(hours=2))
    state = blog.load_state()
    assert state["week"] == blog.iso_week(NOW) and state["step"] == 1
    assert blog.list_posts() == []

    tick(NOW + timedelta(hours=3))  # the week is given up: no fourth call
    assert len(writer.calls) == 3

    writer.generate_error = None
    tick(NOW + WEEK)
    assert writer.calls[-1].area == blog.ROTATION[1]
    assert only_post()["area"] == blog.ROTATION[1]


def test_attempts_from_an_earlier_week_do_not_count(writer):
    writer.generate_error = blog_writer.BlogGenerationError("bad output")
    tick()
    tick(NOW + timedelta(hours=1))
    tick(NOW + WEEK)  # a new week starts over at one attempt, not three
    state = blog.load_state()
    assert state["attempts"] == 1 and state["attempts_week"] == blog.iso_week(NOW + WEEK)
    assert state["week"] is None and state["step"] == 0


def test_generation_uses_queue_topic_and_marks_it_used(writer):
    blog.add_topic("stablecoins", "Wrong area")
    t = blog.add_topic("criminal-defense", "Your rights at a traffic stop")
    tick()
    assert writer.calls[0].topic == "Your rights at a traffic stop"
    assert only_post()["topic_id"] == t["id"]
    used = {x["id"]: x["used"] for x in blog.load_topics()}
    assert used[t["id"]] is True
    assert sum(used.values()) == 1


def test_generation_without_a_topic_and_with_past_titles(writer):
    make_draft("An earlier post", status="pulled")
    tick()
    assert writer.calls[0].topic is None
    assert writer.calls[0].past == ["An earlier post"]


def test_autogen_off_generates_nothing(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    tick()
    assert writer.calls == [] and blog.list_posts() == []


# ── One post a week, even when a step fails ───────────────────────────────────

@contextlib.contextmanager
def failing(target, name):
    """Make target.name raise inside the with block."""
    def boom(*a, **k):
        raise OSError("disk full")

    with pytest.MonkeyPatch.context() as m:
        m.setattr(target, name, boom)
        yield


@pytest.mark.parametrize("ticks", [1, 3])
def test_save_post_failure_loses_the_week_without_a_retry(writer, caplog, ticks):
    with failing(blog, "save_post"):  # however long it lasts, one API call
        for i in range(ticks):
            tick(NOW + timedelta(hours=i))
    assert any(r.levelname == "ERROR" and blog.iso_week(NOW) in r.getMessage()
               for r in caplog.records)
    tick(NOW + timedelta(hours=ticks))  # the disk is back
    assert blog.list_posts() == []
    assert len(writer.calls) == 1
    state = blog.load_state()
    assert state["week"] == blog.iso_week(NOW) and state["step"] == 1

    tick(NOW + WEEK)  # next week carries on with the next area
    assert only_post()["area"] == blog.ROTATION[1]


def test_mark_topic_failure_keeps_one_post_and_still_emails(writer, caplog):
    blog.add_topic("criminal-defense", "Traffic stops")
    with failing(blog_scheduler, "_mark_topic_used"):
        tick()
        tick(NOW + timedelta(hours=1))
    assert any(r.levelname == "ERROR" for r in caplog.records)
    tick(NOW + timedelta(hours=2))
    p = only_post()
    assert len(writer.calls) == 1
    assert writer.sent == [p["slug"]]
    assert p["review_email_sent_at"] == NOW.isoformat()
    assert blog.load_state()["week"] == blog.iso_week(NOW)


def test_save_state_failure_writes_no_post_and_retry_makes_only_one(writer):
    with failing(blog, "save_state"):
        tick()
        assert blog.list_posts() == []
        tick(NOW + timedelta(hours=1))
        assert blog.list_posts() == []
    assert writer.sent == []

    tick(NOW + timedelta(hours=2))
    only_post()
    tick(NOW + timedelta(hours=3))
    only_post()
    assert blog.load_state()["week"] == blog.iso_week(NOW)


# ── Drafts: email first, publish only after the window ────────────────────────

def test_real_time_window_starts_at_the_send_not_the_tick(writer):
    sent_at = []
    writer.on_generate = lambda: time.sleep(0.05)
    writer.on_send = lambda post: sent_at.append(datetime.now())
    blog_scheduler.tick(flask_app)  # no explicit now, as the real thread calls it
    p = only_post()
    stamped = datetime.fromisoformat(p["review_email_sent_at"])
    assert datetime.fromisoformat(p["created_at"]) < sent_at[0] <= stamped
    assert p["publish_at"] == (stamped + timedelta(hours=48)).isoformat()


def test_retried_email_in_real_time_starts_window_at_the_send(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = make_draft()
    sent_at = []
    writer.on_send = lambda post: (time.sleep(0.05), sent_at.append(datetime.now()))
    before = datetime.now()
    blog_scheduler.tick(flask_app)
    stamped = datetime.fromisoformat(blog.load_post(d["slug"])["review_email_sent_at"])
    assert before < sent_at[0] <= stamped


def test_auto_publish_logs_at_warning(writer, monkeypatch, caplog):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = sent_draft()
    tick()
    assert [r.levelname for r in caplog.records
            if "Auto-published" in r.getMessage() and d["slug"] in r.getMessage()] == ["WARNING"]


def test_draft_publishes_after_window(writer):
    tick()
    slug = only_post()["slug"]
    tick(NOW + timedelta(hours=47))
    assert blog.load_post(slug)["status"] == "draft"
    tick(NOW + timedelta(hours=48))
    p = blog.load_post(slug)
    assert p["status"] == "published"
    assert p["published_at"] == (NOW + timedelta(hours=48)).isoformat()
    assert writer.sent == [slug]  # never re-emailed


def test_unsent_draft_never_publishes_and_email_retried(writer, monkeypatch):
    writer.send_result = False
    tick()
    slug = only_post()["slug"]
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)  # no second week's draft
    later = NOW + timedelta(days=10)
    tick(later)
    p = blog.load_post(slug)
    assert p["status"] == "draft" and p["publish_at"] is None
    assert p["review_email_sent_at"] is None
    assert len(writer.sent) == 2

    writer.send_result = True
    tick(later + timedelta(hours=1))
    p = blog.load_post(slug)
    assert p["status"] == "draft"
    assert p["publish_at"] == (later + timedelta(hours=49)).isoformat()


def test_send_that_raises_counts_as_unsent(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)

    def boom(post):
        raise RuntimeError("smtp fell over")
    writer.on_send = boom
    d = make_draft()
    tick()
    p = blog.load_post(d["slug"])
    assert p["status"] == "draft" and p["publish_at"] is None


def test_unsent_draft_with_a_publish_date_still_does_not_publish(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = make_draft(publish_at=(NOW - WEEK).isoformat())
    writer.send_result = False
    tick()
    assert blog.load_post(d["slug"])["status"] == "draft"


def test_pulled_draft_never_publishes(writer):
    tick()
    slug = only_post()["slug"]
    assert blog.pull(slug)
    tick(NOW + timedelta(days=3))
    p = blog.load_post(slug)
    assert p["status"] == "pulled" and p["published_at"] is None


def test_autogen_off_still_publishes_due_drafts(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = sent_draft()
    tick()
    assert blog.load_post(d["slug"])["status"] == "published"
    assert writer.calls == []


def test_sent_draft_without_a_publish_date_is_not_published(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = make_draft(review_email_sent_at=NOW.isoformat())
    tick(NOW + WEEK)
    assert blog.load_post(d["slug"])["status"] == "draft"


def test_bad_publish_date_does_not_publish_or_block_other_drafts(writer):
    bad = make_draft("Bad date", review_email_sent_at=NOW.isoformat(), publish_at="soon")
    good = sent_draft("Good date")
    tick()
    assert blog.load_post(bad["slug"])["status"] == "draft"
    assert blog.load_post(good["slug"])["status"] == "published"


def test_draft_pulled_after_listing_is_not_published(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = sent_draft()
    stale = blog.load_post(d["slug"])
    assert blog.pull(d["slug"])
    monkeypatch.setattr(blog, "list_posts", lambda status=None: [stale])
    tick()
    assert blog.load_post(d["slug"])["status"] == "pulled"
    assert writer.sent == []


# ── Pull during the send (POST_LOCK) ──────────────────────────────────────────

def test_draft_pulled_while_email_sends_stays_pulled(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = make_draft()
    # Pull on another thread, as the review route would. It must finish while
    # the send is still running, so the lock can't be held across the send.
    writer.on_send = lambda post: in_other_thread(lambda: blog.pull(post["slug"]))
    tick()
    p = blog.load_post(d["slug"])
    assert writer.sent == [d["slug"]]
    assert p["status"] == "pulled"
    assert p["review_email_sent_at"] is None and p["publish_at"] is None

    writer.on_send = None
    tick(NOW + WEEK)
    assert blog.load_post(d["slug"])["status"] == "pulled"
    assert writer.sent == [d["slug"]]  # a pulled post isn't re-emailed


def test_edit_made_while_email_sends_is_kept(writer, monkeypatch):
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", False)
    d = make_draft()
    writer.on_send = lambda post: in_other_thread(
        lambda: blog.update_post(post["slug"], "Edited", "Sum.", "Edited body."))
    tick()
    p = blog.load_post(d["slug"])
    assert p["title"] == "Edited" and p["body"] == "Edited body."
    assert p["review_email_sent_at"] == NOW.isoformat()


def test_post_lock_not_held_during_api_or_email(writer):
    seen = []
    writer.on_generate = lambda: seen.append(post_lock_is_free())
    writer.on_send = lambda post: seen.append(post_lock_is_free())
    tick()
    assert seen == [True, True]


@pytest.mark.parametrize("change", [
    lambda slug: blog.publish(slug),
    lambda slug: blog.pull(slug),
    lambda slug: blog.update_post(slug, "T", "S", "B"),
], ids=["publish", "pull", "update_post"])
def test_status_changes_wait_for_post_lock(change):
    d = make_draft()
    done = threading.Event()

    def run():
        change(d["slug"])
        done.set()

    t = threading.Thread(target=run, daemon=True)
    with blog.POST_LOCK:
        t.start()
        assert not done.wait(0.1)
    assert done.wait(5)
    t.join(5)


def test_update_post_does_not_revert_a_publish():
    d = make_draft()
    assert blog.publish(d["slug"], now=NOW)
    p = blog.update_post(d["slug"], "New title", "S", "B")
    assert p["status"] == "published" and p["published_at"] == NOW.isoformat()
    assert blog.load_post(d["slug"])["status"] == "published"


# ── The tick lock ─────────────────────────────────────────────────────────────

def lock_path():
    return shared.BLOG_DIR / ".tick.lock"


def test_concurrent_ticks_make_one_draft(writer):
    writer.on_generate = lambda: time.sleep(0.2)
    threads = [threading.Thread(target=tick) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(writer.calls) == 1
    only_post()
    assert not lock_path().exists()


def test_held_lock_makes_tick_return(writer):
    lock_path().touch()
    d = sent_draft()
    tick()
    assert writer.calls == []
    assert blog.load_post(d["slug"])["status"] == "draft"
    assert lock_path().exists()  # someone else's lock stays put


def test_stale_lock_is_cleared(writer):
    lock_path().touch()
    old = time.time() - blog_scheduler.LOCK_STALE_SECONDS - 5
    os.utime(lock_path(), (old, old))
    tick()
    only_post()
    assert not lock_path().exists()


# ── Nothing kills the thread ──────────────────────────────────────────────────

def test_tick_swallows_unexpected_errors_and_releases_lock(writer):
    writer.generate_error = RuntimeError("not a BlogGenerationError")
    tick()
    assert not lock_path().exists()
    assert blog.load_state()["attempts"] == 0


def test_tick_survives_unusable_blog_dir(writer, monkeypatch, tmp_path):
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    monkeypatch.setattr(shared, "BLOG_DIR", not_a_dir)
    tick()


def test_loop_keeps_going_after_a_tick_raises(monkeypatch):
    class Stop(Exception):
        pass

    ticks, sleeps = [], []

    def bad_tick(app):
        ticks.append(app)
        raise RuntimeError("boom")

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise Stop

    monkeypatch.setattr(blog_scheduler, "tick", bad_tick)
    monkeypatch.setattr(blog_scheduler, "time", SimpleNamespace(sleep=fake_sleep))
    with pytest.raises(Stop):
        blog_scheduler._loop(flask_app)
    assert ticks == [flask_app, flask_app]
    assert sleeps == [blog_scheduler.TICK_SECONDS] * 2


# ── Starting the thread ───────────────────────────────────────────────────────

@pytest.fixture
def no_real_loop(monkeypatch):
    """Never run the real loop on a thread: it would outlive the monkeypatches
    and tick against the real blog folder."""
    ran = threading.Event()
    monkeypatch.setattr(blog_scheduler, "_thread", None)
    monkeypatch.setattr(blog_scheduler, "_loop", lambda app: ran.set())
    return ran


def test_start_scheduler_seeds_once_and_starts_one_daemon(no_real_loop, monkeypatch):
    seeds = []
    monkeypatch.setattr(blog, "seed_from_repo", lambda: seeds.append(no_real_loop.is_set()))
    first = blog_scheduler.start_scheduler(flask_app)
    second = blog_scheduler.start_scheduler(flask_app)
    assert first is second
    assert first.daemon
    assert no_real_loop.wait(5)
    first.join(5)
    assert seeds == [False]  # seeded once, before the loop ran


def test_seed_failure_does_not_stop_the_scheduler(no_real_loop, monkeypatch):
    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(blog, "seed_from_repo", boom)
    t = blog_scheduler.start_scheduler(flask_app)
    assert no_real_loop.wait(5)
    t.join(5)


def test_importing_the_app_under_pytest_starts_nothing():
    assert blog_scheduler._thread is None
    assert not [t for t in threading.enumerate() if t.name == "blog-scheduler"]


def run_app_module(monkeypatch):
    """Execute app.py's module body as a production server import would."""
    started = []
    monkeypatch.setattr(blog_scheduler, "start_scheduler", lambda app: started.append(app))
    monkeypatch.setattr(shared, "IS_PRODUCTION", True)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    return started, lambda: runpy.run_path(str(APP_PY), run_name="app_under_test")


def test_production_import_under_pytest_does_not_start_scheduler(monkeypatch):
    started, run = run_app_module(monkeypatch)
    run()
    assert started == []


def test_production_import_starts_scheduler(monkeypatch):
    started, run = run_app_module(monkeypatch)
    monkeypatch.delitem(sys.modules, "pytest")
    ns = run()
    assert started == [ns["app"]]
