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
from dataclasses import dataclass
from itertools import accumulate

MAX_TEXT_UNITS = 4096
"""What one WhatsApp text message may hold, counted in UTF-16 code units."""

_RUN = re.compile(r"`{3,}")
_TAG = re.compile(r"[ \t]*(?:[\w+#-]+(?:\.[\w+#-]+)*)?[ \t]*(?=\n)")
"""What may follow an opening fence on its line: nothing, or one language tag - which
never ends in sentence punctuation, so "``` done." is prose, not a tag."""
_LINE_LEAD = re.compile(r"[ \t>]*(?:(?:[-*+]|\d+[.)])[ \t]+)?[ \t>]*")
"""What may stand before a closing fence on its line: indentation, quote marks, a list marker."""
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


@dataclass(frozen=True)
class _Code:
    """Code the model fenced: `text[start:end]`, from its first backtick to its last.

    `body` is what a block holds between its opening line and its closing marker;
    `None` marks a one-line fence ("```cmd```"), which is kept exactly as written.
    """

    start: int
    end: int
    body: str | None


def _code_spans(text: str) -> list[_Code]:
    """Every fence in `text`, paired in one left-to-right pass over the backtick runs.

    One pass, so an opener can never be taken for a closer and the words after it lost:
    - a run with another run later on its line is a one-line fence, kept as written;
    - a run followed on its line by nothing, or by one language tag, opens a block -
      wherever it stands on the line - which closes at the next run at least as long
      that starts its line (after indentation, quote marks or a list marker). Text
      after that closer stays, as prose; a run inside a line never closes a block, so
      code that quotes a fence stays code;
    - any other run (prose after it, or no closer anywhere) is a literal and stays.

    Nothing is consumed but the markers and a language tag, so no word is ever lost.
    """
    spans: list[_Code] = []
    position = 0
    while opener := _RUN.search(text, position):
        line_end = text.find("\n", opener.end())
        line_end = len(text) if line_end == -1 else line_end
        if (pair := _RUN.search(text, opener.end(), line_end)) is not None:
            spans.append(_Code(opener.start(), pair.end(), None))
            position = pair.end()
            continue
        closer = None
        if _TAG.match(text, opener.end()):
            closer = next(
                (
                    run
                    for run in _RUN.finditer(text, line_end + 1)
                    if len(run[0]) >= len(opener[0])
                    and _LINE_LEAD.fullmatch(
                        text, text.rfind("\n", 0, run.start()) + 1, run.start()
                    )
                ),
                None,
            )
        if closer is None:
            position = opener.end()
            continue
        spans.append(_Code(opener.start(), closer.end(), text[line_end + 1 : closer.start()]))
        position = closer.end()
    return spans


def to_whatsapp(markdown: str) -> str:
    """The answer in WhatsApp's own syntax; code, tables and URLs come through verbatim."""
    lifted: list[str] = []

    def lift(literal: str) -> str:
        lifted.append(literal)
        return f"\x00{len(lifted) - 1}\x00"

    text = markdown.replace("\x00", "").replace(_BOLD_MARK, "")
    pieces: list[str] = []
    done = 0
    for code in _code_spans(text):
        literal = (
            text[code.start : code.end] if code.body is None else f"```\n{code.body.rstrip()}\n```"
        )
        pieces += [text[done : code.start], lift(literal)]
        done = code.end
    text = "".join([*pieces, text[done:]])
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
    re.compile(r"\n[ \t]*\n(?:[ \t]*\n)*"),
    re.compile(r"(?P<keep>[.!?…][\"')\]]*)[ \t]+|\n"),
    re.compile(r"\s+"),
)
"""Where to cut, best first: a paragraph, a sentence or line end, then any whitespace.

`keep` is a sentence's closing punctuation, which stays with the chunk it ends."""


_FENCE_OPEN = "```\n"
_FENCE_CLOSE = "\n```"
_FENCE_ROOM = len(_FENCE_OPEN) + len(_FENCE_CLOSE)
"""What a cut inside a fence adds to a chunk: the closing fence, and the next one's reopening."""

_BLANK_LINES = re.compile(r"(?:[ \t]*\n)*")
_BLANKS = {
    (_BREAKS[0], True): _BLANK_LINES,
    (_BREAKS[1], True): _BLANK_LINES,
    (_BREAKS[1], False): re.compile(r"[ \t]*"),
    (_BREAKS[2], False): re.compile(r"[ \t]*(?:\n(?:[ \t]*\n)*)?"),
}
"""What a cut also skips past the match, by break and whether the match ended in a
newline: the blank lines or the spaces that follow it. The next line's own indentation
is never in it. A whitespace break never ends in a newline: a newline in the window
is the better break before it."""


def split_message(text: str, limit: int = MAX_TEXT_UNITS) -> list[str]:
    """The answer as messages of at most `limit` UTF-16 units, cut at the kindest spot.

    A paragraph break is preferred, then a sentence or line end, then any space,
    and only a word longer than the limit is cut hard - at a character boundary,
    never inside an emoji sequence. Only the whitespace a cut lands on is dropped, so
    no chunk is empty or starts with the whitespace it was cut at, and a chunk keeps its
    own indentation. A cut inside a fenced code block closes the fence at the end of the
    chunk and reopens it at the start of the next. Text that is
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
    # The same pairing `to_whatsapp` lifts a fence by, so every fence is judged as it
    # was converted. Below `_FENCE_ROOM` plus one character there is no room to keep a
    # fence whole.
    spans = (
        [(code.start, code.end) for code in _code_spans(text) if code.body is not None]
        if limit >= 2 + _FENCE_ROOM
        else []
    )
    if spans:
        limit -= _FENCE_ROOM
    ends = cluster_ends(text)
    prefix = [0, *accumulate(utf16_units(char) for char in text)]
    spans_by_start = {(a, 0) for a, _ in spans}
    ranges: list[tuple[int, int]] = []
    start = 0
    while prefix[-1] - prefix[start] > limit:
        fits = bisect_right(ends, prefix[start] + limit, key=lambda end: prefix[end])
        # A single "character" longer than the limit - thousands of stacked marks -
        # cannot be kept whole; cut it by code point rather than loop forever.
        reach = ends[fits - 1] if fits and ends[fits - 1] > start else start + limit // 2
        window = text[start : reach + 1]
        cut = resume = None
        # A chunk that begins at an opening fence must keep some of its body: a cut
        # right after the opener would leave the fence empty.
        floor = text.index("\n", start) + 1 - start if (start, 0) in spans_by_start else 0
        for pattern in _BREAKS:
            found = [m for m in pattern.finditer(window) if floor < m.start() <= reach - start]
            if found:
                last = found[-1]
                kept = last.end("keep") if "keep" in pattern.groupindex and last["keep"] else None
                cut = start + (kept if kept is not None else last.start())
                resume = start + last.end()
                # The window ends one character past the limit, so a long run of
                # blanks is only partly inside it.
                resume = next(_BLANKS[pattern, last[0][-1] == "\n"].finditer(text, resume)).end()
                break
        if cut is None or resume is None:
            cut = resume = reach
        fence = _fence_around(spans, cut)
        if fence and start < fence[0] and not text[fence[0] : cut].strip("`\n").strip():
            # The cut would leave an opening fence alone at the end of the chunk.
            cut = resume = fence[0]
        ranges.append((start, cut))
        start = resume
    if text[start:]:
        ranges.append((start, len(text)))
    # A leading blank run can be cut off alone; sending it would stop the answer there.
    ranges = [(a, b) for a, b in ranges if text[a:b].strip()]
    chunks = [_with_fences_whole(text, spans, a, b) for a, b in ranges]
    return [chunk for chunk in chunks if chunk.strip()]


def _fence_around(spans: list[tuple[int, int]], offset: int) -> tuple[int, int] | None:
    """The fence `offset` is inside of, not at its edge, or None."""
    index = bisect_right(spans, (offset, 0)) - 1
    return spans[index] if index >= 0 and spans[index][0] < offset < spans[index][1] else None


def _with_fences_whole(text: str, spans: list[tuple[int, int]], start: int, cut: int) -> str:
    """`text[start:cut]`, its code fence closed if the cut left it open and reopened if the
    chunk starts inside one.

    Only the markers added here come and go, with one exception: a chunk that would
    begin with nothing but a closing fence loses that marker, because the chunk
    before it was already closed. The words after it stay.
    """
    chunk = text[start:cut]
    opened = _fence_around(spans, start)
    if opened:
        marker = opened[1] - len("```")
        if not text[start:marker].strip():
            chunk = text[start:marker] + text[opened[1] : cut].lstrip(" \t").removeprefix("\n")
            closing = _fence_around(spans, cut)
            return f"{chunk}{_FENCE_CLOSE}" if closing and closing != opened else chunk
        chunk = f"{_FENCE_OPEN}{chunk}"
    return f"{chunk}{_FENCE_CLOSE}" if _fence_around(spans, cut) else chunk
