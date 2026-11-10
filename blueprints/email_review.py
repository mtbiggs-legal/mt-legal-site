"""blueprints/email_review.py — the attorney portal's Inbox tab.

Every route is attorney-only and, through app.py's PUBLIC_SITE_ONLY gate,
switched off on the public site.
"""

import logging

from flask import Blueprint, jsonify, request

import shared
from shared import require_attorney
from services import email_review
from services import gmail

log = logging.getLogger(__name__)

email_review_bp = Blueprint("email_review", __name__)


@email_review_bp.route("/email-review/status")
@require_attorney
def email_review_status():
    state = email_review.load_state()
    return jsonify({
        **gmail.status(),
        "account":     state.get("account", ""),
        "last_check":  state.get("last_check_at", ""),
        "last_digest": state.get("last_digest_at", ""),
        "auto":        shared.EMAIL_REVIEW_AUTO,
        "digest_hour": shared.EMAIL_DIGEST_HOUR,
    })


@email_review_bp.route("/email-review/authorize")
@require_attorney
def email_review_authorize():
    """Opens Google's consent page on this computer. The attorney signs in there."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return ("<h2 style='font-family:Arial;padding:2rem'>Connect Gmail from the computer "
                "running the app: open http://127.0.0.1:5000/email-review/authorize there.</h2>", 403)
    if not gmail.GOOGLE_LIBS:
        return "Google libraries not installed. Run: pip install -r requirements.txt", 400
    if not shared.CREDENTIALS_FILE.exists():
        return ("<h2 style='font-family:Arial;padding:2rem'>credentials.json not found. "
                "See docs/EMAIL_REVIEW_SETUP.md, step 1.</h2>", 400)
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(shared.CREDENTIALS_FILE), shared.GMAIL_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    gmail.save_token(creds)
    return ("<h2 style='font-family:Arial;padding:2rem;color:#1e7e34'>&#10003; Gmail connected. "
            "You can close this tab and click 'Check now' in the Inbox tab.</h2>")


@email_review_bp.route("/email-review/list")
@require_attorney
def email_review_list():
    return jsonify({"reviews": email_review.list_reviews(),
                    "categories": email_review.CATEGORIES})


@email_review_bp.route("/email-review/run", methods=["POST"])
@require_attorney
def email_review_run():
    try:
        counts = email_review.run_review()
    except email_review.ReviewBusy as exc:
        return jsonify({"error": str(exc)}), 409
    except gmail.GmailError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        log.exception("Email review run failed")
        return jsonify({"error": "The check failed. See the app's console for details."}), 500
    return jsonify({"success": True, **counts})


@email_review_bp.route("/email-review/handled", methods=["POST"])
@require_attorney
def email_review_handled():
    data = request.get_json(silent=True) or {}
    msg_id = str(data.get("id") or "")
    if not msg_id or not email_review.set_handled(msg_id, bool(data.get("handled"))):
        return jsonify({"error": "Email not found."}), 404
    return jsonify({"success": True})


@email_review_bp.route("/email-review/digest", methods=["POST"])
@require_attorney
def email_review_digest():
    try:
        result = email_review.send_digest()
    except gmail.GmailError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        log.exception("Email digest failed")
        return jsonify({"error": "The digest could not be sent. See the app's console."}), 500
    return jsonify({"success": True, **result})
