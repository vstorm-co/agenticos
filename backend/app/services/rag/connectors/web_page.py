"""One HTML page reduced to what a crawl needs from it: its text, and where it links.

The ingestion pipeline has no HTML parser of its own - `.html` is routed only
when a collection uses LlamaParse - so the web connector hands it Markdown
rather than the page. That is also what makes a page's `content_hash` mean
something: a docs site stamps a build time, a CSP nonce or a session token into
its markup on every request, and a hash of the raw HTML would call every page
changed on every run and re-embed the whole site nightly. The text a reader
sees changes when the page does.

`html.parser` rather than a library, because what is needed is small - skip the
chrome, keep headings, lists and code blocks, collect `href`s - and a page is
read under a size ceiling the connector enforces before this ever sees it. It
never raises on malformed markup; it reads what it can.
"""

import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# Never text anyone reads. `nav` and `footer` are chrome repeated on every page,
# and indexing them makes every page of a site match a query about the menu -
# but their links are still followed, since a docs site's navigation is how its
# pages are found.
_SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "nav", "footer", "head"})
# Elements with no closing tag: `handle_endtag` never arrives for them, so they
# must not be pushed onto the stack that decides what is skipped.
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_BLOCKS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "li",
        "main",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
)
_HEADINGS = {f"h{level}": level for level in range(1, 7)}


@dataclass(frozen=True)
class ParsedPage:
    """What a page said, and what it asked a crawler to do with it.

    `links` are absolute, resolved against the page's own URL or its `<base>`,
    and not yet normalized or scoped - that is the connector's to decide.
    `index` and `follow` are the page's `<meta name="robots">`: a page that says
    `noindex` is not ingested, and one that says `nofollow` is not crawled
    through.
    """

    title: str | None
    markdown: str
    links: tuple[str, ...]
    index: bool
    follow: bool


def _joined(base: str, href: str) -> str | None:
    """`href` resolved against `base`, or `None` for one `urljoin` cannot parse.

    `http://[::1` is a link any page can carry, and `urljoin` answers it with a
    `ValueError` - which, uncaught, would let one author fail a whole crawl.
    """
    try:
        return urljoin(base, href)
    except ValueError:
        return None


class _PageReader(HTMLParser):
    """Accumulates Markdown lines and links in one pass over the markup."""

    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = url
        self._stack: list[str] = []
        self._skipping = 0
        self._pre = 0
        self._pre_text: list[str] = []
        self._in_title = False
        self._title: list[str] = []
        # Two buffers because `<main>` is only known to exist once it opens: a
        # page with one says which part is the content, and one without it is
        # all content.
        self._all: list[str] = []
        self._main: list[str] = []
        self._in_main = 0
        self._line: list[str] = []
        self._prefix = ""
        self.links: list[str] = []
        self.index = True
        self.follow = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "base" and values.get("href"):
            self._base = _joined(self._base, values["href"]) or self._base
        elif tag == "meta" and values.get("name", "").lower() == "robots":
            directives = {part.strip().lower() for part in values.get("content", "").split(",")}
            if directives & {"noindex", "none"}:
                self.index = False
            if directives & {"nofollow", "none"}:
                self.follow = False
        elif (
            tag == "a"
            and values.get("href")
            and "nofollow" not in values.get("rel", "").lower().split()
            and (link := _joined(self._base, values["href"])) is not None
        ):
            self.links.append(link)
        if tag == "title":
            self._in_title = True
        if tag in _VOID:
            if tag == "br":
                self._flush()
            return
        self._stack.append(tag)
        if tag in _SKIPPED:
            self._skipping += 1
            return
        if tag in _HEADINGS:
            self._flush()
            self._prefix = "#" * _HEADINGS[tag] + " "
        elif tag == "li":
            self._flush()
            self._prefix = "- "
        elif tag == "pre":
            self._flush()
            self._pre += 1
        elif tag in _BLOCKS:
            self._flush()
        # After the flush, so the line before `<main>` opened stays outside it.
        if tag == "main":
            self._in_main += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _VOID or tag not in self._stack:
            return
        # Unwind to the matching open tag, so an unclosed `<p>` or `<li>` inside
        # it cannot leave a skip or a `<pre>` counted for the rest of the page.
        while (opened := self._stack.pop()) != tag:
            self._close(opened)
        self._close(tag)

    def _close(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skipping -= 1
            return
        if tag == "pre":
            self._pre -= 1
            if not self._pre:
                # One block, fenced whole: the lines of a code sample are joined
                # by newlines, where every other block is a paragraph apart.
                code = "".join(self._pre_text).strip("\n")
                self._pre_text = []
                if code.strip():
                    self._emit(f"```\n{code}\n```")
        elif tag in _HEADINGS or tag in _BLOCKS:
            self._flush()
        if tag == "main":
            self._in_main -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
            return
        if self._skipping:
            return
        if self._pre:
            self._pre_text.append(data)
            return
        self._line.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self._line).split())
        self._line = []
        # The prefix survives an empty flush: `<li><p>text` opens the paragraph
        # before any text arrives, and the item's marker belongs to that text.
        if text:
            self._emit(f"{self._prefix}{text}")
            self._prefix = ""

    def _emit(self, line: str) -> None:
        self._all.append(line)
        if self._in_main:
            self._main.append(line)

    def result(self) -> ParsedPage:
        self._flush()
        lines = self._main or self._all
        title = " ".join("".join(self._title).split()) or None
        return ParsedPage(
            title=title,
            markdown="\n\n".join(lines).strip(),
            links=tuple(self.links),
            index=self.index,
            follow=self.follow,
        )


def parse_page(html: str, url: str) -> ParsedPage:
    """Read `html`, fetched from `url`, into its text and its links."""
    reader = _PageReader(url)
    try:
        reader.feed(html)
        reader.close()
    except AssertionError:
        # `html.parser` raises this, not a parse error, on a marked section it
        # does not know (`<![foo[`). The page keeps what was read before it: a
        # malformed page may lose its own tail, never the rest of the crawl.
        logger.info("Stopped reading %s at markup html.parser refuses", url)
    return reader.result()
