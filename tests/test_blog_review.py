import re

import pytest
from itsdangerous import URLSafeTimedSerializer

from services import blog
import shared
from conftest import flask_app


def make_draft(title="Draft One", topic_id=None, **kw):
    p = blog.new_post(title, "Sum.", "## Head\n\nBody text.", "civil-rights", "article",
                      topic_id=topic_id)
    p["publish_at"] = "2026-11-02T09:00:00"
    p.update(kw)
    blog.save_post(p)
    return p


def token(p):
    with flask_app.app_context():
        return blog.make_review_token(p)


def status(slug):
    return blog.load_post(slug)["status"]


def test_get_publish_link_changes_nothing(client):
    d = make_draft()
    r = client.get(f"/blog/review/{token(d)}/publish")
    assert r.status_code == 200
    assert "<form" in r.get_data(as_text=True)
    assert status(d["slug"]) == "draft"


def test_post_publish_then_link_spent(client):
    d = make_draft()
    tok = token(d)
    assert "Published." in client.post(f"/blog/review/{tok}/publish").get_data(as_text=True)
    assert status(d["slug"]) == "published"
    assert blog.load_post(d["slug"])["published_at"]
    assert "already" in client.post(f"/blog/review/{tok}/pull").get_data(as_text=True)
    assert status(d["slug"]) == "published"


def test_pull_returns_topic_to_queue(client):
    t = blog.add_topic("civil-rights", "Topic X")
    topics = blog.load_topics()
    topics[0]["used"] = True
    blog.save_topics(topics)
    d = make_draft(topic_id=t["id"])
    body = client.post(f"/blog/review/{token(d)}/pull").get_data(as_text=True)
    assert "Pulled. Nothing goes up this week." in body
    assert status(d["slug"]) == "pulled"
    assert blog.load_topics()[0]["used"] is False


def test_token_bound_to_one_post(client):
    a, b = make_draft("Post A"), make_draft("Post B")
    with flask_app.app_context():
        forged = URLSafeTimedSerializer(flask_app.secret_key, salt="blog-review").dumps(
            {"s": b["slug"], "r": a["review_token_id"]})
    r = client.post(f"/blog/review/{forged}/publish")
    assert r.status_code == 404
    assert "expired or is no longer valid" in r.get_data(as_text=True)
    assert status(b["slug"]) == "draft"


def test_garbage_and_wrong_salt_tokens_rejected(client):
    d = make_draft()
    with flask_app.app_context():
        other = URLSafeTimedSerializer(flask_app.secret_key, salt="other").dumps(
            {"s": d["slug"], "r": d["review_token_id"]})
    assert client.get("/blog/review/garbage").status_code == 404
    assert client.get(f"/blog/review/{other}").status_code == 404


def test_expired_token_rejected(client, monkeypatch):
    d = make_draft()
    tok = token(d)
    monkeypatch.setattr(blog, "REVIEW_TOKEN_MAX_AGE", -1)
    assert client.get(f"/blog/review/{tok}").status_code == 404
    assert client.post(f"/blog/review/{tok}/publish").status_code == 404
    assert status(d["slug"]) == "draft"


def test_pulled_post_links_dead(client):
    d = make_draft()
    tok = token(d)
    blog.pull(d["slug"])
    assert client.get(f"/blog/review/{tok}").status_code == 410
    r = client.post(f"/blog/review/{tok}", data={"op": "save", "title": "x", "body": "y"})
    assert r.status_code == 410


def test_edit_save_keeps_publish_at(client):
    d = make_draft()
    r = client.post(f"/blog/review/{token(d)}", data={
        "op": "save", "title": "  New Title ", "summary": "S2", "body": "New body"})
    assert r.status_code == 200
    got = blog.load_post(d["slug"])
    assert (got["title"], got["summary"], got["body"]) == ("New Title", "S2", "New body")
    assert got["status"] == "draft"
    assert got["publish_at"] == "2026-11-02T09:00:00"


def test_edit_rejects_empty_title_or_body(client):
    d = make_draft()
    r = client.post(f"/blog/review/{token(d)}", data={"op": "save", "title": " ", "body": "b"})
    assert r.status_code == 400
    assert blog.load_post(d["slug"])["title"] == "Draft One"
    with pytest.raises(ValueError):
        blog.update_post(d["slug"], "T", "S", "  ")


def test_edit_page_escapes_content(client):
    d = make_draft(body="</textarea><script>alert(1)</script>")
    html = client.get(f"/blog/review/{token(d)}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_edit_published_post_allows_save_not_pull(client):
    d = make_draft()
    tok = token(d)
    blog.publish(d["slug"])
    ok = client.post(f"/blog/review/{tok}", data={"op": "save", "title": "Fixed", "body": "b"})
    assert ok.status_code == 200
    assert blog.load_post(d["slug"])["title"] == "Fixed"
    for op in ("pull", "publish"):
        r = client.post(f"/blog/review/{tok}", data={"op": op, "title": "t", "body": "b"})
        assert r.status_code == 409
    assert status(d["slug"]) == "published"


def test_edit_pull_reports_spent_when_pull_fails(client, monkeypatch):
    d = make_draft()
    tok = token(d)
    # The page saw a draft, but it stopped being one before the pull landed.
    monkeypatch.setattr(blog, "pull", lambda slug: False)
    r = client.post(f"/blog/review/{tok}", data={"op": "pull", "title": "t", "body": "b"})
    body = r.get_data(as_text=True)
    assert r.status_code == 409
    assert "This draft was already published or pulled." in body
    assert "Pulled. Nothing goes up this week." not in body


def test_edit_publish_op_saves_then_publishes(client):
    d = make_draft()
    client.post(f"/blog/review/{token(d)}", data={"op": "publish", "title": "Edited", "body": "b"})
    got = blog.load_post(d["slug"])
    assert got["status"] == "published" and got["title"] == "Edited"


def test_add_topic_from_review_page(client):
    d = make_draft()
    r = client.post(f"/blog/review/{token(d)}", data={
        "op": "add_topic", "area": "stablecoins", "topic_title": "GENIUS Act basics"})
    assert r.status_code == 200
    assert [(t["area"], t["title"], t["used"]) for t in blog.load_topics()] == [
        ("stablecoins", "GENIUS Act basics", False)]
    bad = client.post(f"/blog/review/{token(d)}", data={
        "op": "add_topic", "area": "family-law", "topic_title": "x"})
    assert bad.status_code == 400


def test_review_routes_work_in_public_site_only(client, monkeypatch):
    monkeypatch.setattr(shared, "PUBLIC_SITE_ONLY", True)
    d = make_draft()
    tok = token(d)
    assert client.get(f"/blog/review/{tok}").status_code == 200
    assert client.get(f"/blog/review/{tok}/publish").status_code == 200
    assert client.get("/blog").status_code == 200


def test_review_pages_noindex(client):
    d = make_draft()
    tok = token(d)
    for url in (f"/blog/review/{tok}", f"/blog/review/{tok}/publish", "/blog/review/bad"):
        r = client.get(url)
        assert r.headers["X-Robots-Tag"] == "noindex"
        assert '<meta name="robots" content="noindex">' in r.get_data(as_text=True)
    assert "Disallow: /blog/review/" in client.get("/robots.txt").get_data(as_text=True)


def test_review_post_requires_csrf(client):
    d = make_draft()
    tok = token(d)
    flask_app.config["CSRF_ENABLED"] = True
    try:
        assert client.post(f"/blog/review/{tok}/publish").status_code in (400, 403)
        assert status(d["slug"]) == "draft"
        html = client.get(f"/blog/review/{tok}/publish").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = client.post(f"/blog/review/{tok}/publish", data={"csrf_token": csrf})
        assert r.status_code == 200
        assert status(d["slug"]) == "published"
    finally:
        flask_app.config["CSRF_ENABLED"] = False


def test_409_keeps_the_submitted_text(client):
    d = make_draft()
    tok = token(d)
    blog.publish(d["slug"])  # the open form still shows a draft
    r = client.post(f"/blog/review/{tok}", data={
        "op": "publish", "title": "My title edit", "summary": "My summary edit", "body": "My body edit"})
    html = r.get_data(as_text=True)
    assert r.status_code == 409
    for text in ("My title edit", "My summary edit", "My body edit"):
        assert text in html
    assert blog.load_post(d["slug"])["title"] == "Draft One"


def test_takedown_button_only_on_published_posts(client):
    d = make_draft()
    tok = token(d)
    assert 'value="takedown"' not in client.get(f"/blog/review/{tok}").get_data(as_text=True)
    blog.publish(d["slug"])
    html = client.get(f"/blog/review/{tok}").get_data(as_text=True)
    assert 'value="takedown"' in html
    assert "removes it from the site" in html
    assert 'value="pull"' not in html


def test_takedown_removes_post_everywhere(client):
    t = blog.add_topic("civil-rights", "Topic X")
    topics = blog.load_topics()
    topics[0]["used"] = True
    blog.save_topics(topics)
    d = make_draft(topic_id=t["id"])
    tok = token(d)
    blog.publish(d["slug"])
    path = f"/blog/{d['slug']}"
    assert client.get(path).status_code == 200
    assert d["slug"] in client.get("/blog/feed.xml").get_data(as_text=True)

    r = client.post(f"/blog/review/{tok}", data={"op": "takedown", "title": "Unsaved", "body": "x"})
    assert r.status_code == 200
    assert "taken down" in r.get_data(as_text=True).lower()
    got = blog.load_post(d["slug"])
    assert got["status"] == "pulled" and got["title"] == "Draft One"
    assert client.get(path).status_code == 404
    assert d["slug"] not in client.get("/blog").get_data(as_text=True)
    assert d["slug"] not in client.get("/blog/feed.xml").get_data(as_text=True)
    assert d["slug"] not in client.get("/sitemap.xml").get_data(as_text=True)
    assert blog.load_topics()[0]["used"] is True


def test_takedown_of_a_draft_is_refused(client):
    d = make_draft()
    r = client.post(f"/blog/review/{token(d)}", data={"op": "takedown", "title": "Mine", "body": "b"})
    assert r.status_code == 409
    assert "Mine" in r.get_data(as_text=True)
    assert status(d["slug"]) == "draft"


def test_takedown_lost_race_reports_conflict(client, monkeypatch):
    d = make_draft()
    tok = token(d)
    blog.publish(d["slug"])
    monkeypatch.setattr(blog, "takedown", lambda slug: False)
    r = client.post(f"/blog/review/{tok}", data={"op": "takedown", "title": "t", "body": "b"})
    assert r.status_code == 409


def test_expired_session_on_review_post_shows_html_page(client, monkeypatch):
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", True)
    d = make_draft()
    tok = token(d)
    for url in (f"/blog/review/{tok}", f"/blog/review/{tok}/publish", f"/blog/review/{tok}/pull"):
        r = client.post(url, data={"op": "publish", "title": "T", "body": "b"})
        html = r.get_data(as_text=True)
        assert r.status_code == 400
        assert r.mimetype == "text/html"
        assert "expired" in html and "Nothing was changed" in html
        assert "link in the email" in html
        assert r.headers["X-Robots-Tag"] == "noindex"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert r.headers["Cache-Control"] == "no-store"
    assert status(d["slug"]) == "draft"
    assert blog.load_post(d["slug"])["title"] == "Draft One"


def test_csrf_failure_elsewhere_is_still_json(client, monkeypatch):
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", True)
    for path in ("/client-login", "/blog/reviews", "/blog"):
        r = client.post(path)
        assert r.status_code == 400 and r.is_json
        assert r.get_json() == {"error": "Invalid or missing CSRF token."}


def test_review_edit_form_with_csrf_on(client, monkeypatch):
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", True)
    d = make_draft()
    url = f"/blog/review/{token(d)}"
    fields = {"op": "save", "title": "Saved title", "summary": "S", "body": "B"}

    missing = client.post(url, data=fields)
    assert missing.status_code == 400 and missing.mimetype == "text/html"
    assert blog.load_post(d["slug"])["title"] == "Draft One"

    html = client.get(url).get_data(as_text=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    wrong = client.post(url, data={**fields, "csrf_token": "wrong"})
    assert wrong.status_code == 400
    assert blog.load_post(d["slug"])["title"] == "Draft One"

    assert client.post(url, data={**fields, "csrf_token": csrf}).status_code == 200
    assert blog.load_post(d["slug"])["title"] == "Saved title"


def test_publish_and_pull_only_from_draft():
    d = make_draft()
    assert blog.publish(d["slug"]) is True
    assert blog.publish(d["slug"]) is False
    assert blog.pull(d["slug"]) is False
