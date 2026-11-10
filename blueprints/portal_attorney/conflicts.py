"""blueprints/portal_attorney/conflicts.py — Manual conflict checks and conflict decisions."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401


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
