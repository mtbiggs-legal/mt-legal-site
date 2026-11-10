"""blueprints/auth.py — attorney login (password + authenticator code), client
login, logout, and portal invitations."""

from flask import Blueprint, render_template, request, redirect, url_for, session

import shared
from shared import ATTORNEYS, portal_public
from services import audit, two_factor
from services.accounts import (
    acceptable_password, check_password, check_invite, hash_password, redeem_invite,
    MIN_PASSWORD_LENGTH,
)
from services.storage import load_client, _log_activity
from services.security import (
    begin_login_attempt, clear_login_failures, lockout_message, reset_session,
    start_login_session, _now,
)

auth_bp = Blueprint("auth", __name__)

_DUMMY_HASH = None
# How long the password step stays good while the attorney finds their phone.
MFA_PENDING_SECONDS = 5 * 60


def _dummy_check(password: str) -> None:
    """Burn the same hashing time for unknown usernames (anti-enumeration)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    check_password(password, _DUMMY_HASH)


# ── Attorney: password, then authenticator code ───────────────────────────────

def _begin_mfa(username: str) -> None:
    """Password checked; no role yet. Only the code step can finish the login."""
    reset_session()
    session["mfa_user"] = username
    session["mfa_at"]   = _now()


def _mfa_user():
    """The attorney waiting at the code step, if the password step is recent."""
    user = session.get("mfa_user")
    if not user or user not in ATTORNEYS or _now() - session.get("mfa_at", 0) > MFA_PENDING_SECONDS:
        return None
    return user


@auth_bp.route("/attorney-login", methods=["GET", "POST"])
@portal_public
def attorney_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip       = request.remote_addr or ""
        wait     = begin_login_attempt("attorney", username, ip)
        if wait:
            audit.record("login_locked", detail=f"attorney {username}", actor=username, role="")
            return render_template("attorney_login.html", error=lockout_message(wait)), 429
        atty = ATTORNEYS.get(username)
        if not atty:
            _dummy_check(password)
        if atty and check_password(password, atty["password"]):
            clear_login_failures("attorney", username, ip)
            audit.record("login_password_ok", actor=username, role="attorney")
            if two_factor.is_enabled(username):
                _begin_mfa(username)
                return redirect(url_for("auth.attorney_totp"))
            if shared.ATTORNEY_2FA_REQUIRED:
                _begin_mfa(username)
                return redirect(url_for("auth.attorney_totp_setup"))
            start_login_session("attorney", username)
            audit.record("login", actor=username, role="attorney", detail="password only (2FA off)")
            return redirect(url_for("portal_attorney.attorney_portal"))
        audit.record("login_failed", detail=f"attorney {username}"[:100], actor=username, role="")
        error = "Invalid username or password."
    return render_template("attorney_login.html", error=error)


@auth_bp.route("/attorney-login/verify", methods=["GET", "POST"])
@portal_public
def attorney_totp():
    username = _mfa_user()
    if not username or not two_factor.is_enabled(username):
        return redirect(url_for("auth.attorney_login"))
    error = None
    if request.method == "POST":
        ip   = request.remote_addr or ""
        wait = begin_login_attempt("totp", username, ip)
        if wait:
            return render_template("attorney_totp.html", error=lockout_message(wait)), 429
        if two_factor.verify(username, request.form.get("code", "")):
            clear_login_failures("totp", username, ip)
            start_login_session("attorney", username)
            audit.record("login", actor=username, role="attorney", detail="password + code")
            return redirect(url_for("portal_attorney.attorney_portal"))
        audit.record("login_code_failed", actor=username, role="")
        error = "That code didn't work. Use the current code from your app, or a recovery code."
    return render_template("attorney_totp.html", error=error)


@auth_bp.route("/attorney-login/setup", methods=["GET", "POST"])
@portal_public
def attorney_totp_setup():
    """First sign-in after 2FA became required: add the firm to an
    authenticator app, confirm one code, and save the recovery codes."""
    username = _mfa_user()
    if not username or two_factor.is_enabled(username):
        return redirect(url_for("auth.attorney_login"))
    secret = two_factor.pending_secret(username)
    error  = None
    if request.method == "POST":
        ip   = request.remote_addr or ""
        wait = begin_login_attempt("totp", username, ip)
        if wait:
            error = lockout_message(wait)
        else:
            codes = two_factor.confirm_setup(username, request.form.get("code", ""))
            if codes:
                clear_login_failures("totp", username, ip)
                start_login_session("attorney", username)
                audit.record("two_factor_enabled", actor=username, role="attorney")
                return render_template("attorney_totp_setup.html", recovery_codes=codes)
            error = "That code didn't match. Check the app shows MT Legal and try the current code."
    return render_template("attorney_totp_setup.html", secret=secret, error=error,
                           uri=two_factor.provisioning_uri(secret, username))


# ── Client ────────────────────────────────────────────────────────────────────

@auth_bp.route("/client-login", methods=["GET", "POST"])
@portal_public
def client_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip       = request.remote_addr or ""
        wait     = begin_login_attempt("client", username, ip)
        if wait:
            audit.record("login_locked", client=username if load_client(username) else "",
                         detail=f"client {username}"[:100], actor=username, role="")
            return render_template("client_login.html", error=lockout_message(wait)), 429
        client = load_client(username)
        if not client:
            _dummy_check(password)
        if client and check_password(password, client.get("password", "")):
            clear_login_failures("client", username, ip)
            start_login_session("client", username)
            audit.record("login", client=username, actor=username, role="client")
            if client.get("must_change_password"):
                return redirect(url_for("portal_client.client_change_password"))
            return redirect(url_for("portal_client.client_portal"))
        audit.record("login_failed", client=username if client else "",
                     detail=f"client {username}"[:100], actor=username, role="")
        error = "Invalid username or password."
    return render_template("client_login.html", error=error)


@auth_bp.route("/logout", methods=["POST"])
@portal_public
def logout():
    """POST only (with the CSRF token), so another site can't sign you out."""
    role = session.get("role")
    if role:
        audit.record("logout", client=session.get("username", "") if role == "client" else "")
    reset_session()
    if role == "attorney":
        return redirect(url_for("auth.attorney_login"))
    return redirect(url_for("auth.client_login"))


# ── Invitations ───────────────────────────────────────────────────────────────
# New client accounts have no password; the client chooses one here through
# the single-use link emailed when the attorney opens the account.

@auth_bp.route("/client-portal/invite/<token>", methods=["GET", "POST"])
@portal_public
def accept_invite(token):
    client = check_invite(token)
    if not client:
        return render_template("accept_invite.html", invalid=True), 404
    error = None
    if request.method == "POST":
        new_pw  = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not acceptable_password(new_pw, client["username"]):
            error = (f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters "
                     "that isn't a common one or your username.")
        elif new_pw != confirm:
            error = "Passwords do not match."
        else:
            username = redeem_invite(token, new_pw)
            if not username:
                return render_template("accept_invite.html", invalid=True), 404
            _log_activity(username, "invite_accepted", "Client set a portal password.")
            audit.record("invite_accepted", client=username, actor=username, role="client")
            start_login_session("client", username)
            return redirect(url_for("portal_client.client_portal"))
    return render_template("accept_invite.html", invalid=False, error=error,
                           username=client["username"])
