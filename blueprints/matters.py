"""blueprints/matters.py — list, open, switch, close and reopen a client's matters."""

from flask import Blueprint, jsonify, request, session

from shared import require_attorney
from services import audit, matters, storage
from services.accounts import load_client_for_attorney
from services.conflicts import clean_names, record_check, redact_hits, hit_message

matters_bp = Blueprint("matters", __name__)


@matters_bp.route("/portal/attorney/matters/<username>")
@require_attorney
def matters_list(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    return jsonify({"matters": matters.list_for(client["username"])})


@matters_bp.route("/portal/attorney/matters/open", methods=["POST"])
@require_attorney
def matters_open():
    """A new matter for an existing client: runs a conflict check on the new
    opposing parties and makes the matter current."""
    data   = request.get_json(silent=True) or {}
    client = load_client_for_attorney(str(data.get("username") or ""), assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    title = str(data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Give the matter a title."}), 400
    opposing = clean_names(data.get("opposing_parties") or [])
    fields = {"title": title, "case_type": str(data.get("case_type") or "Other")[:100],
              "case_no": str(data.get("case_no") or "")[:100],
              "county": str(data.get("county") or "")[:100],
              "court": str(data.get("court") or "")[:200],
              "legal_issue": str(data.get("legal_issue") or "")[:2000],
              "opposing_parties": opposing}
    username = client["username"]
    check = record_check({"username": username}, "new_matter", session["username"],
                         client_names=[client.get("client_name") or username],
                         opposing_names=opposing)
    matter = matters.open_matter(username, fields)
    storage.update_client_atomic(username, lambda c: c.setdefault("conflict_checks", []).append(check))
    audit.record("matter_opened", client=username, detail=title)
    hits = redact_hits(check["hits"], session["username"])
    return jsonify({"success": True, "matter": matter,
                    "conflict_warnings": [hit_message(h) for h in hits], "conflict_hits": hits})


@matters_bp.route("/portal/attorney/matters/<action>", methods=["POST"])
@require_attorney
def matters_action(action):
    if action not in ("switch", "close", "reopen"):
        return jsonify({"error": "Unknown action."}), 404
    data   = request.get_json(silent=True) or {}
    client = load_client_for_attorney(str(data.get("username") or ""),
                                      assigned_only=action != "switch")
    if not client:
        return jsonify({"error": "Client not found."}), 404
    ok = getattr(matters, action)(client["username"], str(data.get("id") or ""))
    if not ok:
        return jsonify({"error": "Matter not found."}), 404
    audit.record(f"matter_{action}", client=client["username"], detail=str(data.get("id") or ""))
    return jsonify({"success": True, "matters": matters.list_for(client["username"])})
