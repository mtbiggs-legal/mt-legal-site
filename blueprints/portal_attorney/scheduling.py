"""blueprints/portal_attorney/scheduling.py — Scheduling orders: extract case dates from an order, confirm them."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401


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
        client.setdefault("billing_log", []).append(billing.auto_entry(
            date=date.today().isoformat(), hours=0.2,
            note=f"Scheduling order review — {source}",
            category="Filing", type="scheduling_order"))
        recalc_hours(client)
    _log_access(client, "case_dates_confirmed", source)
    save_client(client)
    _log_activity(username, "case_dates_updated", f"Case dates updated from {source}.")
    return jsonify({"success": True, "case_dates": updated, "warnings": warnings,
                    "case_dates_history": client.get("case_dates_history") or []})
