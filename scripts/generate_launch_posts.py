"""Write the four launch blog posts into the repo's blog_seed/ folder.

Usage:
    python scripts/generate_launch_posts.py --dry-run
    python scripts/generate_launch_posts.py

Uses the ANTHROPIC_API_KEY from .env to write one post for each of the first
four areas in the rotation (criminal defense, stablecoins, civil rights, estate
planning), in the formats article, qa, tips, article. Each post is saved as
blog_seed/posts/<slug>.json with status "published", and its topic is marked
used in blog_seed/topics.json. Nothing is written until all four posts have
been generated, and nothing is ever written to the live data folder.

--dry-run makes no API call and writes nothing; it prints the plan.

Afterwards, read and edit the posts, then commit them. They go live on the next
deploy (blog.seed_from_repo copies posts the server doesn't have yet).
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    # Only when run as a script (importing it in a test must not read the real
    # .env), and before importing shared, which reads the key at import.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

from services import blog         # noqa: E402
from services import blog_writer  # noqa: E402
import shared       # noqa: E402
from services.storage import read_json, write_json  # noqa: E402

COUNT = 4
FORMATS = ("article", "qa", "tips", "article")


def _slug(title, taken):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70].strip("-") or "post"
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _plan(topics):
    """(area, format, topic) for each launch post; topic is None if none are left."""
    plan = []
    for area, fmt in zip(blog.ROTATION[:COUNT], FORMATS):
        topic = next((t for t in topics if t.get("area") == area and not t.get("used")), None)
        plan.append((area, fmt, topic))
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan without calling the API or writing files")
    args = parser.parse_args(argv)

    seed = Path(shared.BLOG_SEED_DIR)
    posts_dir = seed / "posts"
    topics_path = seed / "topics.json"
    topics = read_json(topics_path, [])
    plan = _plan(topics)

    for area, fmt, topic in plan:
        print(f"{area:18} {fmt:8} {topic['title'] if topic else '(no unused topic)'}")
    if args.dry_run:
        print("Dry run: nothing generated or written.")
        return 0

    if posts_dir.is_dir() and any(posts_dir.glob("*.json")):
        print(f"Refusing to run: {posts_dir} already has post files. Delete them "
              "first if you really want to start over.", file=sys.stderr)
        return 1

    titles = []
    generated = []
    for area, fmt, topic in plan:
        try:
            data = blog_writer.generate_post(area, fmt, topic and topic["title"], list(titles))
        except blog_writer.BlogGenerationError as exc:
            print(f"Stopped: could not write the {area} post: {exc}", file=sys.stderr)
            print("Nothing was written. Run the script again.", file=sys.stderr)
            return 1
        titles.append(data["title"])
        generated.append(data)

    now = datetime.now()
    taken = {f.stem for f in posts_dir.glob("*.json")} if posts_dir.is_dir() else set()
    written = []
    for (area, fmt, topic), data in zip(plan, generated):
        post = blog.new_post(data["title"], data["summary"], data["body"], area, fmt,
                             topic_id=topic and topic["id"], now=now)
        post["slug"] = _slug(post["title"], taken)
        taken.add(post["slug"])
        post["status"] = "published"
        post["published_at"] = now.isoformat()
        path = posts_dir / f"{post['slug']}.json"
        write_json(path, post, ensure_ascii=False)
        written.append(path)
        if topic:
            for t in topics:
                if t.get("id") == topic["id"]:
                    t["used"] = True
    write_json(topics_path, topics, ensure_ascii=False)

    print("\nWrote these posts. Review and edit them, then commit:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
