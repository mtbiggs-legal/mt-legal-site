"""Quick SendGrid diagnostic — run from the project folder:
    python scripts/check_sendgrid.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

api_key   = os.getenv("SENDGRID_API_KEY", "")
from_addr = os.getenv("FROM_EMAIL", "")
firm_addr = os.getenv("FIRM_EMAIL", from_addr)

print("=== SendGrid Diagnostic ===")
print(f"API key   : {'SET (' + api_key[:10] + '...)' if api_key else 'MISSING ✗'}")
print(f"FROM      : {from_addr or 'MISSING ✗'}")
print(f"FIRM_EMAIL: {firm_addr or 'MISSING ✗'}")
print()

if not api_key:
    print("ERROR: SENDGRID_API_KEY is not set in .env — cannot send email.")
    sys.exit(1)

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail, Email, To, Content
except ImportError:
    print("ERROR: sendgrid library not installed. Run: pip install sendgrid")
    sys.exit(1)

print(f"Sending test email FROM {from_addr} TO {firm_addr} ...")
sg = sendgrid.SendGridAPIClient(api_key=api_key)

message = Mail(
    from_email         = Email(from_addr, "Endo-Legal Test"),
    to_emails          = To(firm_addr, "Endo-Legal"),
    subject            = "[TEST] SendGrid connectivity check",
    plain_text_content = Content("text/plain", "This is a test email from your law office app."),
    html_content       = Content("text/html",
                                 "<p>This is a <strong>test email</strong> from your law office app.</p>"),
)

try:
    response = sg.client.mail.send.post(request_body=message.get())
    print(f"Status code : {response.status_code}")
    print(f"Response    : {response.body}")
    if response.status_code in (200, 201, 202):
        print()
        print("✓ Email sent successfully! Check your inbox at:", firm_addr)
    else:
        print()
        print("✗ SendGrid rejected the request — see status/body above.")
except Exception as e:
    print(f"✗ Exception: {e}")
