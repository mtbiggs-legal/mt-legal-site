import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from services import blog
from blueprints.blog import _rfc822
from tests.test_blog_pages import published


def test_feed_is_valid_rss_with_published_only(client):
    published(title="Older Post", published_at="2026-10-01T09:00:00")
    published(title="Newer Post", published_at="2026-10-08T09:00:00")
    d = published(title="Draft Post", status="draft")
    resp = client.get("/blog/feed.xml")
    assert resp.status_code == 200
    assert resp.mimetype == "application/rss+xml"
    root = ET.fromstring(resp.data)
    assert root.tag == "rss" and root.get("version") == "2.0"
    items = root.findall("./channel/item")
    assert [i.findtext("title") for i in items] == ["Newer Post", "Older Post"]
    first = items[0]
    guid = first.find("guid")
    assert guid.get("isPermaLink") == "true"
    assert guid.text == first.findtext("link")
    assert parsedate_to_datetime(first.findtext("pubDate")) == datetime(2026, 10, 8, 9, 0).astimezone()
    assert first.findtext("description") == "A summary."
    assert d["slug"] not in resp.get_data(as_text=True)


def test_rfc822_reads_naive_times_as_server_local():
    # Holds in any machine zone: the stored clock time is local, so the instant
    # is the one the machine's zone gives it, offset included.
    naive = datetime(2026, 1, 15, 9, 0)
    assert parsedate_to_datetime(_rfc822(naive.isoformat())) == naive.astimezone()


def test_rfc822_keeps_the_instant_of_aware_times():
    aware = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert parsedate_to_datetime(_rfc822(aware.isoformat())) == aware


def test_rfc822_bad_input_is_none():
    assert _rfc822("soon") is None
    assert _rfc822(None) is None


def test_feed_route_is_not_a_post_slug(client):
    resp = client.get("/blog/feed.xml")
    assert resp.status_code == 200
    assert resp.mimetype == "application/rss+xml"


def test_feed_escapes_ampersands(client):
    published(title="Wills & Trusts", summary="Q&A <basics>")
    root = ET.fromstring(client.get("/blog/feed.xml").data)
    item = root.find("./channel/item")
    assert item.findtext("title") == "Wills & Trusts"
    assert item.findtext("description") == "Q&A <basics>"


def test_sitemap_lists_blog_and_posts(client):
    p = published(title="Live", updated_at="2026-10-05T10:00:00")
    d = published(title="Draft", status="draft")
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml)
    locs = [u.findtext("s:loc", namespaces=ns) for u in root.findall("s:url", ns)]
    assert any(l.endswith("/blog") for l in locs)
    assert any(l.endswith("/blog/" + p["slug"]) for l in locs)
    assert not any(d["slug"] in l for l in locs)
    assert "<lastmod>2026-10-05</lastmod>" in xml


def test_base_links_rss(client):
    html = client.get("/").get_data(as_text=True)
    assert 'type="application/rss+xml"' in html
    assert 'href="/blog/feed.xml"' in html


def _save(title, status):
    p = blog.new_post(title, "Summary of " + title, "Body of " + title, "civil-rights", "article")
    p["status"] = status
    if status == "published":
        p["published_at"] = "2026-10-08T09:00:00"
    blog.save_post(p)
    return p


def test_llms_txt_lists_blog_and_published_posts_only(client):
    live = _save("Live post", "published")
    _save("Hidden draft", "draft")
    text = client.get("/llms.txt").get_data(as_text=True)
    assert "/blog/feed.xml" in text
    assert f"/blog/{live['slug']}" in text
    assert "Hidden draft" not in text


def test_llms_full_has_published_post_text_only(client):
    _save("Live post", "published")
    _save("Hidden draft", "draft")
    text = client.get("/llms-full.txt").get_data(as_text=True)
    assert "Body of Live post" in text
    assert "Hidden draft" not in text
