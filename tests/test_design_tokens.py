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


# Every token used for text.
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


@pytest.mark.parametrize("fg,bg", [("--red", "--red-lt"), ("--green", "--green-lt")])
def test_alert_states_meet_aa(fg, bg):
    """Alert text sits on its own tinted background, not on --bg."""
    tokens = _parse_tokens()
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= 4.5, f"{fg} on {bg} is {ratio:.2f}:1, needs 4.5:1"


def test_accent_lt_is_not_used_for_text():
    """--accent-lt is a border colour and fails AA — guard against misuse.

    If someone raises it to a text-safe value that is fine, but it must not
    sit in the palette looking usable for text while failing contrast.
    """
    tokens = _parse_tokens()
    ratio = contrast(tokens["--accent-lt"], tokens["--bg"])
    assert ratio < 4.5, (
        "--accent-lt now passes AA; either promote it to a text token with a "
        "test, or keep it below threshold and borders-only"
    )


def test_legacy_aliases_still_defined():
    """99 lines in style.css (190 references) plus inline styles use the old names.

    Dropping them silently breaks the attorney portal, which this redesign
    does not touch.
    """
    tokens = _parse_tokens()
    for legacy in ("--navy", "--gold", "--gray-1", "--gray-2",
                   "--gray-3", "--gray-4", "--text", "--white"):
        assert legacy in tokens, f"legacy alias {legacy} was removed"
