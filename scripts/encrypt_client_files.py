"""Encrypt client documents, intake records and leads that are still plaintext.

The app reads both forms, so this can run at any time. It is a dry run unless
--apply is given, and --apply requires a backup folder outside the project
(which OneDrive may sync): every file is copied there before it is changed.

    python scripts/encrypt_client_files.py
    python scripts/encrypt_client_files.py --apply --backup-dir D:\\mt-legal-backup
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # this project's own only

import shared  # noqa: E402
from services import client_files, storage  # noqa: E402


def _plaintext_documents():
    for p in sorted(shared.CLIENT_FILES_DIR.glob("*/documents/*/*")):
        if p.is_file() and not p.name.endswith(".tmp"):
            with open(p, "rb") as fh:
                if fh.read(len(client_files.MAGIC)) != client_files.MAGIC:
                    yield p


def _plaintext_json(folder: Path):
    for p in sorted(folder.glob("*.json")):
        if storage._is_plaintext(p.read_bytes()):
            yield p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="encrypt (default: only list)")
    ap.add_argument("--backup-dir", help="folder outside the project for copies of the originals")
    args = ap.parse_args()

    storage._fernet()                          # fail early on a missing/bad key
    docs  = list(_plaintext_documents())
    jsons = list(_plaintext_json(shared.CLIENT_DATA_DIR)) + list(_plaintext_json(shared.LEADS_DIR))
    print(f"{len(docs)} plaintext document(s), {len(jsons)} plaintext intake/lead record(s).")
    if not args.apply:
        for p in docs + jsons:
            print("  ", p.relative_to(shared.DATA_ROOT))
        print("Dry run. Re-run with --apply --backup-dir <folder outside the project>.")
        return 0
    if not args.backup_dir:
        print("--apply needs --backup-dir.", file=sys.stderr)
        return 2
    backup = Path(args.backup_dir)
    storage.require_outside_dir(backup, shared.BASE_DIR)
    for p in docs + jsons:
        dest = backup / p.relative_to(shared.DATA_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    for p in docs:
        client_files.write_path(p, p.read_bytes())
    for p in jsons:
        data = storage.read_json(p)
        if data is not None:
            storage.write_encrypted_json(p, data)
    print(f"Encrypted {len(docs) + len(jsons)} file(s). Originals copied to {backup}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
