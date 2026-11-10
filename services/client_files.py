"""services/client_files.py — the only way to read or write a client document.

Files under CLIENT_FILES_DIR/<username>/documents/<category>/ are encrypted
at rest with DATA_ENCRYPTION_KEY. An encrypted file starts with MAGIC followed
by a Fernet token; anything else is a legacy plaintext file, which is still
read (scripts/encrypt_client_files.py converts them).

Callers never open these paths themselves: write with write(), read with
read_bytes(), and serve with send(). Directory listings and file names stay as
they were, so the rest of the portal (live updates, listings) is unchanged.
"""

import io
import mimetypes
from pathlib import Path

from flask import send_file
from werkzeug.utils import secure_filename

from services import storage

MAGIC = b"MTLENC1\n"

# How a document may be shown inline from our own origin. PDFs and images
# render as themselves. HTML renders only inside a CSP sandbox with scripts,
# forms, plugins and network access off, so markup a client, an opposing
# party or an AI wrote can't act in the portal. Text shows as text/plain.
# Everything else is a download.
INLINE_SAFE = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
               ".bmp": "image/bmp"}
SANDBOXED_HTML = {".html", ".htm"}
TEXT_PREVIEW = {".txt", ".rtf"}
HTML_SANDBOX_CSP = ("sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
                    "frame-ancestors 'self'")


def is_encrypted(raw: bytes) -> bool:
    return raw.startswith(MAGIC)


def encrypt(payload: bytes) -> bytes:
    return MAGIC + storage.encrypt_bytes(payload)


def decrypt(raw: bytes) -> bytes:
    return storage.decrypt_bytes(raw[len(MAGIC):]) if is_encrypted(raw) else raw


def folder(username: str, category: str) -> Path:
    return storage._client_docs_dir(username, category)


def unique_path(username: str, category: str, filename: str) -> Path:
    safe = secure_filename(filename) or "document"
    d    = folder(username, category)
    dest = d / safe
    stem, suffix, n = Path(safe).stem, Path(safe).suffix, 2
    while dest.exists():
        dest = d / f"{stem}_{n}{suffix}"
        n += 1
    return dest


def write(username: str, category: str, filename: str, data: bytes,
          overwrite: bool = False) -> Path:
    """Encrypt and save a client document. Returns the path written (a
    numbered name when `filename` is taken, unless overwrite=True)."""
    dest = (folder(username, category) / (secure_filename(filename) or "document")) \
        if overwrite else unique_path(username, category, filename)
    storage._atomic_write(dest, encrypt(data))
    return dest


def write_path(dest: Path, data: bytes) -> Path:
    """Encrypt and save to a path already chosen under a client's documents."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    storage._atomic_write(dest, encrypt(data))
    return dest


def save_upload(upload, username: str, category: str) -> Path:
    """Store a Werkzeug FileStorage upload, encrypted."""
    return write(username, category, upload.filename, upload.read())


def read_bytes(path: Path) -> bytes:
    return decrypt(Path(path).read_bytes())


def read_text(path: Path) -> str:
    return read_bytes(path).decode("utf-8", errors="replace")


def plain_size(path: Path) -> int:
    """Approximate size of the document itself (within 16 bytes), worked out
    from the encrypted file's length so listings never decrypt anything."""
    try:
        size = Path(path).stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(len(MAGIC))
    except OSError:
        return 0
    if head != MAGIC:
        return size
    token = size - len(MAGIC)
    decoded = token * 3 // 4                  # urlsafe base64, padded
    # version(1) + timestamp(8) + IV(16) + HMAC(32) = 57; AES pads 1-16 bytes.
    return max(0, decoded - 57 - 8)


def _bytes_response(data: bytes, mimetype: str, name: str, attachment: bool):
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=attachment,
                     download_name=name)


def send(path: Path, as_attachment: bool = True, download_name: str = None):
    """Serve a client document (decrypted). See INLINE_SAFE above for what
    may be shown inline; the preview pane frames it, so it may be framed by
    our own pages only."""
    path = Path(path)
    name = download_name or path.name
    ext  = path.suffix.lower()
    data = read_bytes(path)
    if as_attachment:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        resp = _bytes_response(data, mime, name, True)
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    elif ext in INLINE_SAFE:
        resp = _bytes_response(data, INLINE_SAFE[ext], name, False)
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    elif ext in SANDBOXED_HTML:
        resp = _bytes_response(data, "text/html; charset=utf-8", name, False)
        resp.headers["Content-Security-Policy"] = HTML_SANDBOX_CSP
    elif ext in TEXT_PREVIEW:
        resp = _bytes_response(data, "text/plain; charset=utf-8", name, False)
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'self'"
    else:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        resp = _bytes_response(data, mime, name, True)
        resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"   # set before the app-wide DENY default
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def send_html(html: str, title: str = "Preview"):
    """Serve generated HTML (e.g. a DOCX converted for preview) in the same sandbox."""
    from flask import make_response
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Content-Security-Policy"] = HTML_SANDBOX_CSP
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Cache-Control"] = "no-store"
    return resp
