"""blueprints/email_service.py — Transactional email via SendGrid.

Sends auto-reply emails when:
  - A prospect submits a lead capture form  (/capture/lead)
  - A client completes the full intake form (/intake/submit)

Required .env variables:
    SENDGRID_API_KEY  — your SendGrid API key (starts with SG.)
    FROM_EMAIL        — verified sender address (e.g. endo.legalbot@gmail.com)
    FIRM_EMAIL        — firm notification address (gets a copy of every lead/intake)
    CAL_BOOKING_URL   — your Cal.com booking link
    FIRM_PHONE        — office phone number shown in emails
"""

import os
import logging
from datetime import datetime
from html import escape

log = logging.getLogger(__name__)

# ── Config helpers (read at call time so .env changes take effect on restart) ──

def _cfg(key, default=""):
    return os.getenv(key, default)

def _api_key():       return _cfg("SENDGRID_API_KEY")
def _from_email():    return _cfg("FROM_EMAIL", "endo.legalbot@gmail.com")
def _from_name():     return _cfg("FROM_NAME",  "MT Legal")
def _cal_url():       return _cfg("CAL_BOOKING_URL", "https://cal.com/mt-legal/consultation")
def _firm_phone():    return _cfg("FIRM_PHONE", "(615) 000-0000")
def _firm_website():  return _cfg("FIRM_WEBSITE", "https://mt-legal.com")
def _firm_email():    return _cfg("FIRM_EMAIL", _from_email())  # defaults to FROM_EMAIL

# Attorney display names for personalisation
class _AttorneyDisplay:
    """Display names from the attorney registry in shared.py (read at call time)."""
    def get(self, username, default=""):
        import shared
        return (shared.ATTORNEYS.get(username) or {}).get("display", default)


ATTORNEY_DISPLAY = _AttorneyDisplay()

# Practice area → short phrase used inside the email body
PRACTICE_BLURB = {
    "Criminal Defense":           "criminal defense",
    "DeFi / Crypto Law":          "DeFi and cryptocurrency law",
    "Crypto LLC Formation":       "crypto LLC formation",
    "Real World Assets Tokenization": "real-world asset tokenization",
    "AI / Technology Law":        "AI and technology law",
    "Stablecoins / Agentic Payments": "stablecoins and agentic commerce",
    "Civil Rights":               "civil rights",
    "Civil Litigation":           "civil litigation",
    "Family Law — Divorce":       "family law / divorce",
    "Family Law — Child Custody": "family law / child custody",
    "Personal Injury":            "personal injury",
    "Employment Law":             "employment law",
    "Real Estate":                "real estate law",
    "Contract Dispute":           "contract disputes",
    "Estate Planning":            "estate planning",
}


# ── Core send helper ──────────────────────────────────────────────────────────

def _send(to_email: str, to_name: str, subject: str, html_body: str, text_body: str,
          cc_firm: bool = False) -> bool:
    """Send one email via SendGrid. Returns True on success, False on failure.
    If cc_firm=True, also sends a notification copy to FIRM_EMAIL.
    """
    api_key = _api_key()
    if not api_key:
        log.warning("SENDGRID_API_KEY not set — email not sent to %s", to_email)
        return False
    if not to_email or "@" not in to_email:
        log.warning("Invalid recipient email: %s", to_email)
        return False

    from_addr  = _from_email()
    from_name  = _from_name()
    firm_email = _firm_email()

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content

        sg = sendgrid.SendGridAPIClient(api_key=api_key)

        message = Mail(
            from_email         = Email(from_addr, from_name),
            to_emails          = To(to_email, to_name),
            subject            = subject,
            plain_text_content = Content("text/plain", text_body),
            html_content       = Content("text/html",  html_body),
        )

        # BCC the firm on every outgoing email so nothing gets missed
        if cc_firm and firm_email and firm_email != to_email:
            message.add_bcc(Email(firm_email, from_name))

        response = sg.client.mail.send.post(request_body=message.get())
        if response.status_code in (200, 201, 202):
            log.info("Email sent to %s (status %s)", to_email, response.status_code)
            return True
        else:
            log.error("SendGrid returned %s for %s: %s",
                      response.status_code, to_email, response.body)
            return False
    except Exception as exc:
        log.error("Email send failed for %s: %s", to_email, exc)
        return False


def _send_firm_alert(subject: str, html_body: str, text_body: str) -> None:
    """Send a standalone alert directly to the firm inbox (no client CC)."""
    firm_email = _firm_email()
    if firm_email:
        _send(firm_email, _from_name(), subject, html_body, text_body, cc_firm=False)


# ── Email template ─────────────────────────────────────────────────────────────

def _html_wrapper(content_html: str) -> str:
    """Wrap content in the firm's branded email shell."""
    year     = datetime.now().year
    website  = _firm_website()
    phone    = _firm_phone()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MT Legal</title>
  <style>
    body {{ margin:0; padding:0; background:#f4f6fa; font-family:Arial,sans-serif; color:#333; }}
    .wrap {{ max-width:600px; margin:32px auto; background:#fff;
             border-radius:8px; overflow:hidden;
             box-shadow:0 2px 12px rgba(0,0,0,.08); }}
    .hdr  {{ background:#1a2d5a; padding:28px 36px; text-align:center; }}
    .hdr-firm {{ color:#c9a84c; font-family:Georgia,serif;
                 font-size:20px; font-weight:bold; letter-spacing:.03em; margin:0; }}
    .hdr-tag  {{ color:#aab6cc; font-size:12px; margin-top:6px; }}
    .gold-bar {{ height:4px; background:#c9a84c; }}
    .body {{ padding:32px 36px; }}
    .body p {{ line-height:1.7; margin:0 0 16px; font-size:15px; }}
    .body .greeting {{ font-size:17px; font-weight:bold; color:#1a2d5a; margin-bottom:12px; }}
    .cta  {{ text-align:center; margin:28px 0; }}
    .cta a {{ display:inline-block; background:#1a2d5a; color:#c9a84c !important;
              padding:14px 32px; border-radius:5px; text-decoration:none;
              font-weight:bold; font-size:15px; letter-spacing:.02em; }}
    .divider {{ border:none; border-top:1px solid #e8eaf0; margin:20px 0; }}
    .detail-box {{ background:#f7f8fc; border-left:4px solid #1a2d5a;
                   border-radius:0 4px 4px 0; padding:14px 18px; margin:20px 0; }}
    .detail-box p {{ margin:4px 0; font-size:14px; color:#444; }}
    .detail-box .label {{ font-weight:bold; color:#1a2d5a; min-width:130px;
                          display:inline-block; }}
    .atty-sig {{ font-style:italic; color:#555; font-size:14px; }}
    .ftr  {{ background:#f0f2f8; padding:18px 36px; text-align:center;
             font-size:12px; color:#888; line-height:1.7; border-top:1px solid #e0e3ec; }}
    .ftr a {{ color:#1a2d5a; text-decoration:none; }}
    @media (max-width:600px) {{
      .body, .ftr {{ padding:20px 18px; }}
      .hdr {{ padding:20px 18px; }}
      .hdr-firm {{ font-size:16px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hdr">
      <p class="hdr-firm">MT LEGAL</p>
      <p class="hdr-tag">Nashville, Tennessee &bull; AI &amp; Blockchain &bull; Tokenization &bull; Estate Planning &bull; Litigation</p>
    </div>
    <div class="gold-bar"></div>
    <div class="body">
      {content_html}
    </div>
    <div class="ftr">
      &copy; {year} MT Legal &bull; Nashville, TN<br>
      <a href="{website}">{website}</a> &bull; {phone}<br>
      <em style="font-size:11px;color:#aaa;">
        This email is for general informational purposes only and does not constitute legal advice
        or create an attorney-client relationship.
      </em>
    </div>
  </div>
</body>
</html>"""


# ── Lead capture email ─────────────────────────────────────────────────────────

def send_lead_email(name: str, email: str, case_type: str, assigned_attorney: str) -> bool:
    """Fires when someone submits the quick lead / contact form."""
    if not email:
        return False

    first_name   = name.strip().split()[0] if name.strip() else "there"
    atty_display = ATTORNEY_DISPLAY.get(assigned_attorney, "our team")
    practice     = PRACTICE_BLURB.get(case_type, "your legal matter")
    cal_url      = _cal_url()
    phone        = _firm_phone()

    content_html = f"""
      <p class="greeting">Hi {escape(first_name)},</p>
      <p>
        Thank you for reaching out to MT Legal. We've received your inquiry regarding
        <strong>{practice}</strong> and will be in touch shortly.
      </p>
      <p>
        The fastest way to get started is to book a brief intro call, at no cost,
        directly on our calendar. If your matter is a fit, we will schedule a full
        consultation; its fee is credited toward your retainer if you hire us.
      </p>
      <div class="cta">
        <a href="{cal_url}">Book Your Intro Call &rarr;</a>
      </div>
      <hr class="divider">
      <p>
        Your inquiry has been assigned to <strong>{atty_display}</strong>.
        If your situation is urgent — upcoming court date, recent arrest, or
        an approaching deadline — please call us directly at
        <strong>{phone}</strong>.
      </p>
      <p class="atty-sig">
        Warm regards,<br>
        <strong>{atty_display}</strong><br>
        MT Legal
      </p>
    """

    text_body = (
        f"Hi {first_name},\n\n"
        f"Thank you for reaching out about your {practice} matter.\n\n"
        f"Book a brief intro call (no cost): {cal_url}\n\n"
        f"Assigned attorney: {atty_display}\n"
        f"Urgent matters: {phone}\n\n"
        f"Warm regards,\n{atty_display}\nMT Legal"
    )

    ok = _send(
        to_email  = email,
        to_name   = name,
        subject   = "We received your inquiry — MT Legal",
        html_body = _html_wrapper(content_html),
        text_body = text_body,
        cc_firm   = True,   # BCC the firm on every lead
    )

    # Also fire a firm-side alert
    firm_html = _html_wrapper(f"""
      <p class="greeting">&#128276; New Lead Received</p>
      <div class="detail-box">
        <p><span class="label">Name:</span> {escape(name)}</p>
        <p><span class="label">Email:</span> {escape(email)}</p>
        <p><span class="label">Case Type:</span> {escape(case_type)}</p>
        <p><span class="label">Assigned To:</span> {atty_display}</p>
      </div>
      <p>Log in to the attorney portal to view and follow up on this lead.</p>
    """)
    _send_firm_alert(
        subject   = f"[NEW LEAD] {name} — {case_type}",
        html_body = firm_html,
        text_body = f"New lead: {name} | {email} | {case_type} | Assigned: {atty_display}",
    )

    return ok


# ── Intake acknowledgement email ───────────────────────────────────────────────

def _urgent_blocks(urgent_dates: list):
    if not urgent_dates:
        return "", ""
    items = "".join(
        f"<p><span style='color:#c62828;font-weight:bold;'>&#9888;</span> "
        f"<strong>{escape(str(d['label']))}:</strong> {escape(str(d['date']))} "
        f"&mdash; <em>{int(d['days_away'])} day(s) away</em></p>"
        for d in urgent_dates)
    html = f"""
          <div style="background:#fff5f5;border:1px solid #e53935;border-radius:4px;
                      padding:14px 18px;margin:16px 0;">
            <p style="color:#c62828;font-weight:bold;margin:0 0 8px;">&#9888; Urgent Deadlines</p>
            {items}
            <p style="margin:8px 0 0;font-size:13px;color:#b71c1c;">
              Please call us right away so we can review these dates.
            </p>
          </div>"""
    lines = [f"  {d['label']}: {d['date']} ({d['days_away']} day(s) away)" for d in urgent_dates]
    text = "\nURGENT DEADLINES:\n" + "\n".join(lines) + "\nPlease call us right away.\n"
    return html, text


def send_intake_email(name: str, email: str, case_type: str, assigned_attorney: str,
                      urgent_dates: list, **_ignored) -> bool:
    """Acknowledge a submitted intake form. It contains no account details:
    the attorney reviews the intake first and, if the firm takes the matter,
    the client gets a separate invitation to the portal."""
    if not email:
        return False
    first        = name.strip().split()[0] if name.strip() else "there"
    atty_plain   = ATTORNEY_DISPLAY.get(assigned_attorney, "our team")
    atty_display = escape(atty_plain)
    practice     = escape(PRACTICE_BLURB.get(case_type, "your legal matter"))
    phone        = escape(_firm_phone())
    urgent_html, urgent_text = _urgent_blocks(urgent_dates)

    content_html = f"""
      <p class="greeting">Hi {escape(first)},</p>
      <p>
        We received your intake form. <strong>{atty_display}</strong> will review your
        <strong>{practice}</strong> matter and contact you. Sending this form does not by
        itself make us your lawyers; we will confirm in writing if we take your matter.
      </p>
      {urgent_html}
      <div class="cta">
        <a href="{escape(_cal_url())}">Schedule Your Consultation &rarr;</a>
      </div>
      <hr class="divider">
      <p>Urgent? Call us at <strong>{phone}</strong> rather than waiting for a callback.</p>
      <p class="atty-sig">&mdash; {atty_display}<br>MT Legal</p>
    """
    text_body = (
        f"Hi {first},\n\n"
        f"We received your intake form. {atty_plain} will review it and contact you. "
        "Sending this form does not by itself make us your lawyers.\n"
        + urgent_text
        + f"\nSchedule a consultation: {_cal_url()}\nUrgent? Call {_firm_phone()}.\n"
    )
    ok = _send(
        to_email  = email,
        to_name   = name,
        subject   = "We received your intake — MT Legal",
        html_body = _html_wrapper(content_html),
        text_body = text_body,
    )

    # Firm-side alert: only enough to know to open the portal. The details
    # stay in the encrypted queue rather than in a mailbox.
    urgent_firm = ("<p style='color:#c62828;font-weight:bold;'>&#9888; Urgent dates: review today</p>"
                   if urgent_dates else "")
    _send_firm_alert(
        subject   = f"[NEW INTAKE] {case_type}" + (" (URGENT)" if urgent_dates else ""),
        html_body = _html_wrapper(
            f"<p class='greeting'>&#128276; New intake waiting for review</p>{urgent_firm}"
            f"<p>Case type: {escape(case_type)}</p>"
            "<p>Open Incoming Leads in the attorney portal to review and approve it.</p>"),
        text_body = f"New intake waiting for review ({case_type}). Open Incoming Leads in the portal.",
    )
    return ok


# ── Portal invitation email ────────────────────────────────────────────────────

def send_invite_email(name: str, email: str, username: str, link: str) -> bool:
    """Invite a client to set their portal password through a single-use link."""
    if not email:
        return False
    first = name.strip().split()[0] if name.strip() else "there"
    content_html = f"""
      <p class="greeting">Hi {escape(first)},</p>
      <p>Your secure client portal at MT Legal is ready. There you can follow your case,
         message your attorney, and see your documents and statements.</p>
      <p>Use the button below to choose your password. The link works once and expires
         in 7 days.</p>
      <div class="cta"><a href="{escape(link)}">Set Up Your Portal &rarr;</a></div>
      <div class="detail-box">
        <p><span class="label">Your username:</span> {escape(username)}</p>
      </div>
      <p style="font-size:13px;color:#888;">If you weren't expecting this, call us at
         {escape(_firm_phone())} and don't use the link.</p>
    """
    text = (f"Hi {first},\n\nYour MT Legal client portal is ready. Choose your password "
            f"here (works once, expires in 7 days):\n{link}\n\nYour username: {username}\n\n"
            f"Not expecting this? Call {_firm_phone()}.\n")
    return _send(email, name, "Your MT Legal client portal", _html_wrapper(content_html), text)


def send_statement_email(name: str, email: str, statement_number: int,
                         amount: float, billed_through: str) -> str:
    """Notify a client that a billing statement was issued.
    Returns "not_configured", "sent", or "failed". No itemisation is included."""
    if not _api_key():
        return "not_configured"
    import shared
    portal = (shared.PORTAL_URL or _firm_website()).rstrip("/") + "/client-login"
    subject = f"Statement #{statement_number} from {_from_name()}"
    text = (f"Hello {name},\n\nStatement #{statement_number} for services through "
            f"{billed_through} has been issued. Amount due: ${amount:,.2f}.\n\n"
            f"View it and pay securely in your client portal: {portal}\n\n"
            f"Questions? Call {_firm_phone()}.\n")
    html_body = _html_wrapper(
        f"<p>Hello {escape(name)},</p>"
        f"<p>Statement <strong>#{statement_number}</strong> for services through "
        f"<strong>{escape(billed_through)}</strong> has been issued.</p>"
        f"<p style='font-size:1.15em'><strong>Amount due: ${amount:,.2f}</strong></p>"
        f"<p><a href='{escape(portal)}'>View and pay in your client portal</a></p>"
        f"<p>Questions? Call {escape(_firm_phone())}.</p>")
    return "sent" if _send(email, name, subject, html_body, text) else "failed"
