"""blueprints/blog.py: public blog index and post pages."""

from datetime import datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, make_response, render_template, request, url_for

from services import blog
from blueprints.practice_areas import PRACTICE_AREAS
from shared import FIRM_NAME, require_auth

blog_bp = Blueprint("blog", __name__)

FORMAT_LABELS = {"article": "Article", "qa": "Q&A", "tips": "Tips"}


@blog_bp.route("/blog")
@require_auth
def index():
    all_posts = blog.published_posts()
    present = {p.get("area") for p in all_posts}
    areas = [{"slug": s, "name": blog.area_label(s)}
             for s in blog.BLOG_AREAS if s in present and s in PRACTICE_AREAS]
    area = request.args.get("area", "")
    selected = area if any(a["slug"] == area for a in areas) else ""
    posts = [p for p in all_posts if p.get("area") == selected] if selected else all_posts
    return render_template("blog_index.html", posts=posts, areas=areas, selected=selected,
                           area_names={a["slug"]: a["name"] for a in areas},
                           format_labels=FORMAT_LABELS)


def _rfc822(iso):
    try:
        # Stored times are naive server-local; astimezone() attaches that zone.
        return format_datetime(datetime.fromisoformat(iso).astimezone())
    except (TypeError, ValueError, OverflowError, OSError):
        return None


@blog_bp.route("/blog/feed.xml")
@require_auth
def feed():
    items = []
    for p in blog.published_posts()[:20]:
        link = escape(url_for("blog.post", slug=p["slug"], _external=True))
        pub = _rfc822(p.get("published_at"))
        items.append(
            "    <item>\n"
            f"      <title>{escape(p.get('title', ''))}</title>\n"
            f"      <link>{link}</link>\n"
            f'      <guid isPermaLink="true">{link}</guid>\n'
            + (f"      <pubDate>{pub}</pubDate>\n" if pub else "")
            + f"      <description>{escape(p.get('summary', ''))}</description>\n"
            "    </item>\n")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<rss version="2.0">\n  <channel>\n'
           f"    <title>{escape(FIRM_NAME)} Blog</title>\n"
           f"    <link>{escape(url_for('blog.index', _external=True))}</link>\n"
           f"    <description>Legal insights from {escape(FIRM_NAME)}.</description>\n"
           + "".join(items) + "  </channel>\n</rss>\n")
    return Response(xml, mimetype="application/rss+xml")


@blog_bp.route("/blog/<slug>")
@require_auth
def post(slug):
    p = blog.load_post(slug)
    if not p or p.get("status") != "published":
        abort(404)
    blocks = blog.parse_body(p.get("body", ""))
    return render_template("blog_post.html", post=p, blocks=blocks,
                           faq=blog.faq_entries(blocks) if p.get("format") == "qa" else [],
                           area_name=blog.area_label(p.get("area")),
                           area_page=blog.area_page(p.get("area")),
                           area_page_name=PRACTICE_AREAS.get(blog.area_page(p.get("area")), {}).get("name", ""),
                           format_label=FORMAT_LABELS.get(p.get("format"), "Article"))


# ── Review links (emailed to the attorney) ────────────────────────────────────

ACTION_TEXT = {
    "publish": "This will publish the post to the blog now.",
    "pull": "This will pull the post. Nothing goes up this week.",
}
INVALID_MSG = "This review link has expired or is no longer valid."
SPENT_MSG = "This draft was already published or pulled."
PULLED_MSG = "Pulled. Nothing goes up this week."
TAKEN_DOWN_MSG = "Taken down. The post is no longer on the site."


def _review_page(template, status=200, **ctx):
    resp = make_response(render_template(template, **ctx), status)
    resp.headers["X-Robots-Tag"] = "noindex"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _invalid():
    return _review_page("blog_action.html", 404, heading="Link not valid", message=INVALID_MSG)


@blog_bp.route("/blog/review/<token>/<any(publish,pull):action>", methods=["GET", "POST"])
@require_auth
def review_confirm(token, action):
    p = blog.read_review_token(token)
    if not p:
        return _invalid()
    if p.get("status") != "draft":
        return _review_page("blog_action.html", heading=p.get("title", ""), message=SPENT_MSG)
    if request.method == "GET":
        # Never changes state: email scanners and link previews fetch GETs.
        return _review_page("blog_action.html", heading=p["title"], message=ACTION_TEXT[action],
                            confirm_label="Publish" if action == "publish" else "Pull this post",
                            form_action=request.path)
    ok = blog.publish(p["slug"]) if action == "publish" else blog.pull(p["slug"])
    if not ok:
        return _review_page("blog_action.html", heading=p["title"], message=SPENT_MSG)
    return _review_page("blog_action.html", heading=p["title"],
                        message="Published." if action == "publish" else PULLED_MSG)


@blog_bp.route("/blog/review/<token>", methods=["GET", "POST"])
@require_auth
def review_edit(token):
    p = blog.read_review_token(token)
    if not p:
        return _invalid()
    if p.get("status") == "pulled":
        return _review_page("blog_action.html", 410, heading=p.get("title", ""),
                            message="This post was pulled. The link is no longer active.")

    def page(post, notice="", error="", status=200, form=None):
        return _review_page(
            "blog_review.html", status, post=post, notice=notice, error=error,
            form=form or post, areas=blog.BLOG_AREAS,
            area_names={s: blog.area_label(s) or s for s in blog.BLOG_AREAS},
            form_action=request.path)

    if request.method == "GET":
        return page(p)

    op = request.form.get("op", "")
    submitted = {k: request.form.get(k, "") for k in ("title", "summary", "body")}
    is_draft = p.get("status") == "draft"

    if op == "add_topic":
        try:
            blog.add_topic(request.form.get("area", ""), request.form.get("topic_title", ""))
        except ValueError as e:
            return page(p, error=str(e), status=400)
        return page(p, notice="Topic idea added.")
    if op in ("publish", "pull") and not is_draft:
        return page(p, error=SPENT_MSG, status=409, form=submitted)
    if op == "takedown":
        if not blog.takedown(p["slug"]):
            return page(p, error="Only a published post can be taken down.", status=409,
                        form=submitted)
        return _review_page("blog_action.html", heading=p["title"], message=TAKEN_DOWN_MSG)
    if op == "pull":
        if not blog.pull(p["slug"]):
            return _review_page("blog_action.html", 409, heading=p["title"], message=SPENT_MSG)
        return _review_page("blog_action.html", heading=p["title"], message=PULLED_MSG)
    if op in ("save", "publish"):
        try:
            updated = blog.update_post(p["slug"], **submitted)
        except ValueError as e:
            return page(p, error=str(e), status=400, form=submitted)
        if op == "publish":
            if not blog.publish(p["slug"]):
                return page(updated, error=SPENT_MSG, status=409)
            return _review_page("blog_action.html", heading=updated["title"], message="Published.")
        return page(updated, notice="Saved.")
    return page(p, error="Unknown action.", status=400)
