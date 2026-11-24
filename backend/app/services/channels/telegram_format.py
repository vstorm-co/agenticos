"""An agent's Markdown, as Telegram's HTML (#2068).

Telegram's own Markdown is two dialects, both strict: an unclosed `*`, an
underscore in a URL or a bracket in prose is a 400, and the reply was then sent
as plain text with every `**` showing. Its HTML mode needs only `<`, `>` and `&`
escaped, so the answer is converted rather than trusted: code first - fenced and
inline, kept verbatim inside `<pre>` and `<code>` - and then bold, italic, links
and headings in the prose between them.
"""

import html
import re

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(
    r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])|(?<![_\w])_(?!\s)([^_\n]+?)(?<!\s)_(?![_\w])"
)
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.M)


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


def to_telegram_html(markdown: str) -> str:
    """The answer as Telegram HTML: code verbatim, the prose's Markdown as tags."""
    parts: list[str] = []
    last = 0
    for match in _FENCE.finditer(markdown):
        parts.append(_with_inline_code(markdown[last : match.start()]))
        parts.append(f"<pre>{html.escape(match.group(1).rstrip(), quote=False)}</pre>")
        last = match.end()
    parts.append(_with_inline_code(markdown[last:]))
    return "".join(parts)


TELEGRAM_TEXT_LIMIT = 4096
"""The most characters Telegram takes in one message, counted after the HTML conversion."""


def _fits(markdown: str, limit: int) -> bool:
    # The Markdown is checked too: it is what is sent when Telegram refuses the HTML.
    return len(markdown) <= limit and len(to_telegram_html(markdown)) <= limit


def _open_fence(markdown: str, cut: int) -> tuple[int, str] | None:
    """The fence a cut at `cut` falls inside: its start and its opening line."""
    for match in _FENCE.finditer(markdown):
        if match.start() < cut < match.end():
            opener = markdown[match.start() : markdown.index("\n", match.start()) + 1]
            return match.start(), opener
    return None


def _piece(markdown: str, cut: int) -> str:
    """The text before `cut`, with a fence it leaves open closed."""
    head = markdown[:cut]
    if _open_fence(markdown, cut) is None:
        return head
    return head + ("```" if head.endswith("\n") else "\n```")


def _cut(markdown: str, limit: int) -> int:
    """Where the first piece ends: at a newline, else a space, else wherever it must."""
    low, high = 1, len(markdown)
    while low < high:
        middle = (low + high + 1) // 2
        if _fits(_piece(markdown, middle), limit):
            low = middle
        else:
            high = middle - 1
    head = markdown[:low]
    for separator in ("\n", " "):
        at = head.rfind(separator)
        if at > low // 2:
            low = at + 1
            break
    fence = _open_fence(markdown, low)
    if fence is not None and low < fence[0] + len(fence[1]) and fence[0] > 0:
        # A cut inside a fence's opening line moves to before the fence.
        low = fence[0]
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
        cut = _cut(rest, limit)
        fence = _open_fence(rest, cut)
        pieces.append(_piece(rest, cut).rstrip())
        tail = rest[cut:]
        # Reopened only when that still makes progress through the text.
        rest = fence[1] + tail if fence is not None and cut > len(fence[1]) else tail.lstrip("\n")
    return [piece for piece in pieces if piece.strip()]
