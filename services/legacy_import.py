"""services/legacy_import.py — move client-accounts/*.json into the database.

Used by scripts/migrate_to_db.py, and by production startup (app.py), where
nobody can run a script before the new code starts.

Each record (encrypted or legacy plaintext) is read, written encrypted into
the `clients` table and read back to check it; its access_log list moves to
the append-only audit log. The originals are copied to the backup folder
BEFORE anything is imported, and removed only after every record checks out.
Safe to re-run: records already in the database are skipped.
"""

import shutil
from datetime import datetime
from pathlib import Path

import shared
from services import audit, db, storage


class ImportError_(Exception):
    """The import could not run or finish; nothing was removed."""


def legacy_files() -> list:
    d = shared.CLIENT_ACCOUNTS_DIR
    return sorted(d.glob("*.json")) if d.exists() else []


def migrate(apply: bool, backup_dir=None) -> dict:
    files = legacy_files()
    report = {"files": len(files), "imported": 0, "already": 0, "audit": 0, "unreadable": []}
    records = []
    for path in files:
        try:
            rec = storage._read_record(path)
        except Exception:
            report["unreadable"].append(path.name)
            continue
        if rec.get("username") != path.stem or storage.safe_username(path.stem) != path.stem:
            report["unreadable"].append(path.name)
            continue
        records.append((path, rec))
    if not apply or report["unreadable"]:
        return report
    if backup_dir is None:
        raise ImportError_("A backup folder is required.")

    # Back up first, before anything is imported or removed, so a bad backup
    # location stops the run with nothing changed.
    backup_root = Path(backup_dir).resolve()
    if not Path(backup_root.anchor).exists():
        raise ImportError_(f"The backup location {backup_root} is on a drive that doesn't exist. "
                           "Choose a folder on a drive this computer has.")
    dest = backup_root / f"client-accounts-{datetime.now():%Y%m%d_%H%M%S}"
    try:
        dest.mkdir(parents=True)
        for path, _ in records:
            shutil.copy2(path, dest / path.name)
    except OSError as exc:
        raise ImportError_(f"Could not write the backup to {dest}: {exc}. Nothing was changed.")
    report["backup"] = str(dest)

    for path, rec in records:
        username = rec["username"]
        if storage.client_exists(username):
            report["already"] += 1
            continue
        access = rec.pop("access_log", None) or []
        with db.transaction() as c:
            storage._db_put(c, rec)
        for e in access:
            audit.record(e.get("action", "access"), client=username, detail=e.get("detail", ""),
                         actor=e.get("attorney", ""), role="attorney", ip=e.get("ip", ""),
                         ts=e.get("timestamp"))
            report["audit"] += 1
        if storage._db_get(db.conn(), username) != rec:
            raise ImportError_(f"Read-back check failed for {username}; nothing was removed.")
        report["imported"] += 1

    # Every record is in the database and read back correctly: retire the files.
    for path, _ in records:
        path.unlink()
    return report
