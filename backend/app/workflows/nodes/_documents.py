"""PDF and DOCX, read and rendered for the file steps - the untyped libraries behind one door.

`pymupdf` and `python-docx` ship no types, so every call into them is here and
answers in plain Python values. A document either opens or raises one of the
two errors below, never the parser's own exception, whose text is the
library's and not an explanation a reader of a run can act on.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pymupdf
from docx import Document


class DocumentCorrupt(ValueError):
    """The bytes do not open as the document they claim to be."""


class DocumentEncrypted(ValueError):
    """The document opens only with a password."""


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


def pdf_text(data: bytes) -> PdfText:
    document = _open_pdf(data)
    try:
        pages: list[str] = []
        scanned: list[int] = []
        for number in range(1, int(document.page_count) + 1):
            page = document[number - 1]
            text = str(page.get_text())
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


def docx_text(data: bytes) -> str:
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises anything a broken ZIP or XML can
        raise DocumentCorrupt("The Word document could not be opened") from exc
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
