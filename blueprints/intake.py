"""blueprints/intake.py — the public intake form.

A submission is queued for attorney review (services/intake_queue.py); it does
not open a client account. The attorney approves it in the portal, which
creates the account and emails the client an invitation to set a password.
"""

from flask import Blueprint, current_app, render_template, request, jsonify

from shared import public, csrf_exempt, require_auth
from services import intake_queue
from services.security import rate_limit
from blueprints.email_service import send_intake_email

intake_bp = Blueprint("intake", __name__)

_REQUIRED = {
    "full_name":          "your full name",
    "email":              "your email address",
    "phone":              "your phone number",
    "matter_description": "a short description of your legal issue",
}


@intake_bp.route("/intake")
@public
@require_auth
def intake():
    return render_template("intake.html")


@intake_bp.route("/intake/submit", methods=["POST"])
@public
@csrf_exempt
@require_auth
@rate_limit("intake", limit=5, window=3600)
def intake_submit():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "No data received."}), 400
    fields = intake_queue.clean_submission(data)
    for field, label in _REQUIRED.items():
        if not fields.get(field):
            return jsonify({"error": f"Please enter {label}."}), 400
    if "@" not in fields["email"]:
        return jsonify({"error": "Please enter a valid email address."}), 400

    entry = intake_queue.submit(fields, ip=request.remote_addr or "",
                                esignature=data.get("esignature"))

    email_sent = False
    try:
        email_sent = send_intake_email(
            name=fields["full_name"], email=fields["email"],
            case_type=fields["case_type"],
            assigned_attorney=entry["assigned_attorney"],
            urgent_dates=entry["urgent_dates"],
        )
    except Exception:
        current_app.logger.exception("Intake acknowledgement email failed")

    # Only what the visitor typed comes back; no account, path or file name.
    return jsonify({
        "success":      True,
        "urgent_dates": entry["urgent_dates"],
        "email_sent":   bool(email_sent),
    })
