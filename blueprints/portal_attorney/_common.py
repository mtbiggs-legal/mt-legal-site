"""Imports and the blueprint shared by the attorney portal modules."""
import logging

import json
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import (
    Blueprint, render_template, request, jsonify, session,
    current_app,
)

import shared
from services import billing, engagement, felony, firm_admin, storage
from shared import (
    require_attorney, ATTORNEYS, CASE_ATTORNEY_MAP, CLIENT_FILES_DIR,
    LEADS_DIR, TOKEN_FILE, MAMMOTH_AVAILABLE, DOCS_CATEGORIES,
    ALLOWED_DOC_EXTENSIONS, MODEL, MANAGING_PARTNER, get_anthropic_client,
)
from services.gcal import (
    GOOGLE_LIBS, get_calendar_service, _push_court_date_to_gcal, _fetch_gcal_events,
    gcal_create_all_day, gcal_update_all_day, gcal_delete_event, gcal_connected,
)
from services.storage import (
    load_client, save_client, all_clients, safe_username,
    recalc_hours, _log_activity, _log_token_usage, update_client_atomic,
    _apply_payment,
)
from services import client_files
from services.html_sanitize import html_document
from blueprints.email_service import send_invite_email
from services.accounts import (
    log_access_atomic,
    issue_invite, invite_url, new_client_username,
    can_access_client, load_client_for_attorney, public_client_view, _log_access,
)
from services.documents import generate_client_pdf, generate_intake_html, resolve_doc_path
from services.scheduling_orders import extract_case_dates, ExtractionError, CASE_DATE_KINDS, CASE_DATE_LABELS
from services.conflicts import (
    DECISIONS, append_firm_log, clean_names, clean_related, has_unresolved_conflict,
    hit_message, make_check_record, record_check, redact_checks, redact_hits,
    run_conflict_check,
)

log = logging.getLogger(__name__)

portal_attorney_bp = Blueprint("portal_attorney", __name__)

log = logging.getLogger(__name__)

# Everything above, underscore helpers included, for the modules star-importing this.
__all__ = [n for n in dir() if not n.startswith("__")]
