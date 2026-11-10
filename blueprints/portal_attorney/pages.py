"""blueprints/portal_attorney/pages.py — The attorney portal page and its dashboard."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401
from .clients import _admin_items
from .scheduling import _case_date_entries


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
                    log.warning("Ignored error in portal_attorney", exc_info=True)
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
            base = shared.CLIENT_FILES_DIR / c.get("username", "") / "documents"
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
            "action_items":     _admin_items() + felony.pending_reviews(my_clients),
        })
    except Exception as exc:
        # Log the full traceback server-side; don't ship it to the browser.
        current_app.logger.exception("Attorney dashboard failed")
        return jsonify({"error": "Could not build the dashboard. The details are in the server log."}), 500
