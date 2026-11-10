"""services/docx_writer.py — plain text to a court-formatted Word document (.docx).

Drafts arrive as plain text, one paragraph per line. This lays them out the
way the firm files them, with no extra dependencies:

- Times New Roman 12 pt, 1-inch margins, page numbers centered in the footer.
- Court filings (a caption at the top, then a document title such as
  "MOTION TO SUPPRESS"): the caption is centered and single-spaced, the title
  and section headings are centered and bold, body paragraphs are justified
  and double-spaced with a half-inch first-line indent, and the signature
  block ("Respectfully submitted," onward, or a "____" signature line) is
  single-spaced and set to the right half of the page. CERTIFICATE OF SERVICE
  is a centered heading; its text is justified and single-spaced.
- Anything without a caption (letters, agreements, memos): justified,
  single-spaced, with space between paragraphs; all-caps headings centered.
- Letters (a "Dear ..." salutation near the top, no caption) open with the
  firm letterhead: the MT Legal logo, the office address, and the phone,
  email and website line over a thin gold rule. Filings, wills and other
  documents never get it.

Blank lines in the text are dropped: spacing comes from the layout, so a
draft looks the same however many blank lines the model put between sections.
"""

import io
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import shared

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "images" / "letterhead-logo.png"
LOGO_EMU = 777240                          # 0.85 inch square
GOLD, GRAY = "A89A78", "4A4F5A"

# Twentieths of a point ("twips"): 720 = 0.5 inch, 240 = single line.
SINGLE, DOUBLE = 240, 480
INDENT_FIRST = 720
SIGNATURE_LEFT = 4680                      # signature block starts 3.25" in

_TITLE_RE = re.compile(r"\b(MOTION|PETITION|ANSWER|COMPLAINT|NOTICE|RESPONSE|REPLY|BRIEF|MEMORANDUM|"
                       r"ORDER|AFFIDAVIT|STIPULATION|AGREEMENT|PLAN|WARRANT|REQUESTS?|INTERROGATORIES|"
                       r"SUBPOENA|DECLARATION|OBJECTION|CERTIFICATE)\b")
_ROMAN_HEADING = re.compile(r"^([IVXLC]+|[A-Z])\.\s+\S")
_NUMBERED = re.compile(r"^(\d+|[a-z])[.)]\s")


def _is_caps(s: str) -> bool:
    return s.isupper() and any(c.isalpha() for c in s)


def _is_heading(s: str) -> bool:
    """A section heading: short, on its own line, all capitals (or "I. ..." style)."""
    if len(s) > 90 or s.endswith((".", ",", ";", ":")) and not _ROMAN_HEADING.match(s):
        return False
    if _NUMBERED.match(s):
        return False
    return _is_caps(s) or bool(_ROMAN_HEADING.match(s) and _is_caps(re.sub(r"^\S+\s+", "", s)[:30]))


def layout(text: str) -> list:
    """[(line, kind)] with kind in caption, title, heading, body, signature, cert."""
    lines = [l.rstrip() for l in (text or "").replace("\r\n", "\n").split("\n")]
    lines = [l for l in lines if l.strip()]
    # A court filing has an all-caps document title within its first lines,
    # preceded by caption lines (court, parties, case number).
    title_at = next((i for i, l in enumerate(lines[:30])
                     if i > 0 and _is_caps(l.strip()) and _TITLE_RE.search(l.strip())
                     and not l.strip().startswith("IN THE")), None)
    filing = title_at is not None and any("COURT" in l.upper() for l in lines[:title_at])
    out, section = [], "body"
    for i, raw in enumerate(lines):
        s = raw.strip()
        if filing and i < title_at:
            out.append((s, "caption"))
        elif filing and i == title_at:
            out.append((s, "title"))
        elif s.upper().startswith("CERTIFICATE OF SERVICE") and len(s) < 40:
            section = "cert"
            out.append((s, "heading"))
        elif s.lower().startswith("respectfully submitted") or s.startswith("____") or s.startswith("/s/"):
            section = "signature"
            out.append((s, "signature"))
        elif section == "signature" and not _is_heading(s) and len(s) < 90:
            out.append((s, "signature"))
        elif _is_heading(s):
            section = "cert" if section == "cert" else "body"
            out.append((s, "heading"))
        else:
            if section == "signature":
                section = "body"
            out.append((s, "cert" if section == "cert" else ("body" if filing else "letter")))
    return out


def _ppr(kind: str) -> str:
    # keep: a heading or signature line stays on the same page as what follows it.
    def p(jc, line, before=0, after=0, first=0, left=0, keep=False):
        ind = ""
        if first or left:
            ind = f'<w:ind w:left="{left}" w:firstLine="{first}"/>'
        return (f'<w:pPr>{"<w:keepNext/>" if keep else ""}'
                f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="auto"/>'
                f'{ind}<w:jc w:val="{jc}"/></w:pPr>')
    return {
        "caption":   p("center", SINGLE),
        "court":     p("center", SINGLE, after=240),
        "title":     p("center", SINGLE, before=360, after=360, keep=True),
        "heading":   p("center", SINGLE, before=240, after=240, keep=True),
        "body":      p("both", DOUBLE, first=INDENT_FIRST),
        "cert":      p("both", SINGLE, after=240, first=INDENT_FIRST),
        "signature": p("left", SINGLE, left=SIGNATURE_LEFT, keep=True),
        "letter":    p("both", SINGLE, after=200),
        "letter-keep": p("both", SINGLE, after=200, keep=True),
        "accept":    p("both", SINGLE, before=360, after=200, keep=True),
        "address":   p("left", SINGLE, after=200),
    }[kind]


def _paragraph(text: str, kind: str, first_signature: bool, last_court: bool = False) -> str:
    court = kind == "caption" and _is_caps(text) and "COURT" in text.upper()
    bold = kind in ("title", "heading") or court
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    ppr = _ppr("court" if last_court else kind)
    if first_signature:                      # space above "Respectfully submitted,"
        ppr = ppr.replace('w:before="0"', 'w:before="360"', 1)
    t = escape(text.replace("\t", "    "))
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{t}</w:t></w:r></w:p>'


def is_letter(rows: list) -> bool:
    """A letter: no court caption, and a "Dear ..." salutation near the top."""
    if any(k in ("caption", "title") for _, k in rows):
        return False
    return any(l.lower().startswith("dear ") for l, _ in rows[:15])


_CLOSINGS = {"sincerely", "very truly yours", "respectfully", "best regards", "regards"}


def _letter_rows(rows: list) -> list:
    """Letter fixes: everything above the salutation ("VIA E-MAIL", the
    address, "Re:") sits flush left rather than being read as a heading, and
    the client's acceptance paragraph stays on the page with its signature line."""
    salutation = next(i for i, (l, _) in enumerate(rows) if l.lower().startswith("dear "))
    out = []
    for i, (line, kind) in enumerate(rows):
        if i < salutation:
            kind = "address"
        elif kind in ("letter", "signature") and line.upper().startswith("ACCEPTED"):
            kind = "accept"
        elif kind == "letter" and line.rstrip(",").lower() in _CLOSINGS:
            kind = "letter-keep"
        out.append((line, kind))
    return out


def letterhead_lines() -> list:
    """The address and contact lines under the logo, read from config at call time."""
    lines = []
    address = [p.strip() for p in (shared.FIRM_ADDRESS or "").split(";") if p.strip()]
    if address:
        lines.append(" · ".join(address))
    else:
        lines.append(shared.FIRM_CITY)
    contact = [shared.FIRM_PHONE_DISPLAY, shared.FIRM_EMAIL_DISPLAY, shared.FIRM_WEBSITE]
    lines.append(" · ".join(c for c in contact if c))
    return lines


def _letterhead_xml(with_logo: bool) -> str:
    parts = []
    if with_logo:
        e = LOGO_EMU
        parts.append(
            '<w:p><w:pPr><w:spacing w:after="80"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{e}" cy="{e}"/>'
            '<wp:docPr id="1" name="MT Legal logo" descr="MT Legal"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="1" name="letterhead-logo.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="rId3"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{e}" cy="{e}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    lines = letterhead_lines()
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        border = (f'<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="6" w:color="{GOLD}"/></w:pBdr>'
                  if last else "")
        parts.append(
            f'<w:p><w:pPr>{border}<w:spacing w:after="{480 if last else 0}"/><w:jc w:val="center"/></w:pPr>'
            f'<w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:color w:val="{GRAY}"/>'
            f'<w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>')
    return "".join(parts)


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="png" ContentType="image/png"/>
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
{logo}</Relationships>"""
_LOGO_REL = ('<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
             'relationships/image" Target="media/letterhead-logo.png"/>')

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults>
<w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="Times New Roman" w:cs="Times New Roman"/>
<w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
</w:styles>"""

_FOOTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:p><w:pPr><w:jc w:val="center"/></w:pPr>
<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>
</w:p></w:ftr>"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator></cp:coreProperties>"""

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def text_to_docx(title: str, text: str, creator: str = "", letterhead: bool | None = None) -> bytes:
    """A court-formatted .docx of `text` (one paragraph per line). Letters get
    the firm letterhead unless `letterhead` says otherwise."""
    parts, prev = [], None
    rows = layout(text)
    letter = is_letter(rows)
    if letter:
        rows = _letter_rows(rows)
    if letterhead is None:
        letterhead = letter
    logo = LOGO_PATH.read_bytes() if letterhead and LOGO_PATH.exists() else b""
    if letterhead:
        parts.append(_letterhead_xml(bool(logo)))
    # Space after the court's name: the last caption line naming the court.
    court_rows = [i for i, (l, k) in enumerate(rows) if k == "caption" and "COURT" in l.upper()]
    last_court = court_rows[-1] if court_rows else -1
    for i, (line, kind) in enumerate(rows):
        parts.append(_paragraph(line, kind, kind == "signature" and prev != "signature", i == last_court))
        prev = kind
    body = "".join(parts) or "<w:p/>"
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{_W}" xmlns:r="{_R}" xmlns:wp="{_WP}"><w:body>{body}'
                f'<w:sectPr><w:footerReference w:type="default" r:id="rId2"/>'
                f'<w:pgSz w:w="12240" w:h="15840"/>'
                f'<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
                f'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS.format(logo=_LOGO_REL if logo else ""))
        if logo:
            z.writestr("word/media/letterhead-logo.png", logo)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/footer1.xml", _FOOTER)
        z.writestr("docProps/core.xml", _CORE.format(title=escape(title or ""), creator=escape(creator or "")))
    return buf.getvalue()
