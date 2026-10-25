# Editorial Redesign — Design Spec

**Date:** 2026-08-31
**Status:** Approved
**Approach:** Editorial direction, Ink & Bone palette, applied to public and client-facing pages

---

## Overview

Replace the current navy/gold, centre-aligned, courthouse-columns design with an editorial
layout: asymmetric hero, display serif headlines over a clean sans body, generous white space,
hairline rules instead of boxes and drop shadows.

The current design is the default law-firm template — centred text over stock columns, Georgia
body copy, pill buttons. It is competent but indistinguishable from thousands of other firm
sites. The goal is a site that reads like a boutique firm that charges well, without losing the
credibility a legal practice needs.

This is a presentation change. No routes, forms, or request/response shapes change.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Visual direction | Editorial | User selected from three mockups (Editorial / Dark Luxe / Warm Boutique) |
| Palette | Ink & Bone — near-black on warm off-white, antique brass accent | User selected from three palettes; biggest departure, most editorial |
| Scope | Public site + client-facing tools | Attorney portal inherits tokens only, layout untouched |
| Headline type | Fraunces (display serif) | Georgia body copy is the main thing dating the current site |
| Body type | Inter | Serif headline + clean sans body is the current "premium" pairing |
| Photography | Prominent, replaced with restrained stock from Pexels | Current images are recognisable stock (Scrabble tiles, fashion shoot) |
| Stats strip | Dropped | Placeholder figures could not be substantiated; bar-advertising exposure |
| Testimonials | Auto-rotating carousel → static quotes | Carousels are dated and convert poorly. The carousel lives on Meet the Firm (`meet_the_firm.html:420`), not the homepage |
| Font delivery | Self-hosted | App runs on LAN and sometimes offline; a CDN failure must not break typography |

---

## Design System

All values live in `:root` in a new `static/css/tokens.css`, loaded before `style.css`.
Every page already consumes these variable names, so the change propagates automatically —
including to the attorney portal. Tokens are split into their own file because they are
referenced from both the stylesheet and inline template styles, and a short file is far
easier to audit for contrast than 1,641 lines.

### Colour tokens

| Token | Value | Use |
|-------|-------|-----|
| `--bg` | `#F7F5F0` | Page background (warm off-white) |
| `--paper` | `#FFFDF9` | Cards and raised surfaces |
| `--ink` | `#14181F` | Headlines, primary buttons, high-emphasis text |
| `--ink-2` | `#39414F` | Secondary text |
| `--muted` | `#5A6472` | Body copy |
| `--faint` | `#686F79` | Labels, captions, metadata |
| `--accent` | `#7D6E4C` | Antique brass — eyebrows, italic emphasis, rules |
| `--accent-lt` | `#B9AE93` | Underlines and hairline accents (non-text only) |
| `--rule` | `#E2DED4` | All borders and dividers |

The mockup used `--faint` `#8A93A0` and `--accent` `#8A7A55`. Measured against `--bg`, those
are 2.85:1 and 3.86:1 — the first fails AA outright, the second fails for normal-size text.
Both are darkened here to the nearest value on the same hue that clears 4.5:1. The change is
visually negligible and the design intent is unchanged.

Existing semantic tokens (`--red`, `--green` and their light variants) are retained for
alerts, urgent-deadline banners, and billing states. They are re-tuned to sit against the
warm background rather than the current cool grey.

**Backwards compatibility:** the old token names (`--navy`, `--gold`, `--gray-1`…`--gray-4`,
`--text`, `--white`) are kept as aliases pointing at the new values. 99 lines in `style.css` (190 references)
use them, plus inline styles across the templates — aliasing avoids a 190-site find-and-
replace and keeps the attorney portal rendering correctly without touching it.

### Type scale

- **Display serif:** Fraunces — headlines only (`h1`, `h2`, section titles, pull-quotes, stat figures)
- **Sans:** Inter — body, navigation, buttons, forms, tables, all portal UI
- Headline sizes: 52 / 33 / 21 px with `line-height` 1.02–1.2 and `letter-spacing` −0.015 to −0.02em
- Body: 14.5px / 1.7; small print 12–12.5px
- Eyebrows: 10px, `letter-spacing` 0.24em, uppercase, brass

### Component rules

- **Border radius:** 2px on buttons and inputs (was pill/12px). Cards keep a small radius; the hero photo panel is square.
- **Elevation:** removed. Separation comes from 1px `--rule` borders and white space, not shadows.
- **Alignment:** left-aligned throughout. The closing CTA band is the only centred element.
- **Grid gaps:** the practice grid uses 1px gaps over a `--rule` background so cells read as one table.

---

## Page Structure

### Homepage (`templates/index.html`)

Replaces the current stacked double header — a navy "JUSTICE. INTEGRITY. RESULTS." bar *plus*
a full-height hero — which consumes an entire screen before any content.

The existing page carries more than the mockup showed. Every current section is preserved and
restyled — nothing is dropped. Current order is hero → practice cards → case search → feature
cards → consult CTA.

1. **Hero** — asymmetric split, ~55/45. Left: eyebrow ("Nashville, Tennessee"), h1 with one
   italic brass word, lede, primary + text-link CTAs. Right: full-bleed photograph.
   Replaces the full-viewport photo hero at `index.html:229`.
2. **Practice areas** — 3×2 grid, six featured areas, each numbered 01–06 with title,
   one-sentence description, and the responsible attorney. Section header carries an
   "All practice areas →" link. Replaces the full-bleed video-strip cards at
   `index.html:243–289`. The intake dropdown has thirteen case types; featuring six and
   listing the rest on a later practice page keeps the page focused.
3. **Case search** — kept and restyled, not removed. This is working functionality
   (`index.html:294–433` posting to `/api/case-search`, plus the warning modal at
   `435–582`) and it is a genuine differentiator most firm sites lack, so it keeps a
   full section rather than being demoted. Restyle only: hairline-bordered card, left-aligned
   heading, the county/case-type selects and recent-search chips inheriting the new form
   styling. The form id, field ids, submit handler, and modal behaviour are untouched.
4. **Pull-quote** — split panel, photograph left, single italic testimonial right with
   attribution. New section on the homepage.
5. **Free tools** — the Research Bot and Document Generator cards (`index.html:584–611`),
   restyled as a two-up editorial split rather than the current feature-card row.
6. **The attorneys** — two cards, portrait left, name / practice / one-line bio right, linking
   through to Meet the Firm.
7. **CTA band** — full-width ink background, headline plus a single intake button. Replaces
   the free-consult section at `index.html:612–619`.
8. **Footer** — four columns (firm, practice, clients, contact) with a legal sub-bar carrying
   the attorney-advertising disclaimer.

`index.html` also carries a 214-line `{% block styles %}` (lines 4–218) of page-specific CSS.
Rules that become part of the design system move into `style.css`; the rest are rewritten
against the new tokens.

### Other in-scope pages

| File | Lines | Change |
|------|-------|--------|
| `templates/base.html` | 543 | Nav, footer, chat widget, and both modals restyled |
| `templates/index.html` | 621 | Full restructure per above |
| `templates/meet_the_firm.html` | 495 | Editorial attorney profiles, larger portraits; the rotating testimonial carousel at line 420 becomes a static three-up quote grid |
| `templates/intake.html` | 624 | Form restyle: hairline fields, sectioned layout |
| `templates/research.html` | 115 | Memo output restyled for reading |
| `templates/drafting.html` | 868 | Template picker and preview restyle |
| `templates/client_login.html` | 170 | Split layout — form left, photograph right |
| `templates/attorney_login.html` | 31 | Matches client login |
| `templates/change_password.html` | 47 | Matches login styling |
| `templates/client_portal.html` | 901 | Tabs, cards, tables, billing restyled |
| `static/css/style.css` | 1641 | Tokens, type, and component rules |

### Out of scope

`templates/attorney_portal.html` (3,720 lines) and `templates/tax_summary.html` keep their
current layout. They inherit the new tokens and fonts through `style.css` and must be
visually verified for breakage — specifically contrast on the dashboard cards, the client
table, and the insights charts, which assume a cool grey background.

---

## Photography

Current images are recognisable stock that undercuts the direction: `hero-firm.jpg` is
Scrabble tiles spelling "LAWYER"; the attorney headshots are full-body fashion shots.

**Sourcing:** Pexels API, using the `PEXELS_API_KEY` already in `.env`. Every candidate is
presented to the user — filename, source URL, dimensions, file size — before it is saved.
Nothing is downloaded without that confirmation.

**Selection criteria:** Nashville and Tennessee architecture, courthouse and civic detail,
desk and document close-ups, office interiors. Muted, low-saturation, no gavels, no scales
of justice, no Scrabble tiles, no smiling-handshake stock.

**Treatment:** consistent across the site — desaturated toward monochrome with a slight warm
cast so images sit inside the Ink & Bone palette rather than fighting it. Applied in CSS
(`filter`) so a replacement photo inherits the treatment automatically.

**Slots and dimensions:**

| Slot | Target size | Content |
|------|-------------|---------|
| Homepage hero | 1600×1200 | Nashville skyline or courthouse detail |
| Pull-quote panel | 1200×900 | Desk, documents, or office interior |
| Attorney portraits ×2 | 1080×1350 | Headshots — flagged as the one slot where real photography matters most |
| Login split panel | 1200×1600 | Architectural detail |
| Intake / research / drafting headers | 1600×600 | Muted texture or interior |

Headshots stay stock for now; the spec notes that real portraits of Marcus and Sophia are the
single highest-value photography upgrade available and should replace these when taken.

---

## Accessibility

Measured ratios against `--bg` `#F7F5F0` (WCAG AA needs 4.5:1 for normal text, 3:1 for large):

| Token | Ratio | Normal text | Large text |
|-------|-------|-------------|------------|
| `--ink` `#14181F` | 16.33:1 | pass | pass |
| `--ink-2` `#39414F` | 9.43:1 | pass | pass |
| `--muted` `#5A6472` | 5.51:1 | pass | pass |
| `--faint` `#686F79` | 4.66:1 | pass | pass |
| `--accent` `#7D6E4C` | 4.58:1 | pass | pass |
| `--bg` on `--ink` (CTA band) | 16.33:1 | pass | pass |

Every text token now clears AA at normal size, so no usage depends on being rendered large.
`--accent-lt` `#B9AE93` is below threshold and is therefore restricted to borders and
underlines — never text.
- Focus states are visible: 2px `--accent` outline with offset, not `outline: none`.
- Photography treatment never carries meaning on its own.

## Responsive

- Hero split collapses to stacked at ≤ 900px, photograph below the text.
- Practice grid: 3 columns → 2 → 1 at 900px and 620px.
- Attorney and pull-quote splits stack at 780px.
- Display headline scales 52px → 34px at 620px via `clamp()`.
- Footer: four columns → two → one.
- Existing mobile behaviour is preserved, including the research page's collapsible query panel.

## Fonts

Fraunces and Inter are self-hosted as woff2 in `static/fonts/`, declared with `@font-face` and
`font-display: swap`, with full local fallback stacks (`Fraunces, Georgia, 'Times New Roman',
serif` and `Inter, system-ui, 'Segoe UI', sans-serif`). The app runs over HTTPS on a LAN and
is used offline; a Google Fonts CDN dependency would leave the site unstyled in exactly the
situation where it must work. Font files are downloaded under the same confirmation rule as
photography.

## Testing

No Python behaviour changes, so the existing 73 tests must continue to pass unchanged — that
is the regression signal that this stayed presentational.

Additionally:

1. **Render smoke test** — every in-scope route returns 200 with the share password, extended
   to cover the client portal and change-password pages.
2. **Visual verification** — each redesigned page loaded in the browser at desktop (1440px),
   tablet (768px), and mobile (375px) widths.
3. **Attorney portal regression** — dashboard, client detail, documents, research, insights,
   and token-usage tabs opened and checked for contrast or layout breakage from the new tokens.
4. **Contrast audit** — computed ratios for every text/background token pair, asserting AA.
5. **Offline font check** — page loaded with the network blocked to confirm fallbacks hold.

## Risks

| Risk | Mitigation |
|------|------------|
| Token change breaks attorney portal styling | Old token names aliased to new values; portal visually verified tab by tab |
| Inline styles throughout templates hardcode old colours | Audited during the work; hardcoded hex values replaced with tokens |
| Warm palette makes red/green alert states clash | Alert tokens re-tuned against `--bg` and checked on the urgent-deadline banner and billing states |
| Self-hosted fonts add page weight | Subset to Latin, woff2 only, two weights per family |
| Restyling drops a working feature | Every section is inventoried before edit and re-verified after. Case search, the case-search modal, the free-tool cards, the chat widget, the intake gate modal, and the consult modal all keep their ids and handlers. The JS in `app.js` binds by id, so any renamed element breaks silently — ids are treated as an interface and left alone |

## Out of Scope

- Attorney portal layout redesign
- Any change to routes, forms, or data handling
- New pages (a dedicated practice-areas page is referenced by the "All practice areas" link
  and should be a follow-up)
- Real attorney photography
- Streaming AI responses, JS extraction from `attorney_portal.html`, and the storage-layer
  change — all previously identified, all separate work
