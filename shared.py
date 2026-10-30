"""
shared.py — Configuration, constants, the Anthropic client, and route decorators.

Import this module in blueprints instead of importing from app.py to avoid circular imports.
Client records live in services/storage.py, passwords and access control in
services/accounts.py, and Google Calendar/Drive in services/gcal.py.
"""

import os
import functools
import anthropic

from pathlib import Path

from flask import request, Response, session, redirect, url_for

# Optional document libraries
try:
    import mammoth  # noqa: F401 - availability probe for MAMMOTH_AVAILABLE
    MAMMOTH_AVAILABLE = True
except ImportError:
    MAMMOTH_AVAILABLE = False

try:
    import pypdf  # noqa: F401 - availability probe for PYPDF_AVAILABLE
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    from fpdf import FPDF  # noqa: F401 - availability probe for FPDF_AVAILABLE
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

# ── Base directory ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

# ── Firm identity ─────────────────────────────────────────────────────────────
# MT Legal is a solo practice. Every public page, email, PDF and AI prompt reads
# the firm and managing-partner names from here, so a rename is one edit.

FIRM_NAME     = "MT Legal"
FIRM_TAGLINE  = "Nashville & Middle Tennessee"
FIRM_CITY     = "Nashville, Tennessee"

MANAGING_PARTNER = {
    "username": "Endocide",
    "name":     "Madison T. Biggs",
    "display":  "Madison T. Biggs, Esq.",
    "title":    "Founder & Managing Attorney",
    "role":     "AI · Blockchain · Estate · Litigation",
    "photo":    "managing-partner.jpg",
}

# Counties the marketing site names as the firm's service area.
SERVICE_COUNTIES = [
    "Davidson", "Williamson", "Rutherford", "Wilson", "Sumner",
    "Maury", "Montgomery", "Robertson", "Bedford", "Dickson",
]


def partner_photo_filename() -> str:
    """The managing partner's headshot, or a monogram placeholder until the
    real photo is saved to static/images/managing-partner.jpg."""
    if (BASE_DIR / "static" / "images" / MANAGING_PARTNER["photo"]).exists():
        return MANAGING_PARTNER["photo"]
    return "managing-partner-placeholder.svg"


# ── Attorney registry ─────────────────────────────────────────────────────────

ATTORNEYS = {
    "Endocide": {
        "password":  os.getenv("ATTORNEY_ENDOCIDE_HASH", ""),
        "display":   MANAGING_PARTNER["display"],
        "case_type": "Criminal Defense",
    },
    "SophiaH": {
        "password":  os.getenv("ATTORNEY_SOPHIAH_HASH", ""),
        "display":   "Sophia L. Hargrove, Esq.",
        "case_type": "Civil Litigation",
    },
}

# Solo practice: every matter is handled by the managing partner.
CASE_ATTORNEY_MAP = {
    "Criminal Defense":           "Endocide",
    "Civil Litigation":           "Endocide",
    "Contract Dispute":           "Endocide",
    "Personal Injury":            "Endocide",
    "Family Law — Divorce":       "Endocide",
    "Family Law — Child Custody": "Endocide",
    "Family Law — Other":         "Endocide",
    "Real Estate":                "Endocide",
    "Employment Law":             "Endocide",
    "DeFi / Crypto Law":          "Endocide",
    "Crypto LLC Formation":       "Endocide",
    "Real World Assets Tokenization": "Endocide",
    "AI / Technology Law":        "Endocide",
    "Civil Rights":               "Endocide",
    "Stablecoins / Agentic Payments": "Endocide",
    "Estate Planning":            "Endocide",
    "Other":                      "Endocide",
}

# ── Deployment ────────────────────────────────────────────────────────────────
# APP_ENV=production turns on HTTPS-only cookies and HSTS, and fails fast at
# startup on missing secrets. PUBLIC_SITE_ONLY=1 serves only the marketing site
# and intake: portals, logins, and attorney tools return 404 (see app.py).

def _env(name: str) -> str:
    """An env var with surrounding whitespace and stray quotes removed, so a
    value pasted into a hosting dashboard as "1" or 'production' still counts."""
    return os.getenv(name, "").strip().strip("\"'").strip()


IS_PRODUCTION    = _env("APP_ENV").lower() == "production"
PUBLIC_SITE_ONLY = _env("PUBLIC_SITE_ONLY").lower() in ("1", "true", "yes", "on")

# ── Data directories ──────────────────────────────────────────────────────────
# DATA_DIR points every runtime data folder at a persistent disk in hosting
# (e.g. /var/data); locally it defaults to the project folder as before.

DATA_ROOT = Path(_env("DATA_DIR") or BASE_DIR)

CLIENT_DATA_DIR      = DATA_ROOT / "client-data"
RESEARCH_HISTORY_DIR = DATA_ROOT / "research-history"
DRAFT_HISTORY_DIR    = DATA_ROOT / "draft-history"
LEADS_DIR            = DATA_ROOT / "leads"
CLIENT_ACCOUNTS_DIR  = DATA_ROOT / "client-accounts"
CLIENT_FILES_DIR     = DATA_ROOT / "client-files"
CASE_SEARCHES_DIR    = DATA_ROOT / "case-searches"
TOKEN_USAGE_DIR      = DATA_ROOT / "token-usage"
SECURITY_STATE_DIR   = DATA_ROOT / "security-state"
CLIENT_BILLING_DIR   = DATA_ROOT / "client-billing"
FIRM_SETTINGS_DIR    = DATA_ROOT / "firm-settings"
BLOG_DIR             = DATA_ROOT / "blog"          # created by blog.seed_from_repo()
BLOG_SEED_DIR        = BASE_DIR / "blog_seed"      # versioned posts/topics merged into BLOG_DIR

for _d in (
    CLIENT_DATA_DIR, RESEARCH_HISTORY_DIR, DRAFT_HISTORY_DIR, LEADS_DIR,
    CLIENT_ACCOUNTS_DIR, CLIENT_FILES_DIR, CASE_SEARCHES_DIR, TOKEN_USAGE_DIR,
    SECURITY_STATE_DIR, CLIENT_BILLING_DIR, FIRM_SETTINGS_DIR,
):
    _d.mkdir(exist_ok=True)

# ── API / payment config ──────────────────────────────────────────────────────

ANTHROPIC_API_KEY        = _env("ANTHROPIC_API_KEY") or None
# Only needed for an API key that isn't scoped to a workspace: the API then
# requires the workspace ID with every request.
ANTHROPIC_WORKSPACE_ID   = _env("ANTHROPIC_WORKSPACE_ID")
MODEL                    = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
BLOG_MODEL               = os.getenv("BLOG_MODEL", "claude-sonnet-5-5")
BLOG_AUTOGEN             = _env("BLOG_AUTOGEN").lower() in ("1", "true", "yes", "on")

HOURLY_RATE              = float(os.getenv("HOURLY_RATE", "350"))
MONTHLY_RENT             = float(os.getenv("MONTHLY_RENT")         or "0")
MONTHLY_SALARIES         = float(os.getenv("MONTHLY_SALARIES")     or "0")
MONTHLY_SOFTWARE         = float(os.getenv("MONTHLY_SOFTWARE")     or "0")
MONTHLY_INSURANCE        = float(os.getenv("MONTHLY_INSURANCE")    or "0")
MONTHLY_MARKETING        = float(os.getenv("MONTHLY_MARKETING")    or "0")
MONTHLY_MISC             = float(os.getenv("MONTHLY_MISC")         or "0")
OVERHEAD_RESERVE_PCT     = float(os.getenv("OVERHEAD_RESERVE_PCT") or "0.35")

# ── Document categories & allowed extensions ──────────────────────────────────

DOCS_CATEGORIES = [
    "Intake",
    "Generated Documents",
    "Motions",
    "Litigation Drafts",
    "Court Orders",
    "Scheduling Orders",
    "Warrants & Discovery",
    "Research",
    "Other",
]

ALLOWED_DOC_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".txt", ".rtf", ".odt", ".html",
}

STRIPE_SECRET_KEY                = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY           = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET            = os.getenv("STRIPE_WEBHOOK_SECRET", "")
COINBASE_COMMERCE_API_KEY        = os.getenv("COINBASE_COMMERCE_API_KEY", "")
COINBASE_COMMERCE_WEBHOOK_SECRET = os.getenv("COINBASE_COMMERCE_WEBHOOK_SECRET", "")

# ── Google Calendar config ────────────────────────────────────────────────────

CALENDAR_SCOPES  = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
]
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE       = DATA_ROOT / "calendar-token.json"


# ═════════════════════════════════════════════════════════════════════════════
# Anthropic client
# ═════════════════════════════════════════════════════════════════════════════

def get_anthropic_client():
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set. Please add it to your .env file.")
    headers = {"anthropic-workspace-id": ANTHROPIC_WORKSPACE_ID} if ANTHROPIC_WORKSPACE_ID else None
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, default_headers=headers)


# ═════════════════════════════════════════════════════════════════════════════
# Route decorators
# ═════════════════════════════════════════════════════════════════════════════

def require_auth(f):
    """Gate every route behind HTTP Basic Auth when SHARE_PASSWORD is set.
    After first successful Basic Auth, stores a session flag so that
    JS fetch() calls (which send cookies but not Basic Auth headers) also pass.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        password = os.getenv("SHARE_PASSWORD", "").strip()
        if password:
            # Session cookie already set from a prior successful auth — let through
            if session.get("share_authed"):
                return f(*args, **kwargs)
            auth = request.authorization
            if not auth or auth.password != password:
                return Response(
                    "Authentication required.",
                    401,
                    {"WWW-Authenticate": 'Basic realm="Law Office App"'},
                )
            # Stamp the session so fetch() calls don't need to re-send Basic Auth
            session["share_authed"] = True
        return f(*args, **kwargs)
    return decorated


def require_attorney(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "attorney":
            return redirect(url_for("auth.attorney_login"))
        return f(*args, **kwargs)
    return decorated


def require_client(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "client":
            return redirect(url_for("auth.client_login"))
        return f(*args, **kwargs)
    return decorated
