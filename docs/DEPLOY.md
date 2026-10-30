# Publishing the MT Legal website (Render)

Launch mode is **public site + intake only**: the marketing pages, case search,
intake form, and chat assistant are live; client and attorney portals, logins,
billing, and the attorney research/drafting tools return 404 until
`PUBLIC_SITE_ONLY` is removed. Cost is about $7/month for the web service plus
about $0.25/month for a 1 GB disk.

## 0. Before anything goes to GitHub

Old commits in this repository contain `.env` with real secrets. Do one of these
before pushing:

- **Fresh history (simplest):** push a single clean snapshot of the current code
  to a new repository, leaving the old history local only.
- **Purge history:** rewrite history with `git filter-repo --path .env --invert-paths`
  (back up `.env` and the repo first).

Either way, **rotate the Anthropic API key and SECRET_KEY**, since the old values
are in local history. Production uses its own generated SECRET_KEY.

## 1. Fill in real firm details

These go into Render's environment settings (step 4), not into code:

| Variable | What to enter |
|---|---|
| `FIRM_PHONE` | Firm phone number |
| `FIRM_EMAIL` | Inbox that receives intake and lead alerts |
| `FROM_EMAIL` | Address emails are sent from (verify it in SendGrid) |
| `FIRM_WEBSITE` | `https://yourdomain.com` |
| `CAL_BOOKING_URL` | Your real booking link (Calendly, Cal.com, etc.) |

## 2. Create a private GitHub repository

Create a **private** repository (for example `mt-legal-site`) and push the code
to it.

### Updating it later

The deploy repo is checked out at `mt-legal-site/` inside this folder. To bring
it up to date with `master`, preview the changes, then apply them:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_site.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sync_site.ps1 -Apply
```

The script copies only committed files, so `.env`, credentials and client data
never reach the deploy repo. It doesn't commit or push: review with
`git status` in `mt-legal-site`, then commit and push there. `-Ref <branch>`
syncs a different branch.

## 3. Create the Render service

1. Sign up at render.com and connect your GitHub account.
2. Choose **New > Blueprint**, select the repository. Render reads `render.yaml`
   and creates the web service with its disk at `/var/data`.

## 4. Enter the secrets in Render

In the service's **Environment** tab, fill in each variable marked "sync: false"
in `render.yaml`:

- `DATA_ENCRYPTION_KEY`: generate a **new** key with
  `python scripts/generate_data_key.py`. Store it in your password manager
  and an offline backup. If it is lost, encrypted client records on the server
  cannot be recovered.
- `ANTHROPIC_API_KEY`: a new key (see step 0).
- `SENDGRID_API_KEY`: for intake confirmation emails.
- The firm details from step 1.

The app refuses to start in production if `SECRET_KEY` or
`DATA_ENCRYPTION_KEY` is missing, so a failed deploy usually means a missing
variable.

## 5. Connect the domain (Squarespace Domains)

1. In Render: service **Settings > Custom Domains**, add `yourdomain.com` and
   `www.yourdomain.com`. Render shows the exact DNS values to use.
2. In Squarespace: **Domains > your domain > DNS > Custom records**, add:
   - `CNAME` record, host `www`, pointing to `mt-legal.onrender.com`
     (use the hostname Render shows).
   - `A` record, host `@`, pointing to the IP address Render shows for root
     domains.
   Remove any conflicting default Squarespace records for `@` and `www`.
3. Wait for DNS to propagate (minutes to a few hours). Render issues the HTTPS
   certificate automatically once DNS resolves.

## 6. Check the live site

- `https://yourdomain.com/healthz` returns `{"ok": true}`.
- Pages load over HTTPS; `/client-login` returns 404 (portals off).
- Submit a test intake and confirm the emails arrive without portal logins.

## Later: turning on the portals

Remove `PUBLIC_SITE_ONLY`, set `ATTORNEY_ENDOCIDE_HASH` (and any other attorney
hashes), and configure Stripe/Coinbase webhooks and Google Calendar. Do a
security review before enabling client logins on the public internet.
