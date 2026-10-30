"""Encrypt every plaintext client account record in place.

Usage:
    python scripts/encrypt_existing_records.py --backup-dir D:\\law-office-backups

1. Copies client-accounts/ to a timestamped folder under --backup-dir
   (refused if that folder is inside this OneDrive-synced project).
2. Encrypts each plaintext record, re-reads it, and restores it from the
   backup if the round trip does not match.
Safe to re-run: already-encrypted records are skipped.
Stop the app before running this script.
"""

import argparse
import json
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


def encrypt_all(accounts_dir: Path, backup_root: Path, project_root: Path = ROOT):
    backup_root  = Path(backup_root).resolve()
    project_root = Path(project_root).resolve()
    storage.require_outside_dir(backup_root, project_root)
    # Microseconds keep two runs in the same second from colliding.
    backup = backup_root / f"client-accounts-{datetime.now():%Y%m%d_%H%M%S_%f}"
    shutil.copytree(accounts_dir, backup)

    counts = {"encrypted": 0, "already": 0, "failed": 0}
    for path in sorted(Path(accounts_dir).glob("*.json")):
        try:
            raw = path.read_bytes()
            if not storage._is_plaintext(raw):
                counts["already"] += 1
                continue
            original = json.loads(raw.decode("utf-8-sig"))
            storage._write_record(path, original)
            if storage._read_record(path) == original:
                counts["encrypted"] += 1
                continue
        except Exception:
            pass
        # Round-trip mismatch or any error: put the original back if we can.
        if (backup / path.name).exists():
            shutil.copy2(backup / path.name, path)
        counts["failed"] += 1
    return counts, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()
    try:
        storage._fernet()
    except RuntimeError as exc:
        print(exc)
        return 2
    counts, backup = encrypt_all(shared.CLIENT_ACCOUNTS_DIR, Path(args.backup_dir))
    print(f"Backup:            {backup}")
    print(f"Encrypted:         {counts['encrypted']}")
    print(f"Already encrypted: {counts['already']}")
    print(f"Failed (restored): {counts['failed']}")
    if not counts["failed"]:
        print("The backup folder still holds PLAINTEXT client records. Once you "
              "have confirmed the app works, securely delete it.")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
