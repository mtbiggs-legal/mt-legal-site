"""Remove an attorney's two-factor setup (lost phone). The next sign-in asks
them to set up an authenticator app again, and signs out every open session.

    python scripts/reset_attorney_2fa.py Endocide
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # this project's own only

import shared  # noqa: E402
from services import security, two_factor  # noqa: E402


def main(argv) -> int:
    if len(argv) != 2 or argv[1] not in shared.ATTORNEYS:
        print(__doc__)
        return 2
    username = argv[1]
    if two_factor.reset(username):
        security.bump_session_version("attorney", username)
        print(f"Two-factor sign-in reset for {username}. Open sessions were signed out.")
    else:
        print(f"{username} had no two-factor setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
