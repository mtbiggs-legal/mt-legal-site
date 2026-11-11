"""IndexNow: tell Bing (and through it ChatGPT search and Copilot), Yandex and
other participating search engines the moment a page changes, instead of
waiting for their next crawl. See https://www.indexnow.org.

The key is public by design: the engines confirm ownership by fetching
/<KEY>.txt from the site (served by blueprints/public.py).
"""

import json
import logging
import threading
import urllib.request
from urllib.parse import urlsplit

import shared

KEY = "8cedf94058eb4c252574e3cbce9128ca"
ENDPOINT = "https://api.indexnow.org/indexnow"

log = logging.getLogger(__name__)


def _live_site() -> str:
    """The public https site address, or "" locally and in tests (never ping then)."""
    site = shared.SITE_URL
    host = urlsplit(site).hostname or ""
    if not site.startswith("https://") or host in ("localhost", "127.0.0.1") or host.endswith((".test", ".localhost")):
        return ""
    return site


def _send(site: str, urls: list) -> None:
    body = json.dumps({
        "host": urlsplit(site).hostname,
        "key": KEY,
        "keyLocation": f"{site}/{KEY}.txt",
        "urlList": urls,
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("IndexNow accepted %d URL(s): HTTP %s", len(urls), resp.status)
    except Exception:
        # A missed ping only means the engines find the change on their next crawl.
        log.warning("IndexNow ping failed", exc_info=True)


def submit(paths: list) -> bool:
    """Announce changed site paths (e.g. "/blog/my-post") in the background.
    Returns False when nothing was sent because this isn't the live site."""
    site = _live_site()
    if not site or not paths:
        return False
    urls = [site + p for p in paths]
    threading.Thread(target=_send, args=(site, urls), daemon=True).start()
    return True
