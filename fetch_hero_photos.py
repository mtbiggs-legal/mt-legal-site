"""
fetch_hero_photos.py
--------------------
Downloads hero background photos from Unsplash and activates them in the app.

Usage:
    python fetch_hero_photos.py
"""

import urllib.request
import urllib.parse
import json
import os
import re
import pathlib

BASE_URL   = "https://api.unsplash.com"
STATIC_DIR = pathlib.Path(__file__).parent / "static" / "images"
CSS_FILE   = pathlib.Path(__file__).parent / "static" / "css" / "style.css"

SEARCHES = [
    {
        "query":    "law office attorney professional",
        "filename": "hero-home.jpg",
        "css_key":  ".photo-hero--home",
        "label":    "Home page hero",
    },
    {
        "query":    "attorney client meeting consultation",
        "filename": "hero-intake.jpg",
        "css_key":  ".photo-hero--intake",
        "label":    "Intake page hero",
    },
]


def unsplash_search(access_key, query, per_page=5):
    params = urllib.parse.urlencode({
        "query":       query,
        "orientation": "landscape",
        "per_page":    per_page,
        "order_by":    "relevant",
    })
    url = f"{BASE_URL}/search/photos?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def show_results(results):
    photos = results.get("results", [])
    if not photos:
        print("  No results found.")
        return []
    print()
    for i, p in enumerate(photos):
        desc = p.get("alt_description") or p.get("description") or "(no description)"
        user = p["user"]["name"]
        print(f"  [{i+1}] {desc[:70]}")
        print(f"       by {user}  —  {p['urls']['small']}")
        print()
    return photos


def download_photo(photo, dest_path):
    url = photo["urls"]["full"]
    print(f"  Downloading full-resolution image…", end=" ", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "endo-legal-app/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest_path.write_bytes(resp.read())
    kb = dest_path.stat().st_size // 1024
    print(f"done ({kb} KB) → {dest_path}")


def activate_css(css_key, filename):
    """Uncomment the background-image line for the given hero section."""
    css = CSS_FILE.read_text(encoding="utf-8")

    # Match the commented-out background-image line inside the correct block
    pattern = (
        r'(/\*\s*background-image:\s*url\([\'"]?/static/images/'
        + re.escape(filename)
        + r'[\'"]?\);?\s*\*/)'
    )
    replacement = f"background-image: url('/static/images/{filename}');"
    new_css, count = re.subn(pattern, replacement, css)

    if count:
        CSS_FILE.write_text(new_css, encoding="utf-8")
        print(f"  CSS activated: background-image for {css_key}")
    else:
        print(f"  (CSS line already active or not found — check style.css manually)")


def main():
    print("=" * 60)
    print("  Endo-Legal Hero Photo Fetcher — powered by Unsplash")
    print("=" * 60)
    print()
    print("Paste your Unsplash Access Key and press Enter:")
    access_key = input("  > ").strip()
    if not access_key:
        print("No key entered. Exiting.")
        return

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    for job in SEARCHES:
        print()
        print(f"── {job['label']} ──────────────────────────────")
        print(f"  Searching Unsplash for: \"{job['query']}\"")

        try:
            results = unsplash_search(access_key, job["query"])
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        photos = show_results(results)
        if not photos:
            continue

        dest = STATIC_DIR / job["filename"]
        if dest.exists():
            print(f"  File already exists: {dest}")
            overwrite = input("  Overwrite? [y/N] > ").strip().lower()
            if overwrite != "y":
                print("  Skipped.")
                continue

        print(f"  Which photo? (1–{len(photos)}, or press Enter for #1): ", end="")
        choice_raw = input().strip()
        try:
            choice = int(choice_raw) - 1 if choice_raw else 0
            if not (0 <= choice < len(photos)):
                choice = 0
        except ValueError:
            choice = 0

        selected = photos[choice]
        try:
            download_photo(selected, dest)
            activate_css(job["css_key"], job["filename"])
        except Exception as e:
            print(f"  ERROR downloading: {e}")
            continue

    print()
    print("=" * 60)
    print("  Done! Restart Flask (or it will reload automatically)")
    print("  if TEMPLATES_AUTO_RELOAD is enabled.")
    print("=" * 60)


if __name__ == "__main__":
    main()
