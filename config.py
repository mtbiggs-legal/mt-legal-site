"""config.py — every setting the app has, read from the environment in one place.

    settings = Settings()                       # from os.environ
    settings = Settings(env={...}, base_dir=p)  # from anything, e.g. in a test

Settings only reads; it creates no folders and talks to nothing, so building
one is safe anywhere. Values that don't parse (HOURLY_RATE=abc) fall back to
their default and are listed in `settings.problems`, which app.py reports at
startup instead of crashing on import.

The rest of the app does not read this object directly: shared.py publishes
each value as `shared.<NAME>`, which is what the code and the tests use.
"""

import os
from datetime import date
from pathlib import Path

_TRUE  = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def env_value(name: str, env=None) -> str:
    """An env var with surrounding whitespace and stray quotes removed, so a
    value pasted into a hosting dashboard as "1" or 'production' still counts."""
    env = os.environ if env is None else env
    return (env.get(name) or "").strip().strip("\"'").strip()


class Settings:
    def __init__(self, env=None, base_dir=None):
        env = os.environ if env is None else env
        self.problems: list = []

        def get(name):
            return env_value(name, env)

        def raw(name, default=""):
            return env.get(name, default)

        def flag(name, default=False):
            v = get(name).lower()
            return default if not v else (v in _TRUE if not default else v not in _FALSE)

        def number(name, default, kind=float):
            v = get(name)
            if not v:
                return kind(default)
            try:
                return kind(v)
            except ValueError:
                self.problems.append(f"{name}={v!r} is not a number; using {default}.")
                return kind(default)

        # ── Base directory ───────────────────────────────────────────────────
        self.BASE_DIR = Path(base_dir) if base_dir else Path(__file__).parent

        # ── Firm identity ────────────────────────────────────────────────────
        # MT Legal is a solo practice. Every public page, email, PDF and AI
        # prompt reads the firm and managing-partner names from here, so a
        # rename is one edit.
        self.FIRM_NAME    = "MT Legal"
        self.FIRM_TAGLINE = "Nashville & Middle Tennessee"
        self.FIRM_CITY    = "Nashville, Tennessee"
        self.MANAGING_PARTNER = {
            "username": "Endocide",
            "name":     "Madison T. Biggs",
            "display":  "Madison T. Biggs, Esq.",
            "title":    "Founder & Managing Attorney",
            "role":     "AI · Blockchain · Estate · Litigation",
            "photo":    "managing-partner.jpg",
            # Public profiles that use the same headshot (LinkedIn, Avvo, bar
            # directory...). Google uses them to tie the photo to the name.
            "profiles": [],
        }
        # Counties the marketing site names as the firm's service area.
        self.SERVICE_COUNTIES = [
            "Davidson", "Williamson", "Rutherford", "Wilson", "Sumner",
            "Maury", "Montgomery", "Robertson", "Bedford", "Dickson",
        ]

        # ── Attorney registry ────────────────────────────────────────────────
        partner = self.MANAGING_PARTNER["username"]
        self.ATTORNEYS = {
            partner: {
                "password":  raw("ATTORNEY_ENDOCIDE_HASH"),
                "display":   self.MANAGING_PARTNER["display"],
                "case_type": "Criminal Defense",
            },
        }
        # Solo practice: every matter is handled by the managing partner.
        self.CASE_ATTORNEY_MAP = {case_type: partner for case_type in (
            "Criminal Defense", "Civil Litigation", "Contract Dispute", "Personal Injury",
            "Family Law — Divorce", "Family Law — Child Custody", "Family Law — Other",
            "Real Estate", "Employment Law", "DeFi / Crypto Law", "Crypto LLC Formation",
            "Real World Assets Tokenization", "AI / Technology Law", "Civil Rights",
            "Stablecoins / Agentic Payments", "Estate Planning", "Other",
        )}

        # ── Deployment ───────────────────────────────────────────────────────
        # APP_ENV=production turns on HTTPS-only cookies and HSTS, and fails
        # fast at startup on missing secrets. PUBLIC_SITE_ONLY=1 serves only the
        # marketing site and intake: portals, logins and attorney tools return
        # 404 (see app.py).
        self.IS_PRODUCTION    = get("APP_ENV").lower() == "production"
        self.PUBLIC_SITE_ONLY = flag("PUBLIC_SITE_ONLY")
        # The attorney login needs an authenticator-app code
        # (services/two_factor.py). On unless ATTORNEY_2FA=0; once set up it is
        # always asked for.
        self.ATTORNEY_2FA_REQUIRED = flag("ATTORNEY_2FA", default=True)
        # The site's own base URL for links in emails and payment redirects.
        # Never built from the request's Host header, which the sender controls.
        self.SITE_URL = (get("SITE_URL") or get("FIRM_WEBSITE") or "http://127.0.0.1:5000").rstrip("/")
        # The client and attorney portals' own address (e.g.
        # https://portal.example.com), served by wsgi.py on that host. Empty:
        # no portal is served in production.
        self.PORTAL_URL = get("PORTAL_URL").rstrip("/")
        for name in ("SITE_URL", "PORTAL_URL"):
            value = getattr(self, name)
            if value and not value.startswith(("http://", "https://")):
                self.problems.append(f"{name}={value!r} must start with https:// (or http://).")

        # ── Data directories ─────────────────────────────────────────────────
        # DATA_DIR points every runtime data folder at a persistent disk in
        # hosting (e.g. /var/data); locally it defaults to the project folder.
        self.DATA_ROOT = root = Path(get("DATA_DIR") or self.BASE_DIR)
        self.CLIENT_DATA_DIR      = root / "client-data"
        self.RESEARCH_HISTORY_DIR = root / "research-history"
        self.DRAFT_HISTORY_DIR    = root / "draft-history"
        self.LEADS_DIR            = root / "leads"
        self.CLIENT_ACCOUNTS_DIR  = root / "client-accounts"    # legacy record files (pre-database)
        self.CLIENT_FILES_DIR     = root / "client-files"
        self.CASE_SEARCHES_DIR    = root / "case-searches"
        self.TOKEN_USAGE_DIR      = root / "token-usage"
        self.SECURITY_STATE_DIR   = root / "security-state"
        self.CLIENT_BILLING_DIR   = root / "client-billing"
        self.FIRM_SETTINGS_DIR    = root / "firm-settings"
        self.PENDING_INTAKE_DIR   = root / "pending-intake"     # encrypted; awaiting attorney review
        self.DB_PATH              = root / "db" / "mt-legal.db" # services/db.py
        self.BLOG_DIR             = root / "blog"               # created by blog.seed_from_repo()
        self.BLOG_SEED_DIR        = self.BASE_DIR / "blog_seed" # versioned posts/topics merged into BLOG_DIR

        # ── AI models ────────────────────────────────────────────────────────
        self.ANTHROPIC_API_KEY      = get("ANTHROPIC_API_KEY") or None
        # Only needed for an API key that isn't scoped to a workspace: the API
        # then requires the workspace ID with every request.
        self.ANTHROPIC_WORKSPACE_ID = get("ANTHROPIC_WORKSPACE_ID")
        self.MODEL                  = raw("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        self.BLOG_MODEL             = raw("BLOG_MODEL", "claude-sonnet-5-5")
        # The attorney portal's chat assistant (services/assistant.py).
        self.ASSISTANT_MODEL        = raw("ASSISTANT_MODEL", "claude-opus-5-5")
        self.BLOG_AUTOGEN           = flag("BLOG_AUTOGEN")
        # Until this date the website chat sends a fixed "not taking new
        # clients" reply and never calls the model.
        self.CHAT_OPENS_ON          = date(2027, 1, 2)

        # ── Rates and overhead ───────────────────────────────────────────────
        self.HOURLY_RATE          = number("HOURLY_RATE", 350)
        self.MONTHLY_RENT         = number("MONTHLY_RENT", 0)
        self.MONTHLY_SALARIES     = number("MONTHLY_SALARIES", 0)
        self.MONTHLY_SOFTWARE     = number("MONTHLY_SOFTWARE", 0)
        self.MONTHLY_INSURANCE    = number("MONTHLY_INSURANCE", 0)
        self.MONTHLY_MARKETING    = number("MONTHLY_MARKETING", 0)
        self.MONTHLY_MISC         = number("MONTHLY_MISC", 0)
        self.OVERHEAD_RESERVE_PCT = number("OVERHEAD_RESERVE_PCT", 0.35)
        if self.HOURLY_RATE <= 0:
            self.problems.append("HOURLY_RATE must be greater than 0.")

        # ── Document categories & allowed extensions ─────────────────────────
        self.DOCS_CATEGORIES = [
            "Intake", "Generated Documents", "Motions", "Litigation Drafts", "Court Orders",
            "Scheduling Orders", "Warrants & Discovery", "Research", "Signed Documents",
            "Filing Packages", "Drafts", "Other",
        ]
        # Attorney-only folders: the client portal never lists or serves them.
        # The assistant saves its unreviewed drafts in "Drafts", so nothing it
        # writes reaches a client until the attorney finalizes it and files it
        # elsewhere.
        self.ATTORNEY_ONLY_CATEGORIES = frozenset({"Drafts"})
        self.CLIENT_DOCS_CATEGORIES = [c for c in self.DOCS_CATEGORIES
                                       if c not in self.ATTORNEY_ONLY_CATEGORIES]
        self.ALLOWED_DOC_EXTENSIONS = {
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
            ".txt", ".rtf", ".odt",
        }

        # ── Payments ─────────────────────────────────────────────────────────
        self.STRIPE_SECRET_KEY                = raw("STRIPE_SECRET_KEY")
        self.STRIPE_PUBLISHABLE_KEY           = raw("STRIPE_PUBLISHABLE_KEY")
        self.STRIPE_WEBHOOK_SECRET            = raw("STRIPE_WEBHOOK_SECRET")
        self.COINBASE_COMMERCE_API_KEY        = raw("COINBASE_COMMERCE_API_KEY")
        self.COINBASE_COMMERCE_WEBHOOK_SECRET = raw("COINBASE_COMMERCE_WEBHOOK_SECRET")

        # ── E-signature (Dropbox Sign) and court filings ─────────────────────
        # Test mode is on unless DROPBOX_SIGN_TEST_MODE=0: test requests are
        # free and carry no legal weight, so nothing binding goes out until it
        # is switched off.
        self.DROPBOX_SIGN_API_KEY   = get("DROPBOX_SIGN_API_KEY")
        self.DROPBOX_SIGN_TEST_MODE = flag("DROPBOX_SIGN_TEST_MODE", default=True)
        # Signature block on filing packages (the managing partner's Tennessee
        # BPR number). Some .env files name it ATTORNEY_BPR_NUMBER.
        self.ATTORNEY_BPR = get("ATTORNEY_BPR") or get("ATTORNEY_BPR_NUMBER")
        self.FIRM_ADDRESS = get("FIRM_ADDRESS")
        # Letterhead contact line on firm letters (the public numbers on the
        # business card).
        self.FIRM_PHONE_DISPLAY = get("FIRM_PHONE") or "615-606-2603"
        self.FIRM_EMAIL_DISPLAY = get("FIRM_EMAIL") or "mtbiggs@midtennlegal.com"
        self.FIRM_WEBSITE       = "midtennlegal.com"

        # ── Google Calendar ──────────────────────────────────────────────────
        self.CALENDAR_SCOPES = [
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/drive.file",
        ]
        self.CREDENTIALS_FILE = self.BASE_DIR / "credentials.json"
        self.TOKEN_FILE       = root / "calendar-token.json"

        # ── Email reviewer (Gmail) ───────────────────────────────────────────
        # Its own token, so the firm mailbox can be a different Google account
        # from the calendar. gmail.modify reads, labels and sends; Google never
        # lets it delete mail permanently. See docs/EMAIL_REVIEW_SETUP.md.
        self.GMAIL_SCOPES       = ["https://www.googleapis.com/auth/gmail.modify"]
        self.GMAIL_TOKEN_FILE   = root / "gmail-token.json"
        self.EMAIL_REVIEW_DIR   = root / "email-review"   # encrypted results; created on first write
        self.EMAIL_REVIEW_MODEL = raw("EMAIL_REVIEW_MODEL", "claude-haiku-5-5")
        # Hourly background checks (local app only). Off with EMAIL_REVIEW_AUTO=0.
        self.EMAIL_REVIEW_AUTO  = flag("EMAIL_REVIEW_AUTO", default=True)
        # The morning digest goes out on the first check at or after this hour;
        # -1 turns it off.
        self.EMAIL_DIGEST_HOUR  = number("EMAIL_DIGEST_HOUR", 7, kind=int)

    def as_dict(self) -> dict:
        """Every setting by name (what shared.py publishes)."""
        return {k: v for k, v in vars(self).items() if k.isupper()}

    def data_dirs(self) -> tuple:
        """Folders the app creates at startup."""
        return (self.CLIENT_DATA_DIR, self.RESEARCH_HISTORY_DIR, self.DRAFT_HISTORY_DIR,
                self.LEADS_DIR, self.CLIENT_FILES_DIR, self.CASE_SEARCHES_DIR,
                self.TOKEN_USAGE_DIR, self.SECURITY_STATE_DIR, self.CLIENT_BILLING_DIR,
                self.FIRM_SETTINGS_DIR, self.PENDING_INTAKE_DIR)
