"""services/audit.py — the append-only audit log (database table audit_log).

Who did what, to which client, from where: attorney access to client files,
sign-ins and failed sign-ins, lockouts, two-step setup, invitations, password
changes. Entries can't be edited or deleted (database triggers refuse), and
the free-text detail is encrypted like the client records. Unlike the old
access_log list inside each client record, it isn't capped and doesn't
depend on the client record being saved.
"""

from datetime import datetime, timedelta

from flask import has_request_context, request, session

from services import db, storage

VIEW_DEDUP = timedelta(minutes=10)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def record(action: str, client: str = "", detail: str = "", actor: str = None,
           role: str = None, ip: str = None, ts: str = None) -> None:
    """Append one entry. Actor, role and IP default to the current request."""
    if has_request_context():
        actor = session.get("username", "") if actor is None else actor
        role  = session.get("role", "") if role is None else role
        ip    = (request.remote_addr or "") if ip is None else ip
    db.conn().execute(
        "INSERT INTO audit_log(ts, actor, actor_role, client, action, detail, ip) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        (ts or _now(), actor or "", role or "", client or "", action,
         storage.encrypt_bytes((detail or "")[:500].encode("utf-8")) if detail else None, ip or ""))


def recently_viewed(actor: str, client: str, action: str) -> bool:
    """True if `actor` logged `action` on `client` in the last VIEW_DEDUP."""
    since = (datetime.now() - VIEW_DEDUP).strftime("%Y-%m-%dT%H:%M:%S")
    return db.conn().execute(
        "SELECT 1 FROM audit_log WHERE client = ? AND actor = ? AND action = ? AND ts >= ? LIMIT 1",
        (client, actor, action, since)).fetchone() is not None


def _detail(blob) -> str:
    if not blob:
        return ""
    try:
        return storage.decrypt_bytes(bytes(blob)).decode("utf-8")
    except Exception:
        return "(unreadable)"


def for_client(client: str, limit: int = 1000) -> list:
    """Newest first, shaped like the old per-record access_log entries."""
    rows = db.conn().execute(
        "SELECT ts, actor, actor_role, action, detail, ip FROM audit_log "
        "WHERE client = ? ORDER BY id DESC LIMIT ?", (client, limit))
    return [{"timestamp": r["ts"], "attorney": r["actor"], "role": r["actor_role"],
             "action": r["action"], "detail": _detail(r["detail"]), "ip": r["ip"]} for r in rows]


def recent(limit: int = 200, actions=None) -> list:
    sql, args = "SELECT * FROM audit_log", []
    if actions:
        sql += " WHERE action IN (%s)" % ",".join("?" * len(actions))
        args += list(actions)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return [{"timestamp": r["ts"], "actor": r["actor"], "role": r["actor_role"],
             "client": r["client"], "action": r["action"], "detail": _detail(r["detail"]),
             "ip": r["ip"]} for r in db.conn().execute(sql, args)]
