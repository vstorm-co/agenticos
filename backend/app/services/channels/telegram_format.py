"""An agent's Markdown, as Telegram's HTML (#2068).

Telegram's own Markdown is two dialects, both strict: an unclosed `*`, an
underscore in a URL or a bracket in prose is a 400, and the reply was then sent
as plain text with every `**` showing. Its HTML mode needs only `<`, `>` and `&`
escaped, so the answer is converted rather than trusted: code first - fenced and
inline, kept verbatim inside `<pre>` and `<code>` - and then list bullets, bold,
italic, links and headings in the prose between them.
"""

import html
import re
from dataclasses import dataclass

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(
    r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])|(?<![_\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![_\w])"
)
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.M)
_BULLET = re.compile(r"^([ \t]*)[-*+][ \t]+(?:\[([ xX])\][ \t]+)?", re.M)


def _prose(text: str) -> str:
    """Escape prose, then turn its Markdown into the handful of tags Telegram knows."""
    escaped = html.escape(text, quote=False)
    # The URL is escaped already, with the rest of the prose; only a quote would
    # still end the attribute early.
    escaped = _LINK.sub(
        lambda m: f'<a href="{m.group(2).replace(chr(34), "&quot;")}">{m.group(1)}</a>', escaped
    )
    escaped = _HEADING.sub(r"<b>\1</b>", escaped)
    escaped = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", escaped)
    return _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", escaped)


def _with_inline_code(text: str) -> str:
    parts: list[str] = []
    last = 0
    for match in _INLINE_CODE.finditer(text):
        parts.append(_prose(text[last : match.start()]))
        parts.append(f"<code>{html.escape(match.group(1), quote=False)}</code>")
        last = match.end()
    parts.append(_prose(text[last:]))
    return "".join(parts)


# Not ☑: Telegram draws it as an emoji beside a text ☐, even with U+FE0E after it.
_MARKS = {None: "•", " ": "☐", "x": "☒", "X": "☒"}


def _bullets(text: str) -> str:
    """List markers as bullets: Telegram's HTML has no lists, and `- ` reads as a dash.

    A task list's `[ ]` and `[x]` become an empty and a crossed box.

    Done on whole lines before inline code is split out, where a segment can
    start mid-line and a dash after a code span would read as a line start.
    """
    return _BULLET.sub(lambda m: f"{m.group(1)}{_MARKS[m.group(2)]} ", text)


def to_telegram_html(markdown: str) -> str:
    """The answer as Telegram HTML: code verbatim, the prose's Markdown as tags."""
    parts: list[str] = []
    last = 0
    for match in _FENCE.finditer(markdown):
        parts.append(_with_inline_code(_bullets(markdown[last : match.start()])))
        parts.append(f"<pre>{html.escape(match.group(1).rstrip(), quote=False)}</pre>")
        last = match.end()
    parts.append(_with_inline_code(_bullets(markdown[last:])))
    return "".join(parts)


TELEGRAM_TEXT_LIMIT = 4096
"""The most Telegram takes in one message: UTF-16 units of the text after parsing."""

_TAG = re.compile(r"<[^>]+>")


def _units(text: str) -> int:
    """Length as Telegram counts it: a character outside the basic plane is two."""
    return len(text.encode("utf-16-le")) // 2


def _fits(markdown: str, limit: int) -> bool:
    # The Markdown is checked too: it is what is sent when Telegram refuses the HTML.
    if _units(markdown) > limit:
        return False
    return _units(html.unescape(_TAG.sub("", to_telegram_html(markdown)))) <= limit


@dataclass(frozen=True)
class _Fence:
    start: int
    end: int
    opener: str


def _fences(markdown: str, limit: int) -> list[_Fence]:
    """The fences a cut could reopen: one whose opening line is too long to repeat is text."""
    found: list[_Fence] = []
    for match in _FENCE.finditer(markdown):
        opener = markdown[match.start() : markdown.index("\n", match.start()) + 1]
        if len(opener) <= limit // 4:
            found.append(_Fence(match.start(), match.end(), opener))
    return found


def _inside(fences: list[_Fence], cut: int) -> _Fence | None:
    for fence in fences:
        if fence.start >= cut:
            break
        if cut < fence.end:
            return fence
    return None


def _piece(markdown: str, fences: list[_Fence], cut: int) -> str:
    """The text before `cut`, with a fence it leaves open closed."""
    head = markdown[:cut]
    if _inside(fences, cut) is None:
        return head
    return head + ("```" if head.endswith("\n") else "\n```")


def _cut(markdown: str, fences: list[_Fence], limit: int) -> int:
    """Where the first piece ends: at a newline, else a space, else wherever it must."""
    low, high = 1, min(len(markdown), limit)
    while low < high:
        middle = (low + high + 1) // 2
        if _fits(_piece(markdown, fences, middle), limit):
            low = middle
        else:
            high = middle - 1
    head = markdown[:low]
    for separator in ("\n", " "):
        at = head.rfind(separator)
        if at > low // 2:
            low = at + 1
            break
    fence = _inside(fences, low)
    if fence is not None and low < fence.start + len(fence.opener) and fence.start > 0:
        # A cut inside a fence's opening line moves to before the fence.
        low = fence.start
    return low


def telegram_pieces(markdown: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """The answer as Markdown pieces that each fit one Telegram message.

    Each piece fits as HTML and as plain text, so either can be sent. A piece
    cut inside a code fence closes it, and the next piece opens it again with
    the same language, so both render as code. None is empty.
    """
    pieces: list[str] = []
    rest = markdown
    while rest.strip():
        if _fits(rest, limit):
            pieces.append(rest)
            break
        fences = _fences(rest, limit)
        cut = _cut(rest, fences, limit)
        fence = _inside(fences, cut)
        pieces.append(_piece(rest, fences, cut).rstrip())
        tail = rest[cut:]
        # Reopened only when that still makes progress through the text.
        if fence is not None and cut > len(fence.opener):
            rest = fence.opener + tail
        else:
            rest = tail.lstrip("\n")
    return [piece for piece in pieces if piece.strip()]
