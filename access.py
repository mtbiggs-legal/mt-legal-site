"""access.py — who may reach a route: access levels, auth decorators, the
share password. Blueprints import these through shared.py as before
(`from shared import require_attorney`).

Every view must declare who may reach it; app.py refuses (404) any endpoint
that doesn't, so a new route is private until someone marks it otherwise.
  "public"   marketing site and intake: served even with PUBLIC_SITE_ONLY
  "portal"   anonymous but part of the portal (logins, invites, webhooks):
             hidden while PUBLIC_SITE_ONLY is set
  "attorney" / "client"  a signed-in session with that role
"""

import functools
import hmac
import os

from flask import Response, redirect, request, session, url_for

ACCESS_ATTR = "_access"
CSRF_EXEMPT_ATTR = "_csrf_exempt"


def _mark(f, level):
    setattr(f, ACCESS_ATTR, level)
    return f


def public(f):
    """Anyone, including on the public-site-only deployment."""
    return _mark(f, "public")


def portal_public(f):
    """Anonymous portal pages: logins, invitation links, signed webhooks."""
    return _mark(f, "portal")


def csrf_exempt(f):
    """Skip the CSRF check: only for signature-verified webhooks and anonymous
    endpoints that act on no session."""
    setattr(f, CSRF_EXEMPT_ATTR, True)
    return f


def require_attorney(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "attorney":
            return redirect(url_for("auth.attorney_login"))
        return f(*args, **kwargs)
    return _mark(decorated, "attorney")


def require_client(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "client":
            return redirect(url_for("auth.client_login"))
        return f(*args, **kwargs)
    return _mark(decorated, "client")


# ── Share password ────────────────────────────────────────────────────────────

def share_password_challenge():
    """When SHARE_PASSWORD is set, a 401 Basic-Auth challenge unless this
    browser already passed it; None otherwise. app.py runs this before every
    route (webhooks excepted), so logins and portals are covered too. After
    the first success a session flag lets fetch() calls through."""
    password = os.getenv("SHARE_PASSWORD", "").strip()
    if not password or session.get("share_authed"):
        return None
    auth = request.authorization
    if not auth or not auth.password or not hmac.compare_digest(auth.password, password):
        return Response("Authentication required.", 401,
                        {"WWW-Authenticate": 'Basic realm="Law Office App"'})
    session["share_authed"] = True
    return None


def require_auth(f):
    """Kept as a marker on older routes; the check itself runs app-wide
    (share_password_challenge), so it also covers routes without it."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        challenge = share_password_challenge()
        return challenge if challenge is not None else f(*args, **kwargs)
    return decorated
