"""The website connector (`app/services/rag/connectors/web.py`, #984).

What is worth pinning is where a crawl stops and what it refuses, because the
start URL is typed by a tenant and every link after it is chosen by whoever
wrote the page. The network is replaced below `PinnedAsyncClient`, never above
it, so every request here still passes the real SSRF check and is dialled at
the address that check approved; DNS is stubbed so the check has something to
resolve.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

from app.core.exceptions import BadRequestError
from app.services.rag.connectors import CONNECTOR_REGISTRY, RemoteFile, RemoteListing
from app.services.rag.connectors.web import WebConnector, normalized_url

pytestmark = pytest.mark.anyio

_PUBLIC = "93.184.216.34"
_METADATA = "169.254.169.254"

Page = tuple[int, dict[str, str], bytes]


def _html(body: str, *, head: str = "") -> Page:
    return (
        200,
        {"content-type": "text/html; charset=utf-8"},
        f"<html><head>{head}</head><body>{body}</body></html>".encode(),
    )


def _status(code: int, **headers: str) -> Page:
    return code, headers, b""


class _Site(httpx2.AsyncBaseTransport):
    """A web of pages keyed by `host/path`, recording every request that reached it."""

    def __init__(self, pages: dict[str, Page | list[Page]]) -> None:
        self._pages = pages
        self.requested: list[str] = []
        self.dialled: list[str] = []
        self._hosts: set[str] = set()

    def hosts(self) -> set[str]:
        """Every `Host` a request was sent for - the name, not the dialled address."""
        return self._hosts

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self._hosts.add(request.headers["host"])
        key = request.headers["host"] + request.url.raw_path.decode()
        self.requested.append(key)
        self.dialled.append(request.url.host)
        answer = self._pages.get(key, _status(404))
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        status, headers, body = answer
        return httpx2.Response(status, headers=headers, content=body)


class _Fast(WebConnector):
    """No pacing and no backoff: what is under test is the order, not the wait."""

    MIN_REQUEST_INTERVAL = 0.0
    RETRY_BACKOFF = 0.0


@pytest.fixture(autouse=True)
def _dns(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, str]], None]:
    """Every name resolves to a public address unless a test says otherwise."""
    answers: dict[str, str] = {}

    def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(2, 1, 6, "", (answers.get(host, _PUBLIC), port))]

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
    return answers.update


def _config(**overrides: object) -> dict[str, object]:
    return {"root_url": "https://docs.example.com/guide/", **overrides}


async def _list(site: _Site, **overrides: object) -> RemoteListing:
    return await _Fast(transport=site).list_files(_config(**overrides), None)


class TestTheConnectorIsRegistered:
    def test_web_needs_no_credential(self) -> None:
        connector = CONNECTOR_REGISTRY["web"]
        assert connector is WebConnector
        assert connector.SECRET_KIND.value == "none"


class TestWhereACrawlGoes:
    async def test_it_follows_links_under_the_start_folder_and_nowhere_else(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html(
                    "<main><h1>Guide</h1><p>Start here.</p></main>"
                    '<a href="install">Install</a>'
                    '<a href="/blog/news">Blog</a>'
                    '<a href="https://evil.example.net/guide/x">Elsewhere</a>'
                    '<a href="mailto:team@example.com">Mail</a>'
                ),
                "docs.example.com/guide/install": _html("<p>Run the installer.</p>"),
            }
        )

        listing = await _list(site)

        assert [f.source_path for f in listing.files] == [
            "web://docs.example.com/guide/",
            "web://docs.example.com/guide/install",
        ]
        assert listing.complete
        assert site.hosts() == {"docs.example.com"}
        assert not any(r.startswith("docs.example.com/blog/") for r in site.requested)

    async def test_depth_bounds_how_far_links_are_followed(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="a">a</a>'),
                "docs.example.com/guide/a": _html('<p>a</p><a href="b">b</a>'),
                "docs.example.com/guide/b": _html("<p>b</p>"),
            }
        )

        listing = await _list(site, max_depth=1)

        assert {f.id for f in listing.files} == {
            "https://docs.example.com/guide/",
            "https://docs.example.com/guide/a",
        }
        assert "docs.example.com/guide/b" not in site.requested

    async def test_the_page_limit_stops_the_crawl_and_marks_the_listing_partial(self) -> None:
        links = "".join(f'<a href="p{n}">p{n}</a>' for n in range(5))
        pages: dict[str, Page | list[Page]] = {
            "docs.example.com/guide/": _html(f"<p>root</p>{links}")
        }
        pages.update({f"docs.example.com/guide/p{n}": _html(f"<p>page {n}</p>") for n in range(5)})
        site = _Site(pages)

        listing = await _list(site, max_pages=3)

        assert len(listing.files) == 3
        assert not listing.complete
        assert listing.problems == []

    async def test_a_redirect_off_the_site_is_not_followed(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="moved">moved</a>'),
                "docs.example.com/guide/moved": _status(302, location="https://evil.example.net/"),
            }
        )

        listing = await _list(site)

        assert [f.id for f in listing.files] == ["https://docs.example.com/guide/"]
        assert site.hosts() == {"docs.example.com"}
        assert listing.complete

    async def test_a_redirect_within_the_site_is_listed_under_where_it_landed(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _status(301, location="/guide/index.html"),
                "docs.example.com/guide/index.html": _html("<p>root</p>"),
            }
        )

        listing = await _list(site)

        assert [f.source_path for f in listing.files] == ["web://docs.example.com/guide/index.html"]

    async def test_a_page_redirecting_in_a_loop_is_a_problem(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="loop">loop</a>'),
                "docs.example.com/guide/loop": _status(302, location="/guide/loop"),
            }
        )

        listing = await _list(site)

        assert not listing.complete
        assert listing.problems == ["docs.example.com/guide/loop redirected more than 5 times."]

    async def test_path_prefix_widens_the_crawl_beyond_the_start_folder(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="/api/ref">ref</a>'),
                "docs.example.com/api/ref": _html("<p>reference</p>"),
            }
        )

        listing = await _list(site, path_prefix="/")

        assert "https://docs.example.com/api/ref" in {f.id for f in listing.files}

    async def test_a_non_html_link_is_neither_downloaded_nor_listed(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="video.mp4">video</a>'),
                "docs.example.com/guide/video.mp4": (
                    200,
                    {"content-type": "video/mp4"},
                    b"\x00" * 64,
                ),
            }
        )

        listing = await _list(site)

        assert [f.id for f in listing.files] == ["https://docs.example.com/guide/"]
        assert listing.complete


class TestWhatAPageAsksFor:
    async def test_robots_txt_is_obeyed(self) -> None:
        site = _Site(
            {
                "docs.example.com/robots.txt": (
                    200,
                    {"content-type": "text/plain"},
                    b"User-agent: *\nDisallow: /guide/private\n",
                ),
                "docs.example.com/guide/": _html(
                    '<p>root</p><a href="private">p</a><a href="open">o</a>'
                ),
                "docs.example.com/guide/open": _html("<p>open</p>"),
                "docs.example.com/guide/private": _html("<p>secret</p>"),
            }
        )

        listing = await _list(site)

        assert "docs.example.com/guide/private" not in site.requested
        assert {f.id for f in listing.files} == {
            "https://docs.example.com/guide/",
            "https://docs.example.com/guide/open",
        }

    async def test_a_start_url_robots_forbids_is_a_problem_not_an_empty_site(self) -> None:
        site = _Site(
            {
                "docs.example.com/robots.txt": (200, {}, b"User-agent: *\nDisallow: /\n"),
            }
        )

        listing = await _list(site)

        assert listing.files == []
        assert not listing.complete
        assert listing.problems == [
            "robots.txt does not allow the start URL docs.example.com/guide/."
        ]

    async def test_a_forbidden_robots_txt_means_no_rules(self) -> None:
        site = _Site(
            {
                "docs.example.com/robots.txt": _status(403),
                "docs.example.com/guide/": _html("<p>root</p>"),
            }
        )

        listing = await _list(site)

        assert len(listing.files) == 1

    async def test_an_unreachable_robots_txt_stops_the_sync(self) -> None:
        site = _Site({"docs.example.com/robots.txt": _status(503)})

        with pytest.raises(BadRequestError) as exc:
            await _list(site)

        assert "robots.txt could not be read" in exc.value.message
        assert site.requested.count("docs.example.com/robots.txt") == 3

    async def test_crawl_delay_raises_the_interval_up_to_its_cap(self) -> None:
        site = _Site(
            {
                "docs.example.com/robots.txt": (200, {}, b"User-agent: *\nCrawl-delay: 3600\n"),
                "docs.example.com/guide/": _html('<p>root</p><a href="next">next</a>'),
                "docs.example.com/guide/next": _html("<p>next</p>"),
            }
        )
        connector = _Fast(transport=site)
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("app.services.rag.connectors.web.asyncio.sleep", fake_sleep)
            await connector.list_files(_config(), None)

        # The second page waits out the delay, and an hour is cut to ten seconds.
        assert slept
        assert 9.0 < max(slept) <= 10.0

    async def test_noindex_is_not_listed_and_nofollow_is_not_crawled(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html(
                    '<p>root</p><a href="hub">hub</a><a href="leaf">leaf</a>'
                ),
                "docs.example.com/guide/hub": _html(
                    '<p>hub</p><a href="behind-hub">x</a>',
                    head='<meta name="robots" content="noindex">',
                ),
                "docs.example.com/guide/behind-hub": _html("<p>found through the hub</p>"),
                "docs.example.com/guide/leaf": _html(
                    '<p>leaf</p><a href="behind-leaf">x</a>',
                    head='<meta name="robots" content="nofollow">',
                ),
            }
        )

        listing = await _list(site, max_depth=3)

        ids = {f.id for f in listing.files}
        assert "https://docs.example.com/guide/hub" not in ids
        assert "https://docs.example.com/guide/behind-hub" in ids
        assert "docs.example.com/guide/behind-leaf" not in site.requested


class TestWhatStopsAListingBeingWhole:
    async def test_a_missing_linked_page_is_a_broken_link_and_the_listing_stays_whole(self) -> None:
        site = _Site({"docs.example.com/guide/": _html('<p>root</p><a href="gone">gone</a>')})

        listing = await _list(site)

        assert listing.complete
        assert listing.problems == []

    async def test_a_missing_start_url_is_a_problem(self) -> None:
        listing = await _list(_Site({}))

        assert not listing.complete
        assert listing.problems == [
            "The start URL docs.example.com/guide/ did not lead to an HTML page on docs.example.com."
        ]

    async def test_a_transient_failure_is_retried(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": [
                    _status(503, **{"retry-after": "0"}),
                    _html("<p>root</p>"),
                ],
            }
        )

        listing = await _list(site)

        assert len(listing.files) == 1
        assert listing.complete
        assert site.requested.count("docs.example.com/guide/") == 2

    async def test_a_persistent_failure_is_a_problem_after_three_attempts(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="flaky">f</a>'),
                "docs.example.com/guide/flaky": _status(502),
            }
        )

        listing = await _list(site)

        assert site.requested.count("docs.example.com/guide/flaky") == 3
        assert not listing.complete
        assert listing.problems == ["docs.example.com/guide/flaky answered HTTP 502."]

    async def test_a_forbidden_page_is_a_problem(self) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": _html('<p>root</p><a href="staff">s</a>'),
                "docs.example.com/guide/staff": _status(403),
            }
        )

        listing = await _list(site)

        assert listing.problems == ["docs.example.com/guide/staff answered HTTP 403."]
        assert site.requested.count("docs.example.com/guide/staff") == 1

    async def test_an_unreachable_page_is_a_problem(self) -> None:
        class _Refusing(_Site):
            async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
                if request.url.raw_path == b"/guide/down":
                    self.requested.append("down")
                    raise httpx2.ConnectError("refused", request=request)
                return await super().handle_async_request(request)

        site = _Refusing({"docs.example.com/guide/": _html('<p>root</p><a href="down">d</a>')})

        listing = await _list(site)

        assert site.requested.count("down") == 3
        assert listing.problems == [
            "docs.example.com/guide/down could not be reached (ConnectError)."
        ]

    async def test_a_page_over_the_size_ceiling_is_a_problem(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.rag.connectors.web._MAX_PAGE_BYTES", 64)
        site = _Site({"docs.example.com/guide/": _html("<p>" + "x" * 200 + "</p>")})

        listing = await _list(site)

        assert listing.problems == [
            "docs.example.com/guide/ is larger than 1 MB, so it was not read."
        ]


class TestAddressesItRefuses:
    async def test_a_start_url_resolving_to_the_metadata_service_is_never_dialled(
        self, _dns: Callable[[dict[str, str]], None]
    ) -> None:
        _dns({"docs.example.com": _METADATA})
        site = _Site({"docs.example.com/guide/": _html("<p>credentials</p>")})

        with pytest.raises(BadRequestError):
            # robots.txt is the first request, and the refusal is on it.
            await _list(site)

        assert site.dialled == []

    async def test_the_request_is_dialled_at_the_address_that_was_checked(self) -> None:
        site = _Site({"docs.example.com/guide/": _html("<p>root</p>")})

        await _list(site)

        assert set(site.dialled) == {_PUBLIC}


class TestTheSitemap:
    _SITEMAP = (
        200,
        {"content-type": "application/xml"},
        b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.example.com/guide/a</loc><lastmod>2026-09-01</lastmod></url>
  <url><loc>https://docs.example.com/guide/b</loc></url>
  <url><loc>https://docs.example.com/blog/c</loc></url>
  <url><loc>https://evil.example.net/guide/d</loc></url>
</urlset>""",
    )

    async def test_it_lists_what_the_sitemap_names_within_the_scope_without_reading_the_pages(
        self,
    ) -> None:
        site = _Site({"docs.example.com/sitemap.xml": self._SITEMAP})

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml")

        assert [f.id for f in listing.files] == [
            "https://docs.example.com/guide/a",
            "https://docs.example.com/guide/b",
        ]
        assert listing.files[0].modified_at is not None
        assert listing.complete
        assert site.requested == ["docs.example.com/robots.txt", "docs.example.com/sitemap.xml"]

    async def test_a_sitemap_index_is_followed_to_its_sitemaps(self) -> None:
        index = (
            200,
            {},
            b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://docs.example.com/sitemap-guide.xml</loc></sitemap>
  <sitemap><loc>https://evil.example.net/sitemap.xml</loc></sitemap>
</sitemapindex>""",
        )
        site = _Site(
            {
                "docs.example.com/sitemap.xml": index,
                "docs.example.com/sitemap-guide.xml": self._SITEMAP,
            }
        )

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml")

        assert len(listing.files) == 2
        assert site.hosts() == {"docs.example.com"}

    async def test_a_sitemap_declaring_a_dtd_is_refused(self) -> None:
        bomb = (
            200,
            {},
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><urlset>&lol;</urlset>',
        )
        site = _Site({"docs.example.com/sitemap.xml": bomb})

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml")

        assert listing.files == []
        assert not listing.complete
        assert listing.problems == [
            "The sitemap docs.example.com/sitemap.xml declares a DTD, which a sitemap does not need."
        ]

    @pytest.mark.parametrize(
        ("page", "problem"),
        [
            (
                _status(404),
                "The sitemap docs.example.com/sitemap.xml was not found on docs.example.com.",
            ),
            (
                (200, {}, b"not xml <"),
                "The sitemap docs.example.com/sitemap.xml is not readable XML.",
            ),
            ((200, {}, b"<html></html>"), "docs.example.com/sitemap.xml is not a sitemap."),
        ],
    )
    async def test_an_unreadable_sitemap_is_a_problem(self, page: Page, problem: str) -> None:
        site = _Site({"docs.example.com/sitemap.xml": page})

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml")

        assert listing.problems == [problem]
        assert not listing.complete

    async def test_entries_it_cannot_use_are_passed_over(self) -> None:
        sitemap = (
            200,
            {},
            b"""<urlset>
  <url><lastmod>2026-09-01</lastmod></url>
  <url><loc>mailto:team@example.com</loc></url>
  <url><loc>https://docs.example.com/guide/a</loc><lastmod>last tuesday</lastmod></url>
</urlset>""",
        )
        site = _Site({"docs.example.com/sitemap.xml": sitemap})

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml")

        assert [(f.id, f.modified_at) for f in listing.files] == [
            ("https://docs.example.com/guide/a", None)
        ]
        assert listing.complete

    async def test_a_sitemap_index_is_read_only_so_far(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.rag.connectors.web._MAX_SITEMAPS", 1)
        index = (
            200,
            {},
            b"<sitemapindex><sitemap><loc>https://docs.example.com/s2.xml</loc></sitemap></sitemapindex>",
        )
        site = _Site({"docs.example.com/sitemap.xml": index})

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml")

        assert not listing.complete
        assert listing.problems == [
            "The sitemap index lists more than 1 sitemaps; the rest were not read."
        ]
        assert "docs.example.com/s2.xml" not in site.requested

    async def test_the_page_limit_applies_to_a_sitemap_too(self) -> None:
        site = _Site({"docs.example.com/sitemap.xml": self._SITEMAP})

        listing = await _list(site, sitemap_url="https://docs.example.com/sitemap.xml", max_pages=1)

        assert len(listing.files) == 1
        assert not listing.complete

    async def test_a_sitemap_listed_page_is_read_when_it_is_fetched(self, tmp_path: Path) -> None:
        site = _Site(
            {
                "docs.example.com/sitemap.xml": self._SITEMAP,
                "docs.example.com/guide/a": _html("<h1>Page A</h1><p>Alpha text.</p>"),
            }
        )
        connector = _Fast(transport=site)
        config = _config(sitemap_url="https://docs.example.com/sitemap.xml")
        listing = await connector.list_files(config, None)

        path = await connector.download_file(listing.files[0], tmp_path, config=config)

        assert (
            path.read_text()
            == "Source: https://docs.example.com/guide/a\n\n# Page A\n\nAlpha text.\n"
        )

    @pytest.mark.parametrize(
        ("page", "message"),
        [
            (_status(404), "docs.example.com/guide/a is no longer an HTML page on this site."),
            (_status(500), "docs.example.com/guide/a answered HTTP 500."),
            (
                _html("<p>x</p>", head='<meta name="robots" content="noindex">'),
                "docs.example.com/guide/a has no text to index.",
            ),
        ],
    )
    async def test_a_sitemap_listed_page_that_cannot_be_read_fails_as_a_file(
        self, tmp_path: Path, page: Page, message: str
    ) -> None:
        site = _Site({"docs.example.com/guide/a": page})
        file = RemoteFile(
            id="https://docs.example.com/guide/a",
            name="a.md",
            source_path="web://docs.example.com/guide/a",
        )

        with pytest.raises(BadRequestError) as exc:
            await _Fast(transport=site).download_file(file, tmp_path, config=_config())

        assert exc.value.message == message

    async def test_a_page_robots_now_forbids_fails_as_a_file(self, tmp_path: Path) -> None:
        site = _Site(
            {"docs.example.com/robots.txt": (200, {}, b"User-agent: *\nDisallow: /guide/a\n")}
        )
        file = RemoteFile(id="https://docs.example.com/guide/a", name="a.md", source_path="web://x")

        with pytest.raises(BadRequestError) as exc:
            await _Fast(transport=site).download_file(file, tmp_path, config=_config())

        assert exc.value.message == "robots.txt no longer allows docs.example.com/guide/a."


class TestWhatIsWritten:
    async def test_a_crawled_page_is_written_from_what_the_crawl_read(self, tmp_path: Path) -> None:
        site = _Site(
            {"docs.example.com/guide/": _html("<main><h1>Guide</h1><p>Start here.</p></main>")}
        )
        connector = _Fast(transport=site)
        listing = await connector.list_files(_config(), None)
        requests_after_listing = len(site.requested)

        path = await connector.download_file(listing.files[0], tmp_path, config=_config())

        assert len(site.requested) == requests_after_listing
        assert path.name == "docs.example.com-guide.md"
        assert (
            path.read_text()
            == "Source: https://docs.example.com/guide/\n\n# Guide\n\nStart here.\n"
        )

    async def test_a_charset_python_does_not_know_is_read_as_utf8(self, tmp_path: Path) -> None:
        site = _Site(
            {
                "docs.example.com/guide/": (
                    200,
                    {"content-type": "text/html; charset=nonsense"},
                    "<p>Zażółć.</p>".encode(),
                )
            }
        )
        connector = _Fast(transport=site)
        listing = await connector.list_files(_config(), None)

        path = await connector.download_file(listing.files[0], tmp_path, config=_config())

        assert "Zażółć." in path.read_text()

    async def test_the_title_heads_a_page_with_no_heading_of_its_own(self, tmp_path: Path) -> None:
        site = _Site(
            {"docs.example.com/guide/": _html("<p>Text.</p>", head="<title>Guide</title>")}
        )
        connector = _Fast(transport=site)
        listing = await connector.list_files(_config(), None)

        path = await connector.download_file(listing.files[0], tmp_path, config=_config())

        assert path.read_text().startswith("# Guide\n\nSource: https://docs.example.com/guide/")

    async def test_markup_that_changes_on_every_request_does_not_change_the_document(
        self, tmp_path: Path
    ) -> None:
        """The content hash is the change signal (#990): a nonce in the markup
        must not read as a changed page, or every sync re-embeds the site."""
        written: list[str] = []
        for nonce in ("a1", "b2"):
            site = _Site(
                {
                    "docs.example.com/guide/": _html(
                        f'<script nonce="{nonce}">track()</script><p>Same text.</p>',
                        head=f'<meta name="build" content="{nonce}">',
                    )
                }
            )
            connector = _Fast(transport=site)
            listing = await connector.list_files(_config(), None)
            (tmp_path / nonce).mkdir()
            path = await connector.download_file(
                listing.files[0], tmp_path / nonce, config=_config()
            )
            written.append(hashlib.sha256(path.read_bytes()).hexdigest())

        assert written[0] == written[1]

    async def test_beyond_the_cache_a_page_is_read_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.rag.connectors.web._MAX_CACHED_BYTES", 0)
        site = _Site({"docs.example.com/guide/": _html("<p>Text.</p>")})
        connector = _Fast(transport=site)
        listing = await connector.list_files(_config(), None)

        path = await connector.download_file(listing.files[0], tmp_path, config=_config())

        assert site.requested.count("docs.example.com/guide/") == 2
        assert "Text." in path.read_text()


class TestTheConfigIsCheckedWhereItWasTyped:
    @pytest.mark.parametrize(
        ("config", "field", "message"),
        [
            ({}, "root_url", "Missing required field: Start URL"),
            (
                {"root_url": "ftp://docs.example.com/"},
                "root_url",
                "The start URL must be an http:// or https:// address.",
            ),
            (
                _config(path_prefix="docs"),
                "path_prefix",
                "The path must start with '/', e.g. /docs/.",
            ),
            (_config(max_depth=11), "max_depth", "Input should be less than or equal to 10"),
            (
                _config(path_prefix="/api/"),
                None,
                "The start URL must be under the path it stays under.",
            ),
            (
                _config(sitemap_url="https://other.example.com/sitemap.xml"),
                None,
                "The sitemap must be on the start URL's host.",
            ),
            (
                _config(sitemap_url="not a url"),
                "sitemap_url",
                "The sitemap URL must be an http:// or https:// address.",
            ),
        ],
    )
    async def test_a_config_the_crawl_could_not_run_is_refused(
        self, config: dict[str, object], field: str | None, message: str
    ) -> None:
        refusal = await WebConnector().validate_config(config)

        assert refusal is not None
        assert (refusal.field, refusal.message) == (field, message)

    async def test_a_start_url_inside_the_network_is_refused(
        self, _dns: Callable[[dict[str, str]], None]
    ) -> None:
        _dns({"docs.example.com": "10.0.0.5"})

        refusal = await WebConnector().validate_config(_config())

        assert refusal is not None
        assert refusal.field == "root_url"
        assert "private/internal" in refusal.message

    async def test_a_sitemap_inside_the_network_is_refused(
        self, _dns: Callable[[dict[str, str]], None]
    ) -> None:
        refusal = await WebConnector().validate_config(
            _config(root_url="https://127.0.0.1/", sitemap_url="https://127.0.0.1/sitemap.xml")
        )

        assert refusal is not None
        assert refusal.field == "root_url"

    @pytest.mark.parametrize(
        "config",
        [
            _config(),
            # What the wizard posts for a field left empty.
            _config(sitemap_url=None, path_prefix=None),
            _config(sitemap_url="https://docs.example.com/s.xml"),
        ],
    )
    async def test_a_public_config_is_accepted(self, config: dict[str, object]) -> None:
        assert await WebConnector().validate_config(config) is None


class TestTheSpellingItCompares:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("HTTPS://Docs.Example.com:443/a#top", "https://docs.example.com/a"),
            ("http://docs.example.com", "http://docs.example.com/"),
            ("https://docs.example.com:8443/a?page=2", "https://docs.example.com:8443/a?page=2"),
            ("https://[::1]/a", "https://[::1]/a"),
            ("https://user:pw@docs.example.com/", None),
            ("javascript:alert(1)", None),
            ("https://docs.example.com:notaport/", None),
            ("/relative", None),
        ],
    )
    def test_normalized_url(self, url: str, expected: str | None) -> None:
        assert normalized_url(url) == expected
