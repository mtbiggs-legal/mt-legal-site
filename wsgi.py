"""wsgi.py — production entry point: gunicorn wsgi:application

Serves the public site on every host, and the portals on PORTAL_URL's host
(for example portal.midtennlegal.com), from one process on one data disk.
Each is a separate Flask app (app.create_app) with its own routes and its own
session cookie: nothing from the portal is registered on the public site.
Without PORTAL_URL only the public site is served.
"""

import os
from urllib.parse import urlsplit

# Tell app.py (while it is first imported) not to do its own `gunicorn app:app`
# startup; this file does it below.
os.environ["MTL_WSGI"] = "1"
try:
    import app as app_module  # noqa: E402
finally:
    os.environ.pop("MTL_WSGI", None)
import shared  # noqa: E402

public_app = app_module.create_app("public")
portal_app = app_module.create_app("portal") if shared.PORTAL_URL else None
PORTAL_HOST = (urlsplit(shared.PORTAL_URL).hostname or "").lower() if shared.PORTAL_URL else ""


def application(environ, start_response):
    # The Host header names the domain the request was sent to. Not
    # X-Forwarded-Host: a client can set that to anything.
    host = environ.get("HTTP_HOST") or ""
    host = host.split(",")[0].strip().split(":")[0].lower()
    target = portal_app if portal_app is not None and host == PORTAL_HOST else public_app
    return target(environ, start_response)


if shared.IS_PRODUCTION:
    app_module.prepare_for_serving()
    app_module.start_background_jobs(public_app, include_local_only=False)
