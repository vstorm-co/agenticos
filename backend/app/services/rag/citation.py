"""Where in its document a retrieved chunk came from, as a citation can say it (#2489).

Every stored chunk carries a `page_num`, but only some formats have pages. The
native parsers that read Markdown, plain text and `.docx` files return the whole
file as one page numbered 1, because the pipeline chunks page by page and needs one; the
number is structural, not a location. Handed to the model as "page 1", it was
cited as one - `[capabilities.pl.md, s. 1]` - a precision the citation does not
have.

So the page is decided here, from the document's format, when a result is shown
rather than when it is stored: `page_num` stays what ordering and small-to-big
expansion read, and a collection ingested before this change cites correctly
without being ingested again.
"""

from collections.abc import Mapping
from pathlib import PurePosixPath

from app.services.rag.config import LITEPARSE_PAGED_OFFICE_FORMATS, NATIVE_FORMATS

PAGED_FORMATS: frozenset[str] = frozenset(
    # A PDF, read page by page by every PDF parser, and the word-processing and
    # presentation formats LiteParse converts to PDF and LlamaParse paginates, so
    # a page or slide number is one a reader can open. `.docx` is not one: the
    # pipeline always reads it with the native parser, which returns one page.
    {"pdf"} | {ext.lstrip(".") for ext in LITEPARSE_PAGED_OFFICE_FORMATS - NATIVE_FORMATS}
)
"""Formats whose stored `page_num` names a real page.

Everything else - Markdown, text, `.docx`, HTML, spreadsheets, CSV, images - is
cited without one. A spreadsheet's pages are an artefact of printing it, and an
image is a single page, so a number there would mislead as much as "page 1" of
a Markdown file does.
"""


def _format_of(metadata: Mapping[str, object]) -> str:
    """The document's format as a lower-cased extension, from what the chunk stored."""
    filetype = metadata.get("filetype")
    if isinstance(filetype, str) and filetype:
        return filetype.lower().lstrip(".")
    filename = metadata.get("filename")
    if isinstance(filename, str):
        return PurePosixPath(filename).suffix.lower().lstrip(".")
    return ""


def cited_page(metadata: Mapping[str, object]) -> int | None:
    """The page a citation may name for this chunk, or `None` when it has none.

    Args:
        metadata: The stored chunk's metadata, as a search returns it.

    Returns:
        The stored `page_num` for a paged format, else `None` - including the
        `page_num` of 1 every Markdown, text and Word chunk carries, and a
        missing or zero page on a paged one.
    """
    if _format_of(metadata) not in PAGED_FORMATS:
        return None
    page = metadata.get("page_num")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        return None
    return page


def citation_locator(metadata: Mapping[str, object]) -> str:
    """The reliable location after a document's name, or nothing when unknown.

    A chunk does not retain its original section or code-fence context, so a
    leading hash line could be a code comment. Do not turn it into a section
    title: name the document alone when no real page is known.
    """
    page = cited_page(metadata)
    return "" if page is None else f", page {page}"
