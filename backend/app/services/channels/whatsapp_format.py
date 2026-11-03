"""An agent's Markdown as WhatsApp text, and the answer cut to its message limit (#2076).

WhatsApp draws `*bold*`, `_italic_`, `~strike~`, fenced and inline code, `- ` lists
and `> ` quotes, and nothing else: no headings, link text or tables. The answer is
converted rather than trusted. Code, tables and URLs are lifted out first and put
back untouched, because a URL full of `_` and `*` - the link invitation is one -
must survive character for character.
"""

import re
import unicodedata
from bisect import bisect_right
from itertools import accumulate

MAX_TEXT_UNITS = 4096
"""What one WhatsApp text message may hold, counted in UTF-16 code units."""

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_TABLE = re.compile(r"(?:^[ \t]*\|.*\|[ \t]*\n?){2,}", re.M)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_URL = re.compile(r"https?://[^\s<>()]+")
_URL_TAIL = "*_.,;:!?'\""
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", re.M)
_BOLD = re.compile(r"\*\*(.+?)\*\*|(?<!\w)__(.+?)__(?!\w)")
_STRIKE = re.compile(r"~~(.+?)~~")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])")
_BULLET = re.compile(r"^([ \t]*)[*+][ \t]+", re.M)

_BOLD_MARK = "\x01"
"""Stands for a converted bold `*`, so the italic pass cannot take it for an emphasis."""


def utf16_units(text: str) -> int:
    """How many UTF-16 code units `text` is - the unit WhatsApp's limit is counted in."""
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def to_whatsapp(markdown: str) -> str:
    """The answer in WhatsApp's own syntax; code, tables and URLs come through verbatim."""
    lifted: list[str] = []

    def lift(literal: str) -> str:
        lifted.append(literal)
        return f"\x00{len(lifted) - 1}\x00"

    text = markdown.replace("\x00", "").replace(_BOLD_MARK, "")
    text = _FENCE.sub(lambda m: lift(f"```\n{m.group(1).rstrip()}\n```"), text)
    text = _INLINE_CODE.sub(lambda m: lift(m.group(0)), text)
    text = _TABLE.sub(lambda m: lift(f"```\n{m.group(0).strip()}\n```") + "\n", text)
    text = _LINK.sub(
        lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})", text
    )
    # Like a GFM autolink, the URL stops before markup or punctuation that ends it:
    # `**https://x.y**` and "see https://x.y." are not part of the address.
    text = _URL.sub(
        lambda m: (
            lift(m.group(0).rstrip(_URL_TAIL)) + m.group(0)[len(m.group(0).rstrip(_URL_TAIL)) :]
        ),
        text,
    )

    text = _HEADING.sub(lambda m: f"**{m.group(1).replace('**', '')}**", text)
    text = _BULLET.sub(r"\1- ", text)
    text = _BOLD.sub(lambda m: f"{_BOLD_MARK}{m.group(1) or m.group(2)}{_BOLD_MARK}", text)
    text = _STRIKE.sub(lambda m: f"~{m.group(1)}~", text)
    text = _ITALIC.sub(lambda m: f"_{m.group(1)}_", text)
    text = text.replace(_BOLD_MARK, "*")

    # A later literal can hold an earlier placeholder (a table with inline code).
    for index in reversed(range(len(lifted))):
        text = text.replace(f"\x00{index}\x00", lifted[index])
    return text


def cluster_ends(text: str) -> list[int]:
    """Offsets where a user-perceived character ends, so a cut never lands inside one.

    The cases that matter in an answer: combining marks and variation selectors,
    emoji skin tones, zero-width-joiner sequences (a family), tag sequences (a
    subdivision flag), keycaps and regional-indicator pairs (a country flag).
    """
    ends: list[int] = []
    regional = 0
    for index, char in enumerate(text):
        code = ord(char)
        if index == 0:
            joins = False
        else:
            previous = text[index - 1]
            joins = (
                previous == "\u200d"
                or char in "\u200c\u200d"
                or unicodedata.category(char) in {"Mn", "Me", "Mc"}
                or 0x1F3FB <= code <= 0x1F3FF
                or 0xE0020 <= code <= 0xE007F
                or (0x1F1E6 <= code <= 0x1F1FF and regional % 2 == 1)
            )
        regional = regional + 1 if 0x1F1E6 <= code <= 0x1F1FF else 0
        if joins and ends:
            ends[-1] = index + 1
        else:
            ends.append(index + 1)
    return ends


_BREAKS = (
    re.compile(r"\n[ \t]*\n\s*"),
    re.compile(r"(?P<keep>[.!?…][\"')\]]*)[ \t]+|\n"),
    re.compile(r"\s+"),
)
"""Where to cut, best first: a paragraph, a sentence or line end, then any whitespace.

`keep` is a sentence's closing punctuation, which stays with the chunk it ends."""


def split_message(text: str, limit: int = MAX_TEXT_UNITS) -> list[str]:
    """The answer as messages of at most `limit` UTF-16 units, cut at the kindest spot.

    A paragraph break is preferred, then a sentence or line end, then any space,
    and only a word longer than the limit is cut hard - at a character boundary,
    never inside an emoji sequence. Only the whitespace a cut lands on is dropped, so
    no chunk is empty or starts with the whitespace it was cut at. Text that is
    empty once stripped gives no chunks: there is nothing to send.

    Raises:
        ValueError: If `limit` is under 2, too small to hold one astral character.
    """
    if limit < 2:
        raise ValueError("limit must hold at least one character (2 UTF-16 units)")
    if not text.strip():
        return []
    if utf16_units(text) <= limit:
        return [text]
    ends = cluster_ends(text)
    prefix = [0, *accumulate(utf16_units(char) for char in text)]
    chunks: list[str] = []
    start = 0
    while prefix[-1] - prefix[start] > limit:
        fits = bisect_right(ends, prefix[start] + limit, key=lambda end: prefix[end])
        # A single "character" longer than the limit - thousands of stacked marks -
        # cannot be kept whole; cut it by code point rather than loop forever.
        reach = ends[fits - 1] if fits and ends[fits - 1] > start else start + limit // 2
        window = text[start : reach + 1]
        cut = resume = None
        for pattern in _BREAKS:
            found = [m for m in pattern.finditer(window) if 0 < m.start() <= reach - start]
            if found:
                last = found[-1]
                kept = last.end("keep") if "keep" in pattern.groupindex and last["keep"] else None
                cut = start + (kept if kept is not None else last.start())
                resume = start + last.end()
                break
        if cut is None or resume is None:
            cut = resume = reach
        chunks.append(text[start:cut])
        start = resume
        while start < len(text) and text[start].isspace():
            start += 1
    if text[start:]:
        chunks.append(text[start:])
    # A leading blank run can be cut off alone; sending it would stop the answer there.
    return [chunk for chunk in chunks if chunk.strip()]
