"""YouTube videos on the blog (content/videos.toml, services/videos.py)."""
import json
import re

from services import videos
from test_blog_pages import published


def _ld(html):
    return [json.loads(m) for m in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_video_list_is_well_formed():
    assert videos.VIDEOS
    for v in videos.VIDEOS:
        assert re.fullmatch(r"[A-Za-z0-9_-]{11}", v["id"]), v
        assert v["title"] and v["summary"] and v["uploaded"]
        assert re.fullmatch(r"PT\d+M\d+S", v["duration"]), v


def test_matching_post_shows_its_video(client):
    p = published(title="Blockchain 101: A Plain-English Guide to How It Works")
    assert p["slug"] == "blockchain-101-a-plain-english-guide-to-how-it-works"
    v = videos.for_post(p["slug"])
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert f'data-yt-id="{v["id"]}"' in html
    graph = next(d for d in _ld(html) if "@graph" in d)["@graph"]
    assert graph[0]["@type"] == "VideoObject" and graph[0]["name"] == v["title"]


def test_other_posts_have_no_video(client):
    p = published(title="Something Else")
    assert "data-yt-id=" not in client.get(f"/blog/{p['slug']}").get_data(as_text=True)


def test_csp_allows_only_the_privacy_enhanced_player(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    frame_src = re.search(r"frame-src ([^;]+)", csp).group(1).split()
    assert frame_src == ["'self'", "https://www.youtube-nocookie.com"]


def test_footer_and_profiles_link_the_channel(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="https://www.youtube.com/@MTLEGAL615"' in html
    firm = next(d for d in _ld(html) if d.get("@type") == "LegalService")
    assert "https://www.youtube.com/@MTLEGAL615" in firm["sameAs"]


def test_every_video_belongs_to_a_seed_post():
    """Videos only appear inside posts, so one without a post would never show."""
    from pathlib import Path
    seed = {f.stem for f in Path("blog_seed/posts").glob("*.json")}
    for v in videos.VIDEOS:
        assert v.get("post") in seed, v


def test_blog_page_has_no_video_section(client):
    published()
    html = client.get("/blog").get_data(as_text=True)
    assert "data-yt-id=" not in html and "blog-videos" not in html


def test_player_opens_in_a_dialog_not_inline():
    js = open("static/js/site.js", encoding="utf-8").read()
    assert 'className = "yt-modal"' in js and 'setAttribute("aria-modal", "true")' in js
    assert "youtube-nocookie.com/embed/" in js

