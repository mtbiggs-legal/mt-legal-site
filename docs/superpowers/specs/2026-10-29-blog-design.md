# Blog: weekly AI-drafted posts with email review: design

Date: 2026-10-29

## Intent

MT Legal needs a steady flow of helpful, current content on the public site:
articles, Q&As and tips that explain where a reader stands and make it easy
to reach the firm. The readers are people in a hard moment: someone who has
just been charged with a crime, someone with a cryptocurrency or DeFi legal
problem, someone facing a civil rights issue, someone planning an estate.

The attorney doesn't have time to write weekly, so AI writes the drafts. But
under Tennessee RPC 7.1 everything on the site is the attorney's advertising,
and the attorney answers for it. So every post waits in a review window
before it goes live, and the attorney can publish, edit or pull it.

Content has to be readable by people and by machines: search engines, feed
readers and AI assistants.

## Goals

- A public **Blog** at `/blog` with a post index (newest first, filterable by
  practice area) and one page per post at `/blog/<slug>`.
- One new draft every week, written by Claude, rotating across four practice
  areas and three formats.
- An email to the attorney with each draft: **Publish now**, **Pull it**, and
  **Edit**. If the attorney does nothing, the draft publishes on its own when
  the 48-hour window closes.
- Machine-readable output: an RSS feed, posts added to `sitemap.xml`, and
  JSON-LD on every post page.
- 3–4 launch posts drafted ahead of time and reviewed before launch, so the
  page isn't empty on day one.

## Non-goals

- Posting to X or other social networks (maybe later).
- Comments, likes, newsletter sign-up, author pages.
- Reopening the attorney portal on the production site. Review happens by
  email.
- A full CMS. The only editing is the one-draft edit page described below.

## Anti-goals (a failure even if it works)

- A post that misstates Tennessee or federal law, quotes a statute or case the
  model isn't sure of, promises results ("we'll get your charges dropped"),
  or reads as legal advice to a specific person.
- Any mention of public-defender work (allowed only in the attorney bio).
- Wording that suggests more than one attorney. The site presents a solo
  practice.
- A review or edit link that opens anything other than its single draft, or
  that keeps working after the draft is decided.
- A post going live that the attorney pulled, or two posts in one week.

## Constraints (from the codebase)

- Flask, file-based, no database. Production runs on Render: gunicorn with
  **1 worker and 4 threads**, `PUBLIC_SITE_ONLY=1`, data on the persistent
  disk at `DATA_DIR` (`shared.DATA_ROOT`).
- `PUBLIC_SITE_ONLY` 404s `/portal`, `/attorney-portal`, `/drafting` and the
  other private prefixes (`app.py` `_PRIVATE_PREFIXES`). The blog's review
  routes must **not** use those prefixes, and must stay reachable in
  public-only mode.
- Render has `ANTHROPIC_API_KEY` and SendGrid (`SENDGRID_API_KEY`,
  `FROM_EMAIL`, `FIRM_EMAIL`) already. Use `shared.get_anthropic_client()` and
  `email_service._send()`. Review emails go to `FIRM_EMAIL`.
- A Render cron job can't see the web service's disk, so scheduling happens
  inside the web app (see *Scheduling*).
- `shared.MODEL` defaults to Haiku for chat. Blog writing uses its own setting,
  `BLOG_MODEL`, defaulting to `claude-sonnet-5-5`.
- Project conventions apply: blueprints import from `shared`, JSON routes
  return `{"success": True}` / `{"error": ...}`, new CSS classes go at the
  bottom of `static/css/style.css` with the theme variables, and user content
  in JS is escaped. Tests use the `conftest.py` fixtures and never touch real
  data or call the real API or SendGrid.

## Decided with the attorney

- **Cadence:** weekly.
- **Review:** a 48-hour window, then auto-publish. The attorney reviews by
  email: Publish now / Pull it / Edit (a private page reached through a signed,
  single-draft link).
- **Practice areas:** criminal defense, crypto/DeFi (stablecoins, RWA
  tokenization), civil rights, estate planning. Family law and personal
  injury stay out of the blog rotation on purpose.
- **X:** not now.

## How it works

### Data

New data directory `DATA_ROOT / "blog"`, holding one JSON file per post
(`<slug>.json`) and `topics.json` (the topic queue). It is public content, not
privileged, but it lives on the persistent disk like everything else, so add
it to `.gitignore` alongside the other data folders. The launch posts and the
starter topic list ship as seed files in the repo (for example
`blog_seed/`) and are copied in on first run if the directory is empty.

A post record has: `slug`, `title`, `summary` (for the index card, feed and
meta description), `body` (Markdown or a restricted HTML subset; the builder
picks, and it gets sanitized on render), `area` (a practice-area slug from
`practice_areas.PRACTICE_AREAS`), `format` (`article` / `qa` / `tips`),
`status` (`draft` / `published` / `pulled`), `created_at`, `publish_at`,
`published_at`, `review_token_id`, and, for Q&A posts, a list of
question/answer pairs so the page can emit `FAQPage` structured data.

### Scheduling

There is no external cron. A lightweight check runs at most once an hour (a
daemon thread started in the app factory, or a time-gated check in
`before_request`; the builder picks). On each tick it does two things:

1. **Publish due drafts:** any `draft` whose `publish_at` has passed becomes
   `published`.
2. **Write this week's draft:** if no post (any status) was created in the
   current ISO week, and today is Monday or later, it generates one, emails
   it, and sets `publish_at` = created + 48h. So the normal rhythm is: draft
   Monday, live Wednesday.

Both steps must be idempotent and guarded by a file lock or an atomic
create, so a restart, the 4 threads, or a dev-server reloader can't produce
two drafts in one week. A missed week (the site was down) just produces
the draft late; it never backfills.

A `BLOG_AUTOGEN` env flag (default off locally, on in `render.yaml`) turns
generation on or off so dev and tests never call the API by accident.

### Topic rotation

The area rotates in a fixed order (criminal defense → crypto/DeFi → civil
rights → estate planning), and the format rotates article → Q&A → tips, so
each area comes up about once a month. The next topic is the first unused
entry for that area in `topics.json`. When an area's list runs out, the
model proposes a topic, given the titles of past posts so it doesn't repeat
itself. The attorney can add ideas to the list.

### Generation prompt (guardrails)

The system prompt has to enforce the anti-goals: Tennessee and federal law in
general terms; no promises of results; no statute or case citation unless
it's well established, and if in doubt, describe the rule without the number;
no public-defender mentions; first-person-plural is fine but it must not
imply more than one attorney (say "MT Legal" or "our office"); a
client-centered, plain-English voice for a worried reader; 600–1,000 words.
The model returns structured JSON (title, summary, body, Q&A pairs), which
gets validated before saving. A failed or malformed generation is logged and
retried on the next tick, up to a few attempts that week. Every post page
renders a fixed disclaimer and an intake CTA from the template, not from the
model.

### Review email and links

Sent to `FIRM_EMAIL` when a draft is created. It holds the full draft text,
the scheduled publish time, and three buttons:

- **Publish now:** publishes immediately.
- **Pull it:** sets `pulled`. Nothing replaces it that week.
- **Edit:** opens `/blog/review/<token>`, a plain page with title, summary
  and body fields plus Save / Save & publish / Pull. Saving keeps the original
  `publish_at`.

Tokens are signed (itsdangerous with `SECRET_KEY`, which Flask already
depends on), bound to one post slug and its `review_token_id`, and expire
after 7 days. A link stops working once the draft is published or pulled,
except the Edit link: it may still fix a typo in a published post until the
token expires (the builder's call whether that's worth it). The review routes
are `noindex`, left out of the sitemap, and rate-limited if the existing
security module makes that easy. Publish/Pull buttons in the email go to a
GET confirmation page that does the change on a POST, so mail scanners that
prefetch links can't publish or pull anything.

### Public pages

- `/blog`: index of published posts, newest first, with area filter chips
  (`?area=`). It reuses the editorial styles of the existing pages. Add a
  **Blog** link to the main nav in `base.html`.
- `/blog/<slug>`: the post, area and format label, date, a link to the
  matching practice page, the disclaimer, and the intake CTA. Drafts and
  pulled posts 404 on the public route.
- Each practice-area page shows its latest 2–3 posts (nice to have; the
  builder may defer this).

### Machine-readable

- `/blog/feed.xml`: RSS 2.0 of published posts, linked with
  `<link rel="alternate" type="application/rss+xml">` in `base.html`.
- `sitemap.xml`: add `/blog` and every published post, with `lastmod`.
- JSON-LD on each post: `BlogPosting` (headline, datePublished, dateModified,
  author = the managing partner, publisher = the firm's `LegalService`), plus
  `FAQPage` for Q&A posts.
- Canonical URL and Open Graph meta per post.

### Launch posts

Before launch, generate 3–4 posts (one per area) with the same prompt, using a
small script in `scripts/` that writes them as drafts. The attorney reviews and
edits them through the normal email/edit flow (or by hand-editing the seed
files), and they ship published. The weekly cycle starts the Monday after
launch.

## Calls made after the builder check

These were not discussed with the attorney. They are the designer's calls.

- **No email, no auto-publish.** A draft records `review_email_sent_at`. If
  the email fails (`_send()` returns False, or SendGrid/`FIRM_EMAIL` is
  missing), every tick retries the email. The 48-hour window starts only once
  an email is sent, so a post the attorney never saw can't go live. Failures
  are logged loudly.
- **Launch posts are reviewed in the repo.** `scripts/generate_launch_posts.py`
  runs locally and writes posts straight into `blog_seed/posts/`, marked
  `published`. The attorney reads and edits those files (or the rendered pages
  on the local dev server) before they're committed. Nothing is emailed, and
  there's no export step.
- **Topic ideas come from two places.** On every startup, new entries in
  `blog_seed/topics.json` are merged into the disk copy by `id`. Entries
  already on disk keep their used/unused state. The edit page also has an
  "Add a topic idea" field, so the attorney can add one from a review email
  without a deploy.
- **Crypto slug.** The crypto/DeFi step alternates between `stablecoins` and
  `rwa-tokenization`. Estate planning is `estate-business`. Filter chips show
  only areas that have at least one published post.
- **A pulled or failed week still advances the rotation.** The area and format
  move on the next week. A pulled post's topic goes back into the queue as
  unused.

## Left to the builder

- Thread vs. request-time scheduling tick; Markdown vs. sanitized HTML for
  bodies and which sanitizer.
- The exact starter topic list: 8–10 per area, grounded in the existing
  practice-area pages.
- Email and page layout within the existing visual style.
- Whether Edit links keep working on published posts.
- Test coverage. At minimum: token signing, expiry and single-use; the
  scheduler's idempotence (no double drafts, no publishing pulled posts);
  public routes hiding drafts; the feed, sitemap and JSON-LD output; and the
  review routes staying reachable with `PUBLIC_SITE_ONLY=1`.

## Deploy notes

Add `BLOG_AUTOGEN=1` (and optionally `BLOG_MODEL`) to `render.yaml`, then
sync to `mt-legal-site/` by hand per the usual process. Update
`docs/DEPLOY.md` with the blog env vars and how to add topic ideas.
