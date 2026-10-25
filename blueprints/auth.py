"""blueprints/auth.py — Attorney login, client login, logout, client registration."""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify

from shared import (
    ATTORNEYS, CASE_ATTORNEY_MAP, MIN_PASSWORD_LENGTH,
    load_client, save_client, hash_password, check_password, upgrade_password_if_needed,
    _make_username, _log_activity,
)

from conflicts import record_check
from security import start_login_session, begin_login_attempt, clear_login_failures, lockout_message

auth_bp = Blueprint("auth", __name__)

_DUMMY_HASH = None


def _dummy_check(password: str) -> None:
    """Burn the same hashing time for unknown usernames (anti-enumeration)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    check_password(password, _DUMMY_HASH)


@auth_bp.route("/attorney-login", methods=["GET", "POST"])
def attorney_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        ip       = request.remote_addr or ""
        wait     = begin_login_attempt("attorney", username, ip)
        if wait:
            return render_template("attorney_login.html", error=lockout_message(wait)), 429
        atty = ATTORNEYS.get(username)
        if not atty:
            _dummy_check(password)
        if atty and check_password(password, atty["password"]):
            clear_login_failures("attorney", username, ip)
            start_login_session("attorney", username)
            return redirect(url_for("portal_attorney.attorney_portal"))
        error = "Invalid username or password."
    return render_template("attorney_login.html", error=error)


@auth_bp.route("/client-login", methods=["GET", "POST"])
def client_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        ip       = request.remote_addr or ""
        wait     = begin_login_attempt("client", username, ip)
        if wait:
            return render_template("client_login.html", error=lockout_message(wait)), 429
        client = load_client(username)
        if not client:
            _dummy_check(password)
        if client and check_password(password, client.get("password", "")):
            clear_login_failures("client", username, ip)
            upgrade_password_if_needed(client, password)
            start_login_session("client", username)
            if client.get("must_change_password"):
                return redirect(url_for("portal_client.client_change_password"))
            return redirect(url_for("portal_client.client_portal"))
        error = "Invalid username or password."
    return render_template("client_login.html", error=error)


@auth_bp.route("/logout")
def logout():
    role = session.get("role")
    session.clear()
    if role == "attorney":
        return redirect(url_for("auth.attorney_login"))
    return redirect(url_for("auth.client_login"))


@auth_bp.route("/client-register", methods=["POST"])
def client_register():
    data      = request.get_json() or {}
    full_name = data.get("full_name", "").strip()
    password  = data.get("password", "").strip()
    email     = data.get("email", "").strip()
    phone     = data.get("phone", "").strip()
    case_type = data.get("case_type", "Other").strip()

    if not full_name or not password:
        return jsonify({"error": "Full name and password are required."}), 400
    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "error": f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        }), 400

    # _make_username already guarantees a name that is not taken.
    username = _make_username(full_name)

    atty         = CASE_ATTORNEY_MAP.get(case_type, "Endocide")
    atty_display = ATTORNEYS[atty]["display"]
    now_str      = datetime.now().strftime("%Y-%m-%d")

    record = {
        "username":             username,
        "password":             hash_password(password),
        "must_change_password": False,
        "client_name":          full_name,
        "case_type":            case_type,
        "assigned_attorney":    atty,
        "legal_issue":          data.get("legal_issue", ""),
        "legal_issue_summary":  "",
        "next_court_date":      "",
        "hours_billed":         0,
        "last_communication":   now_str,
        "phone":                phone,
        "email":                email,
        "google_drive_url":     "",
        "next_meeting":         "",
        "time_logs":            [],
        "notes":                [],
        "billing_log":          [],
        "activity_log":         [],
        "messages": [{
            "from": "attorney",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "text": (
                f"Welcome to your MT Legal client portal. I'm {atty_display}. "
                "We look forward to assisting you with your legal matter."
            ),
        }],
    }
    record_check(record, "self_register", "public", client_names=[full_name])
    save_client(record)
    _log_activity(username, "registration", "Client self-registered via portal.")

    return jsonify({
        "success":  True,
        "username": username,
        "attorney": atty_display,
    })
