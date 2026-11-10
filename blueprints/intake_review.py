"""blueprints/intake_review.py — the attorney's queue of submitted intakes.

The public form only queues an intake (services/intake_queue.py). Approving
one here opens the client account and emails the client an invitation;
declining keeps the encrypted entry for the record but takes no action.
"""

from flask import Blueprint, jsonify, request, session

from shared import require_attorney
from services import audit, intake_queue

intake_review_bp = Blueprint("intake_review", __name__)

# What the list shows; the full entry stays server-side until approval.
_LIST_FIELDS = ("full_name", "email", "phone", "case_type", "matter_description",
                "county", "court_name", "case_no", "court_date_1", "arrest_date",
                "opposing_party", "referral_source")


@intake_review_bp.route("/portal/attorney/intakes")
@require_attorney
def intakes_list():
    rows = []
    for e in intake_queue.list_pending(session["username"]):
        f = e.get("fields") or {}
        rows.append({"id": e["id"], "submitted_at": e.get("submitted_at", ""),
                     "urgent_dates": e.get("urgent_dates") or [],
                     **{k: f.get(k, "") for k in _LIST_FIELDS}})
    return jsonify({"intakes": rows})


@intake_review_bp.route("/portal/attorney/intakes/approve", methods=["POST"])
@require_attorney
def intakes_approve():
    intake_id = str((request.get_json(silent=True) or {}).get("id") or "")
    result = intake_queue.approve(intake_id, session["username"])
    if result.get("error"):
        return jsonify(result), 404
    audit.record("intake_approved", client=result["username"])
    return jsonify({"success": True, **result})


@intake_review_bp.route("/portal/attorney/intakes/decline", methods=["POST"])
@require_attorney
def intakes_decline():
    intake_id = str((request.get_json(silent=True) or {}).get("id") or "")
    if not intake_queue.decline(intake_id, session["username"]):
        return jsonify({"error": "Intake not found."}), 404
    audit.record("intake_declined", detail=intake_id)
    return jsonify({"success": True})


_SIGN_IN_ACTIONS = ("login", "login_failed", "login_locked", "login_code_failed",
                    "login_password_ok", "two_factor_enabled", "logout", "invite_accepted",
                    "password_changed")


@intake_review_bp.route("/portal/attorney/sign-in-activity")
@require_attorney
def sign_in_activity():
    """Recent sign-ins, failures and lockouts across the portal."""
    from services import audit as _audit
    return jsonify({"events": _audit.recent(200, actions=_SIGN_IN_ACTIONS)})
