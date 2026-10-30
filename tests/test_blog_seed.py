import json
import sys
from pathlib import Path

import pytest

from services import blog
from services import blog_writer
import shared

ROOT = Path(__file__).parent.parent
SEED = ROOT / "blog_seed"  # the real repo files; conftest redirects shared.BLOG_SEED_DIR
sys.path.insert(0, str(ROOT / "scripts"))

import generate_launch_posts  # noqa: E402


def _topics():
    return json.loads((SEED / "topics.json").read_text(encoding="utf-8"))


def test_topics_ids_unique_and_areas_valid():
    topics = _topics()
    ids = [t["id"] for t in topics]
    assert len(ids) == len(set(ids))
    for t in topics:
        assert t["area"] in blog.ROTATION
        assert t["id"].startswith(t["area"] + "-")
        assert t["title"].strip() and len(t["title"]) <= 200


def test_each_area_has_enough_topics():
    topics = _topics()
    for area in set(blog.ROTATION):
        n = sum(1 for t in topics if t["area"] == area)
        assert 8 <= n <= 10, (area, n)


def test_topics_exclude_family_and_injury_and_public_defender():
    text = " ".join(t["title"] for t in _topics()).lower()
    for word in ("family", "injury", "public defender"):
        assert word not in text


def test_seed_posts_are_published_and_named_by_slug():
    for f in (SEED / "posts").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["status"] == "published"
        assert data["slug"] == f.stem


def test_dry_run_makes_no_network_call_and_writes_nothing(monkeypatch, tmp_path, capsys):
    seed = tmp_path / "seed"
    (seed / "posts").mkdir(parents=True)
    (seed / "topics.json").write_text((SEED / "topics.json").read_text(encoding="utf-8"),
                                      encoding="utf-8")
    monkeypatch.setattr(shared, "BLOG_SEED_DIR", seed)

    def boom(*a, **k):
        raise AssertionError("dry run must not call the writer")

    monkeypatch.setattr(blog_writer, "generate_post", boom)
    assert generate_launch_posts.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    for fmt in ("article", "qa", "tips"):
        assert fmt in out
    assert list((seed / "posts").iterdir()) == []
    assert json.loads((seed / "topics.json").read_text(encoding="utf-8")) == _topics()


def test_real_run_writes_published_posts_and_marks_topics(monkeypatch, tmp_path, capsys):
    seed = tmp_path / "seed"
    (seed / "posts").mkdir(parents=True)
    # The real file marks its launch topics used once the posts are written.
    topics = json.loads((SEED / "topics.json").read_text(encoding="utf-8"))
    for t in topics:
        t["used"] = False
    (seed / "topics.json").write_text(json.dumps(topics), encoding="utf-8")
    monkeypatch.setattr(shared, "BLOG_SEED_DIR", seed)
    calls = []

    def fake(area, fmt, topic, past_titles):
        calls.append((area, fmt, topic, list(past_titles)))
        return {"title": f"Post {len(calls)}", "summary": "s", "body": "b"}

    monkeypatch.setattr(blog_writer, "generate_post", fake)
    assert generate_launch_posts.main([]) == 0

    assert [(c[0], c[1]) for c in calls] == [
        ("criminal-defense", "article"), ("stablecoins", "qa"),
        ("civil-rights", "tips"), ("estate-business", "article")]
    assert calls[3][3] == ["Post 1", "Post 2", "Post 3"]
    files = sorted((seed / "posts").glob("*.json"))
    assert [f.stem for f in files] == ["post-1", "post-2", "post-3", "post-4"]
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["status"] == "published" and data["slug"] == f.stem
        assert data["published_at"] and data["topic_id"]
        assert "qa" not in data
    used = [t for t in json.loads((seed / "topics.json").read_text(encoding="utf-8")) if t["used"]]
    assert sorted(t["id"] for t in used) == sorted(
        json.loads(f.read_text(encoding="utf-8"))["topic_id"] for f in files)
    assert str(files[0]) in capsys.readouterr().out


def test_real_run_stops_cleanly_when_the_writer_fails(monkeypatch, tmp_path):
    seed = tmp_path / "seed"
    (seed / "posts").mkdir(parents=True)
    (seed / "topics.json").write_text((SEED / "topics.json").read_text(encoding="utf-8"),
                                      encoding="utf-8")
    monkeypatch.setattr(shared, "BLOG_SEED_DIR", seed)

    def fail(*a, **k):
        raise blog_writer.BlogGenerationError("nope")

    monkeypatch.setattr(blog_writer, "generate_post", fail)
    assert generate_launch_posts.main([]) == 1
    assert list((seed / "posts").iterdir()) == []


def test_real_run_refuses_when_seed_posts_exist(monkeypatch, tmp_path, capsys):
    seed = tmp_path / "seed"
    (seed / "posts").mkdir(parents=True)
    (seed / "posts" / "old.json").write_text("{}", encoding="utf-8")
    (seed / "topics.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(shared, "BLOG_SEED_DIR", seed)

    def boom(*a, **k):
        raise AssertionError("must not call the writer")

    monkeypatch.setattr(blog_writer, "generate_post", boom)
    assert generate_launch_posts.main([]) == 1
    assert "already has post files" in capsys.readouterr().err
    assert generate_launch_posts.main(["--dry-run"]) == 0
