"""blueprints/research.py — Public legal research routes (attorney/public) and client portal research.

Attorney portal research routes (analyze, authority, issue-spot, draft, save-draft, save-report)
are handled by blueprints/portal_attorney.py to keep the full prompt dictionaries and billing
logic together with the rest of the attorney portal.
"""

import html
import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session
import anthropic
import billing

from shared import (
    require_auth, require_attorney, require_client,
    RESEARCH_HISTORY_DIR, MODEL,
    get_anthropic_client, load_client, save_client, _log_activity, _log_token_usage,
    _client_docs_dir, recalc_hours,
    SYSTEM_PROMPTS, CIVIL_SYSTEM_PROMPT,
)

research_bp = Blueprint("research", __name__)


def _pick_prompt(case_type: str) -> str:
    return SYSTEM_PROMPTS.get(case_type, CIVIL_SYSTEM_PROMPT)


# ── Attorney research page (not linked from the public site) ──────────────────────────────────────────

@research_bp.route("/research")
@require_auth
@require_attorney
def research():
    return render_template("research.html")


@research_bp.route("/research/query", methods=["POST"])
@require_auth
@require_attorney
def research_query():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received."}), 400

    question  = data.get("question", "").strip()
    case_type = data.get("case_type", "Criminal Defense")
    if not question:
        return jsonify({"error": "Please enter a research question."}), 400

    try:
        client = get_anthropic_client()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_pick_prompt(case_type),
            messages=[{"role": "user", "content": question}],
        )
        memo_html = message.content[0].text
        try:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = case_type.lower().replace(" ", "_")
            with open(RESEARCH_HISTORY_DIR / f"{ts}_{slug}.json", "w") as f:
                json.dump({"timestamp": ts, "case_type": case_type,
                           "question": question, "memo": memo_html}, f, indent=2)
        except Exception:
            pass
        return jsonify({"success": True, "memo": memo_html})
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Please check your .env file."}), 401
    except anthropic.APIError as e:
        return jsonify({"error": f"API error: {str(e)}"}), 500


# ── Client portal research ────────────────────────────────────────────────────

@research_bp.route("/portal/client/research-query", methods=["POST"])
@require_client
def client_research_query():
    data      = request.get_json() or {}
    username  = session.get("username", "")
    question  = data.get("question", "").strip()
    case_type = data.get("case_type", "")
    if not question:
        return jsonify({"error": "Question is required."}), 400
    client_rec = load_client(username)
    if not case_type and client_rec:
        case_type = client_rec.get("case_type", "")
    try:
        ai = get_anthropic_client()
        msg = ai.messages.create(
            model=MODEL, max_tokens=2048,
            system=_pick_prompt(case_type),
            messages=[{"role": "user", "content": question}],
        )
        _log_token_usage(username, "client_research", msg.usage)
        return jsonify({"success": True, "memo": msg.content[0].text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@research_bp.route("/portal/client/research-save", methods=["POST"])
@require_client
def client_research_save():
    data     = request.get_json() or {}
    username = session.get("username", "")
    memo     = data.get("memo", "").strip()
    question = data.get("question", "")
    if not memo:
        return jsonify({"error": "No memo to save."}), 400

    now_ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{now_ts}_research.html"
    doc_dir  = _client_docs_dir(username, "Research")
    (doc_dir / filename).write_text(
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<title>Research — {now_ts}</title></head><body>"
        f"<p><strong>Question:</strong> {html.escape(question)}</p>{memo}</body></html>",
        encoding="utf-8",
    )

    # The portal tells the client this costs 0.2 hrs before they confirm — bill it.
    client_rec = load_client(username)
    if client_rec:
        client_rec.setdefault("billing_log", []).append({
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0.2,
            "note":     f"Client research saved — {question[:60]}",
            "type":     "research_client",
            "category": "Research",
        })
        recalc_hours(client_rec)
        save_client(client_rec)

    _log_activity(username, "research_saved", f"Research saved by client ({filename})")
    return jsonify({"success": True, "filename": filename,
                    "billed_hours": billing.billed_hours(billing.load_ledger(username))})
