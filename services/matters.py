"""services/matters.py — a client's matters (cases), past and present.

A client is the person; a matter is one engagement for them. Each matter is
a row in the `matters` table (its details encrypted). The client record
keeps the *current* matter's details in its usual fields (case_type, case_no,
county, court, legal_issue, next_court_date, opposing_parties) and its id in
`current_matter`, so every existing screen keeps working on the current
matter. Switching or closing saves those fields back to the matter row first.

A client from before matters existed gets one matter made from their record
the first time their matters are listed.
"""

import json
import secrets
from datetime import datetime

from services import db, storage

FIELDS = ("title", "case_type", "case_no", "county", "court", "legal_issue",
          "next_court_date", "opposing_parties")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _enc(data: dict) -> bytes:
    return storage.encrypt_bytes(json.dumps(data).encode("utf-8"))


def _dec(blob) -> dict:
    return json.loads(storage.decrypt_bytes(bytes(blob)).decode("utf-8"))


def _fields_from(client: dict) -> dict:
    out = {k: client.get(k, [] if k == "opposing_parties" else "") for k in FIELDS if k != "title"}
    out["title"] = client.get("matter_title") or client.get("case_type") or "Matter"
    return out


def _row(r) -> dict:
    return {"id": r["id"], "status": r["status"], "opened_at": r["opened_at"],
            "closed_at": r["closed_at"], **_dec(r["data"])}


def _rows(c, username):
    return c.execute("SELECT * FROM matters WHERE client = ? ORDER BY opened_at, rowid", (username,)).fetchall()


def list_for(username: str) -> list:
    """All matters for a client, oldest first, the current one up to date."""
    _ensure(username)
    _sync_current(username)
    client = storage.load_client(username) or {}
    out = [_row(r) for r in _rows(db.conn(), username)]
    for m in out:
        m["current"] = m["id"] == client.get("current_matter")
    return out


def _ensure(username: str) -> None:
    """Give a pre-matters client one matter, made from their record."""
    if db.conn().execute("SELECT 1 FROM matters WHERE client = ? LIMIT 1", (username,)).fetchone():
        return
    client = storage.load_client(username)
    if not client:
        return
    mid = "m_" + secrets.token_hex(5)
    with db.transaction() as c:
        if c.execute("SELECT 1 FROM matters WHERE client = ? LIMIT 1", (username,)).fetchone():
            return
        c.execute("INSERT INTO matters(id, client, data, status, opened_at) VALUES(?, ?, ?, ?, ?)",
                  (mid, username, _enc(_fields_from(client)),
                   "closed" if client.get("archived") else "open",
                   (client.get("created_at") or client.get("last_communication") or _now())[:19]))
    storage.update_client_field_atomic(username, "current_matter", mid)


def _sync_current(username: str) -> None:
    """Save the record's current-matter fields into that matter's row."""
    client = storage.load_client(username)
    mid = (client or {}).get("current_matter")
    if not mid:
        return
    with db.transaction() as c:
        c.execute("UPDATE matters SET data = ? WHERE id = ? AND client = ?",
                  (_enc(_fields_from(client)), mid, username))


def open_matter(username: str, fields: dict) -> dict:
    """Open a new matter for an existing client and make it current."""
    _ensure(username)
    _sync_current(username)
    data = {k: fields.get(k, [] if k == "opposing_parties" else "") for k in FIELDS}
    data["title"] = (data.get("title") or data.get("case_type") or "New matter")[:200]
    mid = "m_" + secrets.token_hex(5)
    with db.transaction() as c:
        c.execute("INSERT INTO matters(id, client, data, status, opened_at) VALUES(?, ?, ?, 'open', ?)",
                  (mid, username, _enc(data), _now()))
    _make_current(username, mid, data)
    return {"id": mid, "status": "open", **data}


def _make_current(username: str, mid: str, data: dict) -> None:
    def _apply(c):
        for k in FIELDS:
            if k == "title":
                c["matter_title"] = data.get("title", "")
            else:
                c[k] = data.get(k, [] if k == "opposing_parties" else "")
        c["current_matter"] = mid
        c["archived"] = False
    storage.update_client_atomic(username, _apply)


def switch(username: str, matter_id: str) -> bool:
    _sync_current(username)
    row = db.conn().execute("SELECT * FROM matters WHERE id = ? AND client = ?",
                            (matter_id, username)).fetchone()
    if not row:
        return False
    _make_current(username, matter_id, _dec(row["data"]))
    return True


def close(username: str, matter_id: str) -> bool:
    _sync_current(username)
    with db.transaction() as c:
        n = c.execute("UPDATE matters SET status = 'closed', closed_at = ? "
                      "WHERE id = ? AND client = ? AND status = 'open'",
                      (_now(), matter_id, username)).rowcount
    return bool(n)


def reopen(username: str, matter_id: str) -> bool:
    with db.transaction() as c:
        n = c.execute("UPDATE matters SET status = 'open', closed_at = '' "
                      "WHERE id = ? AND client = ? AND status = 'closed'",
                      (matter_id, username)).rowcount
    return bool(n)
