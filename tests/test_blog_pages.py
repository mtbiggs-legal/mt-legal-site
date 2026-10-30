import json
import re

from services import blog
import shared


def published(**kw):
    p = blog.new_post(kw.pop("title", "A Title"), kw.pop("summary", "A summary."),
                      kw.pop("body", "## Head\n\nPara"), kw.pop("area", "civil-rights"),
                      kw.pop("fmt", "article"))
    p["status"] = kw.pop("status", "published")
    p["published_at"] = "2026-10-01T09:00:00"
    p.update(kw)
    blog.save_post(p)
    return p


def _ld(html):
    return [json.loads(m) for m in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def test_parse_body_blocks():
    assert blog.parse_body("## Head\n\nPara one\ncontinues\n\n- a\n- b") == [
        {"type": "h2", "text": "Head"},
        {"type": "p", "text": "Para one continues"},
        {"type": "ul", "items": ["a", "b"]}]


def test_parse_body_heading_ends_at_its_line():
    assert blog.parse_body("## Heading\nText after it\nmore text") == [
        {"type": "h2", "text": "Heading"},
        {"type": "p", "text": "Text after it more text"}]


def test_parse_body_paragraph_then_bullets():
    assert blog.parse_body("Intro:\n- a\n- b\nAfter") == [
        {"type": "p", "text": "Intro:"},
        {"type": "ul", "items": ["a", "b"]},
        {"type": "p", "text": "After"}]


def test_parse_body_numbered_list():
    assert blog.parse_body("1. one\n2. two\n10. ten") == [
        {"type": "ol", "items": ["one", "two", "ten"]}]


def test_parse_body_list_items_separated_by_blank_lines_stay_one_list():
    assert blog.parse_body("1. one\n\n2. two\n\nPara\n\n1. three") == [
        {"type": "ol", "items": ["one", "two"]},
        {"type": "p", "text": "Para"},
        {"type": "ol", "items": ["three"]}]


def test_parse_body_crlf():
    assert blog.parse_body("## Head\r\nText\r\n\r\n- a\r\n- b\r\n") == [
        {"type": "h2", "text": "Head"},
        {"type": "p", "text": "Text"},
        {"type": "ul", "items": ["a", "b"]}]


def test_parse_body_empty_input():
    assert blog.parse_body("") == []
    assert blog.parse_body(None) == []
    assert blog.parse_body(" \n\r\n  ") == []


def test_numbered_list_renders_as_ol(client):
    p = published(body="1. First step\n2. Second step")
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "<ol><li>First step</li><li>Second step</li></ol>" in html


def test_index_lists_only_published(client):
    published(title="Live Post")
    published(title="Draft Post", status="draft")
    html = client.get("/blog").get_data(as_text=True)
    assert "Live Post" in html
    assert "Draft Post" not in html


def test_index_area_filter(client):
    published(title="Rights Post", area="civil-rights")
    published(title="Estate Post", area="estate-business")
    html = client.get("/blog?area=civil-rights").get_data(as_text=True)
    assert "Rights Post" in html and "Estate Post" not in html
    both = client.get("/blog?area=bogus").get_data(as_text=True)
    assert "Rights Post" in both and "Estate Post" in both


def test_draft_and_pulled_posts_404(client):
    d = published(title="Draft", status="draft")
    p = published(title="Pulled", status="pulled")
    assert client.get(f"/blog/{d['slug']}").status_code == 404
    assert client.get(f"/blog/{p['slug']}").status_code == 404
    assert client.get("/blog/nope").status_code == 404


def test_post_page_has_disclaimer_cta_and_practice_link(client):
    p = published()
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "not legal advice" in html
    assert 'href="/intake"' in html
    assert "/practice/civil-rights" in html


QA_BODY = ("Intro paragraph.\n\n## Can I get bail?\n\nA judge decides.\n\n- At the hearing\n"
           "- Or later\n\n## What next?\n\nYou wait.\n\n## A plain heading\n\nNot part of any answer.")


def _article(html):
    return html.split('<article class="blog-post">')[1].split("</article>")[0]


def _faq(html):
    return {d["@type"]: d for d in _ld(html)}["FAQPage"]["mainEntity"]


def test_faq_entries_come_from_question_headings():
    assert blog.faq_entries(blog.parse_body(QA_BODY)) == [
        {"q": "Can I get bail?", "a": "A judge decides. At the hearing Or later"},
        {"q": "What next?", "a": "You wait."}]
    assert blog.faq_entries(blog.parse_body("## Unanswered?\n\n## Next?\n\nYes.")) == [
        {"q": "Next?", "a": "Yes."}]


def test_post_jsonld_blogposting_and_faq(client):
    p = published(title="Headline X", fmt="qa", body=QA_BODY)
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert {d["@type"]: d for d in _ld(html)}["BlogPosting"]["headline"] == "Headline X"
    faq = _faq(html)
    assert [q["name"] for q in faq] == ["Can I get bail?", "What next?"]
    assert faq[1]["acceptedAnswer"]["text"] == "You wait."


def test_question_appears_once_on_the_page(client):
    p = published(fmt="qa", body=QA_BODY)
    article = _article(client.get(f"/blog/{p['slug']}").get_data(as_text=True))
    assert article.count("Can I get bail?") == 1
    assert "blog-qa" not in article


def test_editing_an_answer_changes_page_and_faq(client):
    p = published(fmt="qa", body=QA_BODY)
    blog.update_post(p["slug"], p["title"], p["summary"], QA_BODY.replace("You wait.", "You call us."))
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "You call us." in _article(html) and "You wait." not in html
    assert _faq(html)[1]["acceptedAnswer"]["text"] == "You call us."


def test_old_record_qa_key_is_ignored(client):
    p = published(fmt="qa", body=QA_BODY, qa=[{"q": "Stale question?", "a": "Stale answer."}])
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "Stale" not in html
    assert len(_faq(html)) == 2


def test_no_faq_without_qa_format_or_questions(client):
    article = published(body=QA_BODY)
    no_questions = published(fmt="qa", body="## Plain\n\nText.")
    for p in (article, no_questions):
        docs = _ld(client.get(f"/blog/{p['slug']}").get_data(as_text=True))
        assert "FAQPage" not in {d["@type"] for d in docs}


def test_new_posts_store_no_qa_key():
    assert "qa" not in blog.new_post("T", "S", "B", "civil-rights", "qa")


def test_post_page_has_byline_with_date(client):
    p = published()
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert f"By {shared.MANAGING_PARTNER['display']}" in html
    assert re.search(r'class="blog-byline">By [^<]*2026-10-01<', html)


def test_post_page_cta_is_a_primary_button(client):
    p = published()
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert 'href="/intake" class="btn btn-primary"' in html


def test_post_body_html_is_escaped(client):
    p = published(title="<script>alert(1)</script>", body="<img src=x onerror=1>")
    html = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_nav_has_blog_link(client):
    assert 'href="/blog"' in client.get("/").get_data(as_text=True)


def test_estate_posts_say_estate_planning_and_link_to_family_planning(client):
    p = published(title="Will or Trust", area="estate-business")
    index = client.get("/blog").get_data(as_text=True)
    # The site footer lists every practice page, so check the blog's own labels.
    labels = re.findall(r'class="blog-(?:chip|card-meta)[^"]*">([^<]*)', index)
    assert any("Estate Planning" in l for l in labels)
    assert not any("Digital Asset Structuring" in l for l in labels)
    page = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "Learn more about Estate &amp; Family Planning" in page
    assert 'href="/practice/family-law"' in page
    assert ">Learn more about Digital Asset Structuring" not in page


def test_other_areas_keep_their_own_label_and_page(client):
    p = published(title="Know Your Rights", area="civil-rights")
    page = client.get(f"/blog/{p['slug']}").get_data(as_text=True)
    assert "Learn more about Civil Rights Litigation" in page
    assert 'href="/practice/civil-rights"' in page
