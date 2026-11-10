"""services/gmail.py — the firm mailbox, through the Gmail API.

Only what the email reviewer needs, and deliberately nothing more:
- read Inbox messages,
- add labels (never remove them, so mail is never archived or marked read),
- send one message to the signed-in account itself (the morning digest).

There is no delete, trash, draft or send-to-anyone call here, and
tests/test_email_review.py checks that it stays that way.
"""

import base64
import html
import os
import re
from email.message import EmailMessage
from html.parser import HTMLParser
from email.utils import parseaddr

import shared

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build as google_build
    GOOGLE_LIBS = True
except ImportError:
    GOOGLE_LIBS = False

NOT_CONNECTED = ("Gmail is not connected. Open the Inbox tab and click "
                 "'Connect Gmail' (see docs/EMAIL_REVIEW_SETUP.md).")
LABEL_ROOT = "MT Review"


class GmailError(Exception):
    """User-readable reason the mailbox can't be reached."""


# ── Connection ────────────────────────────────────────────────────────────────

def _credentials():
    if not GOOGLE_LIBS:
        raise GmailError("Google libraries not installed. Run: pip install -r requirements.txt")
    token = shared.GMAIL_TOKEN_FILE
    if not token.exists():
        raise GmailError(NOT_CONNECTED)
    creds = Credentials.from_authorized_user_file(str(token), shared.GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleRequest())
            except Exception as exc:
                raise GmailError("Gmail sign-in has expired. Click 'Connect Gmail' again.") from exc
            save_token(creds)
        else:
            raise GmailError(NOT_CONNECTED)
    return creds


def save_token(creds) -> None:
    """Write the OAuth token owner-only (0600) and atomically, so it is never
    readable by other users and never left half-written."""
    path = shared.GMAIL_TOKEN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        os.chmod(tmp, 0o600)          # in case the file already existed with a wider mode
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def get_service():
    creds = _credentials()      # raises GmailError first, before any Google call
    return google_build("gmail", "v1", credentials=creds, cache_discovery=False)


def status() -> dict:
    """Connection state for the portal, without contacting Google."""
    if not GOOGLE_LIBS:
        return {"connected": False, "reason": "libraries_missing"}
    if not shared.CREDENTIALS_FILE.exists():
        return {"connected": False, "reason": "no_credentials_file"}
    if not shared.GMAIL_TOKEN_FILE.exists():
        return {"connected": False, "reason": "not_authorized"}
    return {"connected": True}


def account_email(service) -> str:
    return service.users().getProfile(userId="me").execute()["emailAddress"]


# ── Reading ───────────────────────────────────────────────────────────────────

def list_inbox_ids(service, after_epoch: int, limit: int) -> list:
    """IDs of Inbox messages received after `after_epoch`, newest first."""
    resp = service.users().messages().list(
        userId="me", q=f"in:inbox after:{int(after_epoch)}", maxResults=limit,
    ).execute()
    return [m["id"] for m in resp.get("messages", [])]


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


# Email bodies are attacker-controlled. Every part is cut to this size before
# any parsing, and HTML is parsed in one linear pass (no backtracking regexes).
MAX_PART_CHARS = 200_000
_SKIP_TAGS = {"script", "style", "head", "title"}
_BREAK_TAGS = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skip += 1
        elif tag in _BREAK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in _BREAK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _html_to_text(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw[:MAX_PART_CHARS])
    parser.close()
    return " ".join(parser.out)


def _decode(data: str) -> str:
    return _b64(data).decode("utf-8", errors="replace")[:MAX_PART_CHARS]


def _walk(part, plain: list, rich: list, attachments: list) -> None:
    mime = part.get("mimeType", "")
    body = part.get("body", {}) or {}
    if part.get("filename"):
        attachments.append(part["filename"])
    elif mime == "text/plain" and body.get("data"):
        plain.append(_decode(body["data"]))
    elif mime == "text/html" and body.get("data"):
        rich.append(_html_to_text(_decode(body["data"])))
    for sub in part.get("parts", []) or []:
        _walk(sub, plain, rich, attachments)


def parse_message(msg: dict) -> dict:
    """A Gmail API message (format=full) as plain fields."""
    payload = msg.get("payload", {}) or {}
    header_list = payload.get("headers", []) or []
    headers = {h["name"].lower(): h["value"] for h in header_list}
    plain, rich, attachments = [], [], []
    _walk(payload, plain, rich, attachments)
    body = ("\n".join(plain) if plain else "\n".join(rich))[:MAX_PART_CHARS]
    body = re.sub(r"[ \t\r\f\v]+", " ", body)
    body = re.sub(r"\n(?: ?\n)+", "\n\n", body).strip()
    name, addr = parseaddr(headers.get("from", ""))
    return {
        "id":          msg["id"],
        "thread_id":   msg.get("threadId", ""),
        "from":        headers.get("from", ""),
        "from_name":   name,
        "from_email":  addr.lower(),
        "to":          headers.get("to", ""),
        "subject":     headers.get("subject", ""),
        "date":        headers.get("date", ""),
        "received_ms": int(msg.get("internalDate") or 0),
        "body":        body or msg.get("snippet", ""),
        "attachments": attachments,
        "sender_verified": sender_verified(header_list, addr),
    }


# ── Sender domain authentication ──────────────────────────────────────────────
# The From header is easy to forge. Gmail checks SPF, DKIM and DMARC on arrival
# and adds its own Authentication-Results header (authserv-id mx.google.com).
# Only that header is read: the first Authentication-Results, and only if it
# sits above every Received line written by a non-Google server (anything a
# sender forges sits below its own servers' Received lines). Only DMARC counts,
# because DMARC already requires SPF or DKIM to align with the From domain, and
# only when its header.from is exactly the From domain. A pass proves the
# message came from that DOMAIN, not from a particular mailbox on it.


MAX_AUTH_HEADER = 8000      # longer than any real Gmail header: fail closed, never truncate


def _strip_comments(value: str):
    """Drop RFC 8601 (comments), nested or with \\-escapes, which can echo
    sender-controlled text such as the envelope sender. Returns None when the
    comments don't balance, so callers fail closed."""
    out, depth, escaped = [], 0, False
    for ch in value:
        if escaped:
            escaped = False
            if depth == 0:
                out.append(ch)
        elif ch == "\\":
            escaped = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return None
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return None if depth or escaped else "".join(out)


def _auth_results(value: str) -> list:
    """[(method, verdict, {property: value})] from one header, comments removed.
    Properties are whole `key=value` tokens, never substrings. Empty (so: not
    authenticated) for an overlong or malformed header."""
    if not value or len(value) > MAX_AUTH_HEADER:
        return []
    stripped = _strip_comments(value)
    if stripped is None:
        return []
    segments = stripped.split(";")
    parsed = []
    for seg in segments[1:]:                    # segments[0] is the authserv-id
        tokens = [t for t in seg.split() if "=" in t]
        if not tokens:
            continue
        method, _, verdict = tokens[0].partition("=")
        props = dict(t.lower().split("=", 1) for t in tokens[1:])
        parsed.append((method.lower(), verdict.lower(), props))
    return parsed


def _domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].strip().strip("<>\"'").lower()


def _is_outside_hop(received: str) -> bool:
    """True for a Received line written by a server other than Google's.
    Gmail's internal hops ("by 2002:...") have no from-clause; its inbound hop
    reads "from <sender host> ... by mx.google.com"."""
    stripped = _strip_comments(received[:MAX_AUTH_HEADER])
    if stripped is None:
        return True              # malformed: treat as an outside hop, so nothing below is trusted
    tokens = stripped.lower().split()
    if "from" not in tokens or "by" not in tokens:
        return False
    by_host = tokens[tokens.index("by") + 1] if tokens.index("by") + 1 < len(tokens) else ""
    return not (by_host == "google.com" or by_host.endswith(".google.com"))


def _gmail_auth_header(header_list: list) -> str:
    """Gmail's own Authentication-Results value, or "" if it can't be trusted.

    Headers run newest first. Gmail's header sits above the Received lines of
    the sender's servers, and anything the sender wrote sits below those."""
    for h in header_list:
        name = h.get("name", "").lower()
        value = h.get("value", "")
        if name == "received" and _is_outside_hop(value):
            return ""
        if name == "authentication-results":
            ok = value.split(";", 1)[0].strip().lower() == "mx.google.com"
            return value if ok else ""
    return ""


def sender_verified(header_list: list, from_addr: str) -> bool:
    """True when Gmail's DMARC check passed for exactly the From domain.

    That authenticates the domain, not the mailbox: anyone who can send from
    that domain passes. The portal says "domain authenticated" accordingly.
    """
    if "@" not in (from_addr or ""):
        return False
    from_domain = _domain(from_addr)
    results = _auth_results(_gmail_auth_header(header_list))
    dmarc = [r for r in results if r[0] == "dmarc"]
    # Exactly one DMARC result, and it is the last entry, where Gmail writes it,
    # so text smuggled out of a comment can neither add nor displace one.
    if len(dmarc) != 1 or results[-1][0] != "dmarc":
        return False
    _, verdict, props = dmarc[0]
    # p=none is the domain's policy for failures; a pass is still a pass.
    return verdict == "pass" and _domain(props.get("header.from", "")) == from_domain


def get_message(service, msg_id: str) -> dict:
    return parse_message(
        service.users().messages().get(userId="me", id=msg_id, format="full").execute())


# ── Labels (add only) ─────────────────────────────────────────────────────────

def ensure_labels(service, names) -> dict:
    """Return {name: label id}, creating any label that doesn't exist yet."""
    existing = {l["name"]: l["id"] for l in
                service.users().labels().list(userId="me").execute().get("labels", [])}
    wanted = [LABEL_ROOT] + [n for n in names if n != LABEL_ROOT]
    for name in wanted:
        if name not in existing:
            created = service.users().labels().create(userId="me", body={
                "name": name, "labelListVisibility": "labelShow",
                "messageListVisibility": "show"}).execute()
            existing[name] = created["id"]
    return {n: existing[n] for n in wanted}


def add_labels(service, msg_id: str, label_ids: list) -> None:
    service.users().messages().modify(
        userId="me", id=msg_id, body={"addLabelIds": list(label_ids)}).execute()


# ── Sending: to the signed-in account only ────────────────────────────────────

def send_to_self(service, subject: str, text_body: str, html_body: str) -> str:
    """Email the signed-in account itself. There is no recipient parameter on
    purpose: this module cannot send mail to anyone else."""
    me = account_email(service)
    msg = EmailMessage()
    msg["To"] = me
    msg["From"] = me
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return service.users().messages().send(userId="me", body={"raw": raw}).execute().get("id", "")
