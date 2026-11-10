# Email reviewer: connecting the firm Gmail

The attorney portal's **Inbox** tab reviews new firm mail. For each email it:

- sorts it into New Client, Existing Client, Court & Counsel, Billing, Vendor,
  Spam & Marketing, or Other;
- flags urgent mail and explains why;
- pulls out any hearing, filing, response or payment dates;
- writes a one- or two-sentence summary.

It also adds matching Gmail labels (`MT Review/...` and `MT Review/Urgent`) and sends
a morning digest from the firm mailbox to itself.

**What it never does:** reply, draft, delete, trash, archive, mark mail read, move mail
to spam, or send mail to anyone but the firm mailbox itself. It holds only the
`gmail.modify` permission, and Google never allows permanent deletion with that
permission. The code has no delete, trash or draft call, and a test keeps it that way.

**Where mail content goes:** the Anthropic API, for the review, and nowhere else. The
digest travels through Gmail itself, not SendGrid. Results are stored encrypted with
`DATA_ENCRYPTION_KEY` in the `email-review\` folder. Only the summary, sender, subject
and dates are kept, never the full email. Results are deleted after 60 days.
`email-review\` and `gmail-token.json` are gitignored.

**Where it runs:** only in the local app (`python app.py`). The portal is switched
off on the public site, so the hourly check and the digest happen only while the local
app is running.

You do every sign-in step yourself. Claude never handles the Google password or the
OAuth consent.

## 1. Turn on the Gmail API in Google Cloud

Use the same Google Cloud project that issued the app's `credentials.json` (the
Calendar setup in `GOOGLE_CALENDAR_SETUP.md`).

1. Go to <https://console.cloud.google.com/>, pick that project, then
   **APIs & Services → Library**. Search for **Gmail API** and click **Enable**.
2. Open **APIs & Services → OAuth consent screen** (in newer consoles: **Google Auth
   Platform → Data access**). Under **Scopes**, click **Add or remove scopes** and add
   `https://www.googleapis.com/auth/gmail.modify`. Save.
3. Choose who can sign in:
   - **Google Workspace (firm domain):** set **User type** to **Internal**. Tokens
     then don't expire, and there is no "unverified app" warning.
   - **Personal @gmail.com account:** leave it **External**. Under **Test users** (in
     newer consoles, **Audience**), add the firm Gmail address. In **Testing** status,
     Google expires the sign-in after **7 days**, so you would click **Connect Gmail**
     again each week. To avoid that, click **Publish app**. You will still see an
     "unverified app" warning when you sign in, which is fine for your own account.
4. If the project has no OAuth client yet, go to **Credentials → Create credentials →
   OAuth client ID** and choose **Desktop app**. Download the JSON and save it as
   `credentials.json` in the project folder. If `credentials.json` is already there
   for Calendar, reuse it.

Check that the file is in place:

```powershell
Test-Path "C:\Users\Endoc\MT LEGAL\credentials.json"
```

## 2. Install requirements (already done if Calendar works)

```powershell
Set-Location "C:\Users\Endoc\MT LEGAL"; python -m pip install -r requirements.txt
```

## 3. Optional settings in `.env`

Every setting has a default, so you can skip this step.

| Setting | Default | Meaning |
|---|---|---|
| `EMAIL_REVIEW_AUTO` | `1` | Check the Inbox hourly while the app runs. `0` = only when you click **Check now**. |
| `EMAIL_DIGEST_HOUR` | `7` | Send the digest on the first check at or after this hour (24-hour clock). `-1` turns the digest off. |
| `EMAIL_REVIEW_MODEL` | `claude-haiku-5-5` | The Claude model used for the review. |

To open `.env` for editing:

```powershell
notepad "C:\Users\Endoc\MT LEGAL\.env"
```

## 4. Connect the mailbox

Start the app:

```powershell
Set-Location "C:\Users\Endoc\MT LEGAL"; python app.py
```

1. Open <http://127.0.0.1:5000/attorney-login> and sign in.
2. Click **Inbox** in the sidebar, then **Connect Gmail**.
3. A Google sign-in window opens. Sign in to the **firm** mailbox, not a personal one,
   and approve the access request ("Read, compose, and send emails…"; Google uses one
   description for the whole `gmail.modify` permission).
4. When the tab says "Gmail connected", close it and click **Check now**.

The first check looks back 3 days and reviews up to 25 emails. If more are waiting,
the portal says so; click **Check now** again. After that, the app checks hourly.

The token is saved to `gmail-token.json` in the project folder, or under `DATA_DIR` if
that is set. Treat it like a password: never copy it anywhere or commit it.

## 5. Using it

- **Inbox tab:** unhandled urgent mail is listed first. Filter by category, or show
  urgent mail only. **Open in Gmail** opens the message. **Handled** hides it in the
  portal only and changes nothing in Gmail. The red count on the sidebar button is
  urgent mail not yet marked handled.
- **Gmail:** use the `MT Review/...` labels in Gmail's left-hand list. The reviewer
  only adds labels, so the Inbox itself is unchanged.
- **Digest:** arrives from and to the firm address each morning, listing urgent items
  first and then new mail by category. Nothing is sent on a day with nothing new or
  urgent. **Send digest now** in the Inbox tab sends one immediately.
- **Client matching:** a sender is tagged **Client, domain authenticated** only when
  the address is on a client record *and* Gmail's DMARC check passed for exactly that
  From domain. That proves the email came from the domain, not from the person:
  anyone with an account on the same domain (for example any @gmail.com user) passes
  too. When the address matches but the domain wasn't authenticated, the email is
  tagged **Client address, not authenticated** because it may be forged.
- **Payment requests:** any request to change payment, bank or wire details is flagged
  urgent as possible fraud, whoever it appears to be from. Confirm by phone before
  acting on it.
- **Cost:** token use is logged under Insights as "Email Review".

## 6. Try it without a mailbox

This runs the reviewer on the fictional sample emails in
`tests\fixtures\sample_emails.json`, with a fake Gmail and a throwaway temp folder.
No mailbox or real data is touched.

Offline, with a keyword stand-in for Claude:

```powershell
Set-Location "C:\Users\Endoc\MT LEGAL"; python scripts\email_review_demo.py
```

With the real Claude API. This sends only the fictional samples and costs a few cents:

```powershell
Set-Location "C:\Users\Endoc\MT LEGAL"; python scripts\email_review_demo.py --live
```

Run the tests:

```powershell
Set-Location "C:\Users\Endoc\MT LEGAL"; python -m pytest tests\test_email_review.py -q
```

## 7. Disconnecting

1. Stop the app, then delete the token:

   ```powershell
   Remove-Item "C:\Users\Endoc\MT LEGAL\gmail-token.json"
   ```

2. Revoke the app's access at <https://myaccount.google.com/permissions>, signed in as
   the firm account.
3. The `MT Review/...` labels stay in Gmail. Delete them in Gmail settings if you no
   longer want them. Deleting a label never deletes mail.
4. To delete the stored summaries as well:

   ```powershell
   Remove-Item -Recurse "C:\Users\Endoc\MT LEGAL\email-review"
   ```

## Troubleshooting

| You see | Fix |
|---|---|
| "credentials.json is missing" | Step 1.4. |
| "Gmail sign-in has expired" | Click **Connect Gmail** again. On a personal Gmail account in Testing status this happens weekly (see step 1.3). |
| Google says "Access blocked" or "app not verified" with no way to continue | Add the firm address as a test user (step 1.3), or set User type to Internal on Workspace. |
| "ANTHROPIC_API_KEY is not set" | Add the key to `.env`. Emails that fail are retried on the next 2 checks, then listed as "Could not be reviewed automatically". |
| The Inbox tab says "Client record could not be decrypted" | `DATA_ENCRYPTION_KEY` changed since the summaries were saved. Restore the old key, or delete `email-review\` and click **Check now**. |
| No digest arrived | The app must be running at or after `EMAIL_DIGEST_HOUR`. Nothing is sent on a day with nothing new or urgent. |
