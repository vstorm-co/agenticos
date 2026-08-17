"""The splitters that decide what a chunk is, and therefore what a search can find.

Written to replace `langchain-text-splitters`, which pulled `langchain-core`
and `langsmith` in behind it - a second hosted-telemetry SDK in a platform that
standardised on Logfire, for two classes and one method (#158).

:class:`RecursiveCharacterSplitter` is a port of that library's
`RecursiveCharacterTextSplitter` at 1.1.2, narrowed to the one configuration
the pipeline ever built: literal separators kept at the *start* of each piece,
`len` as the length function, whitespace stripped from every chunk. Two of its
behaviours read as bugs and are deliberate:

- **Chunks are joined with the empty string**, because `keep_separator` has
  already put the separator inside each piece. Joining with the separator
  instead - the obvious way to write it - doubles every one of them.
- **`chunk_overlap` is a ceiling, not a guarantee.** The merge pops from the
  front while the running total still exceeds the overlap *or* the next piece
  does not yet fit, so the realised overlap is "as much as fits" and is often
  less, sometimes nothing. A splitter that guaranteed the number would be a
  different splitter, and every collection already ingested was chunked by this
  one.

:class:`MarkdownHeaderSplitter` is not a port. It finds the same sections as
`MarkdownHeaderTextSplitter` - same header levels, same fenced-code-block
tracking, headers kept in the chunk - and then runs the recursive splitter over
each of them, which the library's version does not do. That is the fix for the
`markdown` strategy silently ignoring `chunk_size` and `chunk_overlap`, so a
50 KB section between two `##` became one chunk past the input limit of every
embedding model here.
"""

import logging
import re
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", " ", "")
"""Paragraph, line, word, character - the last resort splits between characters."""

_HEADER_MARKERS: tuple[tuple[str, int], ...] = (("###", 3), ("##", 2), ("#", 1))
"""Longest first, so `###` is never read as a `#` with two stray characters."""


class TextSplitter(Protocol):
    """What the ingestion pipeline asks of a splitter: text in, chunks out."""

    def split_text(self, text: str) -> list[str]: ...


def _split_keeping_separator(text: str, separator: str) -> list[str]:
    """Split on a literal separator, leaving it at the front of the piece that follows.

    The empty separator means "between every character", which is the recursion's
    last resort.
    """
    if not separator:
        return list(text)

    parts = re.split(f"({re.escape(separator)})", text)
    pieces = [parts[0]]
    pieces += [parts[i] + parts[i + 1] for i in range(1, len(parts), 2)]
    return [piece for piece in pieces if piece]


class RecursiveCharacterSplitter:
    """Split on the first separator present, recursing into pieces still too long.

    Args:
        chunk_size: The length no merged chunk may exceed.
        chunk_overlap: The most a chunk may repeat of the one before it.
        separators: Tried in order; the first one found in the text is used, and
            anything after it in the list is what an oversized piece recurses with.

    Raises:
        ValueError: If the sizes cannot produce chunks - a non-positive
            `chunk_size`, a negative `chunk_overlap`, or an overlap larger than
            the chunk it would be taken from.
    """

    def __init__(
        self,
        *,
        chunk_size: int,
        chunk_overlap: int,
        separators: Sequence[str] = DEFAULT_SEPARATORS,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be greater than 0, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap must not be negative, got {chunk_overlap}")
        if chunk_overlap > chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must not exceed chunk_size ({chunk_size})"
            )
        if not separators:
            raise ValueError("separators must not be empty")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = tuple(separators)

    def split_text(self, text: str) -> list[str]:
        """Chunk `text`, largest separator first."""
        return self._split(text, self.separators)

    def _split(self, text: str, separators: tuple[str, ...]) -> list[str]:
        separator = separators[-1]
        remaining: tuple[str, ...] = ()
        for index, candidate in enumerate(separators):
            if not candidate:
                separator = candidate
                break
            if candidate in text:
                separator = candidate
                remaining = separators[index + 1 :]
                break

        chunks: list[str] = []
        pending: list[str] = []
        for piece in _split_keeping_separator(text, separator):
            if len(piece) < self.chunk_size:
                pending.append(piece)
                continue
            if pending:
                chunks.extend(self._merge(pending))
                pending = []
            if remaining:
                chunks.extend(self._split(piece, remaining))
            else:
                logger.warning(
                    "Emitting a chunk of %d characters, longer than the configured %d: "
                    "no separator left to split it on",
                    len(piece),
                    self.chunk_size,
                )
                chunks.append(piece)
        if pending:
            chunks.extend(self._merge(pending))
        return chunks

    def _merge(self, pieces: list[str]) -> list[str]:
        """Accumulate pieces up to `chunk_size`, carrying the tail into the next chunk.

        The pieces already carry their separators, so they are joined with nothing.
        """
        chunks: list[str] = []
        current: list[str] = []
        total = 0
        for piece in pieces:
            length = len(piece)
            if current and total + length > self.chunk_size:
                joined = "".join(current).strip()
                if joined:
                    chunks.append(joined)
                while total > self.chunk_overlap or (
                    total > 0 and total + length > self.chunk_size
                ):
                    total -= len(current[0])
                    current = current[1:]
            current.append(piece)
            total += length

        joined = "".join(current).strip()
        if joined:
            chunks.append(joined)
        return chunks


def _header_level(line: str) -> int | None:
    """The ATX header level of a stripped line, or `None` if it is not a header.

    `#foo` is not a header and neither is `#### foo`: the marker has to be
    followed by a space or by nothing at all.
    """
    for marker, level in _HEADER_MARKERS:
        if line.startswith(marker) and (len(line) == len(marker) or line[len(marker)] == " "):
            return level
    return None


def _split_on_headers(text: str) -> list[str]:
    """Cut markdown into sections at `#`, `##` and `###`, keeping the header line.

    A `#` inside a fenced code block is content, not a heading - the one case a
    line scan gets wrong on any document carrying a shell snippet.

    Consecutive headers stay together: `# Title` immediately followed by
    `## Section` is one section, because a title on its own is a chunk that can
    never be retrieved for anything.
    """
    sections: list[str] = []
    blocks: list[str] = []
    block: list[str] = []
    stack: list[int] = []
    depth = 0
    fence = ""

    for raw_line in text.split("\n"):
        line = "".join(filter(str.isprintable, raw_line.strip()))

        if fence:
            if line.startswith(fence):
                fence = ""
            block.append(line)
            continue
        if line.startswith("```") and line.count("```") == 1:
            fence = "```"
            block.append(line)
            continue
        if line.startswith("~~~"):
            fence = "~~~"
            block.append(line)
            continue

        level = _header_level(line)
        if level is None:
            if line:
                block.append(line)
            elif block:
                blocks.append("\n".join(block))
                block = []
            continue

        if block:
            blocks.append("\n".join(block))
            block = []
        while stack and stack[-1] >= level:
            stack.pop()
        stack.append(level)

        continues = (
            bool(blocks) and len(stack) > depth and blocks[-1].rsplit("\n", 1)[-1].startswith("#")
        )
        depth = len(stack)
        if not continues and blocks:
            sections.append("  \n".join(blocks))
            blocks = []
        block = [line]

    if block:
        blocks.append("\n".join(block))
    if blocks:
        sections.append("  \n".join(blocks))
    return sections


class MarkdownHeaderSplitter:
    """Cut on headers first, then chunk each section like any other text.

    Args:
        chunk_size: The length no chunk may exceed, applied per section.
        chunk_overlap: The most a chunk may repeat of the one before it, within
            a section. Sections never overlap each other.
    """

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self._body = RecursiveCharacterSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split_text(self, text: str) -> list[str]:
        """Chunk `text`, never letting a chunk cross a header."""
        chunks: list[str] = []
        for section in _split_on_headers(text):
            chunks.extend(self._body.split_text(section))
        return chunks
