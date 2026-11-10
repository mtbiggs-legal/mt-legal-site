"""services/live.py — change detection for live portal updates.

The portals poll a small endpoint (blueprints/live.py) every few seconds and
after every change they make. A client's revision is built from file
metadata only — the record, its billing ledger, and its documents folders —
so an unchanged file is never decrypted twice. Anything that writes those
files (portal routes, the assistant, the client portal, payment webhooks,
scripts) shows up without that code knowing about live updates.

Summaries are cached per (username, revision), so a poll costs a stat() per
file plus decrypting only the records that actually changed.
"""

import hashlib
import threading

import shared
from services import billing, storage
from services.accounts import can_access_client

_cache_lock = threading.Lock()
_summaries: dict = {}            # (username, rev) -> summary
_MAX_CACHE = 2000


def _stat_sig(path) -> str:
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return "-"


def _docs_sig(username: str, client_view: bool = False) -> str:
    """Changes when a document is added, removed, renamed or rewritten. The
    client's view leaves out attorney-only folders (Drafts)."""
    root = shared.CLIENT_FILES_DIR / username / "documents"
    if not root.exists():
        return "-"
    parts = []
    try:
        for cat in sorted(root.iterdir()):
            if client_view and cat.name in shared.ATTORNEY_ONLY_CATEGORIES:
                continue
            if cat.is_dir():
                for f in sorted(cat.iterdir()):
                    if f.is_file():
                        parts.append(f"{cat.name}/{f.name}:{_stat_sig(f)}")
    except OSError:
        return "?"
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12] if parts else "0"


def client_rev(username: str, client_view: bool = False, revs: dict = None) -> str:
    """Revision of everything shown about one client (in the client portal,
    when client_view, which ignores attorney-only folders). The record's part
    is its database revision, bumped on every write."""
    if not username or storage.safe_username(username) != username:
        return ""
    rec_rev = (revs if revs is not None else storage.client_revs()).get(username)
    return "|".join((
        str(rec_rev) if rec_rev is not None else "-",
        _stat_sig(shared.CLIENT_BILLING_DIR / f"{username}.json"),
        _docs_sig(username, client_view),
    ))


def _summary(username: str, rev: str):
    key = (username, rev)
    with _cache_lock:
        if key in _summaries:
            return _summaries[key]
    client = storage.load_client(username)
    if not client:
        return None
    ledger = billing.load_ledger(username)
    summary = {
        "username":           username,
        "client_name":        client.get("client_name") or username,
        "assigned_attorney":  client.get("assigned_attorney", ""),
        "co_counsel":         list(client.get("co_counsel") or []),
        "archived":           bool(client.get("archived")),
        "case_no":            client.get("case_no", ""),
        "next_court_date":    client.get("next_court_date", ""),
        "hours_billed":       client.get("hours_billed", 0),
        "amount_due":         billing.amount_due(client, ledger),
        "last_communication": client.get("last_communication", ""),
        "phone":              client.get("phone", ""),
        "email":              client.get("email", ""),
        "conflict_unresolved": bool(client.get("conflict_unresolved")),
    }
    with _cache_lock:
        if len(_summaries) > _MAX_CACHE:
            _summaries.clear()
        _summaries[key] = summary
    return summary


def leads_rev() -> str:
    try:
        files = sorted(shared.LEADS_DIR.glob("*.json"))
    except OSError:
        return "-"
    return hashlib.sha1("|".join(f"{p.name}:{_stat_sig(p)}" for p in files).encode()).hexdigest()[:12]


def attorney_snapshot(attorney: str) -> dict:
    """Revision and summary of every client this attorney can see, plus leads."""
    clients = {}
    revs = storage.client_revs()
    for username in sorted(revs):
        if storage.safe_username(username) != username:
            continue
        rev = client_rev(username, revs=revs)
        try:
            s = _summary(username, rev)
        except storage.RecordDecryptError:
            continue
        if s and can_access_client(attorney, s):
            view = {k: v for k, v in s.items() if k not in ("assigned_attorney", "co_counsel")}
            clients[username] = {"rev": rev, **view}
    leads = leads_rev()
    token = hashlib.sha1(("|".join(f"{u}={c['rev']}" for u, c in sorted(clients.items()))
                          + "#" + leads).encode()).hexdigest()
    return {"token": token, "clients": clients, "leads": leads}
