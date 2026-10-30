"""Claude-written weekly blog drafts, with guardrails, and the review email.

Posts publish under the attorney's name, so everything the model returns is
validated before it is saved, and the attorney gets a review email first.
"""
import json
import logging
import os
import re
from datetime import date
from html import escape

from flask import current_app

from services import blog
import shared
from blueprints import email_service
from blueprints.practice_areas import PRACTICE_AREAS

log = logging.getLogger(__name__)


class BlogGenerationError(Exception):
    pass


SYSTEM_PROMPT = """You write blog posts for MT Legal, a solo Nashville, Tennessee law practice.

Audience and tone:
- The reader is a worried person looking for help. Use plain English and a warm, client-centered tone. Avoid legalese.
- Cover Tennessee and federal law in general terms only. This is general information, not legal advice for a specific situation.

Hard rules:
- Never promise or predict outcomes.
- Cite a statute or case only if it is well established. Otherwise describe the rule without a number.
- Never mention public defenders or public-defender work.
- Refer to the firm as "MT Legal" or "our office" and never imply more than one attorney.
- No client stories, testimonials, past results or statistics.
- Never call the attorney or firm an "expert", "specialist", "best" or anything similar.
- Do not compare the firm to other lawyers.
- Do not state the law as current beyond what you know. Where it matters, tell the reader that rules can change.

Length and markup:
- Write 600 to 1,000 words.
- Format the body with this markup only: "## " for headings, "- " for bullet items, "1. " for numbered items, and blank lines between paragraphs. No bold, no HTML, no other markdown. The title and summary are plain text.

Formats:
- article: an explainer that walks the reader through the topic.
- qa: a short introduction, then 5 to 7 questions a person would actually ask. Write each question as a "## " heading ending in "?", with its answer right below it. Do not repeat a question or answer anywhere else.
- tips: a plain list of practical steps the reader can take, with a short introduction.

Return ONLY JSON, with no other text, in exactly this shape:
{"title": "...", "summary": "...", "body": "..."}"""

# Matched against lowercased text with whitespace, hyphens and apostrophes
# normalized. Bare "guarantee" stays allowed: "constitutional guarantee" is fine.
_BANNED = tuple(re.compile(rf"\b{p}\b") for p in (
    r"public defenders?",
    r"guaranteed (results?|outcomes?)",
    r"we guarantee",
    r"our (attorneys?|lawyers?)",
    r"our (team of|legal team|associates|partners)",
    r"we('ll| will| can) (get|win|beat)",
))
_MIN_QA_QUESTIONS = 3


def next_topic(area: str):
    for t in blog.load_topics():
        if isinstance(t, dict) and t.get("area") == area and not t.get("used"):
            return t
    return None


ESTATE_ABOUT = ("Wills, trusts, powers of attorney and business succession, including "
                "crypto and other digital assets.")


def _user_prompt(area, fmt, topic, past_titles):
    about = ESTATE_ABOUT if area == "estate-business" else PRACTICE_AREAS[area]["tagline"]
    lines = [
        f"Practice area: {blog.area_label(area)} ({about})",
        f"Format: {fmt}",
        f"Topic: {topic}" if topic else "Topic: pick a fresh topic that fits the practice area.",
        f"Today's date: {date.today().isoformat()}",
    ]
    if past_titles:
        lines.append("Do not repeat or closely overlap these earlier titles:")
        lines += [f"- {t}" for t in past_titles]
    return "\n".join(lines)


def _parse_json(text):
    text = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise BlogGenerationError("The model did not return valid JSON.") from e
    if not isinstance(data, dict):
        raise BlogGenerationError("The model's JSON was not an object.")
    return data


def generate_post(area, fmt, topic, past_titles):
    if area not in PRACTICE_AREAS:
        raise BlogGenerationError(f"Unknown area: {area}")
    try:
        resp = shared.get_anthropic_client().messages.create(
            model=shared.BLOG_MODEL,
            # Thinking counts toward max_tokens, so leave room for it and the post.
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_prompt(area, fmt, topic, past_titles)}],
        )
        stop_reason = resp.stop_reason
        # The reply can start with a thinking block, so pick out the text.
        text = "".join(b.text for b in resp.content if b.type == "text")
    except Exception as e:  # API errors, missing key, malformed response
        raise BlogGenerationError(f"Claude request failed: {e}") from e
    if stop_reason in ("refusal", "max_tokens"):
        raise BlogGenerationError(f"Claude did not finish the post: {stop_reason}.")
    return validate(_parse_json(text), fmt)


def validate(data, fmt):
    if not isinstance(data, dict):
        raise BlogGenerationError("Post data must be an object.")
    title, summary, body = (data.get(k) for k in ("title", "summary", "body"))
    if not all(isinstance(v, str) for v in (title, summary, body)):
        raise BlogGenerationError("Title, summary and body must be text.")
    title, summary, body = title.strip(), summary.strip(), body.strip()
    if not 1 <= len(title) <= 90:
        raise BlogGenerationError("Title must be 1-90 characters.")
    if not 1 <= len(summary) <= 300:
        raise BlogGenerationError("Summary must be 1-300 characters.")
    n = len(body.split())
    if not 450 <= n <= 1300:
        raise BlogGenerationError(f"Body is {n} words; it must be 450-1,300.")

    if any("**" in v or "<" in v for v in (title, summary, body)):
        raise BlogGenerationError("Post contains bold markup or HTML.")
    if fmt == "qa" and len(blog.faq_entries(blog.parse_body(body))) < _MIN_QA_QUESTIONS:
        raise BlogGenerationError(
            f'A qa post needs at least {_MIN_QA_QUESTIONS} answered "## " headings ending in "?".')

    haystack = " ".join([title, summary, body]).lower()
    haystack = re.sub(r"[\s\u00a0\u2010-\u2015-]+", " ", haystack)
    haystack = re.sub(r"[\u2018\u2019\u02bc]", "'", haystack)
    for pattern in _BANNED:
        found = pattern.search(haystack)
        if found:
            raise BlogGenerationError(f"Post contains a banned phrase: {found.group(0)!r}.")
    return {"title": title, "summary": summary, "body": body}


def send_review_email(post):
    # Read these directly: email_service's helpers fall back to defaults, and a
    # send to the wrong inbox or with dead links would still start the 48 hours.
    to = os.getenv("FIRM_EMAIL", "").strip()
    website = os.getenv("FIRM_WEBSITE", "").strip()
    if not to or not website:
        missing = "FIRM_EMAIL" if not to else "FIRM_WEBSITE"
        log.error("Blog review email not sent for %s: %s is not set", post.get("slug"), missing)
        return False
    with current_app.app_context():
        token = blog.make_review_token(post)
    base = website.rstrip("/") + "/blog/review/" + token
    links = {"Publish now": base + "/publish", "Pull this post": base + "/pull",
             "Review or edit": base}
    note = "Publishes automatically 48 hours after this email unless you pull it."
    title, summary, body = post.get("title", ""), post.get("summary", ""), post.get("body", "")

    paras = "".join(f"<p>{escape(c).replace(chr(10), '<br>')}</p>"
                    for c in re.split(r"\n\s*\n", body) if c.strip())
    link_html = "".join(f'<li><a href="{escape(u, quote=True)}">{escape(label)}</a></li>'
                        for label, u in links.items())
    html = (f"<h2>{escape(title)}</h2><p><em>{escape(summary)}</em></p>{paras}"
            f"<p><strong>{escape(note)}</strong></p><ul>{link_html}</ul>")
    text = "\n\n".join([title, summary, body, note] + [f"{k}: {u}" for k, u in links.items()])
    return email_service._send(to, "MT Legal", f"Blog draft for review: {title}", html, text)
