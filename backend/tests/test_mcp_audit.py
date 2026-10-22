"""Calling every listed MCP server and recording what it did (#2103).

The network is a `MockTransport` behind the real pinned client and DNS is a stub,
so each outcome is reached the way a real server would reach it: a status code,
a content type, a body. Nothing here dials out.
"""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import httpx2
import pytest

from app.agents.mcp import McpToolInfo
from app.agents.mcp_oauth import OAuthError
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.db.models.mcp_server_check import CheckOutcome
from app.services import mcp_audit
from app.services.mcp_audit import CheckRow, Probe, ToolCheck
from app.services.mcp_catalog import CatalogAuth, CatalogEntry

pytestmark = pytest.mark.anyio

_PUBLIC = "93.184.216.34"
_AT = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every name resolves to one public address, except those under `.gone`."""

    def fake_getaddrinfo(host: str, port: object, *_args: object, **_kwargs: object):
        if str(host).endswith(".gone"):
            raise socket.gaierror("no such host")
        return [(2, 1, 6, "", (_PUBLIC, port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _wire(*responses: httpx2.Response) -> httpx2.MockTransport:
    """Answers in order, the last one for every request after."""
    queue = list(responses)

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx2.MockTransport(handler)


def _initialized() -> httpx2.Response:
    return httpx2.Response(
        200, json={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "x"}}
    )


async def _probe(transport: httpx2.MockTransport, url: str = "https://mcp.example.com/mcp"):
    return await mcp_audit.probe_listing(url, timeout=5, transport=transport)


class TestOneServer:
    async def test_a_server_that_answers_and_lists_its_tools_is_open(self, monkeypatch):
        tools = [McpToolInfo("search", "", read_only=True), McpToolInfo("create", "")]
        monkeypatch.setattr(mcp_audit, "validate_mcp_url", AsyncMock())
        monkeypatch.setattr(mcp_audit, "probe_mcp_server", AsyncMock(return_value=tools))

        probe = await _probe(_wire(_initialized()))

        assert probe.outcome is CheckOutcome.OPEN
        assert probe.auth == "none"
        assert probe.tools == tuple(tools)

    async def test_a_stream_answer_is_an_mcp_server_too(self, monkeypatch):
        monkeypatch.setattr(mcp_audit, "validate_mcp_url", AsyncMock())
        monkeypatch.setattr(mcp_audit, "probe_mcp_server", AsyncMock(return_value=[]))

        answer = httpx2.Response(200, headers={"content-type": "text/event-stream"}, text="")
        assert (await _probe(_wire(answer))).outcome is CheckOutcome.OPEN

    async def test_a_handshake_whose_tools_would_not_list_is_still_open(self, monkeypatch):
        monkeypatch.setattr(mcp_audit, "validate_mcp_url", AsyncMock())
        monkeypatch.setattr(
            mcp_audit, "probe_mcp_server", AsyncMock(side_effect=RuntimeError("tools refused"))
        )

        probe = await _probe(_wire(_initialized()))

        assert probe.outcome is CheckOutcome.OPEN
        assert probe.tools is None
        assert "tools refused" in probe.detail

    async def test_a_handshake_whose_second_look_is_refused_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            mcp_audit, "validate_mcp_url", AsyncMock(side_effect=UrlRefusedError("private"))
        )

        assert (await _probe(_wire(_initialized()))).outcome is CheckOutcome.REFUSED

    @pytest.mark.parametrize("status", [401, 403])
    async def test_a_refusal_with_oauth_metadata_asks_for_sign_in(self, monkeypatch, status):
        monkeypatch.setattr(mcp_audit.mcp_oauth, "discover", AsyncMock())

        probe = await _probe(_wire(httpx2.Response(status)))

        assert (probe.outcome, probe.auth) == (CheckOutcome.SIGN_IN, "oauth")

    async def test_a_refusal_without_it_asks_for_a_token(self, monkeypatch):
        monkeypatch.setattr(
            mcp_audit.mcp_oauth, "discover", AsyncMock(side_effect=OAuthError("none"))
        )

        probe = await _probe(_wire(httpx2.Response(401)))

        assert (probe.outcome, probe.auth) == (CheckOutcome.TOKEN, "token")

    @pytest.mark.parametrize(
        "answer",
        [
            httpx2.Response(404),
            httpx2.Response(200, text="<html>a web page</html>"),
            httpx2.Response(200, headers={"content-type": "application/json"}, text="not json"),
            httpx2.Response(200, json=["not", "a", "reply"]),
            httpx2.Response(200, json={"jsonrpc": "2.0", "error": {"code": -1}}),
        ],
    )
    async def test_an_answer_that_is_not_an_mcp_server_is_broken(self, answer):
        assert (await _probe(_wire(answer))).outcome is CheckOutcome.BROKEN

    async def test_a_name_that_does_not_resolve_is_unreachable(self):
        probe = await _probe(_wire(_initialized()), "https://mcp.example.gone/mcp")

        assert probe.outcome is CheckOutcome.UNREACHABLE

    async def test_an_address_with_no_host_is_unreachable(self):
        assert (await _probe(_wire(_initialized()), "not a url")).outcome is (
            CheckOutcome.UNREACHABLE
        )

    async def test_a_connection_that_fails_is_unreachable(self):
        def refuse(_request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection refused")

        probe = await _probe(httpx2.MockTransport(refuse))

        assert probe.outcome is CheckOutcome.UNREACHABLE
        assert probe.detail == "ConnectError"

    async def test_an_address_inside_the_network_is_refused(self, monkeypatch):
        def private(host: str, port: object, *_args: object, **_kwargs: object):
            return [(2, 1, 6, "", ("10.0.0.5", port or 443))]

        monkeypatch.setattr(socket, "getaddrinfo", private)

        assert (await _probe(_wire(_initialized()))).outcome is CheckOutcome.REFUSED

    async def test_a_listed_host_is_refused_at_the_first_request(self, monkeypatch):
        """The audit judges public listings, and its results ship in the bundled
        snapshot every deployment seeds. So one deployment's `MCP_ALLOWED_HOSTS`
        must not let a listing that names an internal host be called. The second
        look and the tool listing are stubbed open, so `REFUSED` can only come
        from the pinned first request."""
        seen: list[httpx2.Request] = []

        def private(host: str, port: object, *_args: object, **_kwargs: object):
            return [(2, 1, 6, "", ("10.0.0.5", port or 443))]

        def answer(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return _initialized()

        monkeypatch.setattr(socket, "getaddrinfo", private)
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.example.com"])
        monkeypatch.setattr(mcp_audit, "validate_mcp_url", AsyncMock())
        monkeypatch.setattr(mcp_audit, "probe_mcp_server", AsyncMock(return_value=[]))

        assert (await _probe(httpx2.MockTransport(answer))).outcome is CheckOutcome.REFUSED
        assert seen == []

    async def test_a_listed_host_is_refused_at_the_second_look_too(self, monkeypatch):
        """The tool listing resolves the name again, so the address is checked
        again first, with the strict default. The name answers public to the
        first two lookups (`_resolves`, then the pinned request) and private to
        the third. Had that check honoured the list, the stub below would have
        made this read `OPEN`."""
        asked: list[str] = []

        def public_then_private(host: str, port: object, *_args: object, **_kwargs: object):
            asked.append(host)
            address = _PUBLIC if len(asked) <= 2 else "10.0.0.5"
            return [(2, 1, 6, "", (address, port or 443))]

        monkeypatch.setattr(socket, "getaddrinfo", public_then_private)
        monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", ["mcp.example.com"])
        monkeypatch.setattr(
            mcp_audit, "probe_mcp_server", AsyncMock(return_value=[McpToolInfo("search", "")])
        )

        assert (await _probe(_wire(_initialized()))).outcome is CheckOutcome.REFUSED
        assert asked == ["mcp.example.com"] * 3

    async def test_a_gateway_that_fails_once_is_asked_again(self, monkeypatch):
        monkeypatch.setattr(mcp_audit, "_RETRY_AFTER_S", 0)
        monkeypatch.setattr(mcp_audit.mcp_oauth, "discover", AsyncMock())

        probe = await _probe(_wire(httpx2.Response(502), httpx2.Response(401)))

        assert probe.outcome is CheckOutcome.SIGN_IN

    async def test_a_redirect_is_followed_a_few_hops_and_no_further(self, monkeypatch):
        moved = httpx2.Response(307, headers={"location": "https://mcp.example.com/mcp/"})
        monkeypatch.setattr(mcp_audit, "validate_mcp_url", AsyncMock())
        monkeypatch.setattr(mcp_audit, "probe_mcp_server", AsyncMock(return_value=[]))

        assert (await _probe(_wire(moved, _initialized()))).outcome is CheckOutcome.OPEN
        assert (await _probe(_wire(moved))).outcome is CheckOutcome.BROKEN


class TestMany:
    async def test_each_listing_gets_its_own_outcome(self, monkeypatch):
        async def by_url(url: str, *, timeout: float) -> Probe:
            return Probe(CheckOutcome.OPEN if "a" in url else CheckOutcome.BROKEN)

        monkeypatch.setattr(mcp_audit, "probe_listing", by_url)

        found = await mcp_audit.probe_many(
            [("one", "https://a.test"), ("two", "https://b.test")], concurrency=2, timeout=1
        )

        assert found["one"].outcome is CheckOutcome.OPEN
        assert found["two"].outcome is CheckOutcome.BROKEN

    async def test_a_server_that_never_finishes_answering_is_unreachable(self, monkeypatch):
        async def forever(url: str, *, timeout: float) -> Probe:
            await mcp_audit.asyncio.sleep(60)
            raise AssertionError("unreachable")

        monkeypatch.setattr(mcp_audit, "probe_listing", forever)

        found = await mcp_audit.probe_many(
            [("slow", "https://s.test")], concurrency=1, timeout=0.01
        )

        assert found["slow"].outcome is CheckOutcome.UNREACHABLE


class TestWhatCounts:
    def test_only_an_answering_server_is_verified(self):
        assert mcp_audit.verified("sign_in")
        assert not mcp_audit.verified("broken")
        assert not mcp_audit.verified(None)

    def test_a_curated_sign_in_must_offer_one(self):
        assert mcp_audit.verified("sign_in", declared="oauth")
        assert not mcp_audit.verified("token", declared="oauth")
        assert mcp_audit.verified("open", declared="token")

    def test_what_each_answer_asks_for(self):
        assert mcp_audit.auth_found(CheckOutcome.OPEN) == "none"
        assert mcp_audit.auth_found(CheckOutcome.TOKEN) == "token"
        assert mcp_audit.auth_found(CheckOutcome.BROKEN) is None

    def test_two_listings_at_one_address_keep_the_shorter_key(self):
        repeated = mcp_audit.duplicates(
            [
                ("com.acme/acme-mcp-server", "https://MCP.acme.com/mcp/"),
                ("com.acme/acme", "https://mcp.acme.com/mcp"),
                ("org.other/x", "https://other.test/mcp"),
            ]
        )

        assert repeated == {"com.acme/acme-mcp-server": "com.acme/acme"}

    def test_an_entry_without_an_address_cannot_be_called(self):
        hosted = CatalogEntry("a", "A", "", "other", CatalogAuth.TOKEN, url="https://a.test")
        theirs = CatalogEntry("b", "B", "", "other", CatalogAuth.TOKEN)

        assert mcp_audit.curated_listings([hosted, theirs]) == ([("a", "https://a.test")], ["b"])


def _rows() -> list[CheckRow]:
    return [
        CheckRow(
            "github",
            "catalog",
            CheckOutcome.SIGN_IN,
            _AT,
            auth="oauth",
            tools=(ToolCheck("search", True), ToolCheck("create", False)),
        ),
        CheckRow("postgres", "catalog", CheckOutcome.SELF_HOSTED, _AT),
        CheckRow("com.x/y", "registry", CheckOutcome.BROKEN, _AT, detail="HTTP 404"),
        CheckRow("com.x/z", "registry", CheckOutcome.DUPLICATE, _AT, duplicate_of="com.x/y"),
    ]


class TestARun:
    async def test_it_calls_what_it_can_and_records_what_it_cannot(self, monkeypatch):
        hosted = CatalogEntry("a", "A", "", "other", CatalogAuth.TOKEN, url="https://a.test")
        theirs = CatalogEntry("b", "B", "", "other", CatalogAuth.TOKEN)
        monkeypatch.setattr(mcp_audit, "CATALOG", (hosted, theirs))
        monkeypatch.setattr(
            mcp_audit.mcp_registry_server_repo,
            "listings",
            AsyncMock(
                return_value=[
                    ("r/1", "https://r1.test"),
                    ("r/1-copy", "https://r1.test/"),
                    ("r/2", "https://r2.test"),
                    ("r/3", "https://r3.test"),
                ]
            ),
        )
        called: list[str] = []

        async def probe_many(listings, *, concurrency: int, timeout: float):
            called.extend(key for key, _url in listings)
            tools = (McpToolInfo("t", "", read_only=True),)
            return {key: Probe(CheckOutcome.OPEN, tools=tools) for key, _url in listings}

        monkeypatch.setattr(mcp_audit, "probe_many", probe_many)

        rows = await mcp_audit.check_listings(
            AsyncMock(),
            sources=frozenset({"catalog", "registry"}),
            limit=1,
            concurrency=1,
            timeout=1,
        )

        by_key = {row.key: row for row in rows}
        assert called == ["a", "r/1"], "the limit narrows the registry, never the catalog"
        assert by_key["b"].outcome is CheckOutcome.SELF_HOSTED
        assert by_key["r/1-copy"].duplicate_of == "r/1"
        assert by_key["a"].tools == (ToolCheck("t", True),)

    async def test_the_catalog_alone_asks_nothing_of_the_registry(self, monkeypatch):
        listings = AsyncMock()
        monkeypatch.setattr(mcp_audit.mcp_registry_server_repo, "listings", listings)
        monkeypatch.setattr(
            mcp_audit,
            "probe_many",
            AsyncMock(
                side_effect=lambda pairs, **_: {k: Probe(CheckOutcome.TOKEN) for k, _ in pairs}
            ),
        )

        rows = await mcp_audit.check_listings(
            AsyncMock(), sources=frozenset({"catalog"}), limit=None, concurrency=1, timeout=1
        )

        listings.assert_not_awaited()
        assert rows and {row.source for row in rows} == {"catalog"}

    async def test_the_registry_alone_calls_every_listing_without_a_limit(self, monkeypatch):
        monkeypatch.setattr(
            mcp_audit.mcp_registry_server_repo,
            "listings",
            AsyncMock(return_value=[("r/1", "https://r1.test"), ("r/2", "https://r2.test")]),
        )
        monkeypatch.setattr(
            mcp_audit,
            "probe_many",
            AsyncMock(
                side_effect=lambda pairs, **_: {k: Probe(CheckOutcome.TOKEN) for k, _ in pairs}
            ),
        )

        rows = await mcp_audit.check_listings(
            AsyncMock(), sources=frozenset({"registry"}), limit=None, concurrency=1, timeout=1
        )

        assert sorted(row.key for row in rows) == ["r/1", "r/2"]

    async def test_a_full_run_forgets_listings_it_did_not_reach(self, monkeypatch):
        upsert = AsyncMock()
        stale = AsyncMock(return_value=3)
        monkeypatch.setattr(mcp_audit.mcp_server_check_repo, "upsert_many", upsert)
        monkeypatch.setattr(mcp_audit.mcp_server_check_repo, "delete_stale", stale)

        assert await mcp_audit.write_checks(AsyncMock(), _rows(), prune=True) == 4
        stale.assert_awaited_once()
        assert stale.await_args.args[1] == _AT

        stale.reset_mock()
        await mcp_audit.write_checks(AsyncMock(), _rows(), prune=False)
        await mcp_audit.write_checks(AsyncMock(), [], prune=True)
        stale.assert_not_awaited()
        stored = upsert.await_args_list[0].args[1]
        assert (stored[0]["tools"], stored[0]["read_only_tools"]) == (2, 1)
        assert stored[0]["outcome"] == "sign_in"


class TestWhatItWrites:
    def test_the_report_lists_every_curated_entry_and_sums_the_registry(self, monkeypatch):
        monkeypatch.setattr(
            mcp_audit,
            "CATALOG",
            (
                CatalogEntry("github", "GitHub", "", "dev", CatalogAuth.OAUTH, url="https://g"),
                CatalogEntry("postgres", "Postgres", "", "data", CatalogAuth.TOKEN),
            ),
        )

        report = mcp_audit.report_markdown(_rows())

        assert "## Curated: 2" in report
        assert "## Registry: 2" in report
        assert "| github | oauth | sign_in | 2 (1) | yes |" in report
        assert "| postgres | token | self_hosted |  | no |" in report

    def test_an_empty_run_still_reports(self):
        assert mcp_audit.report_markdown([]).startswith("# MCP catalog check")

    def test_the_json_keeps_the_detail_and_the_snapshot_does_not(self):
        everything = json.loads(mcp_audit.report_json(_rows()))
        snapshot = json.loads(mcp_audit.snapshot_json(_rows()))

        assert {row["detail"] for row in everything} >= {"HTTP 404"}
        assert all("detail" not in row for row in snapshot)
        assert [row["key"] for row in snapshot] == ["github", "postgres", "com.x/y", "com.x/z"]
        assert (snapshot[0]["tools"], snapshot[0]["read_only_tools"]) == (2, 1)

    async def test_a_snapshot_seeds_what_a_deployment_has_not_checked(self, monkeypatch, tmp_path):
        target = mcp_audit.write_snapshot(_rows(), tmp_path / "checks.json")
        monkeypatch.setattr(
            mcp_audit.catalog,
            "load",
            lambda _name, adapter: adapter.validate_json(target.read_bytes()),
        )
        insert = AsyncMock(return_value=4)
        monkeypatch.setattr(mcp_audit.mcp_server_check_repo, "insert_missing", insert)

        assert await mcp_audit.seed_snapshot(AsyncMock()) == 4
        rows = insert.await_args.args[1]
        assert rows[0]["key"] == "github" and rows[0]["outcome"] == "sign_in"

    def test_the_default_snapshot_is_the_bundled_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mcp_audit.catalog, "__file__", str(tmp_path / "__init__.py"))

        written = mcp_audit.write_snapshot(_rows())

        assert written == Path(tmp_path / mcp_audit.SNAPSHOT)
        assert json.loads(written.read_text())

    def test_the_bundled_snapshot_parses(self):
        """It is seeded at bootstrap, so a malformed file would stop a first install."""
        assert mcp_audit.catalog.load(mcp_audit.SNAPSHOT, mcp_audit._SNAPSHOT_ROWS) is not None
