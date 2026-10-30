import json
import re
from datetime import date
from types import SimpleNamespace

import anthropic
import pytest

from services import blog
from services import blog_writer
import shared
from services.blog_writer import BlogGenerationError
from blueprints import email_service
from conftest import flask_app


def words(n):
    return " ".join(["word"] * n)


def good(**kw):
    d = {"title": "What to Expect at Arraignment", "summary": "A plain look at the first hearing.",
         "body": "## Overview\n\n" + words(700)}
    d.update(kw)
    return d


def qa_body(questions=3):
    parts = ["A short introduction."]
    for i in range(questions):
        parts += [f"## What happens at step {i}?", words(600 // questions)]
    return "\n\n".join(parts)


class FakeClient:
    def __init__(self, text=None, exc=None):
        self.calls = []
        self._text, self._exc = text, exc
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        # Real responses put a thinking block before the text.
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=self._text)],
                               stop_reason="end_turn")


@pytest.fixture
def fake(monkeypatch):
    def _install(text=None, exc=None):
        c = FakeClient(text, exc)
        monkeypatch.setattr(shared, "get_anthropic_client", lambda: c)
        return c
    return _install


def gen(fmt="article"):
    return blog_writer.generate_post("criminal-defense", fmt, None, ["Old Title"])


def test_generate_post_parses_json_and_fenced_json(fake):
    fake(json.dumps(good()))
    assert gen()["title"] == "What to Expect at Arraignment"
    fake("```json\n" + json.dumps(good()) + "\n```")
    assert gen()["summary"].startswith("A plain look")


def test_generate_rejects_public_defender_mention(fake):
    fake(json.dumps(good(body="## H\n\nA Public Defender may help. " + words(700))))
    with pytest.raises(BlogGenerationError):
        gen()


@pytest.mark.parametrize("phrase", ["we guarantee", "guaranteed result", "guaranteed outcome",
                                    "our attorneys", "our lawyers"])
def test_validate_rejects_banned_phrases(phrase):
    with pytest.raises(BlogGenerationError):
        blog_writer.validate(good(summary=f"Sure, {phrase.upper()} it."), "article")


def test_constitutional_guarantee_passes():
    d = blog_writer.validate(good(body="## H\n\nThe constitutional guarantee of counsel. " + words(700)),
                             "article")
    assert "constitutional guarantee" in d["body"]


def test_generate_rejects_short_body(fake):
    fake(json.dumps(good(body=words(100))))
    with pytest.raises(BlogGenerationError):
        gen()


def test_qa_format_accepts_three_question_headings(fake):
    fake(json.dumps(good(body=qa_body(3))))
    assert gen("qa")["body"] == qa_body(3)


@pytest.mark.parametrize("body", [
    "## Overview\n\n" + words(700),
    qa_body(2),
    qa_body(2) + "\n\n## Is this one answered?",
    qa_body(2) + "\n\n## A heading that asks nothing\n\n" + words(50),
], ids=["no questions", "two questions", "third has no answer", "third is no question"])
def test_qa_format_needs_three_answered_question_headings(fake, body):
    fake(json.dumps(good(body=body)))
    with pytest.raises(BlogGenerationError):
        gen("qa")


def test_article_format_needs_no_question_headings():
    assert blog_writer.validate(good(), "article")["title"]


def test_model_qa_key_is_ignored():
    stale = [{"q": "Why?", "a": "A separate answer nobody reviews."}]
    for fmt, body in (("article", good()["body"]), ("qa", qa_body(3))):
        assert set(blog_writer.validate(good(body=body, qa=stale), fmt)) == {"title", "summary", "body"}


def test_prompt_no_longer_asks_for_separate_qa():
    assert '"qa"' not in blog_writer.SYSTEM_PROMPT
    assert 'ending in "?"' in blog_writer.SYSTEM_PROMPT


@pytest.mark.parametrize("field", ["title", "summary", "body"])
@pytest.mark.parametrize("markup", ["**bold**", "a <b>tag</b>"])
def test_validate_rejects_bold_and_html(field, markup):
    d = good()
    d[field] = (d[field] + " " + markup) if field == "body" else markup
    with pytest.raises(BlogGenerationError):
        blog_writer.validate(d, "article")


@pytest.mark.parametrize("phrase", [
    "public defenders", "guaranteed results", "guaranteed outcomes", "our team of attorneys",
    "our legal team", "our associates", "our partners", "our attorney", "our lawyer",
    "we'll get your charges dropped", "we\u2019ll get your charges dropped",
    "we will win your case", "we can beat this charge", "we guarantee",
])
def test_validate_rejects_misleading_phrasing(phrase):
    with pytest.raises(BlogGenerationError):
        blog_writer.validate(good(body=f"## H\n\nHere {phrase} today. " + words(700)), "article")


@pytest.mark.parametrize("phrase", [
    "the guarantee of counsel", "a constitutional guarantee", "no guarantee of any result",
    "your attorneys", "your lawyer", "tour team of guides", "we can help you understand",
])
def test_validate_allows_ordinary_phrasing(phrase):
    assert blog_writer.validate(good(body=f"## H\n\nHere {phrase} today. " + words(700)), "article")


@pytest.mark.parametrize("rule", ["testimonial", "past results", "statistics", "expert",
                                  "specialist", "other lawyers", "rules can change",
                                  "No bold", "No HTML"])
def test_prompt_states_the_rule(rule):
    assert rule.lower() in blog_writer.SYSTEM_PROMPT.lower()


def test_prompt_has_no_numbered_feeling_list():
    assert "numbered-feeling" not in blog_writer.SYSTEM_PROMPT


def test_user_prompt_contains_todays_date(fake):
    c = fake(json.dumps(good()))
    before = date.today().isoformat()
    gen()
    prompt = c.calls[0]["messages"][0]["content"]
    assert before in prompt or date.today().isoformat() in prompt


def test_bad_json_becomes_generation_error(fake):
    fake("not json at all")
    with pytest.raises(BlogGenerationError):
        gen()


def test_api_error_becomes_generation_error(fake):
    fake(exc=anthropic.APIError("boom"))
    with pytest.raises(BlogGenerationError):
        gen()


def test_uses_blog_model(fake):
    c = fake(json.dumps(good()))
    gen()
    call = c.calls[0]
    assert call["model"] == shared.BLOG_MODEL
    assert call["system"] == blog_writer.SYSTEM_PROMPT
    prompt = call["messages"][0]["content"]
    assert "Criminal Defense" in prompt and "Old Title" in prompt and "article" in prompt


def test_next_topic_skips_used_and_other_areas(patch_dirs):
    blog.save_topics([
        {"id": "a", "area": "civil-rights", "title": "Other area", "used": False},
        {"id": "b", "area": "criminal-defense", "title": "Used", "used": True},
        {"id": "c", "area": "criminal-defense", "title": "Fresh", "used": False},
    ])
    assert blog_writer.next_topic("criminal-defense")["id"] == "c"
    assert blog_writer.next_topic("stablecoins") is None


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(email_service, "_send", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setenv("FIRM_EMAIL", "firm@example.com")
    monkeypatch.setenv("FIRM_WEBSITE", "https://site.example/")
    return calls


def test_review_email_has_three_links_and_escapes(sent):
    p = blog.new_post("Rights <b>Now</b>", "Sum & more", "## Head\n\nBody.", "civil-rights", "article")
    blog.save_post(p)
    with flask_app.app_context():
        assert blog_writer.send_review_email(p) is True
    to, name, subject, html, text = sent[0]
    assert to == "firm@example.com" and name == "MT Legal"
    assert subject == "Blog draft for review: Rights <b>Now</b>"
    assert "&lt;b&gt;Now&lt;/b&gt;" in html and "<b>Now</b>" not in html
    assert "Publishes automatically 48 hours after this email unless you pull it." in html
    hrefs = re.findall(r'href="([^"]+)"', html)
    assert len(hrefs) == 3
    prefix = "https://site.example/blog/review/"
    assert all(h.startswith(prefix) for h in hrefs)
    suffixes = sorted(h[len(prefix):].partition("/")[2] for h in hrefs)
    assert suffixes == ["", "publish", "pull"]
    for h in hrefs:
        assert h in text


def test_review_email_contains_the_answers(sent):
    body = "## Can I get bail?\n\nA judge decides that at the first hearing."
    p = blog.new_post("Bail", "S", body, "criminal-defense", "qa")
    with flask_app.app_context():
        assert blog_writer.send_review_email(p) is True
    _, _, _, html, text = sent[0]
    for part in (html, text):
        assert "Can I get bail?" in part and "A judge decides that at the first hearing." in part


def test_review_email_returns_false_when_send_fails(monkeypatch, sent):
    monkeypatch.setattr(email_service, "_send", lambda *a, **k: False)
    p = blog.new_post("T", "S", "B", "civil-rights", "article")
    with flask_app.app_context():
        assert blog_writer.send_review_email(p) is False


@pytest.mark.parametrize("name", ["FIRM_EMAIL", "FIRM_WEBSITE"])
@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_review_email_not_sent_without_setting(monkeypatch, sent, caplog, name, value):
    # The helpers would fall back to a default, which must not start the clock.
    monkeypatch.setenv("FROM_EMAIL", "bot@example.com")
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    p = blog.new_post("T", "S", "B", "civil-rights", "article")
    with flask_app.app_context():
        assert blog_writer.send_review_email(p) is False
    assert sent == []
    assert any(r.levelname == "ERROR" and name in r.getMessage() for r in caplog.records)


def test_other_emails_keep_their_firm_email_fallback(monkeypatch):
    monkeypatch.delenv("FIRM_EMAIL", raising=False)
    monkeypatch.setenv("FROM_EMAIL", "bot@example.com")
    assert email_service._firm_email() == "bot@example.com"


@pytest.mark.parametrize("text", ["public\ndefender", "public-defender", "public  defender",
                                  "public\u00a0defender", "our\nattorneys"])
def test_validate_banned_phrase_variants_rejected(text):
    with pytest.raises(BlogGenerationError):
        blog_writer.validate(good(body=f"## H\n\nA {text} here. " + words(700)), "article")


def test_your_attorneys_and_lawyers_pass():
    d = blog_writer.validate(good(body="## H\n\nTalk to your attorneys and your lawyers. " + words(700)),
                             "article")
    assert "your attorneys" in d["body"]


def test_estate_prompt_describes_estate_planning():
    prompt = blog_writer._user_prompt("estate-business", "article", "Wills", [])
    assert "Practice area: Estate Planning" in prompt
    assert "Digital Asset Structuring" not in prompt
    assert "Practice area: Civil Rights Litigation" in blog_writer._user_prompt(
        "civil-rights", "article", None, [])


def _reply(stop_reason, text=""):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


def test_refused_or_cut_off_reply_is_a_generation_error(monkeypatch):
    for stop_reason in ("refusal", "max_tokens"):
        client = SimpleNamespace(messages=SimpleNamespace(
            create=lambda **kw: _reply(stop_reason, json.dumps(good()))))
        monkeypatch.setattr(shared, "get_anthropic_client", lambda: client)
        with pytest.raises(blog_writer.BlogGenerationError, match=stop_reason):
            blog_writer.generate_post("civil-rights", "article", "Topic", [])


def test_reply_with_no_text_is_a_generation_error(monkeypatch):
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="thinking", thinking="")])))
    monkeypatch.setattr(shared, "get_anthropic_client", lambda: client)
    with pytest.raises(blog_writer.BlogGenerationError):
        blog_writer.generate_post("civil-rights", "article", "Topic", [])
