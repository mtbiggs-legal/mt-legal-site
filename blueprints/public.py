"""blueprints/public.py — Public-facing pages and lead capture."""

import json
from datetime import datetime
from flask import (
    Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request,
    send_from_directory, url_for,
)

from shared import (
    require_auth, require_attorney, LEADS_DIR, CASE_ATTORNEY_MAP,
    FIRM_NAME, MANAGING_PARTNER, partner_photo_filename,
    get_anthropic_client, MODEL,
    _load_page_visits, _save_page_visits,
)
from blueprints.email_service import send_lead_email
from blueprints.practice_areas import (
    PRACTICE_AREAS, EMERGING_TECH_AREAS, EMERGING_TECH_TOPICS,
)

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
@require_auth
def index():
    return render_template("index.html", areas=PRACTICE_AREAS)


@public_bp.route("/meet-the-firm")
@require_auth
def meet_the_firm():
    return render_template("meet_the_firm.html", all_areas=PRACTICE_AREAS)


# ── Search engines and browsers ───────────────────────────────────────────────

# Public pages listed in sitemap.xml (practice pages are added from the data).
_SITEMAP_ENDPOINTS = (
    "public.index", "public.meet_the_firm", "public.emerging_tech", "public.why_nashville",
    "public.case_search", "public.how_it_works", "intake.intake",
)


@public_bp.route("/favicon.ico")
def favicon():
    """Browsers and Google ask for /favicon.ico at the site root."""
    return send_from_directory(current_app.static_folder, "favicon.ico",
                               mimetype="image/vnd.microsoft.icon", max_age=86400)


@public_bp.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Disallow: /portal/", "Disallow: /client-portal", "Disallow: /attorney-portal",
        "Disallow: /client-login", "Disallow: /attorney-login", "Disallow: /research",
        "Disallow: /drafting", "Disallow: /calendar/", "Disallow: /api/",
        "",
        "Sitemap: " + url_for("public.sitemap_xml", _external=True),
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@public_bp.route("/sitemap.xml")
def sitemap_xml():
    urls = [url_for(e, _external=True) for e in _SITEMAP_ENDPOINTS]
    urls += [url_for("public.practice_area", slug=s, _external=True) for s in PRACTICE_AREAS]
    body = "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + body + "</urlset>\n")
    return Response(xml, mimetype="application/xml")


@public_bp.route("/case-search")
@require_auth
def case_search():
    return render_template("case_search.html")


@public_bp.route("/how-it-works")
@require_auth
def how_it_works():
    return render_template("how_it_works.html")


@public_bp.route("/why-nashville")
@require_auth
def why_nashville():
    return render_template("why_nashville.html")


@public_bp.route("/emerging-tech")
@require_auth
def emerging_tech():
    areas = {slug: PRACTICE_AREAS[slug] for slug in EMERGING_TECH_AREAS}
    return render_template("emerging_tech.html", areas=areas, topics=EMERGING_TECH_TOPICS)


# Renamed practice areas: old URLs keep working.
_MOVED_PRACTICE_AREAS = {
    "civil-litigation":         "civil-rights",
    "real-estate-tokenization": "rwa-tokenization",
}


# Practice areas no longer offered: their old pages point to the Emerging Tech hub.
_RETIRED_PRACTICE_AREAS = {"ai-emerging-tech", "defi-digital-assets"}


@public_bp.route("/practice/<slug>")
@require_auth
def practice_area(slug):
    if slug in _RETIRED_PRACTICE_AREAS:
        return redirect(url_for("public.emerging_tech"), 301)
    if slug in _MOVED_PRACTICE_AREAS:
        return redirect(url_for("public.practice_area", slug=_MOVED_PRACTICE_AREAS[slug]), 301)
    area = PRACTICE_AREAS.get(slug)
    if not area:
        abort(404)
    attorney = {
        "name":  MANAGING_PARTNER["name"],
        "role":  MANAGING_PARTNER["title"],
        "blurb": "A client-centered litigator with dedicated support for DeFi and digital assets. "
                 "You work with him directly, start to "
                 "finish — no hand-offs to associates.",
        "photo": partner_photo_filename(),
    }
    return render_template("practice_area.html", area=area, slug=slug,
                           attorney=attorney, all_areas=PRACTICE_AREAS)


@public_bp.route("/capture/lead", methods=["POST"])
@require_auth
def capture_lead():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received."}), 400

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    last_name  = name.split()[-1].replace(" ", "_")
    filename   = f"{timestamp}_{last_name}_lead.json"
    case_type  = data.get("case_type", "")

    record = {
        "timestamp":         timestamp,
        "name":              name,
        "phone":             data.get("phone", ""),
        "email":             data.get("email", ""),
        "case_type":         case_type,
        "source":            data.get("source", ""),
        "notes":             data.get("notes", ""),
        "assigned_attorney": CASE_ATTORNEY_MAP.get(case_type, MANAGING_PARTNER["username"]),
    }

    with open(LEADS_DIR / filename, "w") as f:
        json.dump(record, f, indent=2)

    # Auto-reply email: warm acknowledgment + booking link
    if record.get("email", "").strip():
        try:
            send_lead_email(
                name              = name,
                email             = record["email"],
                case_type         = case_type,
                assigned_attorney = record["assigned_attorney"],
            )
        except Exception:
            pass

    return jsonify({"success": True})


@public_bp.route("/follow-up/schedule", methods=["POST"])
@require_auth
def follow_up_schedule():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received."}), 400

    name  = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    if not name or not phone:
        return jsonify({"error": "Name and phone number are required."}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    last_name  = name.split()[-1].replace(" ", "_")
    filename   = f"{timestamp}_{last_name}_followup.json"
    case_type  = data.get("case_type", "")

    record = {
        "timestamp":         timestamp,
        "type":              "follow_up",
        "name":              name,
        "phone":             phone,
        "case_type":         case_type,
        "message":           data.get("message", ""),
        "assigned_attorney": CASE_ATTORNEY_MAP.get(case_type, MANAGING_PARTNER["username"]),
    }

    with open(LEADS_DIR / filename, "w") as f:
        json.dump(record, f, indent=2)

    return jsonify({"success": True})


# How many prior turns of the public chat to replay to the model.
_CHAT_HISTORY_TURNS = 12


@public_bp.route("/chat/message", methods=["POST"])
@require_auth
def chat_message():
    """Public marketing-site chat widget.

    Deliberately anonymous: it never looks up or writes to a client account.
    Logged-in clients talk to their attorney through /portal/client/message,
    which authenticates them via the session instead of a posted username.
    """
    data = request.get_json() or {}
    text = data.get("message", "").strip()
    if not text:
        return jsonify({"error": "Message is empty."}), 400

    system = (
        f"You are a helpful legal assistant for {FIRM_NAME}, a Nashville, Tennessee law "
        f"practice led by {MANAGING_PARTNER['display']}. It is a client-centered firm "
        "with dedicated support for DeFi and digital-asset operations: digital asset estate and "
        "future planning, stablecoins and agentic payments, and real-world asset tokenization. "
        "It also provides traditional practice: criminal defense, civil rights litigation, "
        "estate and family planning, and personal injury, across Nashville and Middle "
        "Tennessee. The attorney is a litigator who has been involved in the crypto space since "
        "2017, and the firm focuses on representing individuals against bigger players. A core "
        "belief of the firm is that client representation and decentralization share one idea: protecting the individual, their privacy, and their "
        "fundamental rights from overreaching power. You help answer "
        "general legal questions and direct "
        "people to schedule a consultation for specific legal advice (a brief intro call is "
        "at no cost; the full consultation has a fee credited toward the retainer if they "
        "hire the firm). Never call the consultation free. Always recommend "
        "consulting with an attorney for personalized advice."
    )

    # Replay the conversation so follow-up questions keep their context.
    turns = []
    for turn in (data.get("history") or [])[-_CHAT_HISTORY_TURNS:]:
        role    = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            turns.append({"role": role, "content": content})
    # The model requires an alternating transcript that starts with the user.
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    turns.append({"role": "user", "content": text})

    try:
        ai      = get_anthropic_client()
        message = ai.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=turns,
        )
        return jsonify({"success": True, "reply": message.content[0].text})
    except Exception:
        # Log the detail for us; never show provider errors to site visitors.
        current_app.logger.exception("Website chat failed")
        return jsonify({"error": "The assistant is unavailable right now."}), 500


@public_bp.route("/api/track-visit", methods=["POST"])
@require_auth
def api_track_visit():
    data = request.get_json() or {}
    page = data.get("page", "unknown")
    visits = _load_page_visits()
    visits[page] = visits.get(page, 0) + 1
    _save_page_visits(visits)
    return jsonify({"success": True})


@public_bp.route("/api/page-visits")
@require_attorney
def api_page_visits():
    """Marketing analytics — attorney dashboard only, not public."""
    return jsonify(_load_page_visits())
