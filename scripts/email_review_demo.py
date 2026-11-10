"""Run the email reviewer against the fictional sample emails.

    python scripts/email_review_demo.py          # offline: keyword stand-in for Claude
    python scripts/email_review_demo.py --live   # real Claude (ANTHROPIC_API_KEY in .env)

No real mailbox is touched: Gmail is the in-memory fake from tests/gmail_fake.py,
built from tests/fixtures/sample_emails.json. Results go to a throwaway temp
folder, encrypted with a throwaway key, and are deleted afterwards. --live sends
only those fictional samples to the Anthropic API.
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from dotenv import load_dotenv  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()   # never the real key

import shared  # noqa: E402
from services import email_review, storage  # noqa: E402
from gmail_fake import FakeGmail, keyword_classifier  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="classify with the real Claude API")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shared.EMAIL_REVIEW_DIR = tmp / "email-review"
        shared.TOKEN_USAGE_DIR = tmp / "token-usage"
        shared.TOKEN_USAGE_DIR.mkdir()
        shared.CLIENT_ACCOUNTS_DIR = tmp / "accounts"
        shared.CLIENT_ACCOUNTS_DIR.mkdir()
        storage._fernet_cache = None
        # One sample sender is on file as a client, to show local client matching.
        storage.save_client({"username": "testclient", "client_name": "Test Client",
                             "email": "testclient@mail.example", "assigned_attorney": "Endocide"})

        fake = FakeGmail()
        now = datetime(2026, 11, 4, 9, 0)
        classify = None if args.live else keyword_classifier
        mode = f"live Claude ({shared.EMAIL_REVIEW_MODEL})" if args.live else "offline stand-in"
        print(f"Reviewing {len(fake.messages_by_id)} sample emails with {mode}...\n")
        counts = email_review.run_review(fake, now=now, classify=classify)
        print("Run:", counts, "\n")

        for r in email_review.list_reviews():
            flag = "URGENT " if r["urgent"] else ""
            print(f"[{flag}{r['category_label']}] {r['from_name'] or r['from_email']}: {r['subject']}")
            print(f"    {r['summary']}")
            if r["urgency_reason"]:
                print(f"    Why urgent: {r['urgency_reason']}")
            for d in r["deadlines"]:
                print(f"    Date: {d['date'] or 'unclear'} - {d['description']}")
            if r["matched_client"]:
                print("    (sender matches a client record)")
            print()

        print("Gmail labels added (label name -> messages):")
        names = {v: k for k, v in fake.label_store.items()}
        by_label = {}
        for msg_id, ids in fake.added.items():
            for lid in ids:
                by_label.setdefault(names[lid], []).append(msg_id)
        for name in sorted(by_label):
            print(f"    {name}: {', '.join(sorted(by_label[name]))}")
        writes = sorted({n for n, _ in fake.calls} - {"messages.list", "messages.get",
                                                       "labels.list", "getProfile"})
        print("Gmail write calls made:", ", ".join(writes))

        email_review.send_digest(fake, now=now)
        mail = fake.sent[0]
        print(f"\nDigest sent to {mail['To']} (from {mail['From']}):\n")
        print(mail.get_body(("plain",)).get_content())


if __name__ == "__main__":
    main()
