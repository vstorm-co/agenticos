"""Website sync connector: a docs site, crawled from a start URL or read from its sitemap.

The first connector with `SecretKind.NONE`: a public site needs no credential,
so there is no vault entry to scope and nothing but the URL decides the reach.
That makes the URL the thing to be careful with. A tenant types the start URL,
and every link followed from it is chosen by whoever wrote the page, so every
request - robots.txt, the sitemap, each page and each redirect hop - goes
through `PinnedAsyncClient`, which refuses a private, loopback, link-local or
metadata address and dials the address it approved rather than resolving the
name a second time (#840, #860). A redirect is followed only while it stays on
the start URL's host and under the configured path.

What bounds a crawl, because "follow every link" ends at the end of the internet:
a link depth, a page ceiling, one host, a path prefix, robots.txt and its
`Crawl-delay`, a minimum interval between requests, a size ceiling per page, and
a time limit on the whole sync. An `https://` start URL is never left for
`http://`: a link or a redirect that would downgrade is not followed, because
a cleartext page is one anybody on the path can write into the collection.

**The change signal is the page's text.** A page is fetched to find its links,
so there is no transfer to save in a crawl, and the sync path compares a
`content_hash` of what `_fetch` wrote (#990). What it writes is Markdown
extracted from the page (`web_page.parse_page`), not the HTML: markup carries
build stamps and nonces that change on every request, and hashing them would
re-embed an unchanged site on every run. `ETag` and `Last-Modified` would save
the transfer in sitemap mode; the flow has nowhere to keep them between runs, so
they are not read.

**A listing is complete only when nothing stopped it.** The sync removes pages
it brought in earlier and no longer lists, so a crawl that hit its ceiling, or
could not read a page, says `complete=False` and nothing is removed that run -
see `RemoteListing`.

One instance serves one sync: it keeps the site's robots.txt, the request pacing
and the text of the pages the crawl already read, so `_fetch` does not read each
page a second time.
"""

import asyncio
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import ClassVar, LiteralString, Self
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx2
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.core.exceptions import BadRequestError
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError, resolve_pinned_url
from app.core.secret_kinds import SecretKind, StorableSecret
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
    RemoteListing,
    WithdrawnFile,
)
from app.services.rag.connectors.web_page import ParsedPage, parse_page

logger = logging.getLogger(__name__)

USER_AGENT = "AgenticOS-Crawler/1.0"
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}
_TIMEOUT = httpx2.Timeout(15.0)
_MAX_REDIRECTS = 5
_MB = 1024 * 1024
_MAX_PAGE_BYTES = 5 * _MB
_MAX_SITEMAP_BYTES = 10 * _MB
_MAX_ROBOTS_BYTES = _MB // 2
_MAX_SITEMAPS = 50
# A `Crawl-delay` is honoured up to this and no further: a robots.txt asking for
# an hour between requests would otherwise turn a nightly sync into a month.
_MAX_CRAWL_DELAY = 10.0
_ATTEMPTS = 3
_MAX_RETRY_AFTER = 30.0
_TRANSIENT = frozenset({429, 500, 502, 503, 504})
_GONE = frozenset({404, 410})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
# The crawl reads every page to find its links; keeping the extracted text lets
# `_fetch` write it without a second request. Bounded, because a site of five
# thousand long pages is a sync's memory - beyond this `_fetch` fetches again.
_MAX_CACHED_BYTES = 64 * _MB
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _web_url(value: str, *, error: LiteralString) -> str:
    """Refuse a value that is not an absolute http(s) URL with a host."""
    if normalized_url(value) is None:
        raise PydanticCustomError("web_url", error)
    return value


class WebConfig(BaseModel):
    """What a website source crawls, and where the crawl stops.

    `root_url` is required and fixes the host: every page, the sitemap and every
    redirect stays on it. `path_prefix` narrows the crawl within the host and
    defaults to the start URL's own folder - `/docs/intro` crawls `/docs/`.
    Giving a `sitemap_url` replaces link discovery with the sitemap's list, and
    `max_depth` then does not apply.
    """

    root_url: str = Field(
        title="Start URL",
        description="The page the crawl starts from, e.g. https://docs.example.com/guide/",
    )
    max_depth: int = Field(
        default=2,
        ge=0,
        le=10,
        title="Link depth",
        description="How many links away from the start URL to follow. 0 reads the start page only.",
    )
    path_prefix: str | None = Field(
        default=None,
        title="Stay under path",
        description="Only pages whose path starts with this are read, e.g. /docs/. "
        "Leave empty for the start URL's own folder.",
    )
    sitemap_url: str | None = Field(
        default=None,
        title="Sitemap URL",
        description="Read the pages this sitemap lists instead of following links. "
        "Must be on the start URL's host.",
    )
    max_pages: int = Field(
        default=500,
        ge=1,
        le=5000,
        title="Page limit",
        description="The crawl stops after reading this many pages.",
    )

    @field_validator("root_url")
    @classmethod
    def _root_is_a_web_url(cls, value: str) -> str:
        return _web_url(value, error="The start URL must be an http:// or https:// address.")

    @field_validator("sitemap_url")
    @classmethod
    def _sitemap_is_a_web_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _web_url(value, error="The sitemap URL must be an http:// or https:// address.")

    @field_validator("path_prefix")
    @classmethod
    def _prefix_is_a_path(cls, value: str | None) -> str | None:
        if value is None or value.startswith("/"):
            return value
        raise PydanticCustomError("path_prefix", "The path must start with '/', e.g. /docs/.")

    @model_validator(mode="after")
    def _one_site(self) -> Self:
        scope = _Scope.of(self)
        if not scope.admits(_normalized(self.root_url)):
            raise PydanticCustomError(
                "web_scope", "The start URL must be under the path it stays under."
            )
        if self.sitemap_url is not None:
            sitemap = urlsplit(_normalized(self.sitemap_url))
            if sitemap.hostname != scope.host:
                raise PydanticCustomError(
                    "web_scope", "The sitemap must be on the start URL's host."
                )
            if scope.secure and sitemap.scheme != "https":
                raise PydanticCustomError(
                    "web_scope", "The sitemap must be an https:// address, as the start URL is."
                )
        return self


def normalized_url(url: str) -> str | None:
    """`url` in the one spelling a crawl compares and stores, or `None` if it is not a page.

    Lower-case scheme and host, no default port, no fragment, `/` for an empty
    path. The query is kept: some sites page by it. A URL with credentials in
    it is not a page this crawler requests.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    default = 443 if scheme == "https" else 80
    netloc = host if port in (None, default) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def _normalized(url: str) -> str:
    """`normalized_url` for a value `WebConfig` already validated."""
    checked = normalized_url(url)
    if checked is None:  # pragma: no cover - the field validators refuse it first
        raise ValueError("not a web URL")
    return checked


def _address(url: str) -> str:
    """The URL without its scheme: an http page redirected to https is still the same page."""
    parts = urlsplit(url)
    return parts.netloc + parts.path + (f"?{parts.query}" if parts.query else "")


def _shown(url: str) -> str:
    """The URL as a sync log may show it - host and path, never the query string."""
    parts = urlsplit(url)
    return parts.netloc + parts.path


def _cited(url: str) -> str:
    """The URL as a document's text cites it - the page, never its query string.

    The text is embedded and searched by everyone who can read the collection,
    and a query can carry a signed link's token. The full URL stays what the
    crawl requests and what `source_path` is keyed by.
    """
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _file_name(url: str) -> str:
    """A file name for the page, readable in the Documents tab and safe on disk."""
    parts = urlsplit(url)
    raw = "-".join(
        part for part in (parts.netloc, parts.path.strip("/") or "index", parts.query) if part
    )
    return f"{_UNSAFE_NAME.sub('-', raw).strip('-.')[:200]}.md"


def _document(url: str, page: ParsedPage) -> str:
    """The Markdown `_fetch` writes: the page's text, headed by where it came from."""
    heading = "" if page.title is None or page.markdown.startswith("# ") else f"# {page.title}\n\n"
    return f"{heading}Source: {_cited(url)}\n\n{page.markdown}\n"


@dataclass(frozen=True)
class _Scope:
    """The part of the web a source may read: one host, and paths under one prefix.

    `secure` is an `https://` start URL, which admits only `https://` from then
    on; an `http://` one admits both, so a site upgrading its links is followed.
    """

    host: str
    prefix: str
    secure: bool

    @classmethod
    def of(cls, config: WebConfig) -> "_Scope":
        root = urlsplit(_normalized(config.root_url))
        folder = root.path[: root.path.rfind("/") + 1] or "/"
        return cls(
            host=root.hostname or "",
            prefix=config.path_prefix or folder,
            secure=root.scheme == "https",
        )

    def whole_host(self) -> "_Scope":
        """This scope with no path prefix: where robots.txt and the sitemaps live."""
        return replace(self, prefix="/")

    def admits(self, url: str) -> bool:
        parts = urlsplit(url)
        return (
            (parts.scheme == "https" or not self.secure)
            and parts.hostname == self.host
            and (parts.path or "/").startswith(self.prefix)
        )


class _Unreadable(Exception):
    """A URL that could not be read, in a sentence this module wrote.

    `status` is the HTTP status when the server answered one, so robots.txt can
    tell "forbidden" (read as no rules) from "unreachable" (read as no crawl).
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class _Fetched:
    """A successful response, read whole under its size ceiling."""

    url: str
    body: bytes
    charset: str | None

    def text(self) -> str:
        """The body as text, in UTF-8 when the server named a charset Python does not know.

        The charset is the server's to name, and `charset=nonsense` is a
        `LookupError` at decode - uncaught, one page's header would fail the crawl.
        """
        try:
            return self.body.decode(self.charset or "utf-8", errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def _retry_wait(retry_after: str | None, backoff: float) -> float:
    """How long to wait before the next attempt: the server's `Retry-After`, capped, else `backoff`.

    `Retry-After` is seconds or an HTTP date (RFC 9110). A date already past is
    no wait; one this module cannot read is the local backoff.
    """
    value = (retry_after or "").strip()
    if value.isdigit():
        return min(float(value), _MAX_RETRY_AFTER)
    try:
        when = parsedate_to_datetime(value)
    except ValueError:
        return backoff
    # An HTTP date is always GMT; `-0000` parses without a zone.
    remaining = (when.replace(tzinfo=when.tzinfo or UTC) - datetime.now(UTC)).total_seconds()
    return min(max(remaining, 0.0), _MAX_RETRY_AFTER)


def _redirect_target(current: str, location: str | None) -> str | None:
    """Where a redirect from `current` leads, or `None` for a `Location` that is no URL.

    `urljoin` raises on some of those - `http://a]b/`, which the HTTP client
    lets through - rather than answering, and a server's header must not be
    able to stop a whole crawl.
    """
    if not location:
        return None
    try:
        return normalized_url(urljoin(current, location))
    except ValueError:
        return None


def _sitemap_entries(body: bytes, shown: str) -> tuple[bool, list[tuple[str, datetime | None]]]:
    """Whether `body` is a sitemap index, and the `(loc, lastmod)` pairs it lists.

    A document declaring a DTD is refused before it is parsed: a sitemap needs
    none, and entity declarations are how an XML document is made to expand.
    """
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise _Unreadable(f"The sitemap {shown} declares a DTD, which a sitemap does not need.")
    try:
        # The stdlib parser rather than `defusedxml`: the documents it is unsafe
        # for are ones with a DTD, refused above, and it resolves no external
        # entity by default - so what is left is a bounded body of plain elements.
        root = ElementTree.fromstring(body)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise _Unreadable(f"The sitemap {shown} is not readable XML.") from exc
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in ("urlset", "sitemapindex"):
        raise _Unreadable(f"{shown} is not a sitemap.")
    entries: list[tuple[str, datetime | None]] = []
    for entry in root:
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in entry}
        if not values.get("loc"):
            continue
        try:
            modified = datetime.fromisoformat(values["lastmod"]) if values.get("lastmod") else None
        except ValueError:
            modified = None
        entries.append((values["loc"], modified))
    return kind == "sitemapindex", entries


class WebConnector(BaseSyncConnector):
    """Reads a public website into a collection, one Markdown document per page."""

    CONNECTOR_TYPE: ClassVar[str] = "web"
    DISPLAY_NAME: ClassVar[str] = "Website"
    SECRET_KIND: ClassVar[SecretKind] = SecretKind.NONE
    CONFIG_MODEL: ClassVar[type[BaseModel]] = WebConfig
    # Seconds between two requests to the site, raised by its `Crawl-delay`.
    MIN_REQUEST_INTERVAL: ClassVar[float] = 0.5
    # Seconds before the first retry of a transient failure, doubling after.
    RETRY_BACKOFF: ClassVar[float] = 1.0
    # Seconds one sync may spend on the site, listing and fetching together.
    # Every other bound is per request or per page, and a site answering each
    # of five thousand pages with `429 Retry-After: 30` would otherwise hold a
    # worker, and the source's run lock with it, for days.
    MAX_DURATION: ClassVar[float] = 6 * 3600.0

    def __init__(self, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        """`transport` replaces the network for a test; `PinnedAsyncClient` still wraps it."""
        self._transport = transport
        self._robots: RobotFileParser | None = None
        self._interval = self.MIN_REQUEST_INTERVAL
        self._next_request_at = 0.0
        self._pages: dict[str, str] = {}
        self._cached_bytes = 0
        # One instance serves one sync and is made as it starts.
        self._deadline = time.monotonic() + self.MAX_DURATION

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        """Refuse a config the crawl could not run, including a URL it may not request.

        The address check runs here as well as on every request, so a start URL
        pointing inside the deployment's network is refused by the form that
        typed it rather than by a sync log later.
        """
        refusal = await super().validate_config(config)
        if refusal is not None:
            return refusal
        try:
            checked = WebConfig.model_validate(config)
        except ValidationError as exc:
            error = exc.errors(include_url=False, include_input=False)[0]
            field = str(error["loc"][0]) if error["loc"] else None
            return ConfigRefusal(message=error["msg"], field=field)
        for field, url in (("root_url", checked.root_url), ("sitemap_url", checked.sitemap_url)):
            if url is None:
                continue
            try:
                await asyncio.to_thread(resolve_pinned_url, _normalized(url))
            except UrlRefusedError as exc:
                return ConfigRefusal(message=str(exc), field=field)
        return None

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> RemoteListing:
        """The site's pages: followed from the start URL, or listed by its sitemap."""
        settings = WebConfig.model_validate(config)
        scope = _Scope.of(settings)
        async with self._client() as client:
            await self._load_robots(client, settings)
            if settings.sitemap_url is not None:
                return await self._from_sitemap(client, settings, scope)
            return await self._crawl(client, settings, scope)

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Write the page's Markdown, from what the crawl kept or by reading it now.

        Raises:
            WithdrawnFile: the page is no longer the site's to give - gone, not
                HTML, forbidden by robots.txt, or asking not to be indexed. The
                sync removes the document it brought in earlier.
            BadRequestError: the page could not be read, or has no text to
                index. The sync counts it as a failed file, and the document it
                brought in earlier is kept.
        """
        body = self._pages.get(file.source_path)
        if body is None:
            body = await self._read_one(file.id, WebConfig.model_validate(config))
        await asyncio.to_thread(dest_path.write_text, body, encoding="utf-8")

    async def _read_one(self, url: str, settings: WebConfig) -> str:
        """One page read on its own, as a sitemap-listed page is.

        A sitemap lists a page before anything reads it, so what reading it
        finds - gone, forbidden, `noindex` - is the first the sync hears of it,
        and is said as `WithdrawnFile` rather than a failure: a page a site
        keeps in its sitemap after marking it `noindex` must still leave the
        collection.
        """
        if self._out_of_time():
            raise BadRequestError(message=self._time_limit_problem(urlsplit(url).hostname or ""))
        async with self._client() as client:
            await self._load_robots(client, settings)
            if not self._allowed(url):
                raise WithdrawnFile(f"robots.txt no longer allows {_shown(url)}.")
            try:
                page = await self._get(
                    client, url, limit=_MAX_PAGE_BYTES, scope=_Scope.of(settings), types=_HTML_TYPES
                )
            except _Unreadable as exc:
                raise BadRequestError(message=exc.message) from exc
        if page is None:
            raise WithdrawnFile(f"{_shown(url)} is no longer an HTML page on this site.")
        parsed = parse_page(page.text(), page.url)
        if not parsed.index:
            raise WithdrawnFile(f"{_shown(url)} asks not to be indexed.")
        if not parsed.markdown:
            raise BadRequestError(message=f"{_shown(url)} has no text to index.")
        return _document(page.url, parsed)

    def _out_of_time(self) -> bool:
        return time.monotonic() >= self._deadline

    def _time_limit_problem(self, host: str) -> str:
        hours = self.MAX_DURATION / 3600
        return (
            f"The sync of {host} reached its {hours:g}-hour limit, "
            "so the pages after it were not read."
        )

    def _client(self) -> PinnedAsyncClient:
        return PinnedAsyncClient(timeout=_TIMEOUT, transport=self._transport)

    async def _crawl(
        self, client: PinnedAsyncClient, settings: WebConfig, scope: _Scope
    ) -> RemoteListing:
        """Breadth first from the start URL, to `max_depth` links and `max_pages` reads."""
        root = _normalized(settings.root_url)
        queue: deque[tuple[str, int]] = deque([(root, 0)])
        queued = {root}
        listed: dict[str, RemoteFile] = {}
        problems: list[str] = []
        complete = True
        read = 0
        while queue:
            if read >= settings.max_pages:
                complete = False
                break
            if self._out_of_time():
                problems.append(self._time_limit_problem(scope.host))
                complete = False
                break
            url, depth = queue.popleft()
            if not self._allowed(url):
                if depth == 0:
                    problems.append(f"robots.txt does not allow the start URL {_shown(url)}.")
                    complete = False
                continue
            read += 1
            try:
                page = await self._get(
                    client, url, limit=_MAX_PAGE_BYTES, scope=scope, types=_HTML_TYPES
                )
            except _Unreadable as exc:
                problems.append(exc.message)
                complete = False
                continue
            if page is None:
                # A missing page deeper in is a broken link, and removing what it
                # used to be is right. A start URL that leads nowhere is a crawl
                # that saw nothing, and must not read as a site with no pages.
                if depth == 0:
                    problems.append(
                        f"The start URL {_shown(url)} did not lead to an HTML page on {scope.host}."
                    )
                    complete = False
                continue
            queued.add(page.url)
            parsed = parse_page(page.text(), page.url)
            if parsed.follow and depth < settings.max_depth:
                for link in parsed.links:
                    target = normalized_url(link)
                    if target is not None and target not in queued and scope.admits(target):
                        queued.add(target)
                        queue.append((target, depth + 1))
            if parsed.index and parsed.markdown:
                file = self._keep(page.url, parsed)
                listed.setdefault(file.source_path, file)
        if not complete and read >= settings.max_pages:
            logger.info(
                "Web crawl of %s stopped at its %d-page limit", scope.host, settings.max_pages
            )
        return RemoteListing(files=list(listed.values()), complete=complete, problems=problems)

    async def _from_sitemap(
        self, client: PinnedAsyncClient, settings: WebConfig, scope: _Scope
    ) -> RemoteListing:
        """The pages the sitemap lists, through one or more levels of sitemap index."""
        site = scope.whole_host()
        pending: deque[str] = deque([_normalized(settings.sitemap_url or "")])
        pages: dict[str, RemoteFile] = {}
        problems: list[str] = []
        complete = True
        full = False
        read = 0
        while pending and not full:
            sitemap = pending.popleft()
            if read >= _MAX_SITEMAPS:
                problems.append(
                    f"The sitemap index lists more than {_MAX_SITEMAPS} sitemaps; the rest were not read."
                )
                complete = False
                break
            if self._out_of_time():
                problems.append(self._time_limit_problem(scope.host))
                complete = False
                break
            if not self._allowed(sitemap):
                problems.append(f"robots.txt does not allow the sitemap {_shown(sitemap)}.")
                complete = False
                continue
            read += 1
            try:
                is_index, entries = await self._read_sitemap(client, sitemap, site)
            except _Unreadable as exc:
                problems.append(exc.message)
                complete = False
                continue
            for loc, modified_at in entries:
                url = normalized_url(loc)
                if url is None:
                    continue
                if is_index:
                    if site.admits(url):
                        pending.append(url)
                    continue
                if not scope.admits(url) or not self._allowed(url):
                    continue
                if len(pages) >= settings.max_pages:
                    # One page over proves the limit, and the sitemaps still
                    # pending could only list more: none of them is read.
                    complete = False
                    full = True
                    break
                source_path = f"web://{_address(url)}"
                pages.setdefault(
                    source_path,
                    RemoteFile(
                        id=url,
                        name=_file_name(url),
                        mime_type="text/markdown",
                        modified_at=modified_at,
                        source_path=source_path,
                    ),
                )
        return RemoteListing(files=list(pages.values()), complete=complete, problems=problems)

    async def _read_sitemap(
        self, client: PinnedAsyncClient, url: str, site: _Scope
    ) -> tuple[bool, list[tuple[str, datetime | None]]]:
        """One sitemap's entries - see `_sitemap_entries`.

        Raises:
            _Unreadable: the sitemap is missing, unreachable or not a sitemap.
        """
        fetched = await self._get(client, url, limit=_MAX_SITEMAP_BYTES, scope=site, types=None)
        if fetched is None:
            raise _Unreadable(f"The sitemap {_shown(url)} was not found on {site.host}.")
        return _sitemap_entries(fetched.body, _shown(url))

    def _keep(self, url: str, page: ParsedPage) -> RemoteFile:
        """The listing entry for a page the crawl read, keeping its text for `_fetch`."""
        body = _document(url, page)
        size = len(body.encode("utf-8"))
        source_path = f"web://{_address(url)}"
        if self._cached_bytes + size <= _MAX_CACHED_BYTES:
            self._pages[source_path] = body
            self._cached_bytes += size
        return RemoteFile(
            id=url,
            name=_file_name(url),
            mime_type="text/markdown",
            size=size,
            source_path=source_path,
        )

    async def _load_robots(self, client: PinnedAsyncClient, settings: WebConfig) -> None:
        """Read the site's robots.txt once per sync.

        A robots.txt that is missing or forbidden (any 4xx) means no rules, as
        RFC 9309 reads it. One that cannot be reached (5xx, or no answer) means
        the crawl does not run: the site may be saying "stay out" and we cannot
        tell.

        Raises:
            BadRequestError: robots.txt could not be reached.
        """
        if self._robots is not None:
            return
        root = urlsplit(_normalized(settings.root_url))
        robots_url = urlunsplit((root.scheme, root.netloc, "/robots.txt", "", ""))
        rules = RobotFileParser()
        try:
            fetched = await self._get(
                client,
                robots_url,
                limit=_MAX_ROBOTS_BYTES,
                scope=_Scope.of(settings).whole_host(),
                types=None,
            )
        except _Unreadable as exc:
            if exc.status is None or exc.status >= 500:
                raise BadRequestError(
                    message=f"The site's robots.txt could not be read, so it was not crawled: {exc.message}"
                ) from exc
            fetched = None
        rules.parse(fetched.text().splitlines() if fetched is not None else [])
        delay = rules.crawl_delay(USER_AGENT)
        if delay is not None:
            self._interval = min(max(float(delay), self.MIN_REQUEST_INTERVAL), _MAX_CRAWL_DELAY)
        self._robots = rules

    def _allowed(self, url: str) -> bool:
        return self._robots is None or self._robots.can_fetch(USER_AGENT, url)

    async def _get(
        self,
        client: PinnedAsyncClient,
        url: str,
        *,
        limit: int,
        scope: _Scope,
        types: frozenset[str] | None,
    ) -> _Fetched | None:
        """GET `url`, following redirects while they stay in `scope`.

        Answers `None` for a page that is not there to read - gone (404, 410),
        redirected off the site or somewhere robots.txt forbids, or not one of
        `types` - and raises for one that could not be read.

        Raises:
            _Unreadable: refused, unreachable, too large, or an error status.
        """
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            response = await self._send(client, current, limit=limit, types=types)
            if response is None:
                return None
            status, location, body, charset = response
            if status in _REDIRECTS:
                target = _redirect_target(current, location)
                if target is None or not scope.admits(target) or not self._allowed(target):
                    return None
                current = target
                continue
            if status in _GONE:
                return None
            if not 200 <= status < 300:
                raise _Unreadable(f"{_shown(current)} answered HTTP {status}.", status=status)
            return _Fetched(url=current, body=body, charset=charset)
        raise _Unreadable(f"{_shown(url)} redirected more than {_MAX_REDIRECTS} times.")

    async def _send(
        self,
        client: PinnedAsyncClient,
        url: str,
        *,
        limit: int,
        types: frozenset[str] | None,
    ) -> tuple[int, str | None, bytes, str | None] | None:
        """One request, retried on a transient failure: status, `Location`, body, charset.

        Answers `None` for a successful response whose type is not one of
        `types`, without reading its body - a crawl that meets a linked video
        should not download it to learn it is not a page.
        """
        attempt = 1
        while True:
            await self._pace()
            wait = self.RETRY_BACKOFF * 2 ** (attempt - 1)
            try:
                async with client.stream("GET", url, headers=_HEADERS) as response:
                    status = response.status_code
                    if status in _TRANSIENT and attempt < _ATTEMPTS:
                        wait = _retry_wait(response.headers.get("retry-after"), wait)
                    else:
                        if not 200 <= status < 300:
                            return status, response.headers.get("location"), b"", None
                        content_type = (
                            response.headers.get("content-type", "").split(";")[0].strip().lower()
                        )
                        if types is not None and content_type not in types:
                            return None
                        body = await self._read_capped(response, url, limit)
                        return status, None, body, response.charset_encoding
            except UrlRefusedError as exc:
                raise _Unreadable(f"{_shown(url)} was not requested: {exc}") from exc
            except httpx2.TransportError as exc:
                if attempt == _ATTEMPTS:
                    raise _Unreadable(
                        f"{_shown(url)} could not be reached ({type(exc).__name__})."
                    ) from exc
            logger.info("Retrying %s after a transient failure (attempt %d)", _shown(url), attempt)
            await asyncio.sleep(wait)
            attempt += 1

    @staticmethod
    async def _read_capped(response: httpx2.Response, url: str, limit: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise _Unreadable(
                    f"{_shown(url)} is larger than {limit // _MB or 1} MB, so it was not read."
                )
            chunks.append(chunk)
        return b"".join(chunks)

    async def _pace(self) -> None:
        """Wait out the interval since the previous request to the site."""
        now = time.monotonic()
        if self._next_request_at > now:
            await asyncio.sleep(self._next_request_at - now)
        self._next_request_at = max(now, self._next_request_at) + self._interval
