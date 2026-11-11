"""Announce every page in the live sitemap to IndexNow (Bing, Yandex, ...).

Run after a deploy that changes site pages. Blog posts announce themselves
when they're published, edited or taken down.

    python scripts/indexnow_submit.py                      # https://midtennlegal.com
    python scripts/indexnow_submit.py https://example.com  # another site address
"""

import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import indexnow  # noqa: E402

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def main() -> None:
    site = (sys.argv[1] if len(sys.argv) > 1 else "https://midtennlegal.com").rstrip("/")
    with urllib.request.urlopen(f"{site}/sitemap.xml", timeout=20) as resp:
        sitemap = resp.read().decode("utf-8", "replace")
    urls = _LOC.findall(sitemap)
    if not urls:
        sys.exit("The sitemap lists no pages.")
    print(f"Announcing {len(urls)} pages from {site}/sitemap.xml ...")
    indexnow._send(site, urls)
    print("Done. See the log line above for the engine's reply (200 or 202 means accepted).")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
