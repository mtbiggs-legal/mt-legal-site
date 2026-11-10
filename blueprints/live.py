"""blueprints/live.py — polling endpoints behind live portal updates.

Both portals call these every few seconds (static/js/attorney_live.js and the
script in client_portal.html). A poll that finds nothing new is one short
JSON reply. These paths don't count as activity for the 30-minute idle
timeout (see security.LIVE_POLL_PATHS), so leaving a portal open in a tab
doesn't keep the session alive.
"""

from flask import Blueprint, jsonify, request, session

from services import billing, live, storage
from shared import require_attorney, require_client

live_bp = Blueprint("live", __name__)


@live_bp.route("/portal/attorney/live")
@require_attorney
def attorney_live():
    snap = live.attorney_snapshot(session["username"])
    if request.args.get("since") == snap["token"]:
        return jsonify({"token": snap["token"], "changed": False})
    return jsonify({"changed": True, **snap})


@live_bp.route("/portal/client/live")
@require_client
def client_live():
    rev = live.client_rev(session["username"], client_view=True)
    return jsonify({"token": rev, "changed": request.args.get("since") != rev})


@live_bp.route("/portal/client/summary")
@require_client
def client_summary():
    """What the client portal's overview and message thread show."""
    client = storage.load_client(session["username"])
    if not client:
        return jsonify({"error": "Account not found."}), 404
    ledger = billing.load_ledger(client["username"])
    view = billing.client_billing_view(client, ledger)
    return jsonify({
        "client_name":        client.get("client_name", ""),
        "case_type":          client.get("case_type", ""),
        "billed_hours":       billing.billed_hours(ledger),
        "flat_fee":           view["flat_fee"],
        "last_communication": client.get("last_communication", ""),
        "next_court_date":    client.get("next_court_date", ""),
        "legal_issue":        client.get("legal_issue", ""),
        "next_meeting":       client.get("next_meeting", ""),
        "has_new_statement":  view["has_new_statement"],
        "messages": [{"from": m.get("from", ""), "date": m.get("date", ""), "text": m.get("text", "")}
                     for m in client.get("messages") or []],
    })
