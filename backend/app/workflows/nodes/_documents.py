"""PDF and DOCX, read and rendered for the file steps - the untyped libraries behind one door.

PDF rendering uses `pymupdf`; Word text is streamed directly from its XML. Both
return plain Python values. A document either opens or raises one of the
errors below, never the parser's own exception, whose text is the library's and
not an explanation a reader of a run can act on.
"""

import io
import zipfile
from dataclasses import dataclass
from xml.parsers import expat

import pymupdf

from app.services.file_upload import safe_unzip


class DocumentCorrupt(ValueError):
    """The bytes do not open as the document they claim to be."""


class DocumentEncrypted(ValueError):
    """The document opens only with a password."""


class DocumentTooLarge(ValueError):
    """The document unpacks to more than a document may: a small file can hold a
    huge compressed part, and the parser would expand all of it in memory."""


class DocumentTextTooLong(ValueError):
    """The parser reached the step's text budget before reading the remaining pages."""


MAX_PDF_PAGES = 2_000


@dataclass(frozen=True)
class PdfText:
    pages: tuple[str, ...]
    # One-based numbers of the pages with no text layer and an image on them:
    # a scan, which only OCR could read.
    scanned_pages: tuple[int, ...]


def _open_pdf(data: bytes) -> pymupdf.Document:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError) as exc:
        raise DocumentCorrupt("The PDF could not be opened") from exc
    if document.needs_pass:
        document.close()
        raise DocumentEncrypted("The PDF is protected by a password")
    return document


def pdf_text(data: bytes, *, max_chars: int = 200_000) -> PdfText:
    document = _open_pdf(data)
    try:
        if int(document.page_count) > MAX_PDF_PAGES:
            raise DocumentTooLarge(f"The PDF has more than {MAX_PDF_PAGES} pages")
        pages: list[str] = []
        chars = 0
        scanned: list[int] = []
        for number in range(1, int(document.page_count) + 1):
            page = document[number - 1]
            text = str(page.get_text()).strip()
            chars += len(text) + (2 if pages else 0)
            if chars > max_chars:
                raise DocumentTextTooLong("The text exceeds the step's character limit")
            pages.append(text)
            if not text.strip() and page.get_images():
                scanned.append(number)
        return PdfText(pages=tuple(pages), scanned_pages=tuple(scanned))
    finally:
        document.close()


def pdf_page_sizes(data: bytes) -> tuple[tuple[float, float], ...]:
    """Every page's width and height in points - known before anything is drawn."""
    document = _open_pdf(data)
    try:
        if int(document.page_count) > MAX_PDF_PAGES:
            raise DocumentTooLarge(f"The PDF has more than {MAX_PDF_PAGES} pages")
        sizes: list[tuple[float, float]] = []
        for number in range(int(document.page_count)):
            rect = document[number].rect
            sizes.append((float(rect.width), float(rect.height)))
        return tuple(sizes)
    finally:
        document.close()


def pdf_page_png(data: bytes, *, page_number: int, dpi: int) -> tuple[bytes, int, int]:
    """One page (one-based) rendered as PNG, with the picture's width and height."""
    document = _open_pdf(data)
    try:
        pixmap = document[page_number - 1].get_pixmap(dpi=dpi)
        return bytes(pixmap.tobytes("png")), int(pixmap.width), int(pixmap.height)
    finally:
        document.close()


def docx_text(data: bytes, *, max_chars: int = 200_000) -> str:
    """Stream body paragraphs without constructing an OOXML DOM or an unbounded string."""
    try:
        validated = safe_unzip(data)
    except zipfile.BadZipFile as exc:
        raise DocumentCorrupt("The Word document could not be opened") from exc
    except ValueError as exc:
        raise DocumentTooLarge("The Word document unpacks to more than a document may") from exc
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    path: list[str] = []
    paragraph_depth: int | None = None
    text_depth: int | None = None
    seen_paragraph = False
    seen_body = False
    count = 0
    output = io.StringIO()

    def append(text: str) -> None:
        nonlocal count
        if count + len(text) > max_chars:
            raise DocumentTextTooLong("The Word text exceeds the step's character limit")
        output.write(text)
        count += len(text)

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal paragraph_depth, text_depth, seen_paragraph, seen_body
        path.append(name)
        if len(path) > 128:
            raise DocumentTooLarge("The Word XML is nested too deeply")
        if len(path) == 1 and name != word + "document":
            raise DocumentCorrupt("The Word document has no main document element")
        if path == [word + "document", word + "body"]:
            seen_body = True
        if name == word + "p" and path[:-1] == [word + "document", word + "body"]:
            if seen_paragraph:
                append("\n")
            seen_paragraph = True
            paragraph_depth = len(path)
        if paragraph_depth is None:
            return
        run_path = path[paragraph_depth:-1]
        if run_path not in ([word + "r"], [word + "hyperlink", word + "r"]):
            return
        if name == word + "t":
            text_depth = len(path)
        elif name in {word + "tab", word + "ptab"}:
            append("\t")
        elif name == word + "noBreakHyphen":
            append("-")
        elif name == word + "cr" or (
            name == word + "br" and attributes.get(word + "type", "textWrapping") == "textWrapping"
        ):
            append("\n")

    def end(_name: str) -> None:
        nonlocal paragraph_depth, text_depth
        if text_depth == len(path):
            text_depth = None
        if paragraph_depth == len(path):
            paragraph_depth = None
        path.pop()

    def characters(text: str) -> None:
        if text_depth is not None:
            append(text)

    def doctype(_name: str, _system: str | None, _public: str | None, _internal: int) -> None:
        raise DocumentCorrupt("Word XML must not declare a DTD")

    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = doctype
    try:
        with zipfile.ZipFile(validated) as archive:
            archive.getinfo("[Content_Types].xml")
            archive.getinfo("_rels/.rels")
            with archive.open("word/document.xml") as member:
                while chunk := member.read(64 * 1024):
                    parser.Parse(chunk, False)
                parser.Parse(b"", True)
    except (zipfile.BadZipFile, KeyError, expat.ExpatError) as exc:
        raise DocumentCorrupt("The Word document could not be opened") from exc
    if not seen_body:
        raise DocumentCorrupt("The Word document has no body")
    return output.getvalue()
