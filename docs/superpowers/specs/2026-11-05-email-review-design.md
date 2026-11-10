# Email reviewer: design

Approved by the attorney in chat on 2026-11-05.

## Intent

The firm inbox (Gmail / Google Workspace) gets court notices, new-client inquiries,
client mail, billing, vendor mail and spam in one stream. The reviewer reads new
Inbox mail, sorts it, flags anything urgent or deadline-bearing, and writes a short
summary, so the attorney can scan the day's mail in a minute and not miss a deadline.

## Goals

- Sort each new Inbox email into: new-client inquiry, existing client,
  court / opposing counsel, billing, vendor, spam / marketing, other.
- Flag urgent mail with a reason, and pull out any dates or deadlines it mentions.
- Write a 1–2 sentence summary.
- Apply matching Gmail labels (`MT Review/<Category>`, `MT Review/Urgent`).
- Show results in a new **Inbox** tab in the attorney portal.
- Send a morning digest from the firm Gmail account to itself.

## Non-goals and anti-goals

- No drafted replies (the attorney didn't ask for them).
- Never send mail to anyone but the signed-in account itself. Never delete, trash,
  archive, mark read, move to spam or remove labels.
- Mail content goes only to the Anthropic API. The digest goes through Gmail itself,
  not SendGrid.
- Claude never signs in or handles OAuth credentials. The attorney does that.

## Decisions

Decided by the attorney: Gmail API; categories + urgent/deadline flags + summaries;
portal tab plus daily digest; digest sent Gmail-to-self.

Builder's calls (marked "my call" in the chat playback, accepted):
- Own token file `gmail-token.json` (separate from Calendar), scope `gmail.modify`
  only. That scope can read, label and send, but Google won't allow permanent
  deletion with it.
- Runs in the local app only (the portal is off on Render). Hourly check plus a
  "Check now" button. The first run looks back 3 days. At most 25 messages per run.
- Morning digest after 7 AM local (`EMAIL_DIGEST_HOUR`), once a day, skipped when
  there is nothing new or urgent.
- Results are stored Fernet-encrypted with `DATA_ENCRYPTION_KEY` in
  `DATA_DIR/email-review/` (gitignored). Only summaries and metadata are kept, never
  full bodies. Results are pruned after 60 days.
- Email text is untrusted data: Claude has no tools and returns a fixed JSON schema.
  Label names come from a fixed list in code.
- A sender whose address matches a client record is matched locally, and Claude
  gets only the hint "sender matches an existing client".
- "Handled" is a portal-only flag; it changes nothing in Gmail.

## Parts

- `services/gmail.py`: OAuth token, list/read messages, labels (add only), send to self.
- `services/email_review.py`: Claude classification, the encrypted store, a review run, the digest.
- `services/email_review_scheduler.py`: the hourly thread (same pattern as `blog_scheduler`).
- `blueprints/email_review.py`: `/email-review/*` routes, `@require_attorney`, private on Render.
- `templates/attorney/_panel_email_review.html` + `static/js/attorney_email_review.js`.
- `docs/EMAIL_REVIEW_SETUP.md`: connecting the real mailbox.
