"""blueprints/portal_attorney/clients.py — Client list, record, create/update/archive, invitations, co-counsel, felony checklist."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401


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
    view["felony_checklist"] = felony.checklist_view(client)
    return jsonify(view)


def _admin_items() -> list:
    """Firm admin reminders for the dashboard's Action Items (never fails the dashboard)."""
    try:
        return [{"kind": "admin", "client_name": r["title"], "text": r["text"], "stage": r["stage"]}
                for r in firm_admin.reminders()]
    except Exception:
        current_app.logger.exception("Firm admin reminders failed")
        return []


def _felony_payload(username):
    fresh = load_client(username) or {}
    return {"success": True, "felony_checklist": felony.checklist_view(fresh),
            "discovery_draft": fresh.get("discovery_draft")}


@portal_attorney_bp.route("/portal/attorney/felony-checklist", methods=["POST"])
@require_attorney
def portal_felony_checklist():
    """Check or uncheck a felony checklist item. Checking "arraigned" drafts
    the discovery request (through the save hook) if it isn't drafted yet."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    try:
        felony.set_item(client["username"], str(data.get("key") or ""), bool(data.get("done")),
                        session["username"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(_felony_payload(client["username"]))


@portal_attorney_bp.route("/portal/attorney/discovery-reviewed", methods=["POST"])
@require_attorney
def portal_discovery_reviewed():
    """Clear the dashboard notice for an automatic discovery draft."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    felony.mark_reviewed(client["username"])
    return jsonify(_felony_payload(client["username"]))


@portal_attorney_bp.route("/portal/attorney/access-log/<username>")
@require_attorney
def portal_access_log(username):
    client = load_client_for_attorney(username)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    from services import audit
    return jsonify(audit.for_client(client["username"]))


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
    posted    = (data.get("username") or "").strip()
    username  = safe_username(posted) if posted else new_client_username()
    case_type = data.get("case_type", "Criminal Defense")
    if not username or username != posted and posted:
        return jsonify({"error": "Usernames may use only letters, numbers, - and _."}), 400
    if storage.client_exists(username):
        return jsonify({"error": f"Username '{username}' already exists. Please choose a different one."}), 409

    assigned_atty = CASE_ATTORNEY_MAP.get(case_type, MANAGING_PARTNER["username"])

    first_note  = data.get("legal_issue", "").strip()
    billing_log = [billing.auto_entry(
        date=datetime.now().strftime("%Y-%m-%d"), hours=0.2,
        note=f"Intake Processing — New Client File Opened ({case_type})",
        type="intake", category="Intake")]
    if first_note:
        billing_log.append({
            "date":     datetime.now().strftime("%Y-%m-%d"),
            "hours":    0,
            "note":     f"INTAKE NOTES — {case_type}.\nMatter: {first_note}",
            "type":     "intake",
            "category": "Intake",
        })

    # No password: the client chooses one through the emailed invitation.
    record = {
        "username":             username,
        "password":             "",
        "must_change_password": False,
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
            log.warning("Ignored error in portal_attorney", exc_info=True)

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
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if pdf_bytes:
            client_files.write(username, "Intake", f"client_profile_{ts}.pdf", pdf_bytes)
        else:
            intake_html = generate_intake_html(pdf_fields, [], username, atty_display)
            client_files.write(username, "Intake", f"client_profile_{ts}.html",
                               intake_html.encode("utf-8"))
    except Exception:
        current_app.logger.exception("Could not save the client profile PDF")

    invite = _send_invite(record)
    return jsonify({"success": True, "username": username,
                    "invite_sent": invite["sent"], "invite_link": invite["link"],
                    "conflict_warnings": [hit_message(h) for h in visible_hits],
                    "conflict_hits": visible_hits})


def _send_invite(client: dict) -> dict:
    """Issue a fresh invitation for `client` and email it if there's an address.
    The link is also returned so the attorney can hand it over another way."""
    token = issue_invite(client["username"])
    if not token:
        return {"sent": False, "link": ""}
    link = invite_url(token)
    sent = False
    if client.get("email"):
        try:
            sent = send_invite_email(name=client.get("client_name", ""), email=client["email"],
                                     username=client["username"], link=link)
        except Exception:
            current_app.logger.exception("Invitation email failed")
    log_access_atomic(client["username"], "invite_issued", "emailed" if sent else "link only")
    return {"sent": bool(sent), "link": link}


@portal_attorney_bp.route("/portal/attorney/send-invite", methods=["POST"])
@require_attorney
def portal_send_invite():
    """(Re)send a portal invitation, e.g. if it expired or the client lost it.
    Any earlier link stops working."""
    client = load_client_for_attorney(((request.get_json(silent=True) or {}).get("username") or ""),
                                      assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    result = _send_invite(client)
    return jsonify({"success": True, "invite_sent": result["sent"], "invite_link": result["link"]})


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
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = client_files.write(username, "Intake", f"intake_{ts}.pdf", pdf_bytes)
            intake_filename = pdf_path.name
    except Exception:
        log.warning("Ignored error in portal_attorney", exc_info=True)

    new_date = data.get("next_court_date", "").strip()
    if new_date and new_date != _prev_court_date and GOOGLE_LIBS and shared.TOKEN_FILE.exists():
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
                log.warning("Ignored error in portal_attorney", exc_info=True)
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
        current_app.logger.exception("Summary generation failed")
        return jsonify({"error": "The AI service is unavailable right now."}), 503
    client["legal_issue_summary"] = summary
    _log_access(client, "edit_record", "AI summary regenerated.")
    save_client(client)
    return jsonify({"success": True, "summary": summary})
