"""An agent's Markdown, as Telegram's HTML (#2068).

Telegram's own Markdown is two dialects, both strict: an unclosed `*`, an
underscore in a URL or a bracket in prose is a 400, and the reply was then sent
as plain text with every `**` showing. Its HTML mode needs only `<`, `>` and `&`
escaped, so the answer is converted rather than trusted: code first - fenced and
inline, kept verbatim inside `<pre>` and `<code>` - and then bold, italic, links
and headings in the prose between them.
"""

from __future__ import annotations

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
