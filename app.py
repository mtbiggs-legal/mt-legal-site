"""app.py — the Flask application factory.

create_app(kind) builds one of three apps from the same code:

  "public"  the marketing site, blog and intake form. No login, portal or
            attorney route is even registered.
  "portal"  logins and both portals (plus the intake queue they review).
  "all"     everything in one app: local development and the tests.

In production wsgi.py serves "public" on the main domain and "portal" on
PORTAL_HOST, in one process on one data disk, each with its own session
cookie. `python app.py` runs "all" locally.
"""

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

# Only this project's own .env. A bare load_dotenv() searches parent folders,
# so a git worktree inside the main checkout would load the real .env.
load_dotenv(Path(__file__).resolve().with_name(".env"))

import shared  # noqa: E402
from services import accounts, security, storage  # noqa: E402
from services import blog_scheduler, email_review_scheduler, firm_admin_scheduler  # noqa: E402

from blueprints.auth            import auth_bp            # noqa: E402
from blueprints.public          import public_bp          # noqa: E402
from blueprints.intake          import intake_bp          # noqa: E402
from blueprints.research        import research_bp        # noqa: E402
from blueprints.drafting        import drafting_bp        # noqa: E402
from blueprints.calendar        import calendar_bp        # noqa: E402
from blueprints.portal_client   import portal_client_bp   # noqa: E402
from blueprints.portal_attorney import portal_attorney_bp # noqa: E402
from blueprints.blog            import blog_bp            # noqa: E402
from blueprints.insights        import insights_bp        # noqa: E402
from blueprints.assistant       import assistant_bp       # noqa: E402
from blueprints.live            import live_bp            # noqa: E402
from blueprints.esign           import esign_bp           # noqa: E402
from blueprints.filings         import filings_bp         # noqa: E402
from blueprints.email_review    import email_review_bp    # noqa: E402
from blueprints.firm_admin      import firm_admin_bp      # noqa: E402
from blueprints.intake_review   import intake_review_bp   # noqa: E402
from blueprints.matters         import matters_bp         # noqa: E402

PUBLIC_BLUEPRINTS = (public_bp, intake_bp, blog_bp)
PORTAL_BLUEPRINTS = (
    auth_bp, research_bp, drafting_bp, calendar_bp, portal_client_bp, portal_attorney_bp,
    insights_bp, assistant_bp, live_bp, esign_bp, filings_bp, email_review_bp, firm_admin_bp,
    intake_review_bp, matters_bp,
)
KINDS = ("public", "portal", "all")

log = logging.getLogger(__name__)


def configure_logging() -> None:
    """One format for every module's logger; INFO unless LOG_LEVEL says otherwise."""
    root = logging.getLogger()
    if not any(getattr(h, "_mtl", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._mtl = True
        root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


class _CanonicalHost:
    """WSGI middleware: present every request as addressed to `host`."""
    def __init__(self, wsgi_app, host: str, scheme: str):
        self.wsgi_app, self.host, self.scheme = wsgi_app, host, scheme

    def __call__(self, environ, start_response):
        environ["HTTP_HOST"] = self.host
        environ["wsgi.url_scheme"] = self.scheme
        return self.wsgi_app(environ, start_response)


def endpoint_access(endpoint, flask_app=None):
    """The access level a view declared (see shared.py), or None if it declared
    none. Static files are public."""
    if endpoint == "static":
        return "public"
    flask_app = flask_app or app
    view = flask_app.view_functions.get(endpoint or "")
    return getattr(view, shared.ACCESS_ATTR, None) if view else None


def create_app(kind: str = "all") -> Flask:
    if kind not in KINDS:
        raise ValueError(f"Unknown app kind {kind!r}; use one of {KINDS}.")
    configure_logging()
    shared.ensure_data_dirs()
    a = Flask(__name__)
    a.config["APP_KIND"] = kind
    a.secret_key = os.getenv("SECRET_KEY") or os.urandom(24)
    a.config["TEMPLATES_AUTO_RELOAD"] = True
    a.config.update(
        SESSION_COOKIE_HTTPONLY    = True,
        SESSION_COOKIE_SAMESITE    = "Lax",
        # Separate cookies, so a session from one app is never sent to the other.
        SESSION_COOKIE_NAME        = {"public": "mtl_site", "portal": "mtl_portal"}.get(kind, "session"),
        # Shared mode serves HTTPS (see __main__), and production sits behind the
        # host's HTTPS proxy, so the cookie can be Secure in both.
        SESSION_COOKIE_SECURE      = bool(os.getenv("SHARE_PASSWORD", "").strip()) or shared.IS_PRODUCTION,
        PERMANENT_SESSION_LIFETIME = timedelta(minutes=30),
        # Largest request body (uploads included). Court PDFs rarely pass 20 MB.
        MAX_CONTENT_LENGTH         = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024,
    )
    if shared.IS_PRODUCTION:
        _production_wsgi(a, kind)

    @a.before_request
    def _access_gate():
        """Default deny: a route that declares no access level is never served,
        and with PUBLIC_SITE_ONLY only "public" routes are. Role checks also run
        here, so a view whose own decorator was lost still can't be reached."""
        if not request.path.startswith("/webhooks/"):     # providers can't send Basic Auth
            challenge = shared.share_password_challenge()
            if challenge is not None:
                return challenge
        site_only = shared.PUBLIC_SITE_ONLY or kind == "public"
        if request.endpoint is None:
            # Unknown URL or wrong method. With the portal off, a 405 would
            # still reveal that a private route exists, so answer 404.
            if site_only:
                abort(404)
            return None
        level = endpoint_access(request.endpoint, a)
        if level is None or (site_only and level != "public"):
            abort(404)
        if level in ("attorney", "client") and session.get("role") != level:
            login = url_for("auth.attorney_login" if level == "attorney" else "auth.client_login")
            if request.method == "GET" and "application/json" not in request.headers.get("Accept", ""):
                return redirect(login)
            resp = jsonify({"error": "Sign in required."})
            resp.status_code = 401
            resp.headers["X-Session-Expired"] = "1"     # base.html's fetch wrapper goes to login
            resp.headers["X-Login-Url"] = login
            return resp
        return None

    # Registered after the gate, so the gate's before_request runs first.
    security.init_app(a)
    _static_caching(a)

    @a.route("/healthz")
    @shared.public
    def healthz():
        """Uptime check. Reports which modes are on (flags only, never values)."""
        return {
            "ok":               True,
            "production":       shared.IS_PRODUCTION,
            "public_site_only": shared.PUBLIC_SITE_ONLY or kind == "public",
            "persistent_data":  shared.DATA_ROOT != shared.BASE_DIR,
        }

    @a.context_processor
    def _firm_identity():
        """Firm and managing-partner names for every template (see shared.py)."""
        return {
            "firm_name":        shared.FIRM_NAME,
            "firm_tagline":     shared.FIRM_TAGLINE,
            "partner":          shared.MANAGING_PARTNER,
            "partner_photo":    shared.partner_photo_filename(),
            "service_counties": shared.SERVICE_COUNTIES,
            "public_site_only": shared.PUBLIC_SITE_ONLY or kind == "public",
            "app_kind":         kind,
            "portal_link":      lambda path: _portal_link(kind, path),
            "site_link":        lambda endpoint, **values: _site_link(a, endpoint, **values),
        }

    @a.errorhandler(413)
    def _too_large(_exc):
        return jsonify({"error": f"That file is too large (limit "
                                 f"{a.config['MAX_CONTENT_LENGTH'] // 1048576} MB)."}), 413

    @a.errorhandler(storage.RecordDecryptError)
    def _record_decrypt_error(exc):
        log.error("could not decrypt client record: %s", exc)
        return jsonify({"error": "Client record could not be decrypted."}), 500

    for bp in (PUBLIC_BLUEPRINTS if kind in ("public", "all") else ()):
        a.register_blueprint(bp)
    for bp in (PORTAL_BLUEPRINTS if kind in ("portal", "all") else ()):
        a.register_blueprint(bp)
    if kind == "portal":
        # The portal's root is its sign-in page.
        a.add_url_rule("/", "portal_home", shared.portal_public(
            lambda: redirect(url_for("auth.client_login"))))
    return a


def _site_link(flask_app: Flask, endpoint: str, **values) -> str:
    """A link to a public-site page from any app. The portal app doesn't have
    those routes, so it builds the path from the combined app's route map and
    prefixes SITE_URL."""
    if endpoint in flask_app.view_functions:
        return url_for(endpoint, **values)
    external = values.pop("_external", False)  # noqa: F841 - always absolute here
    values.pop("v", None)
    adapter = app.url_map.bind("", url_scheme="https")
    return shared.SITE_URL + adapter.build(endpoint, values)


def _portal_link(kind: str, path: str) -> str:
    """Where the public pages' "Client Login" links point, or "" to hide them."""
    if kind == "all":
        return "" if shared.PUBLIC_SITE_ONLY else path
    if kind == "public":
        return (shared.PORTAL_URL + path) if shared.PORTAL_URL else ""
    return path


def _production_wsgi(a: Flask, kind: str) -> None:
    # Trust the hosting proxy's X-Forwarded-* headers so url_for() builds https
    # links and request.is_secure is true.
    a.wsgi_app = ProxyFix(a.wsgi_app, x_for=1, x_proto=1, x_host=1)
    # Links the app builds from the request (canonical tags, sitemap, RSS,
    # og:image) would otherwise use whatever Host header the sender chose.
    # Pin it to the app's own configured address.
    site = urlsplit(shared.PORTAL_URL if kind == "portal" and shared.PORTAL_URL else shared.SITE_URL)
    if site.hostname and site.hostname not in ("127.0.0.1", "localhost"):
        a.wsgi_app = _CanonicalHost(a.wsgi_app, site.netloc, site.scheme or "https")
    # Optional hard check: refuse requests for any other host.
    hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
    if hosts:
        a.config["TRUSTED_HOSTS"] = hosts

    @a.after_request
    def _hsts(resp):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


def _static_caching(a: Flask) -> None:
    # url_for('static', ...) adds ?v=<file modified time>, so a changed file
    # gets a new URL. Versioned URLs are cached for a year; anything requested
    # without a version (e.g. url() references inside CSS) for a day.
    @a.url_defaults
    def _version_static_urls(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            path = os.path.join(a.static_folder, values["filename"])
            try:
                values["v"] = int(os.path.getmtime(path))
            except OSError:
                pass

    @a.after_request
    def _cache_static(resp):
        if request.endpoint == "static" and resp.status_code in (200, 304):
            resp.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if request.args.get("v")
                else "public, max-age=86400")
        return resp


def check_startup_config() -> list:
    """Return human-readable problems that must be fixed before serving."""
    problems = list(shared.settings.problems)       # settings that didn't parse (config.py)
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
        storage._fernet_cache = None
        try:
            storage._fernet()
        except RuntimeError as exc:
            problems.append(str(exc))
    if problems:
        return problems                      # the checks below need the key
    # Client records moved from one file each into the database.
    legacy = list(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")) if shared.CLIENT_ACCOUNTS_DIR.exists() else []
    if legacy:
        problems.append(
            f"{len(legacy)} client record file(s) have not been moved into the database. Run:\n"
            "    python scripts/migrate_to_db.py --apply --backup-dir <folder outside OneDrive>")
        return problems
    from services import billing
    if not billing.is_migrated():
        if not storage.all_usernames():
            billing.mark_migrated()          # fresh install: nothing to migrate
        else:
            problems.append(
                "Opening statements have not been issued. Stop here and run:\n"
                "    python scripts/issue_opening_statements.py --backup-dir <folder outside OneDrive>")
    return problems


def startup_warnings() -> list:
    """Problems worth showing at startup that must not stop the app."""
    warnings = []
    from services import client_files, two_factor
    for username, atty in shared.ATTORNEYS.items():
        if not atty.get("password"):
            warnings.append(f"ATTORNEY_{username.upper()}_HASH is not set — "
                            f"attorney {username} cannot log in.")
        elif not two_factor.is_enabled(username):
            warnings.append(f"Attorney {username} has not set up two-step sign-in yet; "
                            "the next sign-in will ask for it. Do that before the portal goes live.")
    if not shared.ATTORNEY_2FA_REQUIRED:
        warnings.append("ATTORNEY_2FA=0: the attorney login does not require an authenticator code.")
    plain = 0
    for f in shared.CLIENT_FILES_DIR.glob("*/documents/*/*"):
        try:
            with open(f, "rb") as fh:
                plain += fh.read(len(client_files.MAGIC)) != client_files.MAGIC
        except OSError:
            pass
    if plain:
        warnings.append(f"{plain} client document(s) are not encrypted yet. Run: "
                        "python scripts/encrypt_client_files.py")
    return warnings


def _auto_migrate_records() -> None:
    """Production only: move client-accounts/*.json into the database at
    startup. On the host nobody can run scripts/migrate_to_db.py before the
    new code starts, and a failed start would just keep the old version up.
    The originals are backed up on the data disk first."""
    from services import legacy_import
    if not shared.IS_PRODUCTION or not legacy_import.legacy_files():
        return
    if not os.getenv("DATA_ENCRYPTION_KEY", "").strip():
        return                                   # check_startup_config reports it
    try:
        report = legacy_import.migrate(True, shared.DATA_ROOT / "migration-backup")
    except legacy_import.ImportError_ as exc:
        log.error("Automatic record migration failed: %s", exc)
        return
    if report["unreadable"]:
        log.error("Record migration skipped: unreadable file(s): %s",
                  ", ".join(report["unreadable"]))
    else:
        log.warning("Moved %d client record(s) into the database; originals in %s",
                    report["imported"], report.get("backup"))


def prepare_for_serving() -> None:
    """Refuse to start on a broken configuration, then fix what can be fixed."""
    _auto_migrate_records()
    problems = check_startup_config()
    if problems:
        raise RuntimeError("Cannot start:\n  * " + "\n  * ".join(problems))
    skipped = []
    upgraded = accounts.upgrade_all_plaintext_passwords(skipped=skipped)
    if upgraded:
        log.warning("Secured %d plaintext client password(s); those clients must choose a "
                    "new password at next login.", len(upgraded))
    if skipped:
        log.warning("Could not read %d client record(s): %s", len(skipped), ", ".join(skipped))
    for w in startup_warnings():
        log.warning(w)


def start_background_jobs(flask_app: Flask, include_local_only: bool) -> None:
    """Start the schedulers, once per data disk (services/run_once.py), so a
    second worker process can't run them twice."""
    from services import run_once
    if not run_once.claim("schedulers"):
        log.info("Background jobs already running in another process.")
        return
    blog_scheduler.start_scheduler(flask_app)
    if include_local_only:
        # The Inbox reviewer and firm-admin reminders only run on the local app.
        email_review_scheduler.start_scheduler()
        firm_admin_scheduler.start_scheduler()


# The combined app: local runs, tests, and older start commands (gunicorn app:app).
app = create_app(os.getenv("APP_KIND", "all"))

if shared.IS_PRODUCTION and "pytest" not in sys.modules and __name__ != "__main__" \
        and os.getenv("MTL_WSGI") != "1":
    # Started as `gunicorn app:app` (not wsgi.py): same checks and jobs.
    prepare_for_serving()
    start_background_jobs(app, include_local_only=False)


if __name__ == "__main__":
    try:
        prepare_for_serving()
    except RuntimeError as exc:
        print("\n" + str(exc).replace("Cannot start:", "Cannot start — fix these in .env:\n") + "\n")
        raise SystemExit(1)

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

    # With debug on, the reloader runs this file twice; only its child, marked
    # by WERKZEUG_RUN_MAIN, should run the scheduler.
    debug = False
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_jobs(app, include_local_only=True)

    app.run(debug=debug, host=host, port=5000, ssl_context=ssl_ctx)
