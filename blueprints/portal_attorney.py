"""blueprints/portal_attorney.py — Attorney portal: dashboard, clients, leads, documents.

Research tools live in blueprints/research.py, insights and token usage in
blueprints/insights.py.
"""

import json
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import (
    Blueprint, render_template, request, jsonify, session,
    current_app, send_file,
)
from werkzeug.utils import secure_filename

from services import billing
from shared import (
    require_attorney, ATTORNEYS, CASE_ATTORNEY_MAP, CLIENT_FILES_DIR,
    CLIENT_ACCOUNTS_DIR, LEADS_DIR, TOKEN_FILE, MAMMOTH_AVAILABLE, DOCS_CATEGORIES,
    ALLOWED_DOC_EXTENSIONS, MODEL, get_anthropic_client,
)
from services.gcal import (
    GOOGLE_LIBS, get_calendar_service, _push_court_date_to_gcal, _fetch_gcal_events,
    gcal_create_all_day, gcal_update_all_day, gcal_delete_event, gcal_connected,
)
from services.storage import (
    load_client, save_client, all_clients, _client_docs_dir, safe_username,
    recalc_hours, _log_activity, _log_token_usage, update_client_atomic,
    read_json, write_json,
)
from services.accounts import (
    hash_password, acceptable_password, generate_temp_password, log_access_atomic,
    can_access_client, load_client_for_attorney, public_client_view, _log_access,
)
from services.documents import generate_client_pdf, generate_intake_html, resolve_doc_path
from services.scheduling_orders import extract_case_dates, ExtractionError, CASE_DATE_KINDS, CASE_DATE_LABELS
from services.conflicts import (
    DECISIONS, append_firm_log, clean_names, clean_related, has_unresolved_conflict,
    hit_message, make_check_record, record_check, redact_checks, redact_hits,
    run_conflict_check,
)

portal_attorney_bp = Blueprint("portal_attorney", __name__)


# ── Portal pages ───────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/attorney-portal")
@require_attorney
def attorney_portal():
    atty_user = session["username"]
    atty_info = ATTORNEYS[atty_user]

    def _view(c):
        v = public_client_view(c)
        v["is_co_counsel"] = c.get("assigned_attorney") != atty_user
        v["conflict_unresolved"] = has_unresolved_conflict(c)
        v["amount_due"] = billing.amount_due(c, billing.load_ledger(c["username"]))
        return v

    all_mine = [c for c in all_clients() if can_access_client(atty_user, c)]
    clients          = sorted([_view(c) for c in all_mine if not c.get("archived")],
                              key=lambda c: c.get("last_communication") or "", reverse=True)
    archived_clients = [_view(c) for c in all_mine if c.get("archived")]
    return render_template("attorney_portal.html",
                           clients=clients,
                           archived_clients=archived_clients,
                           attorney=atty_info,
                           attorneys=[{"username": u, "display": i["display"]}
                                      for u, i in ATTORNEYS.items()],
                           viewer=atty_user,
                           case_date_labels=[{"kind": k, "label": CASE_DATE_LABELS[k]} for k in CASE_DATE_KINDS])


@portal_attorney_bp.route("/portal/attorney/dashboard")
@require_attorney
def portal_attorney_dashboard():
    try:
        atty_user  = session["username"]
        today      = date.today()
        my_clients = [c for c in all_clients()
                      if can_access_client(atty_user, c)
                      and not c.get("archived")]

        case_gcal_ids = {(e or {}).get("gcal_event_id")
                         for c in my_clients
                         for _k, e in _case_date_entries(c.get("case_dates"))
                         if e.get("gcal_event_id")}

        calendar_events = []
        for c in my_clients:
            uname  = c.get("username", "")
            cname  = c.get("client_name") or uname
            charge = c.get("charges") or c.get("case_type") or ""

            court_raw = c.get("next_court_date", "")
            if court_raw:
                try:
                    cd = datetime.strptime(court_raw, "%Y-%m-%d").date()
                    calendar_events.append({
                        "date": court_raw,
                        "date_display": cd.strftime("%b %d, %Y"),
                        "time": "",
                        "client_name": cname,
                        "username": uname,
                        "type": "Court Date",
                        "matter": charge,
                    })
                except ValueError:
                    pass

            for kind, entry in _case_date_entries(c.get("case_dates")):
                raw = (entry or {}).get("date")
                try:
                    cd_ = datetime.strptime(raw, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    continue
                calendar_events.append({
                    "date": raw, "date_display": cd_.strftime("%b %d, %Y"), "time": "",
                    "client_name": cname, "username": uname, "type": "Court Date",
                    "matter": CASE_DATE_LABELS.get(kind, kind)})

            meeting_raw = c.get("next_meeting", "")
            if meeting_raw:
                m = re.search(r'(\w+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M)', meeting_raw)
                if m:
                    try:
                        dt = datetime.strptime(m.group(1) + " " + m.group(2), "%B %d, %Y %I:%M %p")
                        sort_key  = dt.strftime("%Y-%m-%d")
                        time_part = dt.strftime("%I:%M %p").lstrip("0")
                        display   = dt.strftime("%b %d, %Y")
                        note_part = meeting_raw.split(" — ", 1)[1].strip() if " — " in meeting_raw else ""
                    except ValueError:
                        sort_key, time_part, display, note_part = "9999-99-99", "", meeting_raw[:30], ""
                else:
                    sort_key, time_part, display, note_part = "9999-99-99", "", meeting_raw[:30], ""
                calendar_events.append({
                    "date": sort_key, "date_display": display, "time": time_part,
                    "client_name": cname, "username": uname,
                    "type": "Meeting", "matter": note_part or charge,
                })

        gcal_raw = _fetch_gcal_events(days_ahead=180)
        for gev in gcal_raw:
            if gev.get("gcal_id") in case_gcal_ids:
                continue
            summary  = gev["summary"]
            date_str = gev["start_date"]
            if not date_str:
                continue
            sl = summary.lower()
            if any(k in sl for k in ("court", "hearing", "arraignment")):
                ev_type = "Court Date (GCal)"
            elif any(k in sl for k in ("meeting", "consult", "deposition")):
                ev_type = "Meeting (GCal)"
            else:
                ev_type = "Event (GCal)"
            time_part = ""
            if gev["start_datetime"]:
                try:
                    raw = gev["start_datetime"]
                    if raw.endswith("Z"):
                        raw = raw[:-1]
                    elif len(raw) > 6 and raw[-6] in ("+", "-"):
                        raw = raw[:-6]
                    dt        = datetime.fromisoformat(raw)
                    time_part = dt.strftime("%I:%M %p").lstrip("0")
                except Exception:
                    pass
            try:
                display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")
            except Exception:
                display = date_str
            calendar_events.append({
                "date":         date_str,
                "date_display": display,
                "time":         time_part,
                "client_name":  summary,
                "username":     "",
                "type":         ev_type,
                "matter":       summary,
            })
        calendar_events.sort(key=lambda x: x["date"])

        deadlines = []
        for c in my_clients:
            court_raw = c.get("next_court_date", "")
            if not court_raw:
                continue
            try:
                cd = datetime.strptime(court_raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            days = (cd - today).days
            if 0 <= days <= 90:
                deadlines.append({
                    "client_name": c.get("client_name") or c.get("username", ""),
                    "username":    c.get("username", ""),
                    "charges":     c.get("charges") or c.get("case_type") or "—",
                    "court_date":  cd.strftime("%b %d, %Y"),
                    "days_until":  days,
                })
        for c in my_clients:
            for kind, entry in _case_date_entries(c.get("case_dates")):
                raw = (entry or {}).get("date")
                try:
                    cd_ = datetime.strptime(raw, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    continue
                days = (cd_ - today).days
                if 0 <= days <= 90:
                    deadlines.append({
                        "client_name": c.get("client_name") or c.get("username", ""),
                        "username":    c.get("username", ""),
                        "charges":     CASE_DATE_LABELS.get(kind, kind),
                        "court_date":  cd_.strftime("%b %d, %Y"),
                        "days_until":  days,
                    })
        # Reuse the 180-day pull above rather than making a second API call —
        # the 90-day window is a subset of it.
        for gev in gcal_raw:
            if gev.get("gcal_id") in case_gcal_ids:
                continue
            summary  = gev["summary"]
            date_str = gev["start_date"]
            if not date_str:
                continue
            try:
                gd = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            days = (gd - today).days
            if not (0 <= days <= 90):
                continue
            sl = summary.lower()
            if any(k in sl for k in ("court", "hearing", "arraignment")):
                ev_type = "Court Date"
            elif any(k in sl for k in ("meeting", "consult", "deposition")):
                ev_type = "Meeting"
            else:
                continue
            already = any(
                d["court_date"] == gd.strftime("%b %d, %Y") and
                (d.get("client_name", "").lower() in gev["summary"].lower() or
                 gev["summary"].lower() in d.get("client_name", "").lower())
                for d in deadlines
            )
            if already:
                continue
            deadlines.append({
                "client_name": summary,
                "username":    "",
                "charges":     ev_type,
                "court_date":  gd.strftime("%b %d, %Y"),
                "days_until":  days,
            })
        deadlines.sort(key=lambda x: x["days_until"])

        follow_up_needed = []
        for c in my_clients:
            lc_raw = c.get("last_communication", "")
            if not lc_raw:
                continue
            try:
                lc_date = datetime.strptime(lc_raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            days_since = (today - lc_date).days
            if days_since >= 30:
                follow_up_needed.append({
                    "client_name":  c.get("client_name") or c.get("username", ""),
                    "username":     c.get("username", ""),
                    "last_contact": lc_date.strftime("%b %d, %Y"),
                    "days_since":   days_since,
                })
        follow_up_needed.sort(key=lambda x: x["days_since"], reverse=True)

        all_files = []
        for c in my_clients:
            base = CLIENT_FILES_DIR / c.get("username", "") / "documents"
            if not base.exists():
                continue
            for cat_dir in base.iterdir():
                if not cat_dir.is_dir():
                    continue
                for f in cat_dir.iterdir():
                    if f.is_file():
                        st = f.stat()
                        all_files.append({
                            "filename":    f.name,
                            "client_name": c.get("client_name") or c.get("username", ""),
                            "username":    c.get("username", ""),
                            "category":    cat_dir.name,
                            "modified":    datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                            "_mtime":      st.st_mtime,
                        })
        all_files.sort(key=lambda x: x["_mtime"], reverse=True)
        recent_files = [{k: v for k, v in f.items() if k != "_mtime"} for f in all_files[:15]]

        all_activity = []
        for c in my_clients:
            cname = c.get("client_name") or c.get("username", "")
            uname = c.get("username", "")
            for entry in c.get("activity_log", []):
                all_activity.append({
                    "timestamp":   entry.get("timestamp", ""),
                    "client_name": cname,
                    "username":    uname,
                    "action_type": entry.get("action_type", ""),
                    "description": entry.get("description", ""),
                })
        all_activity.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        recent_activity = all_activity[:20]

        grand_total   = 0.0
        client_totals = []
        for c in my_clients:
            cname = c.get("client_name") or c.get("username", "")
            uname = c.get("username", "")
            client_hrs = 0.0
            for entry in c.get("billing_log", []):
                hrs = float(entry.get("hours", 0) or 0)
                client_hrs += hrs
                grand_total += hrs
            client_totals.append({
                "client_name": cname,
                "username":    uname,
                "hours":       round(client_hrs, 2),
            })
        client_totals.sort(key=lambda x: x["hours"], reverse=True)

        return jsonify({
            "calendar":         calendar_events,
            "deadlines":        deadlines,
            "follow_up_needed": follow_up_needed,
            "recent_files":     recent_files,
            "billing":          client_totals,
            "billing_total":    round(grand_total, 2),
            "recent_activity":  recent_activity,
        })
    except Exception as exc:
        # Log the full traceback server-side; don't ship it to the browser.
        current_app.logger.exception("Attorney dashboard failed")
        return jsonify({"error": f"Could not build the dashboard: {exc}"}), 500


# ── Client CRUD ────────────────────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/clients")
@require_attorney
def portal_clients_list():
    atty = session["username"]
    return jsonify([public_client_view(c) for c in all_clients() if can_access_client(atty, c)])


@portal_attorney_bp.route("/portal/attorney/client/<username>")
@require_attorney
def portal_client_get(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    log_access_atomic(client["username"], "view_record")
    view = public_client_view(client)
    view["viewer_is_assigned"] = client.get("assigned_attorney") == session["username"]
    view["conflict_checks"] = redact_checks(client.get("conflict_checks"), session["username"])
    view["billing_summary"] = billing.billing_summary(client, billing.load_ledger(client["username"]))
    return jsonify(view)


@portal_attorney_bp.route("/portal/attorney/access-log/<username>")
@require_attorney
def portal_access_log(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    return jsonify(list(reversed(client.get("access_log", []))))


@portal_attorney_bp.route("/portal/attorney/co-counsel", methods=["POST"])
@require_attorney
def portal_co_counsel():
    data   = request.get_json() or {}
    client = load_client_for_attorney(data.get("username", ""), assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    action   = data.get("action")
    attorney = (data.get("attorney") or "").strip()
    if action not in ("add", "remove"):
        return jsonify({"error": "Invalid action."}), 400
    if attorney not in ATTORNEYS or attorney == client.get("assigned_attorney"):
        return jsonify({"error": "Invalid attorney."}), 400
    cc = client.setdefault("co_counsel", [])
    if action == "add" and attorney not in cc:
        cc.append(attorney)
    elif action == "remove" and attorney in cc:
        cc.remove(attorney)
    _log_access(client, "co_counsel_change", f"{action} {attorney}")
    save_client(client)
    return jsonify({"success": True, "co_counsel": cc})


@portal_attorney_bp.route("/portal/attorney/issue-statement", methods=["POST"])
@require_attorney
def portal_issue_statement():
    data   = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username  = client["username"]
    statement = billing.issue_statement(username, reason="manual",
                                        issued_by=session["username"], notify=True)
    if not statement:
        return jsonify({"error": "No unbilled time to bill."}), 400
    log_access_atomic(username, "statement_issued",
                      f"{statement['id']} ${statement['amount']:,.2f}")
    billing.send_pending_notices(username)
    fresh = load_client(username)
    return jsonify({"success": True, "statement": statement,
                    "billing_summary": billing.billing_summary(fresh, billing.load_ledger(username))})


@portal_attorney_bp.route("/portal/attorney/statement-notice", methods=["POST"])
@require_attorney
def portal_statement_notice():
    data   = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username = client["username"]
    if not billing.request_resend(username, str(data.get("statement_id") or "")):
        return jsonify({"error": "Notice can't be resent in its current state."}), 400
    billing.send_pending_notices(username)
    return jsonify({"success": True,
                    "billing_summary": billing.billing_summary(load_client(username),
                                                               billing.load_ledger(username))})


@portal_attorney_bp.route("/portal/attorney/billing-settings", methods=["GET", "POST"])
@require_attorney
def portal_billing_settings():
    atty = session["username"]
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = {}
        try:
            value = billing.set_threshold(atty, data.get("threshold"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"success": True, "threshold": value})
    return jsonify({"threshold": billing.get_threshold(atty),
                    "default": billing.DEFAULT_STATEMENT_THRESHOLD})


@portal_attorney_bp.route("/portal/attorney/conflict-check", methods=["POST"])
@require_attorney
def portal_conflict_check():
    data   = request.get_json() or {}
    names  = clean_names(data.get("names"))
    viewer = session["username"]
    if not names:
        return jsonify({"error": "Enter at least one name."}), 400
    username = str(data.get("username") or "").strip()
    if username:
        client = load_client_for_attorney(username)
        if not client:
            return jsonify({"error": "Client not found."}), 404
        rec = record_check(client, "manual", viewer, other_names=names)
        _log_access(client, "conflict_check", ", ".join(names))
        save_client(client)
    else:
        skipped = []
        rec = make_check_record("manual", viewer, names,
                                run_conflict_check(other_names=names, skipped=skipped))
        if skipped:
            rec["incomplete"] = len(skipped)
        append_firm_log(rec)
    return jsonify({"success": True, "check": dict(rec, hits=redact_hits(rec["hits"], viewer))})


@portal_attorney_bp.route("/portal/attorney/conflict-decision", methods=["POST"])
@require_attorney
def portal_conflict_decision():
    data   = request.get_json() or {}
    client = load_client_for_attorney(data.get("username", ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    decision = data.get("decision")
    note     = (data.get("note") or "").strip()[:1000]
    if decision not in DECISIONS:
        return jsonify({"error": "Invalid decision."}), 400
    if decision == "waiver_obtained" and not note:
        return jsonify({"error": "Describe the waiver obtained."}), 400
    for chk in client.get("conflict_checks", []):
        if chk.get("id") == data.get("check_id"):
            if chk.get("decision"):
                chk.setdefault("decision_history", []).append(
                    {k: chk.get(k) for k in ("decision", "decision_note", "decided_by", "decided_at")})
            chk.update(decision=decision, decision_note=note,
                       decided_by=session["username"],
                       decided_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            _log_access(client, "conflict_check", f"{decision} on {chk['id']}")
            save_client(client)
            return jsonify({"success": True,
                            "check": dict(chk, hits=redact_hits(chk["hits"], session["username"]))})
    return jsonify({"error": "Conflict check not found."}), 404


@portal_attorney_bp.route("/portal/attorney/archive-client", methods=["POST"])
@require_attorney
def portal_archive_client():
    username = (request.get_json() or {}).get("username", "")
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    client["archived"] = True
    _log_access(client, "edit_record", "File archived.")
    save_client(client)
    _log_activity(username, "info_updated", "Client file archived.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/unarchive-client", methods=["POST"])
@require_attorney
def portal_unarchive_client():
    username = (request.get_json() or {}).get("username", "")
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    client["archived"] = False
    _log_access(client, "edit_record", "File restored from archive.")
    save_client(client)
    _log_activity(username, "info_updated", "Client file restored from archive.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/create-client", methods=["POST"])
@require_attorney
def portal_create_client():
    data      = request.get_json() or {}
    username  = safe_username(data.get("username", ""))
    case_type = data.get("case_type", "Criminal Defense")
    if not username:
        return jsonify({"error": "Username is required."}), 400
    if (CLIENT_ACCOUNTS_DIR / f"{username}.json").exists():
        return jsonify({"error": f"Username '{username}' already exists. Please choose a different one."}), 409

    assigned_atty = CASE_ATTORNEY_MAP.get(case_type, "Endocide")
    client_folder = CLIENT_FILES_DIR / username
    client_folder.mkdir(exist_ok=True)

    first_note  = data.get("legal_issue", "").strip()
    billing_log = [{
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "hours":    0.2,
        "note":     f"Intake Processing — New Client File Opened ({case_type})",
        "type":     "intake",
        "category": "Intake",
    }]
    if first_note:
        billing_log.append({
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0,
            "note":     f"INTAKE NOTES — {case_type}.\nMatter: {first_note}",
            "type":     "intake",
            "category": "Intake",
        })

    posted_password   = (data.get("password") or "").strip()
    password_ok       = acceptable_password(posted_password, username)
    password_replaced = bool(posted_password) and not password_ok
    temp_password     = posted_password if password_ok else generate_temp_password()
    record = {
        "username":             username,
        "password":             hash_password(temp_password),
        "must_change_password": True,
        "client_name":          data.get("client_name", ""),
        "case_type":            case_type,
        "assigned_attorney":    assigned_atty,
        "opposing_parties":     clean_names(data.get("opposing_parties")
                                            or [data.get("opposing_party", "")]),
        "related_parties":      clean_related(data.get("related_parties")),
        "legal_issue":          first_note[:400],
        "next_court_date":      data.get("next_court_date", ""),
        "hours_billed":         round(sum(e.get("hours", 0) for e in billing_log), 2),
        "last_communication":   datetime.now().strftime("%Y-%m-%d"),
        "phone":                data.get("phone", ""),
        "email":                data.get("email", ""),
        "google_drive_url":     data.get("google_drive_url", ""),
        "next_meeting":         data.get("next_meeting", ""),
        "client_folder":        str(client_folder),
        "billing_log":          billing_log,
        "time_logs":            [],
        "notes":                [],
        "messages":             [],
    }

    if first_note:
        try:
            ai = get_anthropic_client()
            ai_resp = ai.messages.create(
                model=MODEL,
                max_tokens=200,
                system=(
                    "You are a legal intake analyst for a law firm. When given a client's "
                    "description of their legal matter, write a 2-3 sentence professional "
                    "summary that: (1) identifies the core legal issue(s) and any specific "
                    "charges, statutes, or claims involved, (2) notes key facts such as "
                    "prior history, urgency, or aggravating circumstances, and (3) states "
                    "the likely legal strategy or relief sought. Be specific and use proper "
                    "legal terminology. Do not use bullet points."
                ),
                messages=[{"role": "user", "content": f"Case type: {case_type}\n\nClient's description:\n{first_note}"}],
            )
            record["legal_issue_summary"] = ai_resp.content[0].text.strip()
        except Exception:
            pass

    check = record_check(record, "create", session["username"],
                         client_names=[record["client_name"] or username],
                         opposing_names=record["opposing_parties"],
                         related_names=[r["name"] for r in record["related_parties"]])
    visible_hits = redact_hits(check["hits"], session["username"])
    save_client(record)
    _log_activity(username, "intake", f"Client profile created — {case_type}.")

    court_date_val = data.get("next_court_date", "").strip()
    if court_date_val:
        gcal_id = _push_court_date_to_gcal(data.get("client_name", username), court_date_val)
        if gcal_id:
            record["court_date_gcal_event_id"] = gcal_id
            save_client(record)

    try:
        atty_display = ATTORNEYS.get(assigned_atty, {}).get("display", assigned_atty)
        pdf_fields = {
            "client_name":        data.get("client_name", ""),
            "full_name":          data.get("client_name", ""),
            "phone":              data.get("phone", ""),
            "email":              data.get("email", ""),
            "case_type":          case_type,
            "legal_issue":        first_note,
            "matter_description": first_note,
            "portal_username":    username,
            "atty_display":       atty_display,
            "case_no":            record.get("case_no", ""),
        }
        pdf_bytes = generate_client_pdf(pdf_fields)
        intake_dir = CLIENT_FILES_DIR / username / "documents" / "Intake"
        intake_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if pdf_bytes:
            (intake_dir / f"client_profile_{ts}.pdf").write_bytes(pdf_bytes)
        else:
            intake_html = generate_intake_html(pdf_fields, [], username, atty_display)
            with open(intake_dir / f"client_profile_{ts}.html", "w", encoding="utf-8") as hf:
                hf.write(intake_html)
    except Exception:
        pass

    return jsonify({"success": True, "username": username, "temp_password": temp_password,
                    "password_replaced": password_replaced,
                    "conflict_warnings": [hit_message(h) for h in visible_hits],
                    "conflict_hits": visible_hits})


@portal_attorney_bp.route("/portal/attorney/update-client", methods=["POST"])
@require_attorney
def portal_update_client():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    client   = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    _prev_court_date = client.get("next_court_date", "")
    _prev_name = client.get("client_name", "")
    for field in ("client_name", "case_type", "legal_issue", "next_court_date",
                  "phone", "email", "google_drive_url", "next_meeting",
                  "case_no", "charges", "charge_level", "county", "court"):
        if field in data:
            client[field] = data[field]
    prev_opp = set(client.get("opposing_parties") or [])
    prev_rel = {r.get("name") for r in client.get("related_parties") or []}
    if "opposing_parties" in data:
        client["opposing_parties"] = clean_names(data["opposing_parties"])
    if "related_parties" in data:
        client["related_parties"] = clean_related(data["related_parties"])
    new_opp = [n for n in client["opposing_parties"] if n not in prev_opp]
    new_rel = [r["name"] for r in client["related_parties"] if r["name"] not in prev_rel]
    conflict_hits = []
    new_client = ([client["client_name"]]
                  if client.get("client_name") and client["client_name"] != _prev_name else [])
    if new_opp or new_rel or new_client:
        chk = record_check(client, "edit", session["username"], client_names=new_client,
                           opposing_names=new_opp, related_names=new_rel)
        conflict_hits = redact_hits(chk["hits"], session["username"])
    client.setdefault("activity_log", []).append({
        "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "action_type": "info_updated",
        "description": "Client info updated.",
    })
    _log_access(client, "edit_record", "Client info updated.")
    save_client(client)

    intake_filename = None
    try:
        atty_disp = ATTORNEYS.get(client.get("assigned_attorney", ""), {}).get("display", "")
        pdf_fields = {
            "client_name":        client.get("client_name", ""),
            "full_name":          client.get("client_name", ""),
            "phone":              client.get("phone", ""),
            "email":              client.get("email", ""),
            "case_type":          client.get("case_type", ""),
            "legal_issue":        client.get("legal_issue", ""),
            "matter_description": client.get("legal_issue", ""),
            "portal_username":    username,
            "atty_display":       atty_disp,
            "case_no":            client.get("case_no", ""),
        }
        pdf_bytes = generate_client_pdf(pdf_fields)
        if pdf_bytes:
            intake_dir = _client_docs_dir(username, "Intake")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = intake_dir / f"intake_{ts}.pdf"
            pdf_path.write_bytes(pdf_bytes)
            intake_filename = pdf_path.name
    except Exception:
        pass

    new_date = data.get("next_court_date", "").strip()
    if new_date and new_date != _prev_court_date and GOOGLE_LIBS and TOKEN_FILE.exists():
        existing_id = client.get("court_date_gcal_event_id")
        if existing_id:
            try:
                service = get_calendar_service()
                upd = {
                    "summary":     f"Court Date: {client.get('client_name', username)}",
                    "description": f"Court date for client {client.get('client_name', username)} — MT Legal",
                    "start":       {"date": new_date},
                    "end":         {"date": (datetime.strptime(new_date, "%Y-%m-%d").date()
                                             + timedelta(days=1)).isoformat()},
                }
                service.events().update(
                    calendarId="primary", eventId=existing_id, body=upd
                ).execute()
                save_client(client)
            except Exception:
                pass
        else:
            gcal_id = _push_court_date_to_gcal(client.get("client_name", username), new_date)
            if gcal_id:
                client["court_date_gcal_event_id"] = gcal_id
                save_client(client)

    return jsonify({"success": True, "intake_pdf": intake_filename, "conflict_hits": conflict_hits})


@portal_attorney_bp.route("/portal/attorney/generate-summary", methods=["POST"])
@require_attorney
def portal_generate_summary():
    data     = request.get_json(force=True)
    username = data.get("username", "").strip()
    client   = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    legal_issue = (client.get("legal_issue") or "").strip()
    if not legal_issue:
        return jsonify({"error": "No legal issue on file to summarize."}), 400
    case_type = client.get("case_type", "General")
    try:
        ai = get_anthropic_client()
        ai_resp = ai.messages.create(
            model=MODEL,
            max_tokens=200,
            system=(
                "You are a legal intake analyst for a law firm. When given a client's "
                "description of their legal matter, write a 2-3 sentence professional "
                "summary that: (1) identifies the core legal issue(s) and any specific "
                "charges, statutes, or claims involved, (2) notes key facts such as "
                "prior history, urgency, or aggravating circumstances, and (3) states "
                "the likely legal strategy or relief sought. Be specific and use proper "
                "legal terminology. Do not use bullet points."
            ),
            messages=[{"role": "user", "content": f"Case type: {case_type}\n\nClient's description:\n{legal_issue}"}],
        )
        summary = ai_resp.content[0].text.strip()
    except Exception as exc:
        return jsonify({"error": f"AI unavailable: {exc}"}), 503
    client["legal_issue_summary"] = summary
    _log_access(client, "edit_record", "AI summary regenerated.")
    save_client(client)
    return jsonify({"success": True, "summary": summary})


@portal_attorney_bp.route("/portal/attorney/billing-entry", methods=["POST"])
@require_attorney
def portal_billing_entry():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    client   = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    note = data.get("note", "").strip()
    if not note:
        return jsonify({"error": "Note cannot be empty."}), 400
    hours    = round(float(data.get("hours", 0) or 0), 2)
    category = (data.get("category") or "Other").strip() or "Other"
    entry = {
        "date":     data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "hours":    hours,
        "note":     note,
        "category": category,
    }
    client.setdefault("billing_log", []).append(entry)
    recalc_hours(client)
    client["last_communication"] = datetime.now().strftime("%Y-%m-%d")
    _log_access(client, "billing_entry", f"{hours} hrs — {note[:80]}")
    save_client(client)
    _log_activity(username, "time_logged",
                  str(hours) + " hrs — " + note[:80] + ("..." if len(note) > 80 else ""))
    fresh = load_client(username) or client
    return jsonify({"success": True, "total_hours": client["hours_billed"], "entry": entry,
                    "billing_summary": billing.billing_summary(fresh, billing.load_ledger(username))})


_SCHED_CATEGORY = "Scheduling Orders"
_CASE_DATES_HISTORY_MAX = 20


def _case_date_entries(case_dates):
    """Yield (kind, entry) for well-formed case-date entries only."""
    if not isinstance(case_dates, dict):
        return
    for kind, entry in case_dates.items():
        if isinstance(kind, str) and isinstance(entry, dict):
            yield kind, entry


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@portal_attorney_bp.route("/portal/attorney/scheduling-order/extract", methods=["POST"])
@require_attorney
def portal_sched_extract():
    data   = _json_body()
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    path = resolve_doc_path(client["username"], _SCHED_CATEGORY, str(data.get("filename") or ""))
    if path is None:
        return jsonify({"error": "File not found."}), 404
    log_access_atomic(client["username"], "scheduling_order_read", path.name)
    current = dict(_case_date_entries(client.get("case_dates")))
    try:
        extraction = extract_case_dates(path)
    except ExtractionError as exc:
        return jsonify({"success": False, "error": str(exc), "current": current})
    except Exception as exc:
        print(f"scheduling-order extraction failed: {exc!r}", file=sys.stderr)
        return jsonify({"success": False, "current": current,
                        "error": "The AI reader is unavailable right now; enter the dates manually."})
    usage = extraction.pop("usage", None)
    if usage is not None:
        _log_token_usage(session["username"], "Scheduling Order Extraction", usage)
    return jsonify({"success": True, "extraction": extraction, "current": current})


def _snapshot(case_dates) -> dict:
    return {k: (v.get("date"), v.get("gcal_event_id"))
            for k, v in _case_date_entries(case_dates)}


@portal_attorney_bp.route("/portal/attorney/scheduling-order/confirm", methods=["POST"])
@require_attorney
def portal_sched_confirm():
    data   = _json_body()
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username = client["username"]
    dates = data.get("dates")
    if not isinstance(dates, dict):
        return jsonify({"error": "Dates are required."}), 400
    new = {}
    for kind in dates:
        if kind not in CASE_DATE_KINDS:
            return jsonify({"error": f"Unknown date type: {str(kind)[:40]}."}), 400
    if any(k not in dates for k in CASE_DATE_KINDS):
        return jsonify({"error": "All five dates must be sent."}), 400
    for kind, value in dates.items():
        value = str(value or "").strip()
        if not value:
            continue
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
            if not (datetime(2000, 1, 1) <= parsed <= datetime(2100, 12, 31)):
                raise ValueError
        except ValueError:
            return jsonify({"error": f"Invalid date for {CASE_DATE_LABELS[kind]}."}), 400
        new[kind] = parsed.date().isoformat()
    path = resolve_doc_path(username, _SCHED_CATEGORY, str(data.get("filename") or ""))
    if path is None:
        return jsonify({"error": "File not found."}), 404
    source = path.name

    old_entries = dict(_case_date_entries(client.get("case_dates")))
    first_snapshot = _snapshot(old_entries)
    old = {k: v.get("date") for k, v in old_entries.items()}
    if old == new:
        return jsonify({"success": True, "case_dates": old_entries, "warnings": [], "unchanged": True,
                        "case_dates_history": client.get("case_dates_history") or []})
    would_clear = [k for k in CASE_DATE_KINDS if old.get(k) and not new.get(k)]
    if would_clear and data.get("confirm_clear") is not True:
        labels = ", ".join(CASE_DATE_LABELS[k] for k in would_clear)
        return jsonify({"error": f"This would remove existing dates: {labels}. Confirm to remove them.",
                        "would_clear": would_clear}), 400

    # Google first, outside any client lock (these calls can take seconds).
    cname    = client.get("client_name") or username
    connected = gcal_connected()
    warnings  = [] if connected else ["Google Calendar not connected — dates saved in the app only; "
                                  "update or remove any existing calendar events manually."]
    created   = []
    event_ids = {}
    for kind in CASE_DATE_KINDS:
        before, after = old.get(kind), new.get(kind)
        if before == after:
            continue
        old_id = (old_entries.get(kind) or {}).get("gcal_event_id")
        label  = CASE_DATE_LABELS[kind]
        summary = f"{label}: {cname}"
        desc    = f"{label} for {cname} — from {source} — MT Legal"
        if not connected:
            event_ids[kind] = old_id if after else None
            continue
        if after and old_id:
            outcome = gcal_update_all_day(old_id, summary, desc, after)
            if outcome == "ok":
                event_ids[kind] = old_id
            elif outcome == "gone":
                new_id = gcal_create_all_day(summary, desc, after)
                if new_id:
                    created.append(new_id)
                else:
                    warnings.append(f"Google Calendar event for {label} could not be created.")
                event_ids[kind] = new_id
            else:
                event_ids[kind] = old_id
                warnings.append(f"Google Calendar event for {label} could not be moved — "
                                "update it manually.")
        elif after:
            new_id = gcal_create_all_day(summary, desc, after)
            if new_id:
                created.append(new_id)
            else:
                warnings.append(f"Google Calendar event for {label} could not be created.")
            event_ids[kind] = new_id
        elif old_id:
            if gcal_delete_event(old_id) == "error":
                warnings.append(f"Google Calendar event for {label} ({before}) may be left behind "
                                "— delete it manually.")

    # Re-load and verify nobody else confirmed in between.
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if _snapshot(client.get("case_dates") or {}) != first_snapshot:
        for event_id in created:
            gcal_delete_event(event_id)
        return jsonify({"error": "These dates were just changed by someone else. Reload and "
                                 "try again (check Google Calendar if any events were moved)."}), 409

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    current = dict(_case_date_entries(client.get("case_dates")))
    if current:
        history = client.setdefault("case_dates_history", [])
        history.append({"replaced_at": now, "replaced_by": session["username"],
                        "previous": json.loads(json.dumps(current))})
        del history[:-_CASE_DATES_HISTORY_MAX]
    updated = dict(current)
    for kind in CASE_DATE_KINDS:
        if old.get(kind) == new.get(kind):
            continue
        if new.get(kind):
            updated[kind] = {"date": new[kind], "gcal_event_id": event_ids.get(kind),
                             "source": source, "confirmed_by": session["username"],
                             "confirmed_at": now}
        else:
            updated.pop(kind, None)
    client["case_dates"] = updated
    if any(new.get(k) and new.get(k) != old.get(k) for k in CASE_DATE_KINDS):
        client.setdefault("billing_log", []).append({
            "date": date.today().isoformat(), "hours": 0.2,
            "note": f"Scheduling order review — {source}",
            "category": "Filing", "type": "scheduling_order"})
        recalc_hours(client)
    _log_access(client, "case_dates_confirmed", source)
    save_client(client)
    _log_activity(username, "case_dates_updated", f"Case dates updated from {source}.")
    return jsonify({"success": True, "case_dates": updated, "warnings": warnings,
                    "case_dates_history": client.get("case_dates_history") or []})


@portal_attorney_bp.route("/portal/attorney/leads-list")
@require_attorney
def portal_leads_list():
    atty_user = session.get("attorney") or session.get("username", "")
    leads = []
    for p in sorted(LEADS_DIR.glob("*.json"), reverse=True):
        lead = read_json(p)
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
    lead_path = LEADS_DIR / filename
    if not lead_path.exists():
        return jsonify({"error": "Lead not found."}), 404
    try:
        lead = read_json(lead_path) or {}
        if lead.get("assigned_attorney") != session["username"]:
            return jsonify({"error": "Lead not found."}), 404
        lead["archived"] = True
        write_json(lead_path, lead)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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


# ── Document management ────────────────────────────────────────────────────────

@portal_attorney_bp.route("/portal/attorney/documents/<username>")
@require_attorney
def list_documents(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    log_access_atomic(client["username"], "view_documents")
    uname  = client["username"]
    result = {}
    for cat in DOCS_CATEGORIES:
        cat_dir = CLIENT_FILES_DIR / uname / "documents" / cat
        files   = []
        if uname and cat_dir.exists():
            for f in sorted(cat_dir.iterdir()):
                if f.is_file():
                    st = f.stat()
                    files.append({
                        "name":     f.name,
                        "size":     st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                        "category": cat,
                    })
        result[cat] = files
    return jsonify({"categories": DOCS_CATEGORIES, "files": result})


@portal_attorney_bp.route("/portal/attorney/upload-document", methods=["POST"])
@require_attorney
def upload_document():
    username = safe_username(request.form.get("username", ""))
    category = request.form.get("category", "Other").strip()
    if category not in DOCS_CATEGORIES:
        category = "Other"
    if not username:
        return jsonify({"error": "Username required."}), 400
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected."}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        return jsonify({"error": f"File type '{ext}' not allowed."}), 400
    safe_name = secure_filename(file.filename)
    dest_dir  = _client_docs_dir(username, category)
    dest      = dest_dir / safe_name
    stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
    n = 2
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}{suffix}"
        n += 1
    file.save(str(dest))
    st = dest.stat()

    client = load_client(client["username"])
    if client is None:
        return jsonify({"error": "Client not found."}), 404
    entry = {
        "date":     datetime.now().strftime("%Y-%m-%d"),
        "hours":    0.1,
        "note":     f"{category} — \"{dest.name}\" uploaded.",
        "type":     "document_upload",
        "category": "Filing",
    }
    client.setdefault("billing_log", []).append(entry)
    recalc_hours(client)
    _log_access(client, "document_upload", f"{category}/{dest.name}")
    save_client(client)
    _log_activity(username, "document_upload", f"{category} — \"{dest.name}\" uploaded.")
    billing_entry = entry
    total_hours   = client["hours_billed"]

    return jsonify({
        "success": True,
        "file": {
            "name":     dest.name,
            "size":     st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
            "category": category,
        },
        "billing_entry": billing_entry,
        "total_hours":   total_hours,
    })


@portal_attorney_bp.route("/portal/attorney/delete-document", methods=["POST"])
@require_attorney
def delete_document():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    category = data.get("category", "").strip()
    filename = data.get("filename", "").strip()
    if not all([username, category, filename]):
        return jsonify({"error": "Missing parameters."}), 400
    client = load_client_for_attorney(username, assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return jsonify({"error": "File not found."}), 404
    safe_name = path.name
    path.unlink()
    _log_access(client, "document_delete", f"{category}/{safe_name}")
    save_client(client)
    _log_activity(username, "document_delete", f"{category} — \"{safe_name}\" deleted.")
    return jsonify({"success": True})


@portal_attorney_bp.route("/portal/attorney/document/<username>/<category>/<filename>")
@require_attorney
def serve_document(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "download_document", f"{category}/{path.name}")
    return send_file(str(path), as_attachment=True, download_name=path.name)


@portal_attorney_bp.route("/portal/attorney/preview/<username>/<category>/<filename>")
@require_attorney
def preview_document(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "view_document_preview", f"{category}/{path.name}")
    return send_file(str(path), as_attachment=False)


@portal_attorney_bp.route("/portal/attorney/docx-preview/<username>/<category>/<filename>")
@require_attorney
def docx_preview(username, category, filename):
    client = load_client_for_attorney(username)
    if not client:
        return "File not found.", 404
    if not MAMMOTH_AVAILABLE:
        return "mammoth not installed — run: python -m pip install mammoth", 503
    path = resolve_doc_path(client["username"], category, filename)
    if path is None:
        return "File not found.", 404
    log_access_atomic(client["username"], "view_document_preview", f"{category}/{path.name}")
    safe_name = path.name
    try:
        import mammoth
        with open(path, "rb") as f:
            result = mammoth.convert_to_html(f)
        body_html = result.value
        page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{safe_name}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem 2.5rem; color: #222;
           line-height: 1.65; font-size: .93rem; max-width: 820px; }}
    h1,h2,h3 {{ font-family: Georgia, serif; color: #1a2d5a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    td, th {{ border: 1px solid #ccc; padding: .4rem .65rem; }}
    p {{ margin: .45rem 0; }}
    strong {{ color: #111; }}
  </style>
</head>
<body>{body_html}</body>
</html>"""
        return page, 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as exc:
        return f"Could not convert document: {str(exc)}", 500
