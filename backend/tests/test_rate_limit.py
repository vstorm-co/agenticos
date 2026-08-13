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

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
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

    async def test_an_unreachable_redis_lets_the_caller_through(self):
        """The same trade-off, and the same reasoning, as the channel dedupe
        claim: losing the guarantee beats losing the visitor's answer."""
        client = MagicMock()
        client.count_in_window = AsyncMock(side_effect=ConnectionError("redis is down"))
        rate_limit.configure(client)

        decision = await rate_limit.consume(surface="s", caller="c", limit=Limit(attempts=1))

        assert decision.allowed is True

    async def test_degrading_is_logged_rather_than_silent(self, caplog):
        """ "Under the limit" and "not limited at all" are the same response, so
        the log line is the only thing that tells an operator which one it is."""
        with caplog.at_level("WARNING"):
            await rate_limit.consume(surface="agent_run", caller="user:a", limit=Limit(1))

        assert "unmetered" in caplog.text


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
