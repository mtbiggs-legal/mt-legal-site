"""blueprints/calendar.py — Google Calendar integration routes."""

import os
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session

from shared import require_auth, CALENDAR_SCOPES, CREDENTIALS_FILE, TOKEN_FILE
from services.gcal import GOOGLE_LIBS, get_calendar_service
from services.storage import all_clients, _log_activity
from services.accounts import can_access_client

calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.route("/calendar/status")
@require_auth
def calendar_status():
    if not GOOGLE_LIBS:
        return jsonify({"authorized": False, "reason": "libraries_missing"})
    if not CREDENTIALS_FILE.exists():
        return jsonify({"authorized": False, "reason": "no_credentials_file"})
    if not TOKEN_FILE.exists():
        return jsonify({"authorized": False, "reason": "not_authorized"})
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), CALENDAR_SCOPES)
        if creds.valid or (creds.expired and creds.refresh_token):
            return jsonify({"authorized": True})
    except Exception:
        pass
    return jsonify({"authorized": False, "reason": "token_invalid"})


@calendar_bp.route("/calendar/authorize")
@require_auth
def calendar_authorize():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return (
            "<h2 style='font-family:Arial;padding:2rem'>Authorization must be completed "
            "on the local machine. Open <a href='http://127.0.0.1/calendar/authorize'>"
            "http://127.0.0.1/calendar/authorize</a> in a browser on your computer.</h2>",
            403,
        )
    if not GOOGLE_LIBS:
        return "Google libraries not installed. Run: pip install -r requirements.txt", 400
    if not CREDENTIALS_FILE.exists():
        return (
            f"<h2 style='font-family:Arial;padding:2rem'>credentials.json not found.<br><br>"
            f"The app is looking here:<br><code>{CREDENTIALS_FILE}</code><br><br>"
            f"Make sure the file is named exactly <strong>credentials.json</strong> "
            f"and is in that folder.</h2>",
            400,
        )
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow  = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), CALENDAR_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    return (
        "<h2 style='font-family:Arial;padding:2rem;color:#1e7e34'>"
        "&#10003; Google Calendar authorized! You can close this tab and return to the app.</h2>"
    )


@calendar_bp.route("/calendar/schedule", methods=["POST"])
@require_auth
def calendar_schedule():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received."}), 400

    client_name = data.get("client_name", "").strip()
    matter      = data.get("matter_description", "").strip()
    case_type   = data.get("case_type", "").strip()
    date_str    = data.get("date", "").strip()
    time_str    = data.get("time", "").strip()
    duration    = int(data.get("duration", 60))
    notes       = data.get("notes", "").strip()

    if not client_name or not date_str or not time_str:
        return jsonify({"error": "Client name, date, and time are required."}), 400

    try:
        service = get_calendar_service()
    except ValueError as e:
        return jsonify({"error": str(e)}), 401

    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        end_dt   = start_dt + timedelta(minutes=duration)
    except ValueError:
        return jsonify({"error": "Invalid date or time."}), 400

    timezone     = os.getenv("TIMEZONE", "America/Chicago")
    desc_parts   = []
    if case_type: desc_parts.append(f"Case Type: {case_type}")
    if matter:    desc_parts.append(f"\nMatter:\n{matter}")
    if notes:     desc_parts.append(f"\nNotes:\n{notes}")

    event = {
        "summary":     f"Meeting: {client_name}",
        "description": "\n".join(desc_parts),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": timezone},
    }

    try:
        created = service.events().insert(calendarId="primary", body=event).execute()
        if session.get("role") == "attorney":
            atty = session.get("username", "")
            for c in all_clients():
                if not can_access_client(atty, c):
                    continue
                if (c.get("client_name") or "").strip().lower() == client_name.strip().lower():
                    notes_short = (notes[:80] + "...") if len(notes) > 80 else notes
                    _log_activity(
                        c.get("username", ""), "meeting_scheduled",
                        f"Meeting scheduled: {date_str} at {time_str}"
                        + (f" — {notes_short}" if notes_short else "") + ".",
                    )
                    break
        return jsonify({"success": True, "event_link": created.get("htmlLink")})
    except Exception as e:
        return jsonify({"error": f"Failed to create event: {str(e)}"}), 500
