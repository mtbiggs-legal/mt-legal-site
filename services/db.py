"""services/db.py — the SQLite database on the data disk.

One file, DATA_DIR/db/mt-legal.db, in WAL mode so readers never wait for a
writer. Client records are still encrypted one by one (storage.py encrypts
before it writes here); the database adds real transactions, a revision
number per record for live updates, the append-only audit log, and matters.

Schema changes go in MIGRATIONS, in order; each runs once, inside a
transaction, and bumps PRAGMA user_version.
"""

import sqlite3
import threading
from contextlib import contextmanager

import shared

MIGRATIONS = [
    # 1: client records, audit log
    """
    CREATE TABLE clients (
        username          TEXT PRIMARY KEY,
        data              BLOB NOT NULL,            -- Fernet-encrypted JSON record
        assigned_attorney TEXT NOT NULL DEFAULT '',
        archived          INTEGER NOT NULL DEFAULT 0,
        rev               INTEGER NOT NULL DEFAULT 1,
        updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
    );
    CREATE INDEX clients_attorney ON clients(assigned_attorney, archived);

    CREATE TABLE audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT NOT NULL,
        actor      TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        client     TEXT NOT NULL DEFAULT '',
        action     TEXT NOT NULL,
        detail     BLOB,                            -- Fernet-encrypted text
        ip         TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX audit_client ON audit_log(client, id);
    CREATE INDEX audit_action ON audit_log(action, id);
    -- Append-only: the app never edits or deletes audit entries.
    CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # 2: matters (a client can have several over time)
    """
    CREATE TABLE matters (
        id         TEXT PRIMARY KEY,
        client     TEXT NOT NULL REFERENCES clients(username),
        data       BLOB NOT NULL,                   -- Fernet-encrypted JSON
        status     TEXT NOT NULL DEFAULT 'open',    -- open | closed
        opened_at  TEXT NOT NULL,
        closed_at  TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX matters_client ON matters(client, status);
    """,
]

_local = threading.local()
_init_lock = threading.Lock()
_initialized: set = set()


def db_path():
    return shared.DB_PATH


def _connect(path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA synchronous={getattr(shared, 'DB_SYNCHRONOUS', 'FULL')}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def conn() -> sqlite3.Connection:
    """This thread's connection to the current DB_PATH (tests change it)."""
    path = db_path()
    key = str(path)
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    c = conns.get(key)
    if c is None:
        c = conns[key] = _connect(path)
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                _migrate(c)
                _initialized.add(key)
    return c


def _migrate(c: sqlite3.Connection) -> None:
    version = c.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        c.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _statements(script):
                c.execute(stmt)
            c.execute(f"PRAGMA user_version = {i}")
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def _statements(script: str):
    """Split a migration into statements, keeping trigger bodies whole."""
    out, cur, in_trigger = [], [], False
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        cur.append(line)
        upper = stripped.upper()
        if upper.startswith("CREATE TRIGGER"):
            in_trigger = True
        if (in_trigger and upper.endswith("END;")) or (not in_trigger and stripped.endswith(";")):
            out.append("\n".join(cur))
            cur, in_trigger = [], False
    if cur:
        out.append("\n".join(cur))
    return out


@contextmanager
def transaction():
    """BEGIN IMMEDIATE ... COMMIT: one writer at a time, across processes too."""
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
    except BaseException:
        c.execute("ROLLBACK")
        raise
    c.execute("COMMIT")


def get_meta(key: str, default=None):
    row = conn().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    conn().execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def close_all() -> None:
    """Close this thread's connections (tests, scripts)."""
    for c in (getattr(_local, "conns", None) or {}).values():
        try:
            c.close()
        except Exception:
            pass
    _local.conns = {}
