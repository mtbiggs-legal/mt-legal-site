# Editorial Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the navy/gold centred law-firm template with an editorial layout — Ink & Bone palette, Fraunces display serif over Inter, hairline rules, left-aligned — across the public site and client-facing tools.

**Architecture:** Presentation-only. All colour and type flows from CSS custom properties in `:root` of `static/css/style.css`; old token names are aliased to new values so the 3,720-line attorney portal inherits the palette without being edited. Templates are restructured section by section, preserving every element `id` because `static/js/app.js` and the inline page scripts bind by id. No Python, routes, or form contracts change.

**Tech Stack:** Flask + Jinja2 templates, hand-written CSS with custom properties, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-editorial-redesign-design.md`

---

## Critical Constraints

Read before starting any task.

1. **The 73 existing tests must pass after every commit.** They are the signal that this stayed presentational. Run `python -m pytest tests/ -q` before each commit.
2. **Element ids are an interface.** `static/js/app.js` and inline scripts bind by `getElementById`. Renaming or removing an id breaks a feature silently — no error, just a dead button. Ids to preserve are listed per task.
3. **The app serves HTTPS with Basic Auth.** `SHARE_PASSWORD` in `.env` puts it on `https://127.0.0.1:5000` behind a Basic Auth prompt. Verification commands below already account for this.
4. **Never delete a section to "simplify".** Every existing section is restyled, not removed. If a section seems redundant, flag it rather than dropping it.
5. **Downloads require confirmation.** Fonts and photography are downloaded from the network. Present filename, source, and size to the user and get an explicit yes before saving. This is already approved in principle for Pexels; still list files before writing them.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `static/css/tokens.css` | **New.** Design tokens only — colour, type scale, spacing, radius. Single source of truth. | Create |
| `static/css/style.css` | Component and layout rules consuming the tokens | Modify (1,641 lines) |
| `static/fonts/` | **New.** Self-hosted Fraunces + Inter woff2 | Create |
| `templates/base.html` | Nav, footer, chat widget, both modals, font links | Modify |
| `templates/index.html` | Homepage — 8 sections | Modify (621 lines) |
| `templates/meet_the_firm.html` | Attorney profiles + testimonials | Modify (495 lines) |
| `templates/intake.html` | Intake form | Modify (624 lines) |
| `templates/research.html` | Research tool | Modify (115 lines) |
| `templates/drafting.html` | Document generator | Modify (868 lines) |
| `templates/client_login.html` | Login + registration | Modify (170 lines) |
| `templates/attorney_login.html` | Attorney login | Modify (31 lines) |
| `templates/change_password.html` | Password change | Modify (47 lines) |
| `templates/client_portal.html` | Client portal tabs | Modify (901 lines) |
| `tests/test_design_tokens.py` | **New.** Asserts token contrast and that ids survive | Create |
| `scripts/fetch_photos.py` | **New.** Pexels search + download helper | Create |

Tokens go in their own file because they are referenced by both `style.css` and inline template styles, and because a single small file is far easier to audit for contrast than 1,641 lines.

---

## Chunk 1: Foundation — tokens, fonts, contrast test

### Task 1: Contrast test for the token palette

Write the test before the tokens exist, so the palette is proven accessible rather than assumed.

**Files:**
- Create: `tests/test_design_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
"""The design tokens must meet WCAG AA before any page uses them.

Parsing the CSS rather than hardcoding values means the test fails if
someone later edits a colour to something inaccessible.
"""

import re
from pathlib import Path

import pytest

TOKENS_CSS = Path(__file__).parent.parent / "static" / "css" / "tokens.css"


def _parse_tokens():
    """Return {token_name: hex_value} from the :root block of tokens.css."""
    text = TOKENS_CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", text, re.S)
    assert root, "tokens.css must define a :root block"
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", root.group(1))
    }


def _luminance(hex_colour):
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg):
    lf, lb = _luminance(fg), _luminance(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


# Every token used for text, and the background it sits on.
TEXT_TOKENS = ["--ink", "--ink-2", "--muted", "--faint", "--accent"]


@pytest.mark.parametrize("token", TEXT_TOKENS)
def test_text_token_meets_aa_on_background(token):
    """Text colours need 4.5:1 against the page background."""
    tokens = _parse_tokens()
    ratio = contrast(tokens[token], tokens["--bg"])
    assert ratio >= 4.5, f"{token} is {ratio:.2f}:1 on --bg, needs 4.5:1"


@pytest.mark.parametrize("token", TEXT_TOKENS)
def test_text_token_meets_aa_on_paper(token):
    """Cards use --paper, so text must clear AA there too."""
    tokens = _parse_tokens()
    ratio = contrast(tokens[token], tokens["--paper"])
    assert ratio >= 4.5, f"{token} is {ratio:.2f}:1 on --paper, needs 4.5:1"


def test_inverted_text_on_ink_band_meets_aa():
    """The CTA band puts --bg text on --ink."""
    tokens = _parse_tokens()
    ratio = contrast(tokens["--bg"], tokens["--ink"])
    assert ratio >= 4.5, f"--bg on --ink is {ratio:.2f}:1"


def test_legacy_aliases_still_defined():
    """99 lines in style.css (190 references) plus inline styles use the old names.

    Dropping them silently breaks the attorney portal, which this redesign
    does not touch.
    """
    tokens = _parse_tokens()
    for legacy in ("--navy", "--gold", "--gray-1", "--gray-2",
                   "--gray-3", "--gray-4", "--text", "--white"):
        assert legacy in tokens, f"legacy alias {legacy} was removed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_design_tokens.py -q`
Expected: all tests ERROR/FAIL — `tokens.css` does not exist yet.

- [ ] **Step 3: Create the token file**

Create `static/css/tokens.css`:

```css
/* ─────────────────────────────────────────────────────────────────────────────
   Design tokens — single source of truth for colour and type.

   Every value here is verified by tests/test_design_tokens.py. If you change a
   colour, run that test: several of these were darkened from the approved
   mockup specifically to clear WCAG AA.
   ───────────────────────────────────────────────────────────────────────────── */

:root {
  /* ── Surfaces ── */
  --bg:        #F7F5F0;   /* warm off-white page background */
  --paper:     #FFFDF9;   /* cards and raised surfaces */

  /* ── Text ── */
  --ink:       #14181F;   /* headlines, primary buttons        16.33:1 on --bg */
  --ink-2:     #39414F;   /* secondary text                     9.43:1 */
  --muted:     #5A6472;   /* body copy                          5.51:1 */
  --faint:     #686F79;   /* labels, captions, metadata         4.66:1 */

  /* ── Accent ── */
  --accent:    #7D6E4C;   /* antique brass, text-safe           4.58:1 */
  --accent-lt: #B9AE93;   /* borders and underlines ONLY — fails AA for text */

  /* ── Structure ── */
  --rule:      #E2DED4;   /* all borders and dividers */

  /* ── Semantic states (re-tuned for the warm background) ── */
  --red:       #A33224;
  --red-lt:    #F7E4E0;
  --green:     #1B6B33;
  --green-lt:  #E3F0E6;

  /* ── Type ── */
  --font-display: Fraunces, Georgia, "Times New Roman", serif;
  --font-sans:    Inter, system-ui, "Segoe UI", Arial, sans-serif;

  /* ── Geometry ── */
  --radius:    2px;       /* buttons and inputs — was pill/12px */
  --radius-lg: 6px;       /* cards */
  --shadow:    none;      /* separation comes from rules, not elevation */

  /* ─────────────────────────────────────────────────────────────────────────
     Legacy aliases.

     99 rules in style.css plus inline styles across every template reference
     these names, and the attorney portal is out of scope for this redesign.
     Aliasing lets the portal inherit the new palette untouched.
     Do not remove without auditing every template.
     ───────────────────────────────────────────────────────────────────────── */
  --navy:     #14181F;
  --navy-lt:  #39414F;
  --crimson:  #7D6E4C;
  --gold:     #7D6E4C;
  --gold-lt:  #B9AE93;
  --gray-1:   #F7F5F0;
  --gray-2:   #E2DED4;
  --gray-3:   #686F79;
  --gray-4:   #39414F;
  --white:    #FFFDF9;
  --text:     #14181F;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_design_tokens.py -q`
Expected: PASS (11 tests).

If `--red` or `--green` were used for text anywhere they would need checking too; they are used for backgrounds and icons only, so they are excluded deliberately.

- [ ] **Step 5: Commit**

```bash
git add static/css/tokens.css tests/test_design_tokens.py
git commit -m "feat(design): add Ink & Bone design tokens with contrast tests"
```

---

### Task 2: Self-host the fonts

**Files:**
- Create: `static/fonts/` (woff2 files)
- Modify: `static/css/tokens.css` (append `@font-face`)
- Modify: `templates/base.html` (link the stylesheet)

- [ ] **Step 1: Ask the user before downloading**

STOP. Downloading files needs explicit confirmation. Present exactly this:

> I need to download 4 font files (~180 KB total) from Google Fonts' open-source repository:
> - `fraunces-400.woff2`, `fraunces-600.woff2`
> - `inter-400.woff2`, `inter-500.woff2`
>
> Source: `fonts.gstatic.com`. They'd be saved to `static/fonts/`. OK to download?

Wait for a yes. Do not proceed without one.

- [ ] **Step 2: Download the fonts**

```bash
mkdir -p static/fonts
# URLs resolve from the Google Fonts CSS API; fetch the woff2 the API points at.
curl -sL "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=Inter:wght@400;500&display=swap" \
  -H "User-Agent: Mozilla/5.0" -o /tmp/gf.css
grep -o 'https://fonts.gstatic.com[^)]*\.woff2' /tmp/gf.css | sort -u
```

Download each URL into `static/fonts/` with the names above.

- [ ] **Step 3: Verify the files are real fonts, not error pages**

```bash
ls -la static/fonts/
python -c "
from pathlib import Path
for f in sorted(Path('static/fonts').glob('*.woff2')):
    head = f.read_bytes()[:4]
    print(f.name, f.stat().st_size, 'OK' if head == b'wOF2' else 'NOT A WOFF2 FILE')
"
```

Expected: every file prints `OK`. A file that is not `wOF2` is an HTML error page — delete and retry.

- [ ] **Step 4: Append `@font-face` to `tokens.css`**

```css
/* ── Self-hosted fonts ───────────────────────────────────────────────────────
   The app runs over HTTPS on a LAN and is used offline. A CDN dependency would
   leave the site unstyled in exactly the situation where it has to work.
   ─────────────────────────────────────────────────────────────────────────── */
@font-face {
  font-family: 'Fraunces';
  src: url('/static/fonts/fraunces-400.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Fraunces';
  src: url('/static/fonts/fraunces-600.woff2') format('woff2');
  font-weight: 600; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter';
  src: url('/static/fonts/inter-400.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter';
  src: url('/static/fonts/inter-500.woff2') format('woff2');
  font-weight: 500; font-style: normal; font-display: swap;
}
```

- [ ] **Step 5: Link tokens.css from base.html**

In `templates/base.html`, immediately **before** the existing `style.css` link (so component rules can override tokens), add:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
```

- [ ] **Step 6: Verify the fonts serve**

```bash
PW=$(grep '^SHARE_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
for f in fraunces-400 inter-400; do
  curl -sk -u "x:$PW" -o /dev/null -w "  %{http_code}  %{content_type}  $f\n" \
    "https://127.0.0.1:5000/static/fonts/$f.woff2"
done
curl -sk -u "x:$PW" -o /dev/null -w "  %{http_code}  tokens.css\n" \
  "https://127.0.0.1:5000/static/css/tokens.css"
```

Expected: `200` for all three. Restart the server first if it is not running.

- [ ] **Step 7: Commit**

```bash
git add static/fonts static/css/tokens.css templates/base.html
git commit -m "feat(design): self-host Fraunces and Inter, wire tokens into base"
```

---

### Task 3: Point style.css at the tokens

The old `:root` block is now redundant — `tokens.css` owns those names. Removing the duplicate prevents the two files drifting.

**Files:**
- Modify: `static/css/style.css:4-22` (the `:root` block) and the base typography that follows

- [ ] **Step 1: Snapshot the current rendering for comparison**

```bash
PW=$(grep '^SHARE_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
for p in / /meet-the-firm /intake /research /drafting /client-login /attorney-login; do
  echo "  $(curl -sk -u "x:$PW" -o /dev/null -w '%{http_code}' https://127.0.0.1:5000$p)  $p"
done
```

Expected: `200` for every route. This is the baseline; it must still hold at the end.

- [ ] **Step 2: Delete the duplicated `:root` block**

Remove `static/css/style.css` lines 4–22 entirely (the old `:root { --navy … --shadow }`). Do not replace it — `tokens.css` now provides every one of those names.

- [ ] **Step 3: Update base typography**

Replace the `body` font declaration (around `style.css:26`) so the sans is the default and the serif is reserved for headings:

```css
body {
  font-family: var(--font-sans);
  background: var(--bg);
  color: var(--muted);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3, h4, .display {
  font-family: var(--font-display);
  color: var(--ink);
  font-weight: 400;
  letter-spacing: -0.015em;
  line-height: 1.1;
}

h1 { font-size: clamp(2.1rem, 5vw, 3.25rem); line-height: 1.02; letter-spacing: -0.02em; }
h2 { font-size: clamp(1.6rem, 3.4vw, 2.05rem); }
h3 { font-size: 1.3rem; }

/* Brass is for emphasis inside headlines, never for running text. */
h1 em, h2 em { font-style: italic; color: var(--accent); }

.eyebrow {
  font-family: var(--font-sans);
  font-size: .625rem;
  font-weight: 500;
  letter-spacing: .24em;
  text-transform: uppercase;
  color: var(--accent);
}
```

- [ ] **Step 4: Verify every page still renders**

Re-run the Step 1 command. Expected: `200` across the board.

Then open `https://127.0.0.1:5000/` in a browser and confirm the page is legible — it will look half-converted at this stage, which is expected. What matters is that nothing is invisible (white-on-white) or unstyled.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: `84 passed` (73 existing + 11 new token tests).

- [ ] **Step 6: Commit**

```bash
git add static/css/style.css
git commit -m "refactor(design): move :root to tokens.css, set editorial type scale"
```

---

## Chunk 2: Components and shared chrome

### Task 4: Restyle buttons, forms, cards, and alerts

These are used on every page, so doing them before the page work means each page task is layout-only.

**Files:**
- Modify: `static/css/style.css` — Cards (`103`), Forms (`132`), Buttons (`168`), Alerts (`194`)

- [ ] **Step 1: Rewrite the button rules**

Replace the `.btn` family (from `style.css:168`) with:

```css
.btn {
  display: inline-block;
  font-family: var(--font-sans);
  font-size: .8125rem;
  font-weight: 500;
  letter-spacing: .01em;
  padding: .875rem 1.5rem;
  border-radius: var(--radius);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
  text-decoration: none;
}
.btn-primary { background: var(--ink); color: var(--bg); }
.btn-primary:hover { background: var(--ink-2); }

.btn-secondary { background: transparent; color: var(--ink); border-color: var(--rule); }
.btn-secondary:hover { border-color: var(--ink); }

/* Text link with a brass underline — the editorial secondary action. */
.btn-quiet {
  background: none; border: none; padding: 0;
  color: var(--ink); border-bottom: 1px solid var(--accent-lt);
  border-radius: 0; padding-bottom: 2px;
}
.btn-quiet:hover { border-bottom-color: var(--ink); }

.btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

Keep every existing modifier class name (`.btn-print`, `.btn-calendar`, `.btn-lg`) — templates reference them. Re-point them at the new base rather than deleting them.

- [ ] **Step 2: Rewrite forms**

```css
.form-group label {
  display: block;
  font-family: var(--font-sans);
  font-size: .6875rem;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--faint);
  margin-bottom: .4rem;
}
.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  font-family: var(--font-sans);
  font-size: .9rem;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: .75rem .85rem;
  transition: border-color .15s;
}
.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(125, 110, 76, .12);
}
```

- [ ] **Step 3: Rewrite cards and alerts**

```css
.card {
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius-lg);
  box-shadow: none;              /* elevation removed by design */
  padding: 1.75rem;
}

.alert {
  display: flex;
  gap: .75rem;
  border-radius: var(--radius);
  border: 1px solid var(--rule);
  background: var(--paper);
  padding: .85rem 1.1rem;
  font-size: .875rem;
}
.alert-urgent  { background: var(--red-lt);   border-color: var(--red);   color: var(--red); }
.alert-success { background: var(--green-lt); border-color: var(--green); color: var(--green); }
.alert-info    { background: var(--paper);    border-color: var(--rule);  color: var(--muted); }
```

- [ ] **Step 4: Verify the alert colours still pass contrast**

```bash
python -c "
def lum(h):
    h=h.lstrip('#'); ch=[]
    for i in (0,2,4):
        c=int(h[i:i+2],16)/255
        ch.append(c/12.92 if c<=0.03928 else ((c+0.055)/1.055)**2.4)
    return 0.2126*ch[0]+0.7152*ch[1]+0.0722*ch[2]
def r(a,b):
    la,lb=lum(a),lum(b); hi,lo=max(la,lb),min(la,lb); return (hi+0.05)/(lo+0.05)
for name,fg,bg in [('red on red-lt','#A33224','#F7E4E0'),('green on green-lt','#1B6B33','#E3F0E6')]:
    v=r(fg,bg); print(f'{name}: {v:.2f}:1', 'PASS' if v>=4.5 else 'FAIL')
"
```

Expected: both PASS. If either fails, darken the foreground until it clears 4.5:1.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/ -q` → `84 passed`

```bash
git add static/css/style.css
git commit -m "feat(design): editorial buttons, forms, cards, and alerts"
```

---

### Task 5: Restyle the shared chrome in base.html

**Files:**
- Modify: `templates/base.html` — header (`233-255`), footer (`263-265`), chat widget, intake modal (`498+`), consult modal
- Modify: `static/css/style.css` — Header/Nav (`34`), Footer (`86`), Modal (`556`), Forced Intake Gate Modal (`1155`)

**Ids that must survive:** `chat-widget`, `chat-messages`, `chat-input`, `consultation-modal`, `consult-title`, `consult-body`, `consult-dismiss`, `forced-intake-modal`, `fi-name`, `fi-phone`, `fi-email`, `fi-case-type`, `forced-intake-result`, `calendar-modal` and its fields.

- [ ] **Step 1: List the ids currently in base.html**

```bash
grep -o 'id="[^"]*"' templates/base.html | sort > /tmp/base-ids-before.txt
wc -l /tmp/base-ids-before.txt
```

- [ ] **Step 2: Restyle the header**

The header becomes a single hairline-bottom bar: wordmark left with a small caps subtitle, nav centre, `Client Login` as a quiet link plus `Free Consultation` as a solid ink button right. Remove the gold pill treatment on the portal buttons (`style.css:1203`).

```css
.site-header {
  background: var(--bg);
  border-bottom: 1px solid var(--rule);
  padding: 1.05rem 2.5rem;
  display: flex; align-items: center; justify-content: space-between;
  gap: 1.5rem;
}
.main-nav { display: flex; gap: 1.6rem; }
.main-nav a {
  font-family: var(--font-sans); font-size: .8125rem;
  color: var(--ink-2); text-decoration: none; padding-bottom: 3px;
}
.main-nav a:hover { color: var(--ink); }
.main-nav a.active { color: var(--ink); font-weight: 500; border-bottom: 1px solid var(--accent); }
```

- [ ] **Step 3: Restyle the footer**

Replace the single-line footer with the four-column layout plus a legal sub-bar carrying the attorney-advertising disclaimer (firm / practice / clients / contact — content per the spec).

- [ ] **Step 4: Restyle the two modals and the chat widget**

Keep all structure and ids; change only colour, radius, and type. The chat launcher pill becomes `--ink` with `--bg` text.

- [ ] **Step 5: Verify no id was lost**

```bash
grep -o 'id="[^"]*"' templates/base.html | sort > /tmp/base-ids-after.txt
diff /tmp/base-ids-before.txt /tmp/base-ids-after.txt && echo "NO IDS LOST"
```

Expected: `NO IDS LOST`. Any line prefixed `<` is an id you deleted — restore it.

- [ ] **Step 6: Verify the interactive pieces still work**

Load `https://127.0.0.1:5000/` in a browser and confirm: the chat bubble opens and sends a message; the consultation modal opens and dismisses; nav links route correctly.

- [ ] **Step 7: Run tests and commit**

Run: `python -m pytest tests/ -q` → `84 passed`

```bash
git add templates/base.html static/css/style.css
git commit -m "feat(design): editorial header, footer, modals, and chat widget"
```

---

## Chunk 3: Pages

### Task 6: Homepage

The largest single task. Eight sections, three of which carry working JS.

**Files:**
- Modify: `templates/index.html` (621 lines)
- Modify: `static/css/style.css` — photo hero (`636`), home hero (`691`), services (`872`), practice cards (`969`), feature cards (`1035`), follow-up (`1065`)

**Ids that must survive:** `cs-form`, `cs-county`, `cs-case-type`, `cs-recent-wrap`, `cs-recent-chips`, and every id the case-search modal and `submitCaseSearch()` reference.

- [ ] **Step 1: Inventory ids and handlers before touching anything**

```bash
grep -o 'id="[^"]*"' templates/index.html | sort > /tmp/index-ids-before.txt
grep -o 'onclick="[^"]*"\|onsubmit="[^"]*"\|onchange="[^"]*"' templates/index.html | sort -u
```

Save both. The handler list tells you which functions must stay reachable.

- [ ] **Step 2: Replace the hero (`index.html:229-241`)**

Asymmetric two-column split. Left column: `.eyebrow` "Nashville, Tennessee", `h1` with one `<em>` word, lede paragraph, `.btn-primary` + `.btn-quiet`. Right column: photograph, `object-fit: cover`, square corners, no dark overlay — the text no longer sits on top of it.

Delete the separate navy "JUSTICE. INTEGRITY. RESULTS." banner; the hero replaces both.

- [ ] **Step 3: Replace the practice cards (`index.html:243-289`)**

3×2 grid, `gap: 1px` on a `--rule` background so cells read as one table. Each cell: number `01`–`06` in `--accent-lt`, serif title, one-sentence description, attorney name with an arrow. Six areas per the spec.

- [ ] **Step 4: Restyle case search (`index.html:294-433`) — structure unchanged**

This is a **restyle only**. Do not touch the `<form>`, the selects, the option lists, or `submitCaseSearch()`. Change the wrapper to a hairline card, left-align the heading, and let the selects inherit the Task 4 form styling. The county list stays exactly as-is.

- [ ] **Step 5: Add the pull-quote section**

New section between case search and the free tools: split panel, photograph left, single italic serif quote right with attribution.

- [ ] **Step 6: Restyle the free-tool cards (`index.html:584-611`)**

Two-up editorial split for Research Bot and Document Generator. Keep both links pointing at `/research` and `/drafting`.

- [ ] **Step 7: Add the attorneys preview, then the CTA band (`index.html:612-619`)**

Two portrait cards linking to `/meet-the-firm`, then a full-width `--ink` band with a headline and one button to `/intake`.

- [ ] **Step 8: Verify no id was lost**

```bash
grep -o 'id="[^"]*"' templates/index.html | sort > /tmp/index-ids-after.txt
diff /tmp/index-ids-before.txt /tmp/index-ids-after.txt && echo "NO IDS LOST"
```

- [ ] **Step 9: Verify case search still functions end to end**

In a browser on `https://127.0.0.1:5000/`: pick a county and case type, submit, confirm the warning modal appears and the redirect URL is correct. Then confirm the request hit the server:

```bash
tail -5 server-out.log | grep "case-search"
```

Expected: a `POST /api/case-search` line with status `200`.

- [ ] **Step 10: Run tests and commit**

Run: `python -m pytest tests/ -q` → `84 passed`

```bash
git add templates/index.html static/css/style.css
git commit -m "feat(design): editorial homepage"
```

---

### Task 7: Meet the Firm

**Files:**
- Modify: `templates/meet_the_firm.html` (495 lines)
- Modify: `static/css/style.css` — Meet the Firm (`406`), testimonial carousel (`312`), law quote (`1091`)

- [ ] **Step 1: Inventory ids**

```bash
grep -o 'id="[^"]*"' templates/meet_the_firm.html | sort > /tmp/mtf-ids-before.txt
```

- [ ] **Step 2: Restyle the attorney profiles (`234-415`)**

Large portrait left, biography right, hairline rule between the two attorneys. Keep the click-to-expand bio behaviour and its ids.

- [ ] **Step 3: Replace the rotating carousel (`meet_the_firm.html:420`) with a static grid**

Three quotes side by side, each a serif italic pull-quote with attribution, separated by hairline rules. Auto-rotation goes away.

- [ ] **Step 4: Remove the now-dead carousel JS**

The carousel IIFE in `static/js/app.js` (the block starting `var carousel = document.getElementById("testimonial-carousel")`) has nothing to bind to once the carousel is gone. Delete it and the `.testimonial-*` CSS at `style.css:312`.

Verify nothing else references it:

```bash
grep -rn "testimonial-carousel\|testimonial-slide\|testimonial-bg" templates/ static/ || echo "NO REFERENCES LEFT"
```

Expected: `NO REFERENCES LEFT`.

- [ ] **Step 5: Verify ids, run tests, commit**

```bash
grep -o 'id="[^"]*"' templates/meet_the_firm.html | sort > /tmp/mtf-ids-after.txt
diff /tmp/mtf-ids-before.txt /tmp/mtf-ids-after.txt
python -m pytest tests/ -q
git add templates/meet_the_firm.html static/css/style.css static/js/app.js
git commit -m "feat(design): editorial Meet the Firm, replace carousel with quote grid"
```

Note: the id diff here is expected to show the removed carousel ids. That is the one intentional deletion — confirm the diff contains *only* `testimonial-*` ids.

---

### Task 8: Intake, research, and drafting

Three tool pages sharing form and output patterns.

**Files:**
- Modify: `templates/intake.html`, `templates/research.html`, `templates/drafting.html`
- Modify: `static/css/style.css` — memo output (`225`), draft textarea (`240`), query panel (`276`), intake hero (`749`)

**Ids that must survive:** `intake-form`, `intake-result`, `esig-consent`, `esig-timestamp`; `research-question`, `research-case-type`, `research-result`, `query-panel`, `query-toggle-btn`; `drafting-form`, `template-type`, `drafting-result`, every `fields-*` block, and the claim-modal ids.

- [ ] **Step 1: Inventory ids across all three**

```bash
for f in intake research drafting; do
  grep -o 'id="[^"]*"' templates/$f.html | sort > /tmp/$f-ids-before.txt
done
```

- [ ] **Step 2: Restyle the intake form**

Replace the photo hero with a compact editorial page header (eyebrow + serif h1 + lede on `--bg`, hairline rule beneath). Group fields into labelled sections separated by rules. Keep every field `name` — `submitIntake()` reads them by name.

- [ ] **Step 3: Restyle research**

Editorial page header; the query panel becomes a hairline card; `.memo-output` gets the reading treatment: `--paper`, generous line-height, serif `h2`/`h3` inside the memo, `max-width: 68ch`.

- [ ] **Step 4: Restyle drafting**

Editorial header, restyled template picker, and the preview panel using `--paper` with `white-space: pre-wrap` (already set in the recent fix — do not regress it).

**Critical:** the `fields-*` block ids map to template names via `templateFieldsId()` in `app.js`. Do not rename any of them. Verify:

```bash
grep -o 'id="fields-[^"]*"' templates/drafting.html | wc -l
```

Expected: `19` — one per template in the dropdown.

- [ ] **Step 5: Verify ids survived on all three**

```bash
for f in intake research drafting; do
  grep -o 'id="[^"]*"' templates/$f.html | sort > /tmp/$f-ids-after.txt
  echo "== $f =="; diff /tmp/$f-ids-before.txt /tmp/$f-ids-after.txt && echo "  NO IDS LOST"
done
```

- [ ] **Step 6: Verify the drafting field mapping still resolves**

```bash
python - <<'PY'
import re, io
html = io.open('templates/drafting.html', encoding='utf-8').read()
sel = re.search(r'<select id="template-type".*?</select>', html, re.S).group(0)
values = [v for v in re.findall(r'<option value="([^"]*)"', sel) if v]
ids = set(re.findall(r'id="(fields-[^"]+)"', html))
def fid(n):
    s = re.sub(r'[()]', '', n.lower())
    return 'fields-' + re.sub(r'\s+', '-', s.strip())
missing = [v for v in values if fid(v) not in ids]
print(f'templates: {len(values)}, unmatched: {len(missing)} {missing}')
PY
```

Expected: `unmatched: 0`.

- [ ] **Step 7: Run tests and commit**

Run: `python -m pytest tests/ -q` → `84 passed`

```bash
git add templates/intake.html templates/research.html templates/drafting.html static/css/style.css
git commit -m "feat(design): editorial intake, research, and drafting pages"
```

---

### Task 9: Login pages and client portal

**Files:**
- Modify: `templates/client_login.html`, `templates/attorney_login.html`, `templates/change_password.html`, `templates/client_portal.html`

**Ids that must survive:** the registration form ids in `client_login.html`; in `client_portal.html` — `message-thread`, `msg-text`, `msg-result`, `billing-stats`, `bill-hours-billed`, `bill-hours-paid`, `bill-balance-due`, `bill-rate`, `billing-pay-card`, `billing-paid-msg`, `billing-no-methods`, `btn-pay-card`, `btn-pay-crypto`, `billing-log-body`, `billing-history-body`, `fee-schedule-modal`, `cr-answer`, `cr-result-card`, `cr-save-btn`, and every `tab-*` panel.

- [ ] **Step 1: Inventory ids**

```bash
for f in client_login attorney_login change_password client_portal; do
  grep -o 'id="[^"]*"' templates/$f.html | sort > /tmp/$f-ids-before.txt
done
```

- [ ] **Step 2: Rebuild the login pages as a split layout**

Form left on `--bg`, photograph right. All three login/password pages share the layout. Keep the form `action`, `method`, and field `name`s exactly.

- [ ] **Step 3: Restyle the client portal**

Tabs become an underlined row (active tab carries a `--accent` bottom border) rather than filled pills. Stat blocks, billing tables, and the document list all move to hairline borders on `--paper`. Serif for the figures in `.portal-stat-value`.

- [ ] **Step 4: Verify ids and the portal's live behaviour**

```bash
for f in client_login attorney_login change_password client_portal; do
  grep -o 'id="[^"]*"' templates/$f.html | sort > /tmp/$f-ids-after.txt
  echo "== $f =="; diff /tmp/$f-ids-before.txt /tmp/$f-ids-after.txt && echo "  NO IDS LOST"
done
```

Then log in as a client and confirm: tab switching works, the billing tab loads figures, the message box sends, and the research tab renders an answer.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/ -q` → `84 passed`

```bash
git add templates/client_login.html templates/attorney_login.html templates/change_password.html templates/client_portal.html static/css/style.css
git commit -m "feat(design): editorial login pages and client portal"
```

---

## Chunk 4: Photography, portal regression, and sign-off

### Task 10: Replace the stock photography

**Files:**
- Create: `scripts/fetch_photos.py`
- Modify: `static/images/` (new files)
- Modify: `static/css/style.css` (image treatment)

- [ ] **Step 1: Write the Pexels search helper**

Create `scripts/fetch_photos.py` — searches Pexels and **prints candidates without downloading**. Downloading is a separate, confirmed step.

```python
"""Search Pexels for replacement photography. Prints candidates; downloads nothing.

Usage:
    python scripts/fetch_photos.py "nashville architecture" --n 8
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


def search(query, n):
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        sys.exit("PEXELS_API_KEY is not set in .env")
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": key},
        params={"query": query, "per_page": n, "orientation": "landscape"},
        timeout=20,
    )
    resp.raise_for_status()
    for photo in resp.json().get("photos", []):
        print(f"{photo['id']:>10}  {photo['width']}x{photo['height']}  "
              f"by {photo['photographer']}")
        print(f"            preview : {photo['src']['medium']}")
        print(f"            download: {photo['src']['large2x']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--n", type=int, default=8)
    a = p.parse_args()
    search(a.query, a.n)
```

- [ ] **Step 2: Search for each slot**

```bash
python scripts/fetch_photos.py "nashville tennessee architecture" --n 8
python scripts/fetch_photos.py "law office interior desk documents" --n 8
python scripts/fetch_photos.py "courthouse architecture detail" --n 8
```

- [ ] **Step 3: Present candidates and get confirmation**

STOP. Show the user the preview URLs for your shortlist, one per slot, with the filename and approximate size each would be saved as. Wait for an explicit yes before downloading anything.

- [ ] **Step 4: Download only the approved images**

Save at the spec's target sizes, overwriting: `hero-firm.jpg`, `hero-home.jpg`, `hero-intake.jpg`, `bg-research.jpg`, `bg-documents.jpg`, `quote-justice.jpg`, `service-criminal.jpg`, `service-civil.jpg`.

Leave `attorney-marcus.jpg` and `attorney-sophia.jpg` alone — real portraits are the highest-value upgrade and stock substitutes do not help.

- [ ] **Step 5: Verify the downloads are valid JPEGs**

```bash
python -c "
from pathlib import Path
for f in sorted(Path('static/images').glob('*.jpg')):
    b = f.read_bytes()
    print(f'{f.name:<26} {f.stat().st_size//1024:>5} KB  {\"OK\" if b[:2]==b\"\\xff\\xd8\" else \"NOT A JPEG\"}')
"
```

Expected: every file `OK`.

- [ ] **Step 6: Apply the consistent treatment**

```css
/* One rule so a swapped photo inherits the treatment automatically. */
.photo-treated,
.hero-photo,
.quote-photo {
  filter: grayscale(82%) contrast(1.04) brightness(.98) sepia(9%);
}
```

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_photos.py static/images static/css/style.css
git commit -m "feat(design): replace stock photography and apply consistent treatment"
```

---

### Task 11: Attorney portal regression check

The portal was never edited, but it inherits every token. This task exists to catch what that broke.

**Files:**
- Modify: `templates/attorney_portal.html` (only if something is broken)

- [ ] **Step 1: Open every portal tab and look**

Log in as an attorney and check each of: Dashboard, Clients, client detail, Documents, Research, Leads, Insights, Token Usage.

Look specifically for: white text on a white background, invisible borders, unreadable table rows, charts whose colours no longer separate, and buttons that lost their fill.

- [ ] **Step 2: Find hardcoded colours the tokens could not reach**

```bash
grep -o 'color:#[0-9A-Fa-f]\{3,6\}\|background:#[0-9A-Fa-f]\{3,6\}' templates/attorney_portal.html \
  | sort | uniq -c | sort -rn | head -25
```

Any dark hardcoded background paired with dark inherited text is a break. Fix by replacing the hex with the matching token.

- [ ] **Step 3: Fix only what is actually broken**

Minimal edits. This task is not a redesign — resist restyling.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/ -q` → `84 passed`

```bash
git add templates/attorney_portal.html
git commit -m "fix(design): repair attorney portal contrast under new tokens"
```

---

### Task 12: Full verification and responsive pass

- [ ] **Step 1: Confirm every route still returns 200**

```bash
PW=$(grep '^SHARE_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')
for p in / /meet-the-firm /intake /research /drafting /client-login /attorney-login; do
  echo "  $(curl -sk -u "x:$PW" -o /dev/null -w '%{http_code}' https://127.0.0.1:5000$p)  $p"
done
```

Expected: `200` for all seven.

- [ ] **Step 2: Check each page at three widths**

Load every redesigned page at 1440px, 768px, and 375px. Confirm: the hero split stacks below 900px, the practice grid steps 3→2→1, no horizontal scrollbar appears, and tap targets stay at least 44px on mobile.

- [ ] **Step 3: Confirm the fonts work offline**

Block network access (or rename `static/fonts/` temporarily) and reload. The page must stay fully readable on the Georgia and system-sans fallbacks. Restore the directory afterwards.

- [ ] **Step 4: Run the full suite one last time**

Run: `python -m pytest tests/ -q`
Expected: `84 passed`. Any failure here means something non-presentational changed — investigate before shipping.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(design): complete editorial redesign"
```

---

## Done When

- All 84 tests pass.
- Every public and client-facing page renders in the Editorial style at three widths.
- The attorney portal is legible and functional under the new tokens.
- No element id was lost except the intentionally removed `testimonial-*` set.
- Case search, the chat widget, the intake gate, document generation, and portal billing all still work.
