"""Make an encrypted backup of everything under DATA_DIR, or restore one.

The backup is a zip of the data folders (client records, documents, billing,
settings, the database once it exists), encrypted as a whole with
BACKUP_ENCRYPTION_KEY, a key separate from DATA_ENCRYPTION_KEY: someone who
gets a backup file plus the server's key still can't read it.

    python scripts/backup_data.py create --out D:\\mt-legal-backups
    python scripts/backup_data.py restore D:\\mt-legal-backups\\mt-legal-20261109-0900.bak --to C:\\restore-test

Keep both keys somewhere other than the server (a password manager), and test
a restore now and then. On Render, run `create` from a cron job or the shell
and copy the file off the disk; a backup left on the same disk doesn't survive
losing it.
"""

import argparse
import io
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # this project's own only

from cryptography.fernet import Fernet  # noqa: E402

import shared  # noqa: E402
from services import storage  # noqa: E402

DATA_FOLDERS = (
    "client-accounts", "client-data", "client-files", "client-billing", "firm-settings",
    "security-state", "leads", "pending-intake", "draft-history", "research-history",
    "case-searches", "token-usage", "blog", "email-review",
)
DATA_FILES = ("page-visits.json", "calendar-token.json", "gmail-token.json")


def _fernet() -> Fernet:
    key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    if not key:
        raise SystemExit("BACKUP_ENCRYPTION_KEY is not set. Make one with:\n"
                         '  python -c "from cryptography.fernet import Fernet; '
                         'print(Fernet.generate_key().decode())"\n'
                         "and keep it outside the server.")
    return Fernet(key.encode())


def create(out_dir: Path) -> Path:
    f = _fernet()
    storage.require_outside_dir(out_dir, shared.BASE_DIR)
    buf = io.BytesIO()
    root = shared.DATA_ROOT
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in DATA_FOLDERS:
            for p in sorted((root / name).rglob("*")):
                if p.is_file() and not p.name.endswith(".tmp"):
                    z.write(p, p.relative_to(root).as_posix())
        for name in DATA_FILES:
            if (root / name).is_file():
                z.write(root / name, name)
        # The database through SQLite's online backup: a consistent copy even
        # while the app is writing (copying the file itself could catch it
        # mid-transaction).
        if shared.DB_PATH.exists():
            import sqlite3
            import tempfile
            from services import db
            with tempfile.TemporaryDirectory() as tmp:
                snap = Path(tmp) / "mt-legal.db"
                out = sqlite3.connect(str(snap))
                db.conn().backup(out)
                out.close()
                z.write(snap, shared.DB_PATH.relative_to(root).as_posix())
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"mt-legal-{datetime.now():%Y%m%d-%H%M}.bak"
    dest.write_bytes(f.encrypt(buf.getvalue()))
    return dest


def restore(backup: Path, to: Path) -> int:
    data = _fernet().decrypt(backup.read_bytes())
    to.mkdir(parents=True, exist_ok=True)
    if any(to.iterdir()):
        raise SystemExit(f"Refusing: {to} is not empty. Restore into an empty folder.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            target = (to / info.filename).resolve()
            if to.resolve() not in target.parents:
                raise SystemExit(f"Refusing unsafe path in backup: {info.filename}")
        z.extractall(to)
        return len(z.infolist())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--out", required=True, type=Path)
    r = sub.add_parser("restore")
    r.add_argument("backup", type=Path)
    r.add_argument("--to", required=True, type=Path)
    args = ap.parse_args()
    if args.cmd == "create":
        print(f"Backup written: {create(args.out)}")
    else:
        print(f"Restored {restore(args.backup, args.to)} file(s) into {args.to}. "
              "Point DATA_DIR at it to check, then move it into place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
