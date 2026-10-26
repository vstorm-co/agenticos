"""Where in its document a retrieved chunk came from, as a citation can say it (#2489).

Every stored chunk carries a `page_num`, but only some formats have pages. The
parsers that read Markdown, plain text and Word files return the whole file as
one page numbered 1, because the pipeline chunks page by page and needs one; the
number is structural, not a location. Handed to the model as "page 1", it was
cited as one - `[capabilities.pl.md, s. 1]` - a precision the citation does not
have.

So the page is decided here, from the document's format, when a result is shown
rather than when it is stored: `page_num` stays what ordering and small-to-big
expansion read, and a collection ingested before this change cites correctly
without being ingested again.
"""

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

PAGED_FORMATS: frozenset[str] = frozenset(
    {
        # A PDF, read page by page by every PDF parser.
        "pdf",
        # Word-processing and presentation formats the PDF parsers take, which
        # LiteParse converts to PDF and LlamaParse paginates, so a page or slide
        # number is one a reader can open. `.docx` is not here: the pipeline
        # always reads it with the native parser, which returns it as one page.
        "doc",
        "docm",
        "dot",
        "dotm",
        "dotx",
        "odt",
        "ott",
        "rtf",
        "pages",
        "ppt",
        "pptx",
        "pptm",
        "pot",
        "potm",
        "potx",
        "odp",
        "otp",
        "key",
    }
)
"""Formats whose stored `page_num` names a real page.

Everything else - Markdown, text, `.docx`, HTML, spreadsheets, CSV, images - is
cited without one. A spreadsheet's pages are an artefact of printing it, and an
image is a single page, so a number there would mislead as much as "page 1" of
a Markdown file does.
"""

_HEADING = re.compile(r"#{1,6}[ \t]+(?P<title>.+?)(?:[ \t]+#+)?[ \t]*")

_MAX_HEADING_CHARS = 120


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


def cited_heading(content: str) -> str | None:
    """The section heading a chunk opens with, or `None` when it does not open with one.

    A chunk the Markdown splitter cut starts at its section's heading, and a
    recursive chunk often does too. Only a heading on the chunk's first line is
    taken: a heading further down titles text after the match, not the match.

    Args:
        content: The matched chunk's text.

    Returns:
        The heading's text, without its `#` markers, cut to a length a citation
        can carry.
    """
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    match = _HEADING.fullmatch(first_line)
    if match is None:
        return None
    title = match.group("title").strip()
    if len(title) > _MAX_HEADING_CHARS:
        return title[: _MAX_HEADING_CHARS - 1].rstrip() + "…"
    return title


def citation_locator(metadata: Mapping[str, object], content: str) -> str:
    """The part of a citation after the document's name: a page, a section, or nothing.

    A page for a paged format; otherwise the section heading the chunk opens
    with, when it opens with one; otherwise nothing, so the citation names the
    document alone.

    Args:
        metadata: The stored chunk's metadata.
        content: The matched chunk's text - never an expanded passage, whose
            first line belongs to a neighbouring chunk.

    Returns:
        `", page 3"`, `', section "Install"'` or `""`.
    """
    page = cited_page(metadata)
    if page is not None:
        return f", page {page}"
    heading = cited_heading(content)
    if heading is not None:
        return f', section "{heading}"'
    return ""


__all__ = ["PAGED_FORMATS", "citation_locator", "cited_heading", "cited_page"]
