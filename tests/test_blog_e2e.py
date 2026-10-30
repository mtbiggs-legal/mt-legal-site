"""One whole week of the blog: seed, draft, review email, CSRF-on publish, public pages.

Only the two outside services are faked (the Anthropic client and the SendGrid
send), so the prompt, validator, store, routes and templates all run for real.
"""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

from services import blog
from services import blog_scheduler
import shared
from blueprints import email_service
from conftest import flask_app

LAUNCH = datetime(2026, 11, 2, 9, 0)
NEXT_WEEK = datetime(2026, 11, 9, 9, 0)
FILLER = ("A stablecoin issuer usually publishes its terms, and those terms decide what a holder "
          "can actually ask for when something goes wrong, so it helps to read them early and to "
          "keep a copy with your records in case the terms change later on. ")
QUESTIONS = (
    "What is a stablecoin?",
    "Can I get my money back if an issuer fails?",
    "Does Tennessee regulate stablecoins?",
    "Do I owe tax when I swap one for another?",
    "When should I talk to a lawyer?",
)


def realistic_qa_post():
    parts = ["Stablecoins raise practical questions for ordinary holders. Here are the common ones."]
    for q in QUESTIONS:
        parts += [f"## {q}", FILLER * 3, "Keep these on hand:\n- Your wallet records\n- The issuer's terms"]
    parts.append("Rules in this area can change, so check where things stand before you act.")
    return {"title": "Stablecoin Questions Tennessee Holders Ask",
            "summary": "Plain answers to common questions about holding stablecoins.",
            "body": "\n\n".join(parts)}


def test_a_qa_post_from_draft_to_public_pages(client, monkeypatch):
    # The rotation's step 1 is stablecoins, in the qa format.
    (shared.BLOG_SEED_DIR / "topics.json").write_text(json.dumps([
        {"id": "stablecoins-basics", "area": "stablecoins", "title": "Stablecoin basics", "used": False}]))
    blog.seed_from_repo(LAUNCH)
    state = blog.load_state()
    state["step"] = 1
    blog.save_state(state)

    calls, emails = [], []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=json.dumps(realistic_qa_post()))],
                               stop_reason="end_turn")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr(email_service, "_send", lambda *a, **k: emails.append(a) or True)
    monkeypatch.setenv("FIRM_EMAIL", "firm@example.com")
    monkeypatch.setenv("FIRM_WEBSITE", "https://site.example")
    monkeypatch.setattr(shared, "BLOG_AUTOGEN", True)
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", True)

    # Launch week: the seed claimed it, so nothing is drafted.
    blog_scheduler.tick(flask_app, now=LAUNCH)
    assert calls == [] and blog.list_posts() == []

    # Next week: one draft, one email, and the clock starts.
    blog_scheduler.tick(flask_app, now=NEXT_WEEK)
    assert len(calls) == 1 and len(emails) == 1
    assert "Topic: Stablecoin basics" in calls[0]["messages"][0]["content"]
    draft = blog.list_posts()[0]
    assert (draft["status"], draft["area"], draft["format"]) == ("draft", "stablecoins", "qa")
    assert draft["publish_at"] and "qa" not in draft
    assert blog.load_topics()[0]["used"] is True

    to, _, _, html_mail, _ = emails[0]
    assert to == "firm@example.com"
    assert FILLER.strip() in html_mail
    publish_url = next(h for h in re.findall(r'href="([^"]+)"', html_mail) if h.endswith("/publish"))
    path = urlsplit(publish_url).path

    # Not public yet.
    public = f"/blog/{draft['slug']}"
    assert client.get(public).status_code == 404

    # The confirm page's form, with its CSRF token.
    page = client.get(path).get_data(as_text=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert blog.load_post(draft["slug"])["status"] == "draft"
    done = client.post(path, data={"csrf_token": csrf})
    assert done.status_code == 200 and "Published." in done.get_data(as_text=True)

    # The page: each question once, as a heading, and matching FAQ data.
    resp = client.get(public)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    article = html.split('<article class="blog-post">')[1].split("</article>")[0]
    for q in QUESTIONS:
        escaped = q.replace("'", "&#39;")
        assert article.count(escaped) == 1
        assert f"<h2>{escaped}</h2>" in article
    ld = {d["@type"]: d for d in (json.loads(m) for m in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S))}
    assert [e["name"] for e in ld["FAQPage"]["mainEntity"]] == list(QUESTIONS)
    assert FILLER.strip() in ld["FAQPage"]["mainEntity"][0]["acceptedAnswer"]["text"]

    # The feed and sitemap.
    feed = ET.fromstring(client.get("/blog/feed.xml").data)
    assert [i.findtext("title") for i in feed.findall("./channel/item")] == [draft["title"]]
    assert public in client.get("/sitemap.xml").get_data(as_text=True)
    assert draft["title"] in client.get("/blog").get_data(as_text=True)

    # Published by hand, so the next tick leaves it alone and doesn't draft again.
    blog_scheduler.tick(flask_app, now=NEXT_WEEK)
    assert len(calls) == 1 and len(emails) == 1
