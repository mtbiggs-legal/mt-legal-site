"""blueprints/intake.py — Client intake form and submission."""

import json
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, jsonify

from shared import (
    require_auth,
    CLIENT_DATA_DIR, CLIENT_FILES_DIR,
    ATTORNEYS, CASE_ATTORNEY_MAP, MODEL,
    get_anthropic_client, create_intake_doc,
    save_client, hash_password, generate_temp_password,
    _log_activity, _make_username,
    GOOGLE_LIBS, TOKEN_FILE,
    _push_court_date_to_gcal,
)
from blueprints.email_service import send_intake_email
from conflicts import clean_names, record_check

intake_bp = Blueprint("intake", __name__)


@intake_bp.route("/intake")
@require_auth
def intake():
    return render_template("intake.html")


@intake_bp.route("/intake/submit", methods=["POST"])
@require_auth
def intake_submit():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received."}), 400

    required = {
        "full_name":          "your full name",
        "email":              "your email address",
        "phone":              "your phone number",
        "matter_description": "a short description of your legal issue",
    }
    for field, label in required.items():
        if not data.get(field, "").strip():
            return jsonify({"error": f"Please enter {label}."}), 400
    # Case type is optional; an unselected one is filed as "Other".
    if not data.get("case_type", "").strip():
        data["case_type"] = "Other"

    portal_username = _make_username(data.get("full_name", "client"))
    # Random per-account temp password, emailed to the client and replaced on
    # first login. Never a fixed string — these accounts are reachable until then.
    portal_password = generate_temp_password()

    # Parse dates and flag urgent deadlines (within 30 days)
    today              = date.today()
    deadline_threshold = today + timedelta(days=30)
    urgent_dates       = []

    date_fields = {"arrest_date": "Arrest Date", "court_date_1": "Court Date"}
    for field, label in date_fields.items():
        raw = data.get(field, "").strip()
        if raw:
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d").date()
                if today <= parsed <= deadline_threshold:
                    urgent_dates.append({
                        "label": label, "date": raw,
                        "days_away": (parsed - today).days,
                    })
            except ValueError:
                pass

    # Save intake record to client-data/
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    last_name = data["full_name"].strip().split()[-1].replace(" ", "_")
    filename  = f"{timestamp}_{last_name}.json"
    record    = {
        "timestamp":         timestamp,
        "full_name":         data.get("full_name", ""),
        "dob":               data.get("dob", ""),
        "phone":             data.get("phone", ""),
        "email":             data.get("email", ""),
        "case_type":         data.get("case_type", ""),
        "matter_description":data.get("matter_description", ""),
        "referral_source":   data.get("referral_source", ""),
        "case_no":           data.get("case_no", ""),
        "county":            data.get("county", ""),
        "court_name":        data.get("court_name", ""),
        "arrest_date":       data.get("arrest_date", ""),
        "court_date_1":      data.get("court_date_1", ""),
        "urgent_dates":      urgent_dates,
        "saved_file":        filename,
    }
    with open(CLIENT_DATA_DIR / filename, "w") as f:
        json.dump(record, f, indent=2)

    # Optional: save Google Doc
    doc_link = None
    if GOOGLE_LIBS and TOKEN_FILE.exists():
        try:
            doc_link = create_intake_doc(record, urgent_dates)
        except Exception:
            pass

    # Create client portal account
    assigned_atty = CASE_ATTORNEY_MAP.get(data.get("case_type", ""), "Endocide")
    atty_display  = ATTORNEYS[assigned_atty]["display"]
    client_folder = CLIENT_FILES_DIR / portal_username
    client_folder.mkdir(exist_ok=True)

    intake_note = (
        f"CLIENT INTAKE — {data.get('case_type', '')}.\n"
        f"Matter: {data.get('matter_description', '').strip()}"
    )
    portal_record = {
        "username":             portal_username,
        "password":             hash_password(portal_password),
        "must_change_password": True,
        "client_name":          data.get("full_name", ""),
        "case_type":            data.get("case_type", ""),
        "assigned_attorney":    assigned_atty,
        "opposing_parties":     clean_names([data.get("opposing_party", "")]),
        "legal_issue":          data.get("matter_description", "")[:400],
        "legal_issue_summary":  "",
        "case_no":              data.get("case_no", ""),
        "county":               data.get("county", ""),
        "court":                data.get("court_name", ""),
        "next_court_date":      data.get("court_date_1", ""),
        "hours_billed":         0,
        "last_communication":   datetime.now().strftime("%Y-%m-%d"),
        "phone":                data.get("phone", ""),
        "email":                data.get("email", ""),
        "google_drive_url":     doc_link or "",
        "next_meeting":         "",
        "client_folder":        str(client_folder),
        "intake_file":          filename,
        "billing_log": [{
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0,
            "note":     intake_note,
            "type":     "intake",
            "category": "Intake",
        }],
        "time_logs":  [],
        "notes":      [],
        "esignature": data.get("esignature", None),
        "messages":   [{
            "from": "attorney",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "text": (
                f"Welcome to your MT Legal client portal. "
                f"I'm {atty_display} and I'll be handling your "
                f"{data.get('case_type', '')} matter. "
                "We'll be in touch shortly to schedule your initial consultation."
            ),
        }],
    }

    # AI-generated matter summary
    try:
        ai = get_anthropic_client()
        ai_resp = ai.messages.create(
            model=MODEL, max_tokens=200,
            system=(
                "You are a legal intake analyst for a law firm. When given a client's "
                "description of their legal matter, write a 2-3 sentence professional "
                "summary that identifies the core legal issue, key facts, and likely strategy. "
                "Be specific and use proper legal terminology. Do not use bullet points."
            ),
            messages=[{"role": "user", "content": (
                f"Case type: {data.get('case_type', 'General')}\n\n"
                f"Client's description:\n{data.get('matter_description', '').strip()}"
            )}],
        )
        portal_record["legal_issue_summary"] = ai_resp.content[0].text.strip()
    except Exception:
        pass

    record_check(portal_record, "intake", "public_intake",
                 client_names=[data.get("full_name", "")],
                 opposing_names=[data.get("opposing_party", "")])
    save_client(portal_record)
    _log_activity(portal_username, "intake",
                  f"Client intake completed — {data.get('case_type', '')}.")

    # Push court date to Google Calendar
    court_date_val = data.get("court_date_1", "").strip()
    if court_date_val:
        gcal_id = _push_court_date_to_gcal(
            data.get("full_name", portal_username), court_date_val
        )
        if gcal_id:
            portal_record["court_date_gcal_event_id"] = gcal_id
            save_client(portal_record)

    # Auto-save intake PDF
    try:
        from blueprints.portal_attorney import _generate_client_pdf, _generate_intake_html
        pdf_fields = {
            **data, "portal_username": portal_username,
            "atty_display": atty_display, "urgent_dates": urgent_dates,
        }
        pdf_bytes     = _generate_client_pdf(pdf_fields)
        intake_doc_dir = CLIENT_FILES_DIR / portal_username / "documents" / "Intake"
        intake_doc_dir.mkdir(parents=True, exist_ok=True)
        if pdf_bytes:
            with open(intake_doc_dir / f"intake_{timestamp}.pdf", "wb") as pf:
                pf.write(pdf_bytes)
        else:
            intake_html = _generate_intake_html(data, urgent_dates, portal_username, atty_display)
            with open(intake_doc_dir / f"intake_{timestamp}.html", "w", encoding="utf-8") as hf:
                hf.write(intake_html)
    except Exception:
        pass

    save_client(portal_record)

    # Auto-reply email: confirm intake + deliver portal credentials + booking link
    email_sent = False
    if data.get("email", "").strip():
        try:
            email_sent = send_intake_email(
                name               = data.get("full_name", ""),
                email              = data.get("email", ""),
                case_type          = data.get("case_type", ""),
                assigned_attorney  = assigned_atty,
                portal_username    = portal_username,
                portal_password    = portal_password,
                urgent_dates       = urgent_dates,
            )
        except Exception:
            pass

    return jsonify({
        "success":           True,
        "record":            record,
        "urgent_dates":      urgent_dates,
        "filename":          filename,
        "doc_link":          doc_link,
        "email_sent":        email_sent,
        "portal_account": {
            "username":          portal_username,
            "temp_password":     portal_password,
            "assigned_attorney": atty_display,
            "client_folder":     str(client_folder),
        },
    })
