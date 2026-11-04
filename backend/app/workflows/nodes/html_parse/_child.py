"""The parsing of `html.parse`, as a program the step runs in a child process.

The step cannot parse in its own process: soupsieve backtracks without
memoising, so a descendant selector such as `p div div` over a thousand nested
divs takes minutes, and a thread running it cannot be stopped. `_handler.py`
starts this file instead, under a wall-clock deadline and CPU and memory limits,
and kills it when the deadline passes.

Run as a script (`python _child.py`), it reads one JSON request from stdin -
`markup`, `selector`, `max_matches`, `base_url`, `max_chars` - writes the output
as one JSON object to stdout and exits; anything else it prints is nothing. It
imports nothing from `app.workflows`: this package's `__init__` registers the
node and would load the whole application into every child, so the file keeps to
bs4, soupsieve and the page reader the web connector shares
(`app.services.rag.web_page`, whose packages import nothing). It fetches nothing and
runs no script.

The limits live here because the parsing applies them; `_handler.py` re-exports
them and documents what each one bounds.
"""

import io
import json
import sys
import warnings
from collections.abc import Iterator
from itertools import islice
from typing import BinaryIO, Final
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from bs4.element import NavigableString, PageElement, Tag

from app.services.rag.web_page import parse_page

MAX_LINKS: Final = 500
MAX_HREF_CHARS: Final = 2048
MAX_LINK_TEXT_CHARS: Final = 500
MAX_TITLE_CHARS: Final = 500
MAX_MATCH_TEXT_CHARS: Final = 10_000
MAX_MATCH_HTML_CHARS: Final = 10_000
MAX_ATTRIBUTES: Final = 50
MAX_ATTRIBUTE_CHARS: Final = 2000

# How much of a page one anchor or one match may make the step look at. A page
# can nest ten thousand unclosed `<a>` inside each other, and each would
# otherwise walk everything after it.
MAX_ANCHORS_SCANNED: Final = 5000
MAX_ANCHOR_NODES: Final = 100
MAX_MATCH_NODES: Final = 2000

# Markup that opens with an XML declaration is read as markup like any other: bs4's
# warning about it says nothing a flow can act on. A filter, not a catch, so it
# holds wherever this runs.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Addresses a step further down the flow must never be handed as a link to follow.
_BLOCKED_SCHEMES: Final = frozenset({"javascript", "vbscript", "data"})


def _cut(value: str, limit: int) -> str:
    return value[:limit]


def _text(element: Tag, *, max_chars: int, max_nodes: int) -> str:
    """The element's stripped strings joined by spaces, as `get_text(" ", strip=True)`
    gives, from its first `max_nodes` descendants and at most `max_chars` of them.

    The strings counted are the ones `get_text` counts for this element: the text
    of a comment, a script or a style is left out of a `<div>`'s, and a `<script>`
    element's own text is its script.
    """
    kinds = element.interesting_string_types or Tag.MAIN_CONTENT_STRING_TYPES
    parts: list[str] = []
    size = 0
    for node in islice(element.descendants, max_nodes):
        if isinstance(node, NavigableString) and type(node) in kinds and (piece := node.strip()):
            parts.append(piece)
            size += len(piece) + 1
            if size > max_chars:
                break
    return " ".join(parts)[:max_chars]


def _outer_html(element: Tag, *, max_chars: int, max_nodes: int) -> str:
    """The element's markup cut at `max_chars`, serialised from no more than its
    first `max_nodes` descendants and `max_chars` of their text.

    The string that crosses the budget is cut before it is serialised, and keeps
    its parent so bs4 does not close every open tag on it; bs4 closes the tags
    still open where the walk ends.
    """

    def walk() -> Iterator[PageElement]:
        size = 0
        for node in islice(element.self_and_descendants, max_nodes):
            if not isinstance(node, NavigableString):
                yield node
                continue
            if len(node) > max_chars - size:
                cut = type(node)(node[: max_chars - size])
                cut.parent = node.parent
                yield cut
                return
            size += len(node)
            yield node
            if size >= max_chars:
                return

    return element.decode(iterator=walk())[:max_chars]


def _href(tag: Tag, base_url: str | None) -> str | None:
    href = str(tag["href"]).strip()
    if len(href) > MAX_HREF_CHARS:
        return None
    try:
        resolved = urljoin(base_url, href) if base_url else href
        scheme = urlsplit(resolved).scheme.lower()
    except ValueError:
        return None
    if scheme in _BLOCKED_SCHEMES or len(resolved) > MAX_HREF_CHARS:
        return None
    return resolved


def _links(soup: BeautifulSoup, base_url: str | None) -> tuple[list[dict[str, str]], bool]:
    anchors = soup.select("a[href]", limit=MAX_ANCHORS_SCANNED + 1)
    links: dict[str, dict[str, str]] = {}
    for tag in anchors[:MAX_ANCHORS_SCANNED]:
        href = _href(tag, base_url)
        if href is None or href in links:
            continue
        if len(links) == MAX_LINKS:
            return list(links.values()), True
        text = _text(tag, max_chars=MAX_LINK_TEXT_CHARS, max_nodes=MAX_ANCHOR_NODES)
        links[href] = {"href": href, "text": text}
    return list(links.values()), len(anchors) > MAX_ANCHORS_SCANNED


def _match(element: Tag) -> dict[str, object]:
    attributes: dict[str, str] = {}
    for name, value in islice(element.attrs.items(), MAX_ATTRIBUTES):
        joined = value if isinstance(value, str) else " ".join(value)
        attributes[name] = _cut(joined, MAX_ATTRIBUTE_CHARS)
    return {
        "text": _text(element, max_chars=MAX_MATCH_TEXT_CHARS, max_nodes=MAX_MATCH_NODES),
        "html": _outer_html(element, max_chars=MAX_MATCH_HTML_CHARS, max_nodes=MAX_MATCH_NODES),
        "attributes": attributes,
    }


def parse(
    markup: str,
    *,
    selector: str | None,
    max_matches: int,
    base_url: str | None,
    max_chars: int,
) -> dict[str, object]:
    """The page's title, text, links and matches, as `HtmlParseOutput`'s fields."""
    # A NUL is no character of a page: a browser reads it as U+FFFD, and a text
    # that carries one is refused by the database the output is stored in.
    markup = markup.replace("\x00", "�")
    page = parse_page(markup, base_url or "")
    # A file object, not the string: bs4 warns on a string that looks like an
    # address or a file name, and a short mail body can.
    soup = BeautifulSoup(io.StringIO(markup), "html.parser")
    links, links_truncated = _links(soup, base_url)
    elements = soup.select(selector) if selector else []
    return {
        "title": _cut(page.title, MAX_TITLE_CHARS) if page.title else None,
        "text": _cut(page.markdown, max_chars),
        "text_truncated": len(page.markdown) > max_chars,
        "links": links,
        "links_truncated": links_truncated,
        "matches": [_match(element) for element in elements[:max_matches]],
        "match_count": len(elements),
    }


def main(stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Answer the one request on `stdin` with the output on `stdout`."""
    request = json.load(stdin)
    output = parse(
        request["markup"],
        selector=request["selector"],
        max_matches=request["max_matches"],
        base_url=request["base_url"],
        max_chars=request["max_chars"],
    )
    stdout.write(json.dumps(output).encode("ascii"))


if __name__ == "__main__":  # pragma: no cover - the entry point of the child process
    main(sys.stdin.buffer, sys.stdout.buffer)
