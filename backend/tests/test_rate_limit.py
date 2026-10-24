"""How often a stranger may reach a public surface.

Every assertion here is about a refusal that did not happen for the whole life
of the product. A limiter was constructed, registered on the app and applied to
no route; a second, Redis-backed one sat in `app/services/rate_limit/` and could
not have been imported at all, because it read a `get_redis` that
`app/core/cache.py` has never defined (#39, audit 7).

So the tests worth having are: that the count crosses workers, that a proxy's
address is not mistaken for a visitor's, that the header which could fix that is
not trusted by default, and that a Redis nobody can reach degrades to no limit
rather than to no service.
"""

from contextlib import AbstractAsyncContextManager, AsyncExitStack
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.services import rate_limit
from app.services.rate_limit import Limit

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _unconfigured():
    """Every test says for itself whether a limiter exists."""
    rate_limit.configure(None)
    yield
    rate_limit.configure(None)


def _redis(counts: list[int] | None = None) -> MagicMock:
    """A client whose window counter answers with the given sequence."""
    client = MagicMock()
    client.count_in_window = AsyncMock(side_effect=counts or [1])
    return client


def _connection(host: str | None = "203.0.113.7", **headers: str) -> MagicMock:
    connection = MagicMock()
    connection.client = None if host is None else MagicMock(host=host)
    connection.headers = headers
    return connection


class TestTheAllowanceItself:
    async def test_an_attempt_inside_the_allowance_is_let_through(self):
        rate_limit.configure(_redis([1]))

        decision = await rate_limit.consume(
            surface="s", caller="c", limit=Limit(attempts=3, window_seconds=60)
        )

        assert decision.allowed is True
        assert decision.metered is True

    async def test_the_attempt_after_the_allowance_is_refused(self):
        """Four attempts against a limit of three: the fourth is the one the
        window has no room for."""
        rate_limit.configure(_redis([4]))

        decision = await rate_limit.consume(
            surface="s", caller="c", limit=Limit(attempts=3, window_seconds=60)
        )

        assert decision.allowed is False
        assert decision.retry_after_seconds == 60

    async def test_the_last_attempt_inside_the_allowance_still_counts_as_inside(self):
        """Off-by-one in the direction that matters: a limit of three has to
        allow the third, not refuse it."""
        rate_limit.configure(_redis([3]))

        decision = await rate_limit.consume(
            surface="s", caller="c", limit=Limit(attempts=3, window_seconds=60)
        )

        assert decision.allowed is True

    async def test_the_count_is_kept_per_surface_and_per_caller(self):
        """One key per pair, so the run API and a widget do not share a bucket
        and two callers do not spend each other's allowance."""
        client = _redis([1, 1])
        rate_limit.configure(client)

        await rate_limit.consume(surface="agent_run", caller="user:a", limit=Limit(attempts=1))
        await rate_limit.consume(surface="embed_admission", caller="ip:1.2.3.4", limit=Limit(1))

        keys = [call.args[0] for call in client.count_in_window.await_args_list]
        assert keys == ["ratelimit:agent_run:user:a", "ratelimit:embed_admission:ip:1.2.3.4"]

    async def test_an_oversized_caller_is_digested_so_it_cannot_bloat_redis(self):
        """The login identifier is caller-controlled and unbounded, so a raw key
        would let one request store megabytes. Past the bound it becomes a
        fixed-size hash; the key stays small (#947)."""
        client = _redis([1])
        rate_limit.configure(client)

        await rate_limit.consume(
            surface="auth_login", caller=f"id:{'a' * 1_000_000}", limit=Limit(attempts=3)
        )

        key = client.count_in_window.await_args_list[0].args[0]
        assert key.startswith("ratelimit:auth_login:h:")
        assert len(key) < 128

    async def test_the_window_is_what_the_key_expires_after(self):
        """A window that never expires is an allowance somebody spends once and
        never gets back."""
        client = _redis([1])
        rate_limit.configure(client)

        await rate_limit.consume(
            surface="s", caller="c", limit=Limit(attempts=1, window_seconds=90)
        )

        assert client.count_in_window.await_args.kwargs == {"ttl": 90}


class TestDegradingRatherThanRefusing:
    async def test_no_limiter_configured_lets_the_caller_through(self):
        """A test client, a script, a deployment mid-boot. Refusing here would
        make the limiter a hard dependency of every public request."""
        decision = await rate_limit.consume(surface="s", caller="c", limit=Limit(attempts=1))

        assert decision.allowed is True
        assert decision.metered is False, "allowed by default, not by a count"

    async def test_an_unreachable_redis_lets_the_caller_through(self):
        """The same trade-off, and the same reasoning, as the channel dedupe
        claim: losing the guarantee beats losing the visitor's answer. The
        decision says it was not counted, so a surface that must keep a floor
        under the caller - the channel router - can count locally meanwhile."""
        client = MagicMock()
        client.count_in_window = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(client)

        decision = await rate_limit.consume(surface="s", caller="c", limit=Limit(attempts=1))

        assert decision.allowed is True
        assert decision.metered is False

    async def test_degrading_is_logged_rather_than_silent(self, caplog):
        """ "Under the limit" and "not limited at all" are the same response, so
        the log line is the only thing that tells an operator which one it is."""
        with caplog.at_level("WARNING"):
            await rate_limit.consume(surface="agent_run", caller="user:a", limit=Limit(1))

        assert "unmetered" in caplog.text

    @pytest.mark.security
    async def test_the_degraded_line_names_the_surface_but_not_the_caller(self, caplog):
        """A caller can be a public link's key or a form's token, so the line that
        says it went unmetered must not be where that credential is written down."""
        caller = "key:pk_live_secret_public_link_key"
        with caplog.at_level("WARNING"):
            await rate_limit.consume(surface="public_artifact", caller=caller, limit=Limit(1))

        (record,) = [r for r in caplog.records if "unmetered" in r.getMessage()]
        assert "public_artifact" in record.getMessage()
        assert caller not in record.getMessage()
        assert "pk_live_secret_public_link_key" not in repr(record.args)


class TestALocalFloorWhenTheSharedLimiterCannotCount:
    """`consume_with_local_floor` is for a surface whose limit is a production
    control - a Virtual Tables write bounds how fast a tenant grows the shared
    database - where the shared limiter's fail-open default would remove the limit
    entirely for the length of a Redis outage (#1823)."""

    async def test_a_counted_decision_is_passed_straight_through(self):
        """When Redis answers, the shared count is the whole answer and the local
        window is not consulted at all."""
        rate_limit.configure(_redis([4]))

        decision = await rate_limit.consume_with_local_floor(
            surface="table_write", caller="c", limit=Limit(attempts=3)
        )

        assert decision.allowed is False
        assert decision.metered is True

    async def test_an_unmetered_decision_is_bounded_on_this_worker(self, monkeypatch):
        """A Redis that cannot be reached would leave the surface unmetered; the
        per-process window holds the same allowance instead of none."""
        client = MagicMock()
        client.count_in_window = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(client)
        monkeypatch.setattr(rate_limit, "_floor", rate_limit.LocalWindows())

        decisions = [
            await rate_limit.consume_with_local_floor(
                surface="table_write", caller="org:o:user:u", limit=Limit(attempts=2)
            )
            for _ in range(3)
        ]

        assert [d.allowed for d in decisions] == [True, True, False]
        assert all(d.metered is False for d in decisions)
        assert decisions[-1].retry_after_seconds == 60

    async def test_the_floor_is_kept_per_surface_and_per_caller(self, monkeypatch):
        """The caller is namespaced by surface, so a table write and a channel
        turn do not spend each other's floor while Redis is down."""
        monkeypatch.setattr(rate_limit, "_floor", rate_limit.LocalWindows())

        first = await rate_limit.consume_with_local_floor(
            surface="table_write", caller="c", limit=Limit(attempts=1)
        )
        again = await rate_limit.consume_with_local_floor(
            surface="table_write", caller="c", limit=Limit(attempts=1)
        )
        elsewhere = await rate_limit.consume_with_local_floor(
            surface="ml_call", caller="c", limit=Limit(attempts=1)
        )

        assert first.allowed is True
        assert again.allowed is False
        assert elsewhere.allowed is True


class TestTheLocalWindowItself:
    def test_it_forgets_windows_that_have_expired(self):
        """Bounded the way the shared window is bounded by its TTL: an entry lives
        one window, so the map holds the callers of the last window, not all of them."""
        clock = iter([0.0, 1.0, 61.0, 62.0])
        windows = rate_limit.LocalWindows(clock=lambda: next(clock))

        assert windows.consume("a", attempts=1, window_seconds=60) is True
        assert windows.consume("a", attempts=1, window_seconds=60) is False
        assert windows.consume("b", attempts=1, window_seconds=60) is True
        assert windows.consume("a", attempts=1, window_seconds=60) is True, "a new window"
        assert len(windows) == 2


class TestReadingWithoutCounting:
    """`exhausted`: the check made before work that is counted only if it fails."""

    async def test_nothing_is_exhausted_without_a_limiter_or_a_readable_count(self):
        assert await rate_limit.exhausted(surface="s", caller="c", limit=Limit(1)) is False

        client = MagicMock()
        client.get = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(client)
        assert await rate_limit.exhausted(surface="s", caller="c", limit=Limit(1)) is False

    @pytest.mark.parametrize(("stored", "over"), [(None, False), ("0", False), ("1", True)])
    async def test_it_reads_the_window_and_counts_nothing(self, stored, over):
        client = MagicMock()
        client.get = AsyncMock(return_value=stored)
        client.count_in_window = AsyncMock()
        rate_limit.configure(client)

        assert await rate_limit.exhausted(surface="s", caller="c", limit=Limit(1)) is over
        assert client.get.await_args.args == ("ratelimit:s:c",)
        client.count_in_window.assert_not_awaited()


class TestAKeyReadWithoutBeingSpent:
    """`/mcp` reads a key's allowance; the API its tool calls reach spends it."""

    @pytest.mark.parametrize(("stored", "refused"), [(None, False), ("600", True)])
    async def test_the_allowance_is_read_and_nothing_is_counted(self, stored, refused):
        client = MagicMock()
        client.get = AsyncMock(side_effect=lambda key: stored if ":api_key:" in key else None)
        client.count_in_window = AsyncMock()
        rate_limit.configure(client)

        answer = await rate_limit.key_attempt_refused(_connection(), "aos_x", count=False)

        assert (answer is not None) is refused
        client.count_in_window.assert_not_awaited()


class TestWhichAddressIsCounted:
    def test_the_socket_and_the_request_are_read_the_same_way(self):
        """Both are `HTTPConnection`, and the widget's handshake needs the same
        answer as its config request."""
        assert rate_limit.caller_ip(_connection(host="198.51.100.4")) == "198.51.100.4"

    def test_a_forwarded_header_is_ignored_by_default(self, monkeypatch):
        """It is set by whoever is calling. Trusted unconditionally, a per-IP
        limit becomes a per-header limit anybody bypasses by varying a string."""
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", False)

        address = rate_limit.caller_ip(
            _connection(host="10.0.0.1", **{"x-forwarded-for": "1.1.1.1"})
        )

        assert address == "10.0.0.1"

    def test_a_trusted_deployment_counts_the_hop_its_own_proxy_wrote(self, monkeypatch):
        """Behind a proxy the socket's peer is the proxy, so every visitor would
        share one bucket. The trusted proxy appends the real peer, so the address
        to count is the rightmost entry - the one it wrote, not the list head the
        client controls."""
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", True)

        address = rate_limit.caller_ip(
            _connection(host="10.0.0.1", **{"x-forwarded-for": "1.1.1.1, 203.0.113.9"})
        )

        assert address == "203.0.113.9"

    def test_a_spoofed_leftmost_entry_cannot_mint_a_fresh_bucket(self, monkeypatch):
        """The header is a list the client starts and each proxy appends to. A
        caller varying the leftmost entry per request must not land in a new
        bucket each time - the counted address is the hop the trusted proxy added,
        which they cannot forge."""
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", True)

        first = rate_limit.caller_ip(_connection(**{"x-forwarded-for": "evil-1, 203.0.113.9"}))
        second = rate_limit.caller_ip(_connection(**{"x-forwarded-for": "evil-2, 203.0.113.9"}))

        assert first == second == "203.0.113.9"

    def test_a_forwarded_header_of_only_commas_falls_back_to_unknown(self, monkeypatch):
        """A rightmost entry that is empty must not key everybody sending it into
        one shared bucket."""
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", True)

        assert rate_limit.caller_ip(_connection(**{"x-forwarded-for": "9.9.9.9 , "})) == "unknown"

    def test_an_empty_forwarded_header_falls_back_to_the_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", True)

        assert rate_limit.caller_ip(_connection(**{"x-forwarded-for": ""})) == "203.0.113.7"

    def test_a_connection_with_no_peer_at_all_is_still_counted(self, monkeypatch):
        """Starlette reports none for a test transport, and an unkeyed limit
        would be no limit."""
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", False)

        assert rate_limit.caller_ip(_connection(host=None)) == "unknown"


class TestTheLimitsThemselves:
    def test_the_run_allowance_comes_from_settings(self, monkeypatch):
        """So a deployment can raise or lower it without a release."""
        monkeypatch.setattr(settings, "RATE_LIMIT_RUN_PER_MINUTE", 7)

        assert rate_limit.run_limit() == Limit(attempts=7, window_seconds=60)

    def test_the_auth_allowance_comes_from_settings(self, monkeypatch):
        """The auth surface has its own low ceiling, tunable without a release."""
        monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 5)

        assert rate_limit.auth_limit() == Limit(attempts=5, window_seconds=60)

    def test_the_export_allowance_is_counted_per_hour(self, monkeypatch):
        """Not per minute, and the window is the point. What is rationed is not
        load - assembling everything about a person is cheap - but how fast a
        stolen session can walk the deployment's people (#1421)."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EXPORT_PER_HOUR", 3)

        assert rate_limit.export_limit() == Limit(attempts=3, window_seconds=3_600)

    async def test_admission_is_counted_per_address(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_PER_MINUTE", 2)
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", False)
        client = _redis([1])
        rate_limit.configure(client)

        assert (await rate_limit.embed_admission_allowed(_connection())).allowed is True
        assert client.count_in_window.await_args.args[0] == (
            "ratelimit:embed_admission:ip:203.0.113.7"
        )

    async def test_admission_is_refused_once_an_address_has_had_its_allowance(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_PER_MINUTE", 2)
        rate_limit.configure(_redis([3]))

        assert (await rate_limit.embed_admission_allowed(_connection())).allowed is False

    async def test_the_script_is_counted_apart_from_the_admission_it_precedes(self, monkeypatch):
        """A widget page load fetches the script, then a config, then opens a
        socket. Sharing one counter made the configured twenty admissions a minute
        about seven page loads - a number wrong by a factor of three, which is worse
        than none because it reads as the one that was set. The script is the one
        separated: it is cacheable, and a refusal of it breaks the widget outright
        rather than delaying a message.
        """
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_PER_MINUTE", 2)
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", False)
        client = _redis([1, 1])
        rate_limit.configure(client)

        assert (await rate_limit.embed_script_allowed(_connection())).allowed is True
        script_key = client.count_in_window.await_args.args[0]
        assert (await rate_limit.embed_admission_allowed(_connection())).allowed is True
        admission_key = client.count_in_window.await_args.args[0]

        assert script_key == "ratelimit:embed_script:ip:203.0.113.7"
        assert script_key != admission_key

    async def test_the_script_shares_the_widget_allowance_it_does_not_share_a_bucket(
        self, monkeypatch
    ):
        """One setting, two counters. A second setting would be a second number for
        an operator to keep in step with the first, for no decision they make
        differently."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_PER_MINUTE", 5)
        rate_limit.configure(_redis([6]))

        assert (await rate_limit.embed_script_allowed(_connection())).allowed is False


class TestTheHostedPageIsCountedPerPage:
    """The one surface whose caller is not its visitor.

    `/hosted` is fetched by the frontend server, so the address on the request is
    a container's and every visitor in the deployment arrives as the same one.
    Counted per address it was a single bucket for everybody - ten page loads a
    minute at the widget's allowance, served to the eleventh visitor as a 404 -
    and no setting could have fixed it, because a server-side `fetch` sends no
    `X-Forwarded-For` to trust.
    """

    async def test_the_bucket_is_the_page_and_not_an_address(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_HOSTED_PAGE_PER_MINUTE", 5)
        client = _redis([1])
        rate_limit.configure(client)

        assert (await rate_limit.hosted_admission_allowed("abc123")).allowed is True
        assert client.count_in_window.await_args.args[0] == "ratelimit:hosted_config:key:abc123"

    async def test_two_pages_do_not_share_one_allowance(self, monkeypatch):
        """The failure this replaces, stated as the property it must not have: one
        busy page must not be able to take another page down."""
        monkeypatch.setattr(settings, "RATE_LIMIT_HOSTED_PAGE_PER_MINUTE", 5)
        client = _redis([1, 1])
        rate_limit.configure(client)

        await rate_limit.hosted_admission_allowed("first")
        await rate_limit.hosted_admission_allowed("second")

        keys = [call.args[0] for call in client.count_in_window.await_args_list]
        assert keys == ["ratelimit:hosted_config:key:first", "ratelimit:hosted_config:key:second"]

    async def test_a_page_over_its_allowance_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_HOSTED_PAGE_PER_MINUTE", 5)
        rate_limit.configure(_redis([6]))

        assert (await rate_limit.hosted_admission_allowed("abc123")).allowed is False

    async def test_the_allowance_is_its_own_setting_and_a_wider_one(self, monkeypatch):
        """Not the widget's twenty: that number rations one visitor, and this one
        bounds a whole page. Reusing it would have moved the same squeeze onto a
        single link rather than removing it."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_PER_MINUTE", 20)
        client = _redis([1])
        rate_limit.configure(client)

        await rate_limit.hosted_admission_allowed("abc123")

        assert settings.RATE_LIMIT_HOSTED_PAGE_PER_MINUTE > settings.RATE_LIMIT_EMBED_PER_MINUTE

    async def test_the_logo_is_counted_per_page_on_its_own_surface(self, monkeypatch):
        """The logo is fetched server-side through the same proxy, so per address
        it shared the deployment-wide bucket the config route did. Its own surface,
        so a page's logo fetches and its config fetches do not spend each other's
        allowance."""
        monkeypatch.setattr(settings, "RATE_LIMIT_HOSTED_PAGE_PER_MINUTE", 5)
        client = _redis([1])
        rate_limit.configure(client)

        assert (await rate_limit.hosted_logo_allowed("abc123")).allowed is True
        assert client.count_in_window.await_args.args[0] == "ratelimit:hosted_logo:key:abc123"


class TestAnArtifactAddressIsCountedPerAddress:
    """One signed content address, however it was obtained, is one frame's load
    and a reload or two - not a way to pull a page out of storage on a loop."""

    async def test_the_bucket_is_the_address_by_its_digest(self):
        client = _redis([1])
        rate_limit.configure(client)

        assert (await rate_limit.artifact_content_allowed("eyJ.token.sig")).allowed is True
        key = client.count_in_window.await_args.args[0]
        assert key.startswith("ratelimit:artifact_content:token:")
        assert "eyJ.token.sig" not in key

    async def test_two_addresses_do_not_share_one_allowance(self):
        client = _redis([1, 1])
        rate_limit.configure(client)

        await rate_limit.artifact_content_allowed("first")
        await rate_limit.artifact_content_allowed("second")

        first, second = (call.args[0] for call in client.count_in_window.await_args_list)
        assert first != second

    @pytest.mark.security
    async def test_an_address_loaded_past_its_allowance_is_refused(self):
        rate_limit.configure(_redis([rate_limit.ARTIFACT_CONTENT_LOADS_PER_MINUTE + 1]))

        assert (await rate_limit.artifact_content_allowed("t")).allowed is False


class TestAGeneratedMediaLinkIsCountedPerLink:
    """One signed link to a generated file is one visitor's player - a dozen ranged
    requests a play - not a way to pull a clip out of storage on a loop."""

    async def test_the_bucket_is_the_link_by_its_digest(self):
        client = _redis([1])
        rate_limit.configure(client)

        assert (await rate_limit.embed_generated_media_allowed("1761200000.abab")).allowed is True
        key = client.count_in_window.await_args.args[0]
        assert key.startswith("ratelimit:embed_generated_media:token:")
        assert "1761200000.abab" not in key

    @pytest.mark.security
    async def test_a_link_fetched_past_its_allowance_is_refused(self):
        rate_limit.configure(_redis([rate_limit.EMBED_GENERATED_MEDIA_LOADS_PER_MINUTE + 1]))

        assert (await rate_limit.embed_generated_media_allowed("t")).allowed is False


class TestMapTilesAreCountedPerAddress:
    async def test_the_bucket_is_the_caller_s_address(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", False)
        client = _redis([1])
        rate_limit.configure(client)

        assert (await rate_limit.map_tiles_allowed(_connection())).allowed is True
        assert client.count_in_window.await_args.args[0] == "ratelimit:map_tiles:ip:203.0.113.7"

    @pytest.mark.security
    async def test_an_address_past_its_allowance_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_MAP_TILES_PER_MINUTE", 2)
        rate_limit.configure(_redis([3]))

        assert (await rate_limit.map_tiles_allowed(_connection())).allowed is False


class TestStoringAFileIsCountedTwice:
    """The upload is the only public route that writes bytes to a disk, and the
    only one whose caller has two identities worth counting.

    Counting only the continuity key bounds nothing at all: the key is minted by
    the browser and any 32 hex characters is a valid one, so a script that varies
    it gets the whole allowance again per file. Counting only the address lets one
    browser on a shared one spend everybody's. So both, and both have to allow it.
    """

    async def test_the_address_is_counted_first(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE", 5)
        monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_FORWARDED_FOR", False)
        client = _redis([1, 1])
        rate_limit.configure(client)

        decision = await rate_limit.embed_upload_allowed(
            _connection(), public_key="pk_abc", visitor="a" * 32
        )

        assert decision.allowed is True
        counted = [call.args[0] for call in client.count_in_window.await_args_list]
        assert counted == [
            "ratelimit:embed_upload:ip:203.0.113.7",
            f"ratelimit:embed_upload:key:pk_abc:visitor:{'a' * 32}",
        ]

    async def test_a_fresh_key_does_not_buy_a_fresh_allowance(self, monkeypatch):
        """The hole this closes: the key is the browser's to choose."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE", 5)
        client = _redis([9])
        rate_limit.configure(client)

        decision = await rate_limit.embed_upload_allowed(
            _connection(), public_key="pk_abc", visitor="b" * 32
        )

        assert decision.allowed is False
        # The visitor's own bucket was never reached, so varying the key cannot
        # get past a refusal the address already earned.
        assert client.count_in_window.await_count == 1

    async def test_one_browser_cannot_spend_a_shared_addresss_allowance(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_UPLOAD_PER_MINUTE", 5)
        rate_limit.configure(_redis([1, 9]))

        decision = await rate_limit.embed_upload_allowed(
            _connection(), public_key="pk_abc", visitor="c" * 32
        )

        assert decision.allowed is False


class TestAFormIsCountedPerForm:
    """A workflow's public form is read and submitted through the console's server,
    so every visitor arrives as the same caller: the bucket is the form."""

    async def test_reading_and_submitting_are_two_buckets_of_one_form(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_FORM_SUBMISSIONS_PER_MINUTE", 3)
        client = _redis([1, 1])
        rate_limit.configure(client)

        assert (await rate_limit.form_page_allowed("tok")).allowed is True
        assert (await rate_limit.form_submission_allowed("tok")).allowed is True

        keys = [call.args[0] for call in client.count_in_window.await_args_list]
        assert keys == [
            "ratelimit:workflow_form_page:form:tok",
            "ratelimit:workflow_form_submission:form:tok",
        ]

    async def test_a_form_over_its_submissions_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_FORM_SUBMISSIONS_PER_MINUTE", 3)
        rate_limit.configure(_redis([4]))

        assert (await rate_limit.form_submission_allowed("tok")).allowed is False


class TestAWebhookIsCountedPerExposureAndPerAddress:
    async def test_a_run_spends_its_exposures_allowance(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_WORKFLOW_WEBHOOK_PER_MINUTE", 2)
        client = _redis([1, 3])
        rate_limit.configure(client)

        assert (await rate_limit.workflow_webhook_allowed("wh")).allowed is True
        assert (await rate_limit.workflow_webhook_allowed("wh")).allowed is False
        assert client.count_in_window.await_args.args[0] == (
            "ratelimit:workflow_webhook:exposure:wh"
        )

    async def test_a_request_spends_its_addresss_allowance(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_WORKFLOW_WEBHOOK_IP_PER_MINUTE", 2)
        client = _redis([1, 3])
        rate_limit.configure(client)

        assert (await rate_limit.workflow_webhook_ip_allowed(_connection())).allowed is True
        assert (await rate_limit.workflow_webhook_ip_allowed(_connection())).allowed is False
        assert client.count_in_window.await_args.args[0].startswith(
            "ratelimit:workflow_webhook_ip:ip:"
        )


def _claims() -> tuple[MagicMock, dict[str, str]]:
    """A client whose `SET NX` and compare-and-delete act on a dict, as Redis would."""
    store: dict[str, str] = {}

    async def claim(key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def delete_if_equals(key: str, value: str) -> bool:
        if store.get(key) != value:
            return False
        del store[key]
        return True

    client = MagicMock()
    client.set = AsyncMock(side_effect=claim)
    client.delete_if_equals = AsyncMock(side_effect=delete_if_equals)
    return client, store


def _in_flight(caller: str = "org:o:user:u") -> AbstractAsyncContextManager[None]:
    return rate_limit.one_in_flight("artifact_data", caller, ttl_seconds=10, message="Busy.")


class TestOneLoadInFlight:
    """At most one data load per viewer at a time, refused at once rather than queued."""

    async def test_artifact_data_limit_reads_the_setting(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_ARTIFACT_DATA_PER_MINUTE", 7)

        assert rate_limit.artifact_data_limit() == Limit(attempts=7)

    @pytest.mark.security
    async def test_a_held_claim_refuses_the_same_caller_and_no_other(self):
        client, store = _claims()
        rate_limit.configure(client)

        async with _in_flight():
            assert list(store) == ["inflight:artifact_data:org:o:user:u"]
            client.set.assert_awaited_once()
            assert client.set.await_args.kwargs == {"ttl": 10, "nx": True}
            with pytest.raises(RateLimitError) as refused:
                async with _in_flight():
                    pass
            async with _in_flight("org:o:user:other"):
                pass

        assert refused.value.message == "Busy."
        assert store == {}

    @pytest.mark.security
    async def test_one_in_flight_falls_back_to_the_process_when_redis_is_down(self):
        client = MagicMock()
        client.set = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(client)

        async with _in_flight():
            with pytest.raises(RateLimitError):
                async with _in_flight():
                    pass
            async with _in_flight("org:o:user:other"):
                pass
        async with _in_flight():
            pass

    @pytest.mark.security
    async def test_one_in_flight_holds_per_process_when_unconfigured(self):
        async with _in_flight():
            with pytest.raises(RateLimitError):
                async with _in_flight():
                    pass

    async def test_one_in_flight_releases_on_error(self):
        client, store = _claims()
        rate_limit.configure(client)

        with pytest.raises(ValueError, match="boom"):
            async with _in_flight():
                raise ValueError("boom")
        assert store == {}
        rate_limit.configure(None)
        with pytest.raises(ValueError, match="boom"):
            async with _in_flight():
                raise ValueError("boom")
        async with _in_flight():
            pass

    @pytest.mark.security
    async def test_one_in_flight_never_releases_a_key_it_no_longer_holds(self):
        """A load that outlived its claim's TTL must not free the next load's claim."""
        client, store = _claims()
        rate_limit.configure(client)
        key = "inflight:artifact_data:org:o:user:u"

        async with AsyncExitStack() as later:
            async with _in_flight():
                first = store.pop(key)
                await later.enter_async_context(_in_flight())
                second = store[key]
            assert first != second
            assert store == {key: second}
        assert store == {}

    async def test_a_release_redis_refuses_is_left_to_the_ttl(self):
        client, store = _claims()
        client.delete_if_equals = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(client)

        async with _in_flight():
            pass

        assert list(store) == ["inflight:artifact_data:org:o:user:u"]


class TestAVisitorsCall:
    """Every voice call is a paid realtime session (#54)."""

    async def test_before_admission_only_the_address_is_counted(self, monkeypatch):
        """Codex on #2204: the link's minute spent before the token was checked let
        anybody holding a `jwt` widget's key deny its calls to signed-in visitors."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_VOICE_PER_MINUTE", 3)
        client = _redis([1])
        rate_limit.configure(client)

        decision = await rate_limit.embed_voice_allowed(_connection())

        assert decision.allowed is True
        counted = [call.args[0] for call in client.count_in_window.await_args_list]
        assert counted == ["ratelimit:embed_voice:ip:203.0.113.7"]

    async def test_an_address_past_its_calls_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_VOICE_PER_MINUTE", 3)
        rate_limit.configure(_redis([4]))

        assert (await rate_limit.embed_voice_allowed(_connection())).allowed is False

    async def test_the_links_ceiling_holds_whatever_address_calls(self, monkeypatch):
        """What bounds a leaked link: no visitor can vary the key in the path."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_VOICE_PER_LINK_PER_MINUTE", 6)
        client = _redis([7])
        rate_limit.configure(client)

        decision = await rate_limit.embed_voice_link_allowed(public_key="pk_abc")

        assert decision.allowed is False
        assert client.count_in_window.await_args.args[0] == "ratelimit:embed_voice:key:pk_abc"


class TestASignedInVisitorsCalls:
    async def test_a_signed_in_visitor_is_counted_by_their_subject(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_VOICE_PER_MINUTE", 3)
        client = _redis([4])
        rate_limit.configure(client)

        decision = await rate_limit.embed_voice_visitor_allowed(
            public_key="pk_abc", visitor="customer-42"
        )

        assert decision.allowed is False
        assert client.count_in_window.await_args.args[0] == (
            "ratelimit:embed_voice:key:pk_abc:visitor:customer-42"
        )


class TestAVisitorsDictation:
    """Every dictation is a paid call outside every model budget (#1797)."""

    async def test_before_admission_only_the_address_is_counted(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_MINUTE", 6)
        client = _redis([1])
        rate_limit.configure(client)

        decision = await rate_limit.embed_dictation_allowed(_connection())

        assert decision.allowed is True
        counted = [call.args[0] for call in client.count_in_window.await_args_list]
        assert counted == ["ratelimit:embed_dictation:ip:203.0.113.7"]

    async def test_a_refused_address_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_MINUTE", 6)
        rate_limit.configure(_redis([7]))

        assert (await rate_limit.embed_dictation_allowed(_connection())).allowed is False

    async def test_the_links_ceiling_holds_whatever_address_calls(self, monkeypatch):
        """What bounds a leaked link: no visitor can vary the key in the path."""
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_LINK_PER_MINUTE", 30)
        client = _redis([31])
        rate_limit.configure(client)

        decision = await rate_limit.embed_dictation_link_allowed(public_key="pk_abc")

        assert decision.allowed is False
        assert client.count_in_window.await_args.args[0] == "ratelimit:embed_dictation:key:pk_abc"

    async def test_a_signed_in_visitor_is_counted_by_their_subject(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_MINUTE", 6)
        client = _redis([7])
        rate_limit.configure(client)

        decision = await rate_limit.embed_dictation_visitor_allowed(
            public_key="pk_abc", visitor="customer-42"
        )

        assert decision.allowed is False
        assert client.count_in_window.await_args.args[0] == (
            "ratelimit:embed_dictation:key:pk_abc:visitor:customer-42"
        )


class TestPaidSurfacesKeepAFloorWhileRedisIsDown:
    """A dictation or a call is a paid provider call, and the limit is all that
    bounds a stranger's spend on a public link: failing open there would make a
    Redis outage unlimited paid calls (Codex on #2138)."""

    async def test_an_address_is_held_to_its_allowance_with_no_limiter(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_MINUTE", 6)
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_LINK_PER_MINUTE", 100)

        decisions = [await rate_limit.embed_dictation_allowed(_connection()) for _ in range(7)]

        assert [d.allowed for d in decisions] == [True] * 6 + [False]
        assert decisions[-1].metered is False
        assert decisions[-1].retry_after_seconds == 60

    async def test_the_links_ceiling_holds_when_redis_throws(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_LINK_PER_MINUTE", 10)
        broken = MagicMock()
        broken.count_in_window = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(broken)

        decisions = [
            await rate_limit.embed_dictation_link_allowed(public_key="pk_abc") for _ in range(11)
        ]

        assert [d.allowed for d in decisions] == [True] * 10 + [False]

    async def test_a_signed_in_visitor_and_a_caller_of_voice_are_floored_too(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_DICTATION_PER_MINUTE", 1)
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_VOICE_PER_MINUTE", 1)
        monkeypatch.setattr(settings, "RATE_LIMIT_EMBED_VOICE_PER_LINK_PER_MINUTE", 100)

        visitor = [
            await rate_limit.embed_dictation_visitor_allowed(public_key="pk", visitor="v")
            for _ in range(2)
        ]
        voice = [await rate_limit.embed_voice_allowed(_connection()) for _ in range(2)]

        assert [d.allowed for d in visitor] == [True, False]
        assert [d.allowed for d in voice] == [True, False]

    async def test_a_metered_answer_is_the_shared_limiters_alone(self):
        # The shared count says first, first: a floor counting these too would
        # refuse the second of a one-attempt allowance.
        rate_limit.configure(_redis([1, 1]))
        limit = Limit(attempts=1, window_seconds=60)

        decisions = [
            await rate_limit.consume_floored(surface="s", caller="c", limit=limit) for _ in range(2)
        ]

        assert [(d.allowed, d.metered) for d in decisions] == [(True, True), (True, True)]
