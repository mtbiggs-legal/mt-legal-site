"""blueprints/portal_attorney/leads.py — Incoming leads and attorney replies to clients."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401


@portal_attorney_bp.route("/portal/attorney/leads-list")
@require_attorney
def portal_leads_list():
    atty_user = session.get("attorney") or session.get("username", "")
    leads = []
    for p in sorted(shared.LEADS_DIR.glob("*.json"), reverse=True):
        lead = storage.read_encrypted_json(p)
        if isinstance(lead, dict) and lead.get("assigned_attorney") == atty_user \
                and not lead.get("archived"):
            lead["_filename"] = p.name
            leads.append(lead)
    return jsonify(leads)


@portal_attorney_bp.route("/portal/attorney/archive-lead", methods=["POST"])
@require_attorney
def portal_archive_lead():
    data     = request.get_json() or {}
    filename = data.get("filename", "").strip()
    if not filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename."}), 400
    lead_path = shared.LEADS_DIR / filename
    if not lead_path.exists():
        return jsonify({"error": "Lead not found."}), 404
    try:
        lead = storage.read_encrypted_json(lead_path) or {}
        if lead.get("assigned_attorney") != session["username"]:
            return jsonify({"error": "Lead not found."}), 404
        lead["archived"] = True
        storage.write_encrypted_json(lead_path, lead)
        return jsonify({"success": True})
    except Exception:
        current_app.logger.exception("Could not archive lead")
        return jsonify({"error": "Could not archive this lead."}), 500


@portal_attorney_bp.route("/portal/attorney/reply", methods=["POST"])
@require_attorney
def portal_attorney_reply():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    # load_client_for_attorney is only for the access check here: it confirms
    # this attorney may write to this client. The actual write goes through
    # update_client_atomic below on a freshly re-read copy, not this one —
    # a plain load/save would silently drop a message or billing entry the
    # client's own (slower, AI-calling) send route wrote in between.
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Reply cannot be empty."}), 400
    username = client["username"]

    def _add_reply(c):
        c.setdefault("messages", []).append({
            "from": "attorney",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "text": text,
        })
        c["last_communication"] = datetime.now().strftime("%Y-%m-%d")
        _log_access(c, "message_sent", text[:80])

    if not update_client_atomic(username, _add_reply):
        return jsonify({"error": "Client not found."}), 404
    _log_activity(username, "message_sent",
                  "Attorney message: " + text[:80] + ("..." if len(text) > 80 else ""))
    return jsonify({"success": True})
