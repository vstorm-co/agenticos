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

from app.services.rag._splitters import header_level
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

PLAIN_TEXT_FORMATS: frozenset[str] = frozenset(ext.lstrip(".") for ext in NATIVE_FORMATS - {".md"})
"""Formats the native parsers read as plain text, so a leading `#` is the file's own.

A licence banner in a `.txt` file is not a section, and a `.docx` file is read
as its paragraphs' text with no headings marked. Markdown is taken as written,
and the PDF parsers emit Markdown by default, so their `#` lines are headings.
A deployment that sets a PDF parser to plain-text output can have a `#` line
of its documents cited as a section.
"""

# A heading longer than this is not one a citation can carry, and bounding the
# line first keeps the scan linear in what is kept rather than in what a
# document put on its first line.
_MAX_HEADING_CHARS = 120
_MAX_LINE_CHARS = 4 * _MAX_HEADING_CHARS


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


def _heading_title(line: str) -> str:
    """A heading line's text without its opening and optional closing `#` run."""
    title = line.lstrip("#").strip()
    closed = title.rstrip("#")
    if closed != title and (not closed or closed[-1] in " \t"):
        title = closed.strip()
    return title


def _opens_inside_a_fence(content: str) -> bool:
    """Whether the chunk was cut from inside a fenced code block.

    The surrounding delimiter is not stored with a recursively split chunk,
    so an unmatched initial bare fence may be its closing line. Track the
    marker and length: shorter or differently marked lines inside a block do
    not close it. A longer closing run is ambiguous too - it may close an outer
    block started before this chunk, with the apparent opener being code.
    Ambiguous chunks cite the document alone, even if they were valid Markdown.
    """
    opened: tuple[str, int] | None = None
    first_bare: bool | None = None
    for raw in content.splitlines():
        line = raw.strip()
        if not line.startswith(("```", "~~~")):
            continue
        marker = line[0]
        length = len(line) - len(line.lstrip(marker))
        bare = length == len(line)
        if opened is None:
            if first_bare is None:
                first_bare = bare
            opened = (marker, length)
        elif bare:
            if marker != opened[0] or length > opened[1]:
                # A closing delimiter that does not belong to the visible
                # opener can belong to a block begun before this chunk.
                return True
            if length == opened[1]:
                opened = None
    return first_bare is True and opened is not None


def cited_heading(content: str) -> str | None:
    """The section heading a chunk opens with, or `None` when it does not open with one.

    A heading is what the Markdown splitter cuts at - `#`, `##` or `###` and a
    space - so a `#hashtag` or a `#### aside` is text. Only the headings on the
    chunk's first lines count: one further down titles text after the match,
    not the match. Of a stack of them, `# Guide` then `## Install`, the last is
    the section the text belongs to. A chunk cut from inside a fenced code
    block has none: its `#` lines are comments.

    Args:
        content: The matched chunk's text.

    Returns:
        The heading's text, without its `#` markers or control characters,
        with `"` turned to `'` so it cannot close the quotes a citation puts
        round it, and cut to a length a citation can carry.
    """
    if _opens_inside_a_fence(content):
        return None
    heading: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.lstrip()[:_MAX_LINE_CHARS].rstrip()
        if not line:
            if heading is None:
                continue
            break
        if header_level(line) is None:
            break
        heading = _heading_title(line) or heading
    if not heading:
        return None
    # Any whitespace is one space, so a tab or a no-break space still parts two
    # words; other characters that do not print are dropped.
    printable = "".join(c if c.isprintable() else " " if c.isspace() else "" for c in heading)
    title = " ".join(printable.split()).replace('"', "'")
    if not title:
        return None
    if len(title) > _MAX_HEADING_CHARS:
        return title[: _MAX_HEADING_CHARS - 1].rstrip() + "…"
    return title


def citation_locator(metadata: Mapping[str, object], content: str) -> str:
    """The part of a citation after the document's name: a page, a section, or nothing.

    A page for a paged format; otherwise, unless the format is plain text, the
    section heading the chunk opens with, when it opens with one; otherwise
    nothing, so the citation names the document alone.

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
    if _format_of(metadata) in PLAIN_TEXT_FORMATS:
        return ""
    heading = cited_heading(content)
    if heading is not None:
        return f', section "{heading}"'
    return ""


__all__ = [
    "PAGED_FORMATS",
    "PLAIN_TEXT_FORMATS",
    "citation_locator",
    "cited_heading",
    "cited_page",
]
