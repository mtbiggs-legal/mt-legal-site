"""blueprints/esign.py — send documents for e-signature and track them (Dropbox Sign)."""

from flask import Blueprint, jsonify, request, session

import shared
from services import esign
from services.accounts import load_client_for_attorney

esign_bp = Blueprint("esign", __name__)



@esign_bp.route("/portal/attorney/esign/<username>")
@shared.require_attorney
def esign_list(username):
    client = load_client_for_attorney((username or "").strip())
    if not client:
        return jsonify({"error": "Client not found."}), 404
    return jsonify({"configured": esign.configured(), "test_mode": shared.DROPBOX_SIGN_TEST_MODE,
                    "requests": esign.refresh(client["username"], force=request.args.get("refresh") == "1"),
                    "defaults": {"name": client.get("client_name", ""), "email": client.get("email", "")}})


@esign_bp.route("/portal/attorney/esign/send", methods=["POST"])
@shared.require_attorney
def esign_send():
    data = request.get_json() or {}
    client = load_client_for_attorney((data.get("username") or "").strip())
    if not client:
        return jsonify({"error": "Client not found."}), 404
    try:
        entry = esign.send(client["username"], data.get("category", ""), data.get("filename", ""),
                           data.get("signers"), data.get("subject", ""), data.get("message", ""),
                           session["username"])
    except esign.EsignError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "request": entry})


@esign_bp.route("/portal/attorney/esign/remind", methods=["POST"])
@shared.require_attorney
def esign_remind():
    data = request.get_json() or {}
    client = load_client_for_attorney((data.get("username") or "").strip())
    if not client:
        return jsonify({"error": "Client not found."}), 404
    try:
        names = esign.remind(client["username"], data.get("request_id", ""))
    except esign.EsignError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "reminded": names})


@esign_bp.route("/webhooks/dropbox-sign", methods=["POST"])
@shared.portal_public
@shared.csrf_exempt
def esign_callback():
    """Dropbox Sign event callback. Verified by event_hash; must answer with
    its fixed acknowledgement text or Dropbox Sign retries and then disables it."""
    payload = esign.parse_callback_form(request.form)
    if not esign.handle_callback(payload):
        return "Invalid event", 400
    return esign.CALLBACK_REPLY, 200, {"Content-Type": "text/plain"}
