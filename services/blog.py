"""File-based storage for the weekly blog: posts, topic queue and rotation state.

Everything lives under shared.BLOG_DIR (read at call time so tests can
monkeypatch it):
    posts/<slug>.json   one record per post
    topics.json         the topic queue
    state.json          rotation / attempt bookkeeping
"""
import re
import secrets
import threading
from datetime import datetime, timedelta

import hmac

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

import shared
from blueprints.practice_areas import PRACTICE_AREAS
from services.storage import read_json, write_json

BLOG_AREAS = ("criminal-defense", "stablecoins", "rwa-tokenization", "civil-rights", "estate-business")
FORMATS = ("article", "qa", "tips")
ROTATION = ("criminal-defense", "stablecoins", "civil-rights", "estate-business",
            "criminal-defense", "rwa-tokenization", "civil-rights", "estate-business")
REVIEW_WINDOW = timedelta(hours=48)
REVIEW_TOKEN_MAX_AGE = 7 * 24 * 3600  # seconds; read at call time

_SLUG_RE = re.compile(r"^[a-z0-9-]{1,80}$")
_NUMBERED_RE = re.compile(r"\d+\.\s+")
_DEFAULT_STATE = {"step": 0, "week": None, "attempts": 0, "attempts_week": None}

# Serializes read-check-write on post and topic files between request threads
# and the scheduler thread. Never hold it across a call to Anthropic or SendGrid.
POST_LOCK = threading.RLock()


# The estate topics are stored under the estate-business slug, but readers see
# them as estate planning and are sent to the Estate & Family Planning page.
ESTATE_LABEL = "Estate Planning"
ESTATE_PAGE = "family-law"


def area_label(slug: str) -> str:
    """The name readers see for a blog area ("" for an unknown area)."""
    if slug == "estate-business":
        return ESTATE_LABEL
    return PRACTICE_AREAS.get(slug, {}).get("name", "")


def area_page(slug: str) -> str:
    """The practice page a blog area links to."""
    return ESTATE_PAGE if slug == "estate-business" else slug


def _posts_dir():
    return shared.BLOG_DIR / "posts"


# ── Posts ─────────────────────────────────────────────────────────────────────

def load_post(slug: str):
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        return None
    data = read_json(_posts_dir() / f"{slug}.json", None)
    return data if isinstance(data, dict) else None


def save_post(post: dict) -> None:
    slug = post.get("slug")
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValueError("invalid post slug")
    write_json(_posts_dir() / f"{slug}.json", post, ensure_ascii=False)


def list_posts(status: str | None = None) -> list:
    posts = []
    d = _posts_dir()
    if d.is_dir():
        for f in d.glob("*.json"):
            p = load_post(f.stem)
            if p and (status is None or p.get("status") == status):
                posts.append(p)
    posts.sort(key=lambda p: p.get("published_at") or p.get("created_at") or "", reverse=True)
    return posts


def published_posts(area: str | None = None) -> list:
    return [p for p in list_posts("published") if area is None or p.get("area") == area]


def make_slug(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:70].strip("-") or "post"
    slug, n = base, 2
    while (_posts_dir() / f"{slug}.json").exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def new_post(title, summary, body, area, fmt, topic_id=None, now=None) -> dict:
    now = now or datetime.now()
    return {
        "slug": make_slug(title),
        "title": title,
        "summary": summary,
        "body": body,
        "area": area,
        "format": fmt,
        "status": "draft",
        "topic_id": topic_id,
        "created_at": now.isoformat(),
        "review_email_sent_at": None,
        "publish_at": None,
        "published_at": None,
        "updated_at": now.isoformat(),
        "review_token_id": secrets.token_hex(8),
    }


# ── Review tokens and status changes ──────────────────────────────────────────

def _review_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="blog-review")


def make_review_token(post: dict) -> str:
    return _review_serializer().dumps({"s": post["slug"], "r": post["review_token_id"]})


def read_review_token(token: str):
    """Return the post a valid, unexpired token points at, else None."""
    try:
        data = _review_serializer().loads(token, max_age=REVIEW_TOKEN_MAX_AGE)
    except BadData:
        return None
    if not isinstance(data, dict):
        return None
    post = load_post(data.get("s"))
    rid = data.get("r")
    stored = post.get("review_token_id") if post else None
    if (not post or not isinstance(rid, str) or not isinstance(stored, str)
            or not hmac.compare_digest(rid.encode(), stored.encode())):
        return None
    return post


def publish(slug: str, now: datetime | None = None) -> bool:
    with POST_LOCK:
        post = load_post(slug)
        if not post or post.get("status") != "draft":
            return False
        now = now or datetime.now()
        post["status"] = "published"
        post["published_at"] = now.isoformat()
        post["updated_at"] = now.isoformat()
        save_post(post)
        return True


def pull(slug: str) -> bool:
    with POST_LOCK:
        post = load_post(slug)
        if not post or post.get("status") != "draft":
            return False
        post["status"] = "pulled"
        post["updated_at"] = datetime.now().isoformat()
        save_post(post)
        topic_id = post.get("topic_id")
        if topic_id:
            topics = load_topics()
            changed = False
            for t in topics:
                if isinstance(t, dict) and t.get("id") == topic_id and t.get("used"):
                    t["used"] = False
                    changed = True
            if changed:
                save_topics(topics)
        return True


def takedown(slug: str) -> bool:
    """Take a published post off the site. Unlike pull, its topic stays used."""
    with POST_LOCK:
        post = load_post(slug)
        if not post or post.get("status") != "published":
            return False
        post["status"] = "pulled"
        post["updated_at"] = datetime.now().isoformat()
        save_post(post)
        return True


def update_post(slug: str, title: str, summary: str, body: str) -> dict:
    title, summary, body = (title or "").strip(), (summary or "").strip(), (body or "").strip()
    with POST_LOCK:
        post = load_post(slug)
        if not post:
            raise ValueError("Post not found.")
        if not title:
            raise ValueError("Title can't be empty.")
        if not body:
            raise ValueError("Body can't be empty.")
        # Only the edited fields change; status and publish fields stay as read
        # here, under the lock, so a concurrent publish can't be reverted.
        post.update(title=title, summary=summary, body=body, updated_at=datetime.now().isoformat())
        save_post(post)
        return post


# ── Body format ───────────────────────────────────────────────────────────────

def parse_body(text: str) -> list:
    """Turn the plain-text body into blocks: h2, ul, ol or p. No other markup.

    A heading ends at its line, runs of "- " or "N. " lines are lists, and other
    consecutive lines join into a paragraph. Blank lines end a paragraph only,
    so a list stays one list (and keeps counting) when its items are spaced out.
    """
    blocks, para = [], []

    def end_paragraph():
        if para:
            blocks.append({"type": "p", "text": " ".join(para)})
            para.clear()

    for line in (text or "").splitlines():
        line = line.strip()
        number = _NUMBERED_RE.match(line)
        if line.startswith("## "):
            end_paragraph()
            blocks.append({"type": "h2", "text": line[3:].strip()})
        elif line.startswith("- ") or number:
            end_paragraph()
            kind, item = ("ol", line[number.end():]) if number else ("ul", line[2:].strip())
            if not (blocks and blocks[-1]["type"] == kind):
                blocks.append({"type": kind, "items": []})
            blocks[-1]["items"].append(item)
        elif line:
            para.append(line)
        else:
            end_paragraph()
    end_paragraph()
    return blocks


def faq_entries(blocks: list) -> list:
    """Question/answer pairs from parsed blocks: each h2 ending in "?" and the
    blocks under it. The body is the only source, so edits reach the FAQ data."""
    entries, answer = [], None
    for block in blocks:
        if block["type"] == "h2":
            answer = [] if block["text"].endswith("?") else None
            if answer is not None:
                entries.append((block["text"], answer))
        elif answer is not None:
            answer.append(block["text"] if block["type"] == "p" else " ".join(block["items"]))
    return [{"q": q, "a": " ".join(parts)} for q, parts in entries if parts]


# ── Topics ────────────────────────────────────────────────────────────────────

def load_topics() -> list:
    data = read_json(shared.BLOG_DIR / "topics.json", [])
    return data if isinstance(data, list) else []


def save_topics(topics) -> None:
    write_json(shared.BLOG_DIR / "topics.json", topics, ensure_ascii=False)


def add_topic(area: str, title: str) -> dict:
    title = (title or "").strip()
    if area not in BLOG_AREAS:
        raise ValueError("unknown area")
    if not title or len(title) > 200:
        raise ValueError("title must be 1-200 characters")
    topic = {"id": secrets.token_hex(6), "area": area, "title": title, "used": False}
    with POST_LOCK:
        topics = load_topics()
        topics.append(topic)
        save_topics(topics)
    return topic


# ── Rotation state ────────────────────────────────────────────────────────────

def load_state() -> dict:
    data = read_json(shared.BLOG_DIR / "state.json", None)
    state = dict(_DEFAULT_STATE)
    if isinstance(data, dict):
        state.update(data)
    return state


def save_state(state) -> None:
    write_json(shared.BLOG_DIR / "state.json", state, ensure_ascii=False)


def iso_week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


# ── Seed merge ────────────────────────────────────────────────────────────────

def seed_from_repo(now: datetime | None = None) -> None:
    """Merge the versioned seed into BLOG_DIR without overwriting disk edits."""
    now = now or datetime.now()
    shared.BLOG_DIR.mkdir(parents=True, exist_ok=True)
    seed = shared.BLOG_SEED_DIR

    posts = seed / "posts"
    if posts.is_dir():
        for f in sorted(posts.glob("*.json")):
            if not _SLUG_RE.match(f.stem) or (_posts_dir() / f.name).exists():
                continue
            data = read_json(f, None)
            if isinstance(data, dict):
                data["slug"] = f.stem
                if data.get("status") == "published":
                    data["published_at"] = now.isoformat()  # dated when it first goes live
                save_post(data)

    seed_topics = read_json(seed / "topics.json", [])
    if isinstance(seed_topics, list):
        topics = load_topics()
        have = {t.get("id") for t in topics}
        added = [t for t in seed_topics if isinstance(t, dict) and t.get("id") not in have]
        if added:
            save_topics(topics + added)

    if not (shared.BLOG_DIR / "state.json").exists():
        state = dict(_DEFAULT_STATE)
        state["week"] = iso_week(now)  # launch week doesn't generate a draft
        save_state(state)
