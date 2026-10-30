"""One-off migration: bcrypt-hash any client passwords still stored in plaintext.

Older accounts were written before password hashing existed, so their password
sits in client-accounts/<user>.json in the clear. check_password() still accepts
those (legacy fallback) and upgrades them on next login — but an account whose
client never logs in stays readable forever.

Affected clients are required to choose a new password at next login.

Usage:
    python scripts/hash_existing_passwords.py            # dry run, changes nothing
    python scripts/hash_existing_passwords.py --apply --backup-dir D:\\law-office-backups

Stop the app before running this script.
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import shared  # noqa: E402
from services import storage
from services import accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually rewrite the files (default is a dry run)")
    parser.add_argument("--backup-dir",
                        help="folder OUTSIDE the project for the backup (required with --apply)")
    args = parser.parse_args()
    if args.apply and not args.backup_dir:
        parser.error("--backup-dir is required with --apply")
    if args.apply:
        storage.require_outside_dir(args.backup_dir, ROOT)

    skipped = []
    pending = accounts.upgrade_all_plaintext_passwords(apply=False, skipped=skipped)
    if skipped:
        print("Could not decrypt:")
        for name in skipped:
            print(f"    {name}")
    print(f"Plaintext passwords: {len(pending)}")
    for name in pending:
        print(f"    {name}")
    if not pending:
        print("\nNothing to migrate.")
        return 0
    if not args.apply:
        print("\nDry run — nothing was changed. Re-run with --apply.")
        return 0

    stamp  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = Path(args.backup_dir).resolve() / f"client-accounts-backup-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(shared.CLIENT_ACCOUNTS_DIR, backup)
    print(f"\nBackup written to: {backup}")
    done = accounts.upgrade_all_plaintext_passwords()
    print(f"Done — {len(done)} password(s) hashed; those clients must set a new "
          "password at next login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
