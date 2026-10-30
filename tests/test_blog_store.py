import json
from datetime import datetime

import pytest

from services import blog
import shared


def _published(title, area, when):
    p = blog.new_post(title, "s", "b", area, "article", now=when)
    p["status"] = "published"
    p["published_at"] = when.isoformat()
    blog.save_post(p)
    return p


def test_save_and_load_round_trip(patch_dirs):
    p = blog.new_post("Title", "Sum", "Body", "civil-rights", "article")
    blog.save_post(p)
    assert blog.load_post(p["slug"])["title"] == "Title"
    assert p["status"] == "draft" and len(p["review_token_id"]) == 16


def test_load_post_rejects_path_tricks(patch_dirs):
    assert blog.load_post("../secrets") is None
    assert blog.load_post("missing-post") is None


def test_make_slug_dedupes(patch_dirs):
    blog.save_post(blog.new_post("Your Rights at a Traffic Stop", "s", "b", "criminal-defense", "tips"))
    assert blog.make_slug("Your Rights at a Traffic Stop!") == "your-rights-at-a-traffic-stop-2"


def test_make_slug_trims_to_70(patch_dirs):
    assert len(blog.make_slug("word " * 40)) <= 70


def test_published_posts_filters_status_and_area(patch_dirs):
    blog.save_post(blog.new_post("Draft one", "s", "b", "civil-rights", "article"))
    pulled = blog.new_post("Pulled one", "s", "b", "civil-rights", "article")
    pulled["status"] = "pulled"
    blog.save_post(pulled)
    old = _published("Older", "criminal-defense", datetime(2026, 1, 1))
    new = _published("Newer", "civil-rights", datetime(2026, 2, 1))
    assert [p["slug"] for p in blog.published_posts()] == [new["slug"], old["slug"]]
    assert [p["slug"] for p in blog.published_posts("civil-rights")] == [new["slug"]]
    assert len(blog.list_posts("draft")) == 1


def test_add_topic_rejects_unknown_area(patch_dirs):
    with pytest.raises(ValueError):
        blog.add_topic("family-law", "x")
    with pytest.raises(ValueError):
        blog.add_topic("civil-rights", "   ")
    with pytest.raises(ValueError):
        blog.add_topic("civil-rights", "x" * 201)
    t = blog.add_topic("civil-rights", "Valid topic")
    assert t["used"] is False and blog.load_topics() == [t]


def test_state_defaults_and_round_trip(patch_dirs):
    assert blog.load_state() == {"step": 0, "week": None, "attempts": 0, "attempts_week": None}
    blog.save_state({"step": 3, "week": "2026-W44", "attempts": 1, "attempts_week": "2026-W44"})
    assert blog.load_state()["step"] == 3


def test_iso_week():
    assert blog.iso_week(datetime(2026, 10, 29)) == "2026-W44"


def test_seed_merge_keeps_disk_state(patch_dirs):
    seed = shared.BLOG_SEED_DIR
    (seed / "topics.json").write_text(json.dumps([
        {"id": "a", "area": "civil-rights", "title": "A", "used": False},
        {"id": "b", "area": "civil-rights", "title": "B", "used": False},
    ]))
    (seed / "posts" / "hello.json").write_text(json.dumps({"slug": "hello", "title": "Seeded"}))
    shared.BLOG_DIR.mkdir(exist_ok=True)
    blog.save_topics([{"id": "a", "area": "civil-rights", "title": "A", "used": True}])

    blog.seed_from_repo(datetime(2026, 11, 2))
    topics = {t["id"]: t for t in blog.load_topics()}
    assert topics["a"]["used"] is True and topics["b"]["used"] is False
    assert blog.load_post("hello")["title"] == "Seeded"

    edited = blog.load_post("hello")
    edited["title"] = "Edited on disk"
    blog.save_post(edited)
    blog.seed_from_repo(datetime(2026, 11, 9))
    assert blog.load_post("hello")["title"] == "Edited on disk"
    assert blog.load_state()["week"] == "2026-W45"  # not advanced by second call


@pytest.mark.parametrize("record", [{"title": "No slug"}, {"slug": "other-name", "title": "Mismatch"}],
                         ids=["missing", "mismatched"])
def test_seed_post_slug_is_its_file_name(patch_dirs, record):
    (shared.BLOG_SEED_DIR / "posts" / "file-name.json").write_text(json.dumps(record))
    blog.seed_from_repo(datetime(2026, 11, 2))
    assert blog.load_post("file-name")["slug"] == "file-name"
    assert blog.load_post("other-name") is None


def test_takedown_only_from_published(patch_dirs):
    t = blog.add_topic("civil-rights", "Topic")
    topics = blog.load_topics()
    topics[0]["used"] = True
    blog.save_topics(topics)
    p = blog.new_post("T", "s", "b", "civil-rights", "article", topic_id=t["id"])
    blog.save_post(p)
    assert blog.takedown(p["slug"]) is False  # a draft is pulled, not taken down
    assert blog.load_post(p["slug"])["status"] == "draft"
    assert blog.publish(p["slug"]) is True
    assert blog.takedown(p["slug"]) is True
    assert blog.load_post(p["slug"])["status"] == "pulled"
    assert blog.load_topics()[0]["used"] is True  # the topic stays used
    assert blog.takedown(p["slug"]) is False
    assert blog.takedown("missing") is False


def test_seed_sets_launch_week(patch_dirs):
    now = datetime(2026, 11, 2, 9)
    blog.seed_from_repo(now)
    assert blog.load_state()["week"] == "2026-W45"


def test_seed_post_is_dated_when_it_first_goes_live(patch_dirs):
    post = blog.new_post("Launch Post", "s", "b", "civil-rights", "article")
    post.update(status="published", published_at="2026-10-30T07:10:36")
    (shared.BLOG_SEED_DIR / "posts" / f"{post['slug']}.json").write_text(json.dumps(post), encoding="utf-8")
    launch = datetime(2026, 11, 9, 9)
    blog.seed_from_repo(launch)
    assert blog.load_post(post["slug"])["published_at"] == launch.isoformat()
    # A later boot keeps the original date.
    blog.seed_from_repo(datetime(2026, 12, 1, 9))
    assert blog.load_post(post["slug"])["published_at"] == launch.isoformat()
