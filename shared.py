"""shared.py — what every module imports: settings, the Anthropic client, and
the route-access decorators.

Settings come from config.Settings (config.py), built once from the
environment; each one is published here as `shared.<NAME>` (shared.DATA_ROOT,
shared.HOURLY_RATE, ...). Code in services/ reads them as `shared.<NAME>` at
call time, so a test that patches one name changes it everywhere.

The decorators live in access.py and are re-exported here, so blueprints keep
`from shared import require_attorney`. Import this module, never app.py, to
avoid circular imports.
"""

import anthropic

from config import Settings, env_value
from access import (  # noqa: F401 - re-exported for blueprints
    ACCESS_ATTR, CSRF_EXEMPT_ATTR, csrf_exempt, portal_public, public,
    require_attorney, require_auth, require_client, share_password_challenge,
)

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


# ── Settings ──────────────────────────────────────────────────────────────────
# Every value is listed in config.py with its comment; this publishes them as
# module attributes. `settings.problems` holds values that didn't parse.

settings = Settings()
globals().update(settings.as_dict())

# Explicit names for readers and linters (the same objects as above).
BASE_DIR = settings.BASE_DIR
DATA_ROOT = settings.DATA_ROOT
_env = env_value


def partner_photo_filename() -> str:
    """The managing partner's headshot, or a monogram placeholder until the
    real photo is saved to static/images/managing-partner.jpg."""
    photo = MANAGING_PARTNER["photo"]  # noqa: F821 - published from settings
    if (BASE_DIR / "static" / "images" / photo).exists():
        return photo
    return "managing-partner-placeholder.svg"


def portal_base() -> str:
    """Base address for links into the portals (invitations, statement
    emails, payment return pages): the portal's own host when it has one."""
    return PORTAL_URL or SITE_URL  # noqa: F821


def ensure_data_dirs() -> None:
    """Create the data folders (app startup; not at import, so importing this
    module for a script or a test never creates folders as a side effect).
    Reads the published names, so a test's patched folders are the ones used."""
    for name in ("CLIENT_DATA_DIR", "RESEARCH_HISTORY_DIR", "DRAFT_HISTORY_DIR", "LEADS_DIR",
                 "CLIENT_FILES_DIR", "CASE_SEARCHES_DIR", "TOKEN_USAGE_DIR",
                 "SECURITY_STATE_DIR", "CLIENT_BILLING_DIR", "FIRM_SETTINGS_DIR",
                 "PENDING_INTAKE_DIR"):
        globals()[name].mkdir(parents=True, exist_ok=True)


def get_anthropic_client():
    if not ANTHROPIC_API_KEY:  # noqa: F821
        raise ValueError("ANTHROPIC_API_KEY is not set. Please add it to your .env file.")
    headers = {"anthropic-workspace-id": ANTHROPIC_WORKSPACE_ID} if ANTHROPIC_WORKSPACE_ID else None  # noqa: F821
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, default_headers=headers)  # noqa: F821
