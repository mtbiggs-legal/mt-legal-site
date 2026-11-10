"""Move client records from client-accounts/*.json into the database.

The work is done by services/legacy_import.py: originals are copied to
--backup-dir (outside the project) first, each record is imported and read
back, and only then are the files removed from client-accounts/. Runs as a
dry run unless --apply is given; safe to re-run.

    python scripts/migrate_to_db.py
    python scripts/migrate_to_db.py --apply --backup-dir C:\\Users\\you\\mt-legal-backup

(In production the app does this by itself at startup, backing up to
DATA_DIR/migration-backup.)
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")          # this project's own .env only

import shared  # noqa: E402
from services import legacy_import, storage  # noqa: E402


def migrate(apply: bool, backup_dir=None) -> dict:
    if apply and backup_dir is not None:
        storage.require_outside_dir(backup_dir, shared.BASE_DIR)
    try:
        return legacy_import.migrate(apply, backup_dir)
    except legacy_import.ImportError_ as exc:
        raise SystemExit(str(exc))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir", type=Path)
    args = ap.parse_args()
    if args.apply and not args.backup_dir:
        print("--apply needs --backup-dir.", file=sys.stderr)
        return 2
    storage._fernet()
    r = migrate(args.apply, args.backup_dir)
    print(f"{r['files']} record file(s) found.")
    if r["unreadable"]:
        print("Cannot read (fix or remove these first; nothing was changed):")
        for name in r["unreadable"]:
            print("  ", name)
        return 1
    if not args.apply:
        print("Dry run. Re-run with --apply --backup-dir <folder outside the project>.")
        return 0
    print(f"Imported {r['imported']} (already there: {r['already']}); "
          f"{r['audit']} access-log entries moved to the audit log.")
    if r.get("backup"):
        print(f"Original files copied to {r['backup']} and removed from client-accounts/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
