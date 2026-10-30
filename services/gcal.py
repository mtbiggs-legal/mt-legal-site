"""services/gcal.py — Google Calendar and Drive."""

from datetime import datetime, timedelta, timezone

import shared

# Google Calendar / Drive libraries (optional).
# InstalledAppFlow is imported here only to prove google_auth_oauthlib is present —
# /calendar/authorize needs it, and GOOGLE_LIBS gates that route.
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build as google_build
    GOOGLE_LIBS = True
except ImportError:
    GOOGLE_LIBS = False


# ── Google Calendar / Drive helpers ───────────────────────────────────────────

def _google_credentials(not_authorized_message: str):
    """Load stored Google credentials, refreshing them if they have expired.

    Raises ValueError with a user-facing message when the app has never been
    authorized (or the refresh token is gone and the user must re-consent).
    """
    if not GOOGLE_LIBS:
        raise ValueError("Google libraries not installed. Run: pip install -r requirements.txt")
    creds = None
    if shared.TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(shared.TOKEN_FILE), shared.CALENDAR_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
            with open(shared.TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        else:
            raise ValueError(not_authorized_message)
    return creds


def get_drive_service():
    creds = _google_credentials(
        "Google Drive not authorized. "
        "Go to the Dashboard and click 'Authorize Google Calendar'."
    )
    return google_build("drive", "v3", credentials=creds)


def get_calendar_service():
    creds = _google_credentials(
        "Google Calendar not authorized. "
        "Go to the Dashboard and click 'Authorize Google Calendar'."
    )
    return google_build("calendar", "v3", credentials=creds)


def create_intake_doc(record, urgent_dates):
    from googleapiclient.http import MediaInMemoryUpload

    def row(label, val):
        if not val:
            return ""
        return (
            f"<tr><td style='padding:6px 12px;font-weight:bold;width:38%;"
            f"border-bottom:1px solid #eee'>{label}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{val}</td></tr>"
        )

    urgent_html = ""
    if urgent_dates:
        items = "".join(
            f"<li><strong>{d['label']}:</strong> {d['date']} "
            f"({d['days_away']} day{'s' if d['days_away'] != 1 else ''} away)</li>"
            for d in urgent_dates
        )
        urgent_html = (
            f"<div style='background:#fde8e8;border:2px solid #c0392b;"
            f"padding:12px 16px;margin-bottom:16px;border-radius:4px'>"
            f"<strong style='color:#c0392b'>⚠ URGENT DEADLINES</strong>"
            f"<ul>{items}</ul></div>"
        )

    html = (
        f"<html><body style='font-family:Georgia,serif;max-width:800px;"
        f"margin:0 auto;padding:24px'>"
        f"<h1 style='color:#1a2c4e;border-bottom:2px solid #c9a84c;"
        f"padding-bottom:8px'>Client Intake — {record['full_name']}</h1>"
        f"<p style='color:#888;font-size:14px'>Created: "
        f"{record['timestamp'][:4]}-{record['timestamp'][4:6]}-{record['timestamp'][6:8]}"
        f" &nbsp;|&nbsp; File: {record['saved_file']}</p>"
        f"{urgent_html}"
        f"<h2 style='color:#1a2c4e'>Client Information</h2>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"{row('Full Name', record['full_name'])}"
        f"{row('Date of Birth', record.get('dob', ''))}"
        f"{row('Phone', record.get('phone', ''))}"
        f"{row('Email', record.get('email', ''))}"
        f"{row('Case Type', record.get('case_type', ''))}"
        f"{row('Referral Source', record.get('referral_source', ''))}"
        f"</table>"
        f"<h2 style='color:#1a2c4e'>Matter Description</h2>"
        f"<p style='line-height:1.6'>"
        f"{record.get('matter_description', '').replace(chr(10), '<br>')}</p>"
        f"<h2 style='color:#1a2c4e'>Key Dates</h2>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"{row('Arrest Date', record.get('arrest_date', ''))}"
        f"{row('Court Date', record.get('court_date_1', ''))}"
        f"</table></body></html>"
    )

    service = get_drive_service()
    file_metadata = {
        "name":     f"Intake — {record['full_name']} ({record['timestamp'][:8]})",
        "mimeType": "application/vnd.google-apps.document",
    }
    media = MediaInMemoryUpload(html.encode("utf-8"), mimetype="text/html")
    f = service.files().create(
        body=file_metadata, media_body=media, fields="id,webViewLink"
    ).execute()
    return f.get("webViewLink")


def _push_court_date_to_gcal(client_name: str, court_date_str: str):
    if not GOOGLE_LIBS or not shared.TOKEN_FILE.exists():
        return None
    try:
        court_date = datetime.strptime(court_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    try:
        service = get_calendar_service()
        event = {
            "summary":     f"Court Date: {client_name}",
            "description": f"Court date for client {client_name} — MT Legal",
            "start": {"date": court_date_str},
            "end":   {"date": (court_date + timedelta(days=1)).isoformat()},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return created.get("id")
    except Exception:
        return None


def _gcal_status(exc) -> int | None:
    resp = getattr(exc, "resp", None)
    try:
        return int(getattr(resp, "status", None))
    except (TypeError, ValueError):
        return None


def gcal_connected() -> bool:
    return bool(GOOGLE_LIBS and shared.TOKEN_FILE.exists())


def _gcal_all_day_body(summary: str, description: str, date_str: str):
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    return {"summary": summary, "description": description,
            "start": {"date": date_str},
            "end":   {"date": (day + timedelta(days=1)).isoformat()}}


def gcal_create_all_day(summary: str, description: str, date_str: str):
    """Create an all-day event. Returns its id, or None (not connected / error)."""
    if not GOOGLE_LIBS or not shared.TOKEN_FILE.exists():
        return None
    try:
        body = _gcal_all_day_body(summary, description, date_str)
        created = get_calendar_service().events().insert(calendarId="primary", body=body).execute()
        return created.get("id")
    except Exception:
        return None


def gcal_update_all_day(event_id: str, summary: str, description: str, date_str: str) -> str:
    """Move an all-day event. Returns "ok", "gone" (404/410) or "error"."""
    if not GOOGLE_LIBS or not shared.TOKEN_FILE.exists() or not event_id:
        return "error"
    try:
        body = _gcal_all_day_body(summary, description, date_str)
        get_calendar_service().events().patch(calendarId="primary", eventId=event_id,
                                              body=body).execute()
        return "ok"
    except Exception as exc:
        return "gone" if _gcal_status(exc) in (404, 410) else "error"


def gcal_delete_event(event_id: str) -> str:
    """Delete an event. Returns "ok", "gone" (already deleted) or "error"."""
    if not GOOGLE_LIBS or not shared.TOKEN_FILE.exists() or not event_id:
        return "error"
    try:
        get_calendar_service().events().delete(calendarId="primary", eventId=event_id).execute()
        return "ok"
    except Exception as exc:
        return "gone" if _gcal_status(exc) in (404, 410) else "error"


def _fetch_gcal_events(days_ahead: int = 180) -> list:
    if not GOOGLE_LIBS or not shared.TOKEN_FILE.exists():
        return []
    try:
        service    = get_calendar_service()
        now        = datetime.now(timezone.utc)
        now_iso    = now.isoformat()
        cutoff_iso = (now + timedelta(days=days_ahead)).isoformat()
        result = service.events().list(
            calendarId   = "primary",
            timeMin      = now_iso,
            timeMax      = cutoff_iso,
            maxResults   = 250,
            singleEvents = True,
            orderBy      = "startTime",
        ).execute()
        events = []
        for item in result.get("items", []):
            start        = item.get("start", {})
            date_str     = start.get("date", "")
            datetime_str = start.get("dateTime", "")
            events.append({
                "summary":        item.get("summary", ""),
                "start_date":     date_str or datetime_str[:10],
                "start_datetime": datetime_str,
                "gcal_id":        item.get("id", ""),
            })
        return events
    except Exception:
        return []
