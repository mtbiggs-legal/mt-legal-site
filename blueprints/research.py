"""blueprints/research.py — All legal research: the attorney research page, the
attorney portal's research tools (analyze, authority, issue-spot, draft,
save-draft, save-report), and client portal research.
"""

import html
from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, request, jsonify, session
from werkzeug.utils import secure_filename
import anthropic
from services import billing

from shared import (
    require_auth, require_attorney, require_client, RESEARCH_HISTORY_DIR, MODEL,
    DOCS_CATEGORIES, get_anthropic_client,
)
from services.storage import (
    load_client, save_client, _log_activity, _log_token_usage, _client_docs_dir,
    recalc_hours, safe_username,
    write_json,
)
from services.accounts import load_client_for_attorney
from services.documents import extract_document_text
from services.prompts import (
    CIVIL_SYSTEM_PROMPT, RESEARCH_ANALYZE_PROMPT, RESEARCH_AUTHORITY_PROMPT, SYSTEM_PROMPTS,
    draft_prompt, issuespot_prompt,
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
            write_json(RESEARCH_HISTORY_DIR / f"{ts}_{slug}.json",
                       {"timestamp": ts, "case_type": case_type,
                        "question": question, "memo": memo_html})
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


# ── Attorney portal research (analyze, authority, issue-spot, draft) ─────────

@research_bp.route("/portal/attorney/research/analyze", methods=["POST"])
@require_attorney
def research_analyze():
    data        = request.get_json() or {}
    legal_issue = data.get("legal_issue", "").strip()
    if not legal_issue:
        return jsonify({"error": "No case summary provided."}), 400
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=1500,
            system=RESEARCH_ANALYZE_PROMPT,
            messages=[{"role": "user", "content": f"Case summary:\n{legal_issue}"}],
        )
        _log_token_usage(session.get("username", "unknown"), "Legal Issue Analysis", msg.usage)
        return jsonify({"success": True, "issues": msg.content[0].text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@research_bp.route("/portal/attorney/research/authority", methods=["POST"])
@require_attorney
def research_authority():
    data        = request.get_json() or {}
    issues_text = data.get("issues", "").strip()
    case_type   = data.get("case_type", "Criminal Defense")
    if not issues_text:
        return jsonify({"error": "No issues provided."}), 400
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=3000,
            system=RESEARCH_AUTHORITY_PROMPT,
            messages=[{"role": "user", "content": f"Case Type: {case_type}\n\nIdentified Issues:\n{issues_text}"}],
        )
        _log_token_usage(session.get("username", "unknown"), "Legal Authority Research", msg.usage)
        return jsonify({"success": True, "memo": msg.content[0].text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@research_bp.route("/portal/attorney/research/issue-spot", methods=["POST"])
@require_attorney
def research_issue_spot():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    category = data.get("category", "").strip()
    filename = data.get("filename", "").strip()
    if not all([username, category, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    case_type = client.get("case_type", "Civil Litigation")
    text, err = extract_document_text(username, category, filename)
    if err and not text:
        return jsonify({"error": err}), 400
    if not text or not text.strip():
        return jsonify({"error": "Could not extract text from this document."}), 400
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=2000,
            system=issuespot_prompt(case_type),
            messages=[{"role": "user", "content": f"Document: {filename}\nCase Type: {case_type}\n\n{text[:8000]}"}],
        )
        _log_token_usage(session.get("username", "unknown"), "Document Issue Spotting", msg.usage)
        return jsonify({"success": True, "issues": msg.content[0].text, "filename": filename})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@research_bp.route("/portal/attorney/research/draft", methods=["POST"])
@require_attorney
def research_draft():
    data         = request.get_json() or {}
    motion_type  = data.get("motion_type", "Motion to Suppress").strip()
    issues_text  = data.get("issues", "").strip()
    case_context = data.get("case_context", "").strip()
    username     = data.get("username", "").strip()
    if not issues_text:
        return jsonify({"error": "No issues to draft from."}), 400
    case_type = "Civil Litigation"
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        case_type = client.get("case_type", "Civil Litigation")
    try:
        ai = get_anthropic_client()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    user_msg = (
        f"Motion/Document Type: {motion_type}\n\n"
        f"Practice Area: {case_type}\n\n"
        f"Case Context:\n{case_context}\n\n"
        f"Identified Issues:\n{issues_text}"
    )
    try:
        msg = ai.messages.create(
            model=MODEL, max_tokens=4096,
            system=draft_prompt(case_type),
            messages=[{"role": "user", "content": user_msg}],
        )
        _log_token_usage(session.get("username", "unknown"), "Motion Draft Generation", msg.usage)
        return jsonify({"success": True, "draft": msg.content[0].text, "motion_type": motion_type})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@research_bp.route("/portal/attorney/research/save-draft", methods=["POST"])
@require_attorney
def research_save_draft():
    data        = request.get_json() or {}
    username    = data.get("username", "").strip()
    category    = data.get("category", "Motions").strip()
    draft_text  = data.get("draft", "").strip()
    filename    = data.get("filename", "").strip()
    motion_type = data.get("motion_type", "motion").strip()
    if not all([username, draft_text, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if category not in DOCS_CATEGORIES:
        category = "Motions"
    dest_dir  = _client_docs_dir(username, category)
    safe_name = secure_filename(filename)
    if not safe_name.lower().endswith(".txt"):
        safe_name += ".txt"
    dest = dest_dir / safe_name
    stem, n = Path(safe_name).stem, 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}.txt"
        n += 1
    dest.write_text(draft_text, encoding="utf-8")

    today     = datetime.now().strftime("%Y-%m-%d")
    entry_ai  = {"date": today, "hours": 0.2,
                 "note": f"AI Research — {motion_type} ({dest.name})", "type": "research_ai",
                 "category": "Research"}
    entry_rev = {"date": today, "hours": 0.2,
                 "note": f"Attorney Review — {motion_type} ({dest.name})", "type": "research_review",
                 "category": "Drafting"}
    client.setdefault("billing_log", []).extend([entry_ai, entry_rev])
    recalc_hours(client)
    save_client(client)
    billing_entry = entry_ai

    return jsonify({
        "success":        True,
        "filename":       dest.name,
        "category":       category,
        "billing_entry":  billing_entry,
        "billing_entry2": entry_rev,
        "total_hours":    client["hours_billed"],
    })


@research_bp.route("/portal/attorney/research/save-report", methods=["POST"])
@require_attorney
def research_save_report():
    data        = request.get_json() or {}
    username    = safe_username(data.get("username", ""))
    report_type = data.get("report_type", "").strip()
    text        = data.get("text", "").strip()
    if not all([username, report_type, text]):
        return jsonify({"error": "Missing parameters."}), 400
    if report_type not in ("analysis", "authority"):
        return jsonify({"error": "Invalid report_type. Must be 'analysis' or 'authority'."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    category = "Litigation Drafts"
    if report_type == "analysis":
        label  = "AI legal issues analysis"
        prefix = "legal_issues"
    else:
        label  = "AI legal authority memo"
        prefix = "legal_authority"
    ts        = datetime.now().strftime("%Y%m%d")
    dest_dir  = _client_docs_dir(username, category)
    safe_name = f"{prefix}_{ts}.txt"
    dest      = dest_dir / safe_name
    stem, n   = Path(safe_name).stem, 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}.txt"
        n += 1
    dest.write_text(text, encoding="utf-8")
    today     = datetime.now().strftime("%Y-%m-%d")
    entry_ai  = {"date": today, "hours": 0.2,
                 "note": f"AI Research — {label} ({dest.name})", "type": "research_ai",
                 "category": "Research"}
    entry_rev = {"date": today, "hours": 0.2,
                 "note": f"Attorney Review — {label} ({dest.name})", "type": "research_review",
                 "category": "Drafting"}
    client.setdefault("billing_log", []).extend([entry_ai, entry_rev])
    recalc_hours(client)
    client.setdefault("activity_log", []).append({
        "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "action_type": "time_logged",
        "description": f"0.4 hrs — {label} saved as \"{dest.name}\".",
    })
    save_client(client)
    return jsonify({
        "success":        True,
        "filename":       dest.name,
        "category":       category,
        "billing_entry":  entry_ai,
        "billing_entry2": entry_rev,
        "total_hours":    client["hours_billed"],
    })
