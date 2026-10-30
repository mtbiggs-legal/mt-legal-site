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

## Blog (weekly AI-drafted posts)

The site drafts one blog post a week, emails it to you for review, and
publishes it on its own unless you pull it. It runs inside the web process, so
Render must stay at one worker (see the comment in `render.yaml`).

Settings, all in the Render **Environment** tab:

- `BLOG_AUTOGEN`: `render.yaml` sets it to `1`. Without it nothing is drafted
  (the default is off). Setting it to `0` stops new drafts only. A draft already
  emailed still publishes when its 48 hours are up, so pull any pending draft
  from its review email.
- `TZ`: `render.yaml` sets it to `America/Chicago`, so the week and the post
  dates follow Nashville time.
- `BLOG_MODEL`: optional. Defaults to `claude-sonnet-5-5`. To change it,
  uncomment the line in `render.yaml` or add the variable in the dashboard.
- `FIRM_WEBSITE`: must be the live `https://` address. The Publish, Pull and
  Edit links in the review email are built from it. If it is not set, no review
  email goes out, and an ERROR is logged.
- `FIRM_EMAIL`: where the review email goes. If it is not set, no review email
  goes out, and an ERROR is logged. There is no fallback to `FROM_EMAIL` here.
- `ANTHROPIC_API_KEY`, `SENDGRID_API_KEY` and `FROM_EMAIL` must also be set: the
  first writes the draft and the others send it to you.

Check before relying on it:

- `FIRM_WEBSITE` and `FIRM_EMAIL` are both set in the Render **Environment** tab,
  and `FIRM_WEBSITE` opens the live site.
- SendGrid click tracking is off (SendGrid: **Settings > Tracking**). With it on,
  SendGrid rewrites the review links to pass through its own servers.

Weekly rhythm:

- The site checks hourly. On the first check of a new ISO week (usually Monday)
  it writes the week's draft and emails you a review message. The first
  automatic draft arrives the week after launch.
  Areas rotate criminal defense, crypto (stablecoins, then tokenization), civil
  rights, estate planning; formats rotate article, Q&A, tips.
- The post goes live 48 hours after the email is sent. Until then you can open
  the links in the email to publish it now, pull it, or edit it.
- If no email goes out, nothing is published; the site retries the email each
  check. Until it goes out, no new draft is written and an ERROR is logged each
  new week.
- A pulled post is not replaced that week. Its topic goes back in the queue.
- Review links expire after 7 days.

Taking down a published post:

- Within 7 days of the review email, open the Review or edit link and use **Take
  down this post**. It leaves the blog, the feed and the sitemap. Its topic stays
  used.
- With no working link (a launch post, or after 7 days), set the status on the
  Render disk. Open the service's **Shell** tab in Render and run this, with the
  post's slug (the last part of its address) in place of `your-post-slug`. This
  is the Render shell, which is Linux, not PowerShell:

  ```bash
  python -c "import json,pathlib; p=pathlib.Path('/var/data/blog/posts/your-post-slug.json'); d=json.loads(p.read_text(encoding='utf-8')); d['status']='pulled'; p.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding='utf-8'); print(d['slug'],d['status'])"
  ```

  It should print the slug and `pulled`, and the post's address then returns 404.
  Do not delete the file instead: on the next restart, seeding restores a launch
  post whose file is gone.

Topic ideas:

- Add them on the review page opened from a current review email. The link
  works for 7 days and not for a pulled post. Pick the area and type the title;
  the next draft for that area uses the oldest unused topic.
- Or add entries to `blog_seed/topics.json` (`"id"`, `"area"`, `"title"`,
  `"used": false`) and deploy. New ids are merged in at startup and existing
  topics are never overwritten. With no unused topic, Claude picks one itself.

Launch posts: before the first weekly draft, write four starter posts and
publish them with the site. Run these from the project folder, with
`ANTHROPIC_API_KEY` in `.env`. The check run makes no API call and writes
nothing:

```powershell
python scripts\generate_launch_posts.py --dry-run
```

Then the real run, which calls Claude four times:

```powershell
python scripts\generate_launch_posts.py
```

It saves four published posts in `blog_seed\posts\` and marks their topics
used in `blog_seed\topics.json`, then prints each file path. Read and edit the
four files, then commit them with `blog_seed\topics.json` and deploy. Server
copies are created only the first time, so later edits to a seed file do not
overwrite the live version. Commit and deploy the four posts and the updated
`blog_seed\topics.json` together on the first deploy: the server only adds topic ids it
does not have yet, so it will not pick up "used" flags changed later. The
script refuses to run if `blog_seed\posts\` already holds post files.

`scripts\sync_site.ps1` (see above) copies the blog files to `mt-legal-site\`
along with everything else tracked in git. `blog_seed\` must make it across: without
it the site has no starter topics or launch posts, and the writer picks its own topics.

## Later: turning on the portals

Remove `PUBLIC_SITE_ONLY`, set `ATTORNEY_ENDOCIDE_HASH` (and any other attorney
hashes), and configure Stripe/Coinbase webhooks and Google Calendar. Do a
security review before enabling client logins on the public internet.
