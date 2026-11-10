"""services/html_sanitize.py — reduce untrusted HTML to a small safe subset.

Used for anything stored as HTML that a client, an AI reply, or an uploaded
Word file produced: research memos, generated documents, DOCX previews.
Allowed tags keep their text structure; every attribute is dropped except a
checked href on <a>. Script, style and other active elements are removed
together with their content.
"""

from html import escape
from html.parser import HTMLParser

ALLOWED = frozenset({
    "p", "br", "hr", "strong", "b", "em", "i", "u", "s", "sub", "sup", "small",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "div", "span", "a",
})
VOID = frozenset({"br", "hr"})
# Dropped with everything inside them.
DROP_CONTENT = frozenset({"script", "style", "iframe", "object", "embed", "noscript",
                          "template", "svg", "math", "form", "textarea", "select",
                          "title", "head"})
SAFE_SCHEMES = ("http://", "https://", "mailto:")


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.open = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED:
            return
        extra = ""
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            if href.lower().startswith(SAFE_SCHEMES):
                extra = f' href="{escape(href, quote=True)}" rel="noopener noreferrer"'
        self.out.append(f"<{tag}{extra}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in self.open and tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED or tag in VOID or tag not in self.open:
            return
        while self.open:                 # close anything left open inside it
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))


def sanitize_html(html: str) -> str:
    p = _Sanitizer()
    p.feed(html or "")
    p.close()
    return "".join(p.out) + "".join(f"</{t}>" for t in reversed(p.open))


def html_document(title: str, body_html: str, meta: str = "") -> str:
    """A standalone page for a saved document: sanitized body, fixed styles."""
    return (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<title>{escape(title)}</title>"
        "<style>body{font-family:Georgia,serif;max-width:860px;margin:2rem auto;"
        "padding:1.5rem;line-height:1.7;color:#1a1a2e}h1,h2,h3{color:#1B2A4A}"
        "pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{border:1px solid #ccc;"
        "padding:.3rem .5rem}</style></head><body>"
        + (f"<p style='color:#888;font-size:.8rem;margin-bottom:2rem'>{escape(meta)}</p>" if meta else "")
        + sanitize_html(body_html) + "</body></html>"
    )
