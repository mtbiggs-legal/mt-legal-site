# E-signatures (Dropbox Sign) and filing packages

## What it does

- **Send for signature:** on a client's Documents tab, any PDF or Word document has a
  **✍ Sign** button. The signer defaults to the client (name and email on file); add
  more signers if needed. The assistant can also do it ("send the engagement letter to
  Travis for signature"), and it waits for your Confirm.
- **Track:** the **Signatures** card on the Documents tab shows who has signed, with
  **Remind**. When everyone has signed, the completed PDF is saved to the client's
  **Signed Documents** folder automatically.
- **Your own signature is never applied for you.** If you need to sign, add yourself
  as a signer.
- **Filing packages:** **⚖ Prepare filing** on a PDF or text document builds one PDF:
  the document plus a certificate of service and signature block. Court, county, case
  number, your client's side and the parties to serve are filled in from the client
  file; you're only asked for what's missing, and your answers are saved to the file
  for next time. The `/s/` signature goes on only if you tick the approval box.
  You file it through the court's own system, then use **Mark filed** to store the
  file-stamped copy and add the hearing date (it goes on Google Calendar if connected,
  and becomes the next court date if it's the earliest one).

## Setting up Dropbox Sign

1. Create an account at sign.dropbox.com and add API access (Account → API).
   Test mode is free; live requests need a paid API plan.
2. Copy the API key and add it to `.env` in the project folder:

   ```
   DROPBOX_SIGN_API_KEY=your-key-here
   ```

   Requests stay in **test mode** (free, not legally binding) until you add
   `DROPBOX_SIGN_TEST_MODE=0`. The Signatures card shows "Test mode" or "Live".
3. Check the key works. This sends a one-page test-mode request to the email you give:

   ```powershell
   python scripts\check_dropbox_sign.py you@example.com
   ```

4. Restart the app.

## On the live site (Render)

- Add `DROPBOX_SIGN_API_KEY` (and later `DROPBOX_SIGN_TEST_MODE=0`) in the Render
  Environment tab.
- In Dropbox Sign, set the account callback URL (API settings) to
  `https://midtennlegal.com/webhooks/dropbox-sign`. Dropbox Sign then reports
  signatures immediately; without it, status updates when the Signatures card is
  opened or **Check status** is clicked.
- The callback is verified with the API key, and like the rest of the portal it is
  off while `PUBLIC_SITE_ONLY` is set.

## Signature block on filing packages

Set these in `.env` (and in Render) so the signature block is complete:

```
ATTORNEY_BPR=000000
FIRM_ADDRESS=123 Example St, Suite 100; Nashville, TN 37201
```

`FIRM_ADDRESS` lines are separated with `;`. `FIRM_PHONE` and `FIRM_EMAIL` are already
used elsewhere and appear in the block too. Without `ATTORNEY_BPR` the BPR number is
left blank to fill in.
