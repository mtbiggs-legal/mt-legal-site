"""app.py — Flask application factory: registers all blueprints."""

import os
from datetime import timedelta
from flask import Flask, abort, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

import security
import shared

from blueprints.auth            import auth_bp
from blueprints.public          import public_bp
from blueprints.intake          import intake_bp
from blueprints.research        import research_bp
from blueprints.drafting        import drafting_bp
from blueprints.calendar        import calendar_bp
from blueprints.portal_client   import portal_client_bp
from blueprints.portal_attorney import portal_attorney_bp

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config.update(
    SESSION_COOKIE_HTTPONLY    = True,
    SESSION_COOKIE_SAMESITE    = "Lax",
    # Shared mode serves HTTPS (see __main__), and production sits behind the
    # host's HTTPS proxy, so the cookie can be Secure in both.
    SESSION_COOKIE_SECURE      = bool(os.getenv("SHARE_PASSWORD", "").strip()) or shared.IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30),
)
security.init_app(app)

if shared.IS_PRODUCTION:
    # Trust the hosting proxy's X-Forwarded-* headers so url_for() builds https
    # links and request.is_secure is true.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.after_request
    def _hsts(resp):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


# Routes that stay off while PUBLIC_SITE_ONLY is set: logins, both portals, the
# attorney-only tools, and the calendar integration.
_PRIVATE_PREFIXES = (
    "/portal", "/client-portal", "/attorney-portal", "/attorney-login", "/client-login",
    "/client-register", "/logout", "/webhooks", "/research", "/drafting", "/calendar",
    "/api/page-visits",
)


@app.before_request
def _public_site_only():
    if shared.PUBLIC_SITE_ONLY and request.path.startswith(_PRIVATE_PREFIXES):
        abort(404)


# ── Static file caching ──────────────────────────────────────────────────────
# url_for('static', ...) adds ?v=<file modified time>, so a changed file gets a
# new URL. Versioned URLs can then be cached for a year; anything requested
# without a version (e.g. url() references inside CSS) is cached for a day.

@app.url_defaults
def _version_static_urls(endpoint, values):
    if endpoint == "static" and "filename" in values and "v" not in values:
        path = os.path.join(app.static_folder, values["filename"])
        try:
            values["v"] = int(os.path.getmtime(path))
        except OSError:
            pass


@app.after_request
def _cache_static(resp):
    if request.endpoint == "static" and resp.status_code in (200, 304):
        resp.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if request.args.get("v")
            else "public, max-age=86400")
    return resp


@app.route("/healthz")
def healthz():
    """Uptime check for the hosting platform. Also reports which deployment
    modes are active (yes/no flags only, never values) to diagnose settings."""
    return {
        "ok":               True,
        "production":       shared.IS_PRODUCTION,
        "public_site_only": shared.PUBLIC_SITE_ONLY,
        "persistent_data":  shared.DATA_ROOT != shared.BASE_DIR,
    }


@app.context_processor
def _firm_identity():
    """Firm and managing-partner names for every template (see shared.py)."""
    return {
        "firm_name":        shared.FIRM_NAME,
        "firm_tagline":     shared.FIRM_TAGLINE,
        "partner":          shared.MANAGING_PARTNER,
        "partners":         shared.PARTNERS,
        "partner_photo":    shared.partner_photo_filename(),
        "service_counties": shared.SERVICE_COUNTIES,
        "public_site_only": shared.PUBLIC_SITE_ONLY,
    }


@app.errorhandler(shared.RecordDecryptError)
def _record_decrypt_error(exc):
    print(f"[error] could not decrypt client record: {exc}", flush=True)
    return jsonify({"error": "Client record could not be decrypted."}), 500


def check_startup_config() -> list:
    """Return human-readable problems that must be fixed before serving."""
    problems = []
    if not os.getenv("SECRET_KEY", "").strip():
        problems.append(
            "SECRET_KEY is not set in .env. Generate one with:\n"
            '    python -c "import secrets; print(secrets.token_hex(32))"')
    if not os.getenv("DATA_ENCRYPTION_KEY", "").strip():
        problems.append(
            "DATA_ENCRYPTION_KEY is not set in .env. Generate one with:\n"
            "    python scripts/generate_data_key.py\n"
            "  Back the key up OUTSIDE this folder — if it is lost, encrypted\n"
            "  client records cannot be recovered.")
    else:
        shared._fernet_cache = None
        try:
            shared._fernet()
        except RuntimeError as exc:
            problems.append(str(exc))
    plaintext = 0
    for path in shared.CLIENT_ACCOUNTS_DIR.glob("*.json"):
        raw = path.read_bytes()
        if shared._is_plaintext(raw):
            plaintext += 1
    if plaintext:
        problems.append(
            f"{plaintext} client record(s) are not yet encrypted. Back up and encrypt them first:\n"
            "    python scripts/encrypt_existing_records.py --backup-dir <folder outside OneDrive>")
    import billing
    if not billing.is_migrated():
        if not any(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")):
            billing.mark_migrated()          # fresh install: nothing to migrate
        else:
            problems.append(
                "Opening statements have not been issued. Stop here and run:\n"
                "    python scripts/issue_opening_statements.py --backup-dir <folder outside OneDrive>")
    return problems


def startup_warnings() -> list:
    """Problems worth showing at startup that must not stop the app."""
    warnings = []
    for username, atty in shared.ATTORNEYS.items():
        if not atty.get("password"):
            warnings.append(f"ATTORNEY_{username.upper()}_HASH is not set — "
                            f"attorney {username} cannot log in.")
    return warnings

app.register_blueprint(auth_bp)
app.register_blueprint(public_bp)
app.register_blueprint(intake_bp)
app.register_blueprint(research_bp)
app.register_blueprint(drafting_bp)
app.register_blueprint(calendar_bp)
app.register_blueprint(portal_client_bp)
app.register_blueprint(portal_attorney_bp)

# Under a production WSGI server (gunicorn) __main__ never runs, so check the
# configuration at import time and refuse to start if secrets are missing.
if shared.IS_PRODUCTION:
    _problems = check_startup_config()
    if _problems:
        raise RuntimeError("Cannot start in production:\n  * " + "\n  * ".join(_problems))

if __name__ == "__main__":
    problems = check_startup_config()
    if problems:
        print("\nCannot start — fix these in .env:\n")
        for p in problems:
            print("  * " + p + "\n")
        raise SystemExit(1)
    for w in startup_warnings():
        print(f"[warn] {w}")
    skipped  = []
    upgraded = shared.upgrade_all_plaintext_passwords(skipped=skipped)
    if upgraded:
        print(f"Secured {len(upgraded)} plaintext client password(s); those clients "
              "must choose a new password at next login.")
    if skipped:
        print(f"[warn] Could not read {len(skipped)} client record(s): {', '.join(skipped)}")

    # Setting SHARE_PASSWORD switches the app to "shared" mode: it listens on
    # every interface AND serves HTTPS with a self-signed certificate. That means
    # the address changes from http:// to https:// — print it so it is obvious.
    sharing = bool(os.getenv("SHARE_PASSWORD", "").strip())
    host    = "0.0.0.0" if sharing else "127.0.0.1"
    ssl_ctx = "adhoc"   if sharing else None
    scheme  = "https"   if sharing else "http"

    print("\n" + "=" * 62)
    print(f"  {shared.FIRM_NAME} app  ->  {scheme}://127.0.0.1:5000")
    if sharing:
        print("  Shared mode is ON (SHARE_PASSWORD is set in .env):")
        print("    * You must use https:// — http:// will not connect.")
        print("    * Your browser will warn about the self-signed certificate;")
        print("      choose 'Advanced' -> 'Proceed' to continue.")
        print("    * You will then be asked for the share password.")
        print("    * Remove SHARE_PASSWORD from .env for plain local http://.")
    else:
        print("  Local mode (no SHARE_PASSWORD set) — plain http, this machine only.")
    print("  Tip: if the page stops loading, click this window and press Enter —")
    print("       selecting text in a Windows console pauses the server.")
    print("=" * 62 + "\n", flush=True)

    app.run(debug=False, host=host, port=5000, ssl_context=ssl_ctx)
