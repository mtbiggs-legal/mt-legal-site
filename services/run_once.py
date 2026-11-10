"""services/run_once.py — make a job run in only one process per data disk.

claim(name) takes an exclusive, non-blocking lock on DATA_DIR/locks/<name>.lock
and keeps it for the life of the process. A second gunicorn worker (or a
second copy of the app on the same disk) gets False and skips the job. The
operating system releases the lock if the process dies.
"""

import os

import shared

_held: dict = {}


def claim(name: str) -> bool:
    if name in _held:
        return True
    folder = shared.DATA_ROOT / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    fh = open(folder / f"{name}.lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _held[name] = fh
    return True
