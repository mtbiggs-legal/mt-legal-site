"""blueprints/practice_areas.py — Marketing copy for the practice-area pages.

The copy lives in content/practice_areas.toml (see the notes at the top of that
file); this module loads it once at import.
"""

import tomllib
from pathlib import Path

_CONTENT = Path(__file__).resolve().parent.parent / "content" / "practice_areas.toml"

with open(_CONTENT, "rb") as _f:
    _DATA = tomllib.load(_f)

# Display order is the order the areas appear in the file.
PRACTICE_AREAS = _DATA["practice_areas"]

# Emerging Tech hub (/emerging-tech): the practice areas it links into, and the
# expandable "what's changing" briefings underneath them.
EMERGING_TECH_AREAS  = _DATA["emerging_tech"]["areas"]
EMERGING_TECH_TOPICS = _DATA["emerging_tech"]["topics"]
