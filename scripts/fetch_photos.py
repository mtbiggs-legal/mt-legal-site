"""Search Pexels for replacement photography. Prints candidates; downloads nothing.

Downloading is a deliberate second step (--download) so images are never written
to static/images/ without someone having looked at them first.

Usage:
    python scripts/fetch_photos.py "nashville architecture" --n 8
    python scripts/fetch_photos.py --download <photo_id> --as hero-home.jpg
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# Photographer names and captions contain non-Latin-1 characters; the Windows
# console defaults to cp1252 and would crash on them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "static" / "images"


def _key():
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        sys.exit("PEXELS_API_KEY is not set in .env")
    return key


def search(query, n):
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": _key()},
        params={"query": query, "per_page": n, "orientation": "landscape"},
        timeout=20,
    )
    resp.raise_for_status()
    for photo in resp.json().get("photos", []):
        print(f"{photo['id']:>10}  {photo['width']}x{photo['height']}  "
              f"by {photo['photographer']}")
        print(f"            {photo.get('alt') or '(no description)'}")
        print(f"            preview: {photo['src']['medium']}")


def download(photo_id, filename):
    resp = requests.get(
        f"https://api.pexels.com/v1/photos/{photo_id}",
        headers={"Authorization": _key()},
        timeout=20,
    )
    resp.raise_for_status()
    photo = resp.json()
    url = photo["src"]["large2x"]

    data = requests.get(url, timeout=60).content
    if data[:2] != b"\xff\xd8":
        sys.exit(f"{url} did not return a JPEG — refusing to save")

    dest = IMAGES_DIR / filename
    dest.write_bytes(data)
    print(f"saved {dest}  ({len(data) // 1024} KB)  "
          f"credit: {photo['photographer']} / Pexels")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("query", nargs="?", help="search terms")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--download", metavar="PHOTO_ID")
    p.add_argument("--as", dest="filename", metavar="FILENAME")
    a = p.parse_args()

    if a.download:
        if not a.filename:
            sys.exit("--download requires --as <filename>")
        download(a.download, a.filename)
    elif a.query:
        search(a.query, a.n)
    else:
        p.error("give a search query, or --download with --as")
