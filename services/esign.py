"""services/esign.py — e-signature through Dropbox Sign.

A signature request is created from a document already in the client's file.
Its state lives on the client record (`esign_requests`, encrypted with the
rest of the record), so live updates, the assistant and both portals see it.
When every signer has signed, the completed PDF is saved to the client's
"Signed Documents" folder.

Status reaches us two ways: Dropbox Sign's callback to /webhooks/dropbox-sign
(production, where the site is reachable), and refresh() whenever the
attorney opens the signatures list (local copies the callback can't reach).

All HTTP to Dropbox Sign goes through _api(); nothing else here knows the
wire format. Requests run in test mode (shared.DROPBOX_SIGN_TEST_MODE) until
the firm turns it off.
"""

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime

import requests

import shared
from services import client_files
from services import storage

API_BASE        = "https://api.hellosign.com/v3"
SIGNABLE_EXTS   = {".pdf", ".doc", ".docx"}
MAX_SIGNERS     = 5
REFRESH_SECONDS = 60           # don't ask Dropbox Sign about one request more often
SIGNED_CATEGORY = "Signed Documents"
CALLBACK_REPLY  = "Hello API Event Received"
_EMAIL_RE       = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EsignError(Exception):
    """A problem to show the attorney."""


def configured() -> bool:
    return bool(shared.DROPBOX_SIGN_API_KEY)


# ── Dropbox Sign HTTP ────────────────────────────────────────────────────────

def _api(method: str, path: str, *, data=None, files=None, json_body=None, stream=False):
    if not configured():
        raise EsignError("E-signing isn't set up yet: add DROPBOX_SIGN_API_KEY to .env.")
    try:
        r = requests.request(method, API_BASE + path, auth=(shared.DROPBOX_SIGN_API_KEY, ""),
                             data=data, files=files, json=json_body, timeout=60, stream=stream)
    except requests.RequestException as exc:
        raise EsignError(f"Couldn't reach Dropbox Sign ({type(exc).__name__}).")
    if r.status_code == 409:
        return None                                  # files still being prepared
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("error_msg", "")
        except ValueError:
            msg = ""
        raise EsignError(f"Dropbox Sign refused the request ({r.status_code}){': ' + msg if msg else ''}.")
    return r


def _send_api(title, subject, message, signers, filename, content, metadata):
    data = {"title": title, "subject": subject, "message": message,
            "test_mode": "1" if shared.DROPBOX_SIGN_TEST_MODE else "0"}
    for i, s in enumerate(signers):
        data[f"signers[{i}][name]"] = s["name"]
        data[f"signers[{i}][email_address]"] = s["email"]
        data[f"signers[{i}][order]"] = str(i)
    for k, v in metadata.items():
        data[f"metadata[{k}]"] = v
    r = _api("POST", "/signature_request/send", data=data,
             files={"files[0]": (filename, content)})
    return r.json()["signature_request"]


def _get_api(request_id: str) -> dict:
    return _api("GET", f"/signature_request/{request_id}").json()["signature_request"]


def _download_api(request_id: str):
    r = _api("GET", f"/signature_request/files/{request_id}?file_type=pdf")
    return None if r is None else r.content


def _remind_api(request_id: str, email: str) -> None:
    _api("POST", f"/signature_request/remind/{request_id}", data={"email_address": email})


# ── Records ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _overall(signers: list, api: dict) -> str:
    if api.get("is_declined") or any(s["status"] == "declined" for s in signers):
        return "declined"
    if api.get("has_error"):
        return "error"
    if api.get("is_complete") or (signers and all(s["status"] == "signed" for s in signers)):
        return "signed"
    if any(s["status"] == "signed" for s in signers):
        return "partly signed"
    return "sent"


def _apply_api(entry: dict, api: dict) -> None:
    by_email = {(s.get("signer_email_address") or "").lower(): s for s in api.get("signatures") or []}
    for s in entry["signers"]:
        a = by_email.get(s["email"].lower())
        if a:
            s["status"] = a.get("status_code") or s["status"]
            if a.get("signed_at"):
                s["signed_at"] = datetime.fromtimestamp(int(a["signed_at"])).strftime("%Y-%m-%d %H:%M")
            if a.get("last_viewed_at"):
                s["viewed"] = True
    entry["status"] = _overall(entry["signers"], api)
    entry["checked_at"] = time.time()


def list_requests(client: dict) -> list:
    return list(reversed(client.get("esign_requests") or []))


# ── Sending ──────────────────────────────────────────────────────────────────

def clean_signers(signers) -> list:
    out, seen = [], set()
    for s in signers or []:
        name = (s.get("name") or "").strip()[:100]
        email = (s.get("email") or "").strip()[:200]
        if not name or not _EMAIL_RE.match(email):
            raise EsignError("Each signer needs a name and a valid email address.")
        if email.lower() in seen:
            raise EsignError(f"{email} is listed twice.")
        seen.add(email.lower())
        out.append({"name": name, "email": email, "status": "awaiting_signature"})
    if not out:
        raise EsignError("Add at least one signer.")
    if len(out) > MAX_SIGNERS:
        raise EsignError(f"At most {MAX_SIGNERS} signers.")
    return out


def document_path(username: str, category: str, filename: str):
    from services.documents import resolve_doc_path
    path = resolve_doc_path(username, category, filename)
    if path is None:
        raise EsignError("That document isn't in the client's file.")
    if path.suffix.lower() not in SIGNABLE_EXTS:
        raise EsignError("Only PDF and Word documents can be sent for signature.")
    return path


def send(username: str, category: str, filename: str, signers, subject: str, message: str,
         sent_by: str) -> dict:
    """Send a document from the client's file for signature. Returns the stored entry."""
    path = document_path(username, category, filename)
    signers = clean_signers(signers)
    title = path.stem.replace("_", " ")[:200]
    subject = (subject or f"Please sign: {title}").strip()[:200]
    message = (message or "").strip()[:2000]
    api = _send_api(title, subject, message, signers, path.name, client_files.read_bytes(path),
                    {"client": username, "ref": secrets.token_hex(6)})
    entry = {"id": api["signature_request_id"], "title": title, "document": f"{category}/{path.name}",
             "signers": signers, "subject": subject, "status": "sent", "sent_at": _now(),
             "sent_by": sent_by, "test_mode": bool(shared.DROPBOX_SIGN_TEST_MODE),
             "signed_file": "", "checked_at": time.time()}
    _apply_api(entry, api)
    storage.update_client_atomic(username, lambda c: c.setdefault("esign_requests", []).append(entry))
    storage._log_activity(username, "esign_sent",
                          f"Sent for signature: {title} → " + ", ".join(s["name"] for s in signers))
    return entry


# ── Status ───────────────────────────────────────────────────────────────────

def _save_signed(username: str, entry: dict) -> str:
    """Download the completed PDF into Signed Documents. Returns its
    "category/name", or "" if Dropbox Sign hasn't finished preparing it."""
    content = _download_api(entry["id"])
    if not content:
        return ""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", entry["title"]).strip("_")[:80] or "document"
    folder = storage._client_docs_dir(username, SIGNED_CATEGORY)
    dest = folder / f"{stem}_signed.pdf"
    n = 2
    while dest.exists():
        dest = folder / f"{stem}_signed_{n}.pdf"
        n += 1
    client_files.write_path(dest, content)
    return f"{SIGNED_CATEGORY}/{dest.name}"


def _update(username: str, request_id: str, api: dict) -> dict:
    """Apply Dropbox Sign's view of one request to the record; save the PDF once
    complete. The download runs outside the record lock."""
    result = {}

    def mutate(c):
        for entry in c.get("esign_requests") or []:
            if entry["id"] == request_id:
                was = entry["status"]
                _apply_api(entry, api)
                result.update(entry=dict(entry), was=was)

    storage.update_client_atomic(username, mutate)
    entry = result.get("entry")
    if not entry:
        return {}
    if entry["status"] != result["was"]:
        storage._log_activity(username, "esign_" + entry["status"].replace(" ", "_"),
                              f"Signature request {entry['status']}: {entry['title']}")
    if entry["status"] == "signed" and not entry.get("signed_file"):
        saved = _save_signed(username, entry)
        if saved:
            def mark(c):
                for e in c.get("esign_requests") or []:
                    if e["id"] == request_id and not e.get("signed_file"):
                        e["signed_file"] = saved
            storage.update_client_atomic(username, mark)
            storage._log_activity(username, "document_upload", f"Signed copy saved: {saved}")
            entry["signed_file"] = saved
    return entry


def refresh(username: str, force: bool = False) -> list:
    """Ask Dropbox Sign about this client's open requests (at most once a minute each)."""
    client = storage.load_client(username) or {}
    for entry in client.get("esign_requests") or []:
        done = entry["status"] in ("declined", "error") or (entry["status"] == "signed" and entry.get("signed_file"))
        if done or not configured():
            continue
        if not force and time.time() - float(entry.get("checked_at") or 0) < REFRESH_SECONDS:
            continue
        try:
            _update(username, entry["id"], _get_api(entry["id"]))
        except EsignError:
            continue
    return list_requests(storage.load_client(username) or {})


def remind(username: str, request_id: str) -> list:
    client = storage.load_client(username) or {}
    entry = next((e for e in client.get("esign_requests") or [] if e["id"] == request_id), None)
    if not entry:
        raise EsignError("Signature request not found.")
    waiting = [s for s in entry["signers"] if s["status"] != "signed"]
    if not waiting or entry["status"] in ("declined", "signed"):
        raise EsignError("Nobody is waiting to sign this one.")
    for s in waiting:
        _remind_api(request_id, s["email"])
    storage._log_activity(username, "esign_reminded",
                          f"Signature reminder sent: {entry['title']} → " + ", ".join(s["name"] for s in waiting))
    return [s["name"] for s in waiting]


# ── Callback ─────────────────────────────────────────────────────────────────

def verify_event(event: dict) -> bool:
    """event_hash = HMAC-SHA256(api_key, event_time + event_type), hex."""
    if not configured():
        return False
    expected = hmac.new(shared.DROPBOX_SIGN_API_KEY.encode(),
                        (str(event.get("event_time", "")) + str(event.get("event_type", ""))).encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(event.get("event_hash", "")))


CALLBACK_MAX_AGE = 3 * 24 * 3600      # Dropbox Sign retries failed callbacks for a while
_seen_lock = threading.Lock()
_seen_events: dict = {}               # event_hash -> time first seen


def _fresh_and_new(event: dict) -> bool:
    """Reject events too old (or from the future) and hashes already handled."""
    try:
        age = time.time() - int(event.get("event_time"))
    except (TypeError, ValueError):
        return False
    if not -300 <= age <= CALLBACK_MAX_AGE:
        return False
    h = str(event.get("event_hash", ""))
    with _seen_lock:
        cutoff = time.time() - CALLBACK_MAX_AGE
        for k in [k for k, t in _seen_events.items() if t < cutoff]:
            del _seen_events[k]
        if h in _seen_events:
            return False
        _seen_events[h] = time.time()
    return True


def handle_callback(payload: dict) -> bool:
    """Handle one callback. Returns False when the hash doesn't verify.

    The event_hash covers only the event's time and type, not the request
    details posted with it, so those details are never trusted: a verified,
    fresh, first-seen event only prompts us to ask Dropbox Sign for the
    request's real status, for a request we sent."""
    event = payload.get("event") or {}
    if not verify_event(event):
        return False
    if not _fresh_and_new(event):
        return True                          # acknowledged, but nothing is done
    request = payload.get("signature_request") or {}
    username = storage.safe_username((request.get("metadata") or {}).get("client", ""))
    request_id = str(request.get("signature_request_id", ""))
    client = storage.load_client(username) if username else None
    if client and request_id and any(e["id"] == request_id for e in client.get("esign_requests") or []):
        try:
            _update(username, request_id, _get_api(request_id))
        except EsignError:
            pass                             # the next refresh catches up
    return True


def parse_callback_form(form) -> dict:
    try:
        return json.loads(form.get("json") or "{}")
    except ValueError:
        return {}
