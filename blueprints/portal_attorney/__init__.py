"""blueprints/portal_attorney — the attorney portal: dashboard, clients, billing,
conflicts, scheduling orders, leads and documents, one module each. They all
add routes to the one blueprint in _common.py, so endpoint names
(portal_attorney.<view>) are unchanged.

Research tools live in blueprints/research.py, insights and token usage in
blueprints/insights.py.
"""

from ._common import portal_attorney_bp  # noqa: F401
from . import pages, clients, billing, conflicts, scheduling, leads, documents  # noqa: F401,E402
