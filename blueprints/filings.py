"""blueprints/filings.py — prepare court filing packages and record filings."""

from flask import Blueprint, jsonify, request, session

import shared
from services import filings
from services.accounts import load_client_for_attorney

filings_bp = Blueprint("filings", __name__)



@filings_bp.route("/portal/attorney/filing/<username>")
@shared.require_attorney
def filing_info(username):
    """Pre-filled form values from the client file, plus this client's filings."""
    client = load_client_for_attorney((username or "").strip())
    if not client:
        return jsonify({"error": "Client not found."}), 404
    return jsonify({**filings.prefill(client), "filings": filings.list_filings(client),
                    "methods": list(filings.SERVICE_METHODS)})


@filings_bp.route("/portal/attorney/filing/prepare", methods=["POST"])
@shared.require_attorney
def filing_prepare():
    data = request.get_json() or {}
    client = load_client_for_attorney((data.get("username") or "").strip())
    if not client:
        return jsonify({"error": "Client not found."}), 404
    try:
        entry = filings.prepare(client["username"], data.get("category", ""), data.get("filename", ""),
                                data, session["username"])
    except filings.FilingError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "filing": entry})


@filings_bp.route("/portal/attorney/filing/mark-filed", methods=["POST"])
@shared.require_attorney
def filing_mark_filed():
    client = load_client_for_attorney((request.form.get("username") or "").strip())
    if not client:
        return jsonify({"error": "Client not found."}), 404
    try:
        entry = filings.mark_filed(client["username"], request.form.get("filing_id", ""),
                                   request.files.get("file"), request.form.get("category", "Court Orders"),
                                   request.form.get("hearing_date", ""), request.form.get("hearing_label", ""))
    except filings.FilingError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "filing": entry})
