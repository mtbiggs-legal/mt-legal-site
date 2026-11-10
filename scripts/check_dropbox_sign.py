#!/usr/bin/env python3
"""check_dropbox_sign.py — confirm the Dropbox Sign API key works.

Usage:
    python scripts/check_dropbox_sign.py you@example.com

Sends a one-page TEST-MODE signature request (free, not legally binding) to the
email you give, using DROPBOX_SIGN_API_KEY from .env, then reads its status
back. Nothing is stored in any client file. Sign or ignore the email.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import shared  # noqa: E402
from services import esign  # noqa: E402


def _test_pdf() -> bytes:
    from fpdf import FPDF
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_font("Helvetica", "", 14)
    pdf.multi_cell(0, 8, "MT Legal - Dropbox Sign connection test.\n\nThis is a test-mode request "
                         "and has no legal effect.\n\nSign here:")
    return bytes(pdf.output())


def main():
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print(__doc__)
        sys.exit(2)
    if not esign.configured():
        print("DROPBOX_SIGN_API_KEY is not set in .env.")
        sys.exit(1)
    shared.DROPBOX_SIGN_TEST_MODE = True            # this check never sends a binding request
    signer = [{"name": "Connection Test", "email": sys.argv[1], "status": "awaiting_signature"}]
    try:
        sent = esign._send_api("MT Legal connection test", "Dropbox Sign connection test", "Test only.",
                               signer, "connection_test.pdf", _test_pdf(), {"client": "connection-test"})
        back = esign._get_api(sent["signature_request_id"])
    except esign.EsignError as exc:
        print(f"Failed: {exc}")
        sys.exit(1)
    print("OK: Dropbox Sign accepted the request.")
    print(f"  request id : {sent['signature_request_id']}")
    print(f"  test mode  : {back.get('test_mode')}")
    print(f"  signer     : {back['signatures'][0].get('signer_email_address')} "
          f"({back['signatures'][0].get('status_code')})")
    print(f"Check {sys.argv[1]} for the test email.")


if __name__ == "__main__":
    main()
