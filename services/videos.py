"""Videos from the firm's YouTube channel, each shown at the top of its blog post.

The list lives in content/videos.toml (see the notes at the top of that file)
and is loaded once at import. Players load from YouTube's privacy-enhanced
domain, and only after a visitor presses play (static/js/site.js).
"""

import tomllib
from pathlib import Path

_CONTENT = Path(__file__).resolve().parent.parent / "content" / "videos.toml"

with open(_CONTENT, "rb") as _f:
    _DATA = tomllib.load(_f)

VIDEOS = _DATA.get("videos", [])

# Must match frame-src in services/security.py's CSP.
EMBED_ORIGIN = "https://www.youtube-nocookie.com"


def for_post(slug: str):
    """The video shown at the top of a blog post, or None."""
    return next((v for v in VIDEOS if v.get("post") == slug), None)
