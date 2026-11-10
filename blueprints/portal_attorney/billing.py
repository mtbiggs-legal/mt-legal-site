"""blueprints/portal_attorney/billing.py — Statements, flat fees, payments, billing settings, time entries and their review."""

from ._common import *  # noqa: F401,F403 - shared imports and the blueprint
from ._common import portal_attorney_bp  # noqa: F401


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


def _billing_payload(username):
    fresh = load_client(username)
    return {"success": True,
            "billing_summary": billing.billing_summary(fresh, billing.load_ledger(username))}


@portal_attorney_bp.route("/portal/attorney/flat-fee", methods=["POST"])
@require_attorney
def portal_flat_fee():
    """Set, change or remove a client's flat fee."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    username = client["username"]
    if data.get("action") == "remove":
        billing.clear_flat_fee(username)
        log_access_atomic(username, "flat_fee_removed")
        return jsonify(_billing_payload(username))
    try:
        billing.set_flat_fee(username, data.get("amount"), str(data.get("plan") or ""),
                             str(data.get("due_date") or ""), str(data.get("description") or ""),
                             set_by=session["username"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_access_atomic(username, "flat_fee_set", f"${float(data.get('amount')):,.2f}")
    return jsonify(_billing_payload(username))


MAX_MANUAL_PAYMENT = 1_000_000.0


PAYMENT_METHODS = ("check", "cash", "card", "wire", "zelle", "venmo", "money order", "other")


@portal_attorney_bp.route("/portal/attorney/record-payment", methods=["POST"])
@require_attorney
def portal_record_payment():
    """Record a payment received outside the portal (check, cash, wire...)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    client = load_client_for_attorney(str(data.get("username") or ""))
    if not client:
        return jsonify({"error": "Client not found."}), 404
    try:
        amount = round(float(data.get("amount")), 2)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a dollar amount."}), 400
    if not (0 < amount <= MAX_MANUAL_PAYMENT):
        return jsonify({"error": "Amount must be more than $0."}), 400
    method = str(data.get("method") or "check").strip().lower()
    if method not in PAYMENT_METHODS:
        return jsonify({"error": "Unknown payment method."}), 400
    ref = re.sub(r"[^\w .#/-]", "", str(data.get("reference") or ""))[:60].strip()
    reference = ref or f"manual-{datetime.now():%Y%m%d%H%M%S%f}"
    username = client["username"]
    if not _apply_payment(username, amount, method, reference):
        return jsonify({"error": f"A payment with reference {ref!r} is already recorded."}), 400
    log_access_atomic(username, "payment_recorded", f"${amount:,.2f} {method}")
    return jsonify(_billing_payload(username))


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


@portal_attorney_bp.route("/portal/attorney/time-entry/review", methods=["POST"])
@require_attorney
def portal_review_time_entry():
    """Approve (bill) or reject (never bill) time the portal logged by itself."""
    data   = request.get_json(silent=True) or {}
    client = load_client_for_attorney(str(data.get("username") or ""), assigned_only=True)
    if not client:
        return jsonify({"error": "Client not found."}), 404
    entry = billing.review_auto_entry(client["username"], str(data.get("id") or ""),
                                      bool(data.get("approve")), session["username"])
    if not entry:
        return jsonify({"error": "That entry isn't waiting for review."}), 404
    log_access_atomic(client["username"], "time_entry_reviewed",
                      ("approved " if data.get("approve") else "rejected ") + entry.get("note", "")[:80])
    return jsonify({"success": True, "entry": entry})
