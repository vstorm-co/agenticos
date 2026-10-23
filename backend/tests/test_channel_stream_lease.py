"""One stream per polling bot, however many workers the deployment runs (#2168).

Every API worker ran the lifespan and opened a stream for every polling bot, so
with two workers Telegram terminated one `getUpdates` loop after the other,
about fourteen times a minute. Each process here is a `StreamLeases` against one
shared Redis, the way two workers on one deployment are.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels import stream_lease
from app.services.channels.stream_lease import StreamLeases

pytestmark = pytest.mark.anyio


class _SharedRedis:
    """The Redis every worker shares, as far as a lease reads and writes it."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.keys.get(key)

    async def delete(self, key: str) -> int:
        return int(self.keys.pop(key, None) is not None)

    async def expire(self, key: str, ttl: int) -> bool:
        return key in self.keys

    async def delete_if_equal(self, key: str, value: str) -> bool:
        if self.keys.get(key) != value:
            return False
        del self.keys[key]
        return True


class _DownRedis:
    """A Redis nobody can reach."""

    def __getattr__(self, _name: str) -> AsyncMock:
        return AsyncMock(side_effect=ConnectionError("redis is down"))


class _FlakyRedis(_SharedRedis):
    """The shared Redis, unreachable while `down` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.down = False

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if self.down:
            raise ConnectionError("redis is down")
        return await super().set(key, value, ttl=ttl, nx=nx)

    async def delete(self, key: str) -> int:
        if self.down:
            raise ConnectionError("redis is down")
        return await super().delete(key)


def _workers() -> tuple[StreamLeases, StreamLeases, _SharedRedis]:
    redis = _SharedRedis()
    return StreamLeases(redis, holder="a"), StreamLeases(redis, holder="b"), redis  # ty: ignore[invalid-argument-type]


@pytest.fixture
def adapter():
    adapter = MagicMock(stop_polling=AsyncMock())
    with patch("app.services.channels.stream_lease.get_adapter", return_value=adapter):
        yield adapter


class TestOneHolder:
    async def test_a_bot_one_worker_claimed_is_not_claimed_by_another(self):
        first, second, _ = _workers()

        assert await first.claim("bot") is True
        assert await second.claim("bot") is False
        # Its own lease, claimed again by the next pass, is still its own.
        assert await first.claim("bot") is True

    async def test_a_worker_that_stops_hands_its_bots_to_the_next_pass(self):
        """The other half of the issue's check: when the holder stops, the other
        worker takes the bot over rather than leaving it silent."""
        first, second, _ = _workers()
        await first.claim("bot")
        first.hold("bot", "telegram")

        await first.release()

        assert first.held == {}
        assert await second.claim("bot") is True

    async def test_an_edit_on_another_worker_closes_the_old_stream_at_its_renewal(
        self, adapter: MagicMock
    ):
        """The worker that served the edit opens the stream with the new token;
        the one still polling with the old token stops on its next pass."""
        first, second, _ = _workers()
        await first.take("bot", "telegram")

        await second.take("bot", "telegram")
        lost = await first.renew()

        assert lost == ["bot"]
        assert first.held == {}
        adapter.stop_polling.assert_awaited_once_with("bot")
        assert await second.renew() == []

    async def test_a_paused_bot_stops_on_whichever_worker_held_it(self, adapter: MagicMock):
        first, second, _ = _workers()
        await first.take("bot", "slack")

        await second.withdraw("bot")

        assert await first.renew() == ["bot"]
        adapter.stop_polling.assert_awaited_once_with("bot")

    async def test_a_shutdown_does_not_give_back_a_lease_another_worker_took(self):
        first, second, redis = _workers()
        await first.take("bot", "telegram")
        await second.take("bot", "telegram")

        await first.release()

        assert redis.keys == {"channel:stream:bot": "b"}

    async def test_a_lease_that_ran_out_is_lost(self, adapter: MagicMock):
        first, _, redis = _workers()
        await first.take("bot", "mattermost")
        redis.keys.clear()

        assert await first.renew() == ["bot"]


class TestWhatRedisMissed:
    """A write that did not reach Redis is written again, so the newest word wins."""

    async def test_an_edit_whose_takeover_missed_redis_wins_once_it_is_back(
        self, adapter: MagicMock
    ):
        """Otherwise the old holder keeps renewing with the old token, and the
        worker that served the edit stops its new stream at its first renewal."""
        redis = _FlakyRedis()
        old, new = StreamLeases(redis, holder="old"), StreamLeases(redis, holder="new")  # ty: ignore[invalid-argument-type]
        await old.take("bot", "telegram")

        redis.down = True
        await new.take("bot", "telegram")
        assert new.untaken == {"bot"}
        assert await new.renew() == []
        redis.down = False
        assert await new.renew() == []

        assert redis.keys == {"channel:stream:bot": "new"}
        assert await old.renew() == ["bot"]
        assert new.untaken == set()

    async def test_a_pause_whose_withdrawal_missed_redis_still_stops_the_holder(
        self, adapter: MagicMock
    ):
        redis = _FlakyRedis()
        holder, other = StreamLeases(redis, holder="a"), StreamLeases(redis, holder="b")  # ty: ignore[invalid-argument-type]
        await holder.take("bot", "slack")

        redis.down = True
        await other.withdraw("bot")
        await other.renew()
        assert other.unwithdrawn == {"bot"}
        redis.down = False
        await other.renew()

        assert other.unwithdrawn == set()
        assert await holder.renew() == ["bot"]

    async def test_a_renewal_redis_refuses_is_a_lease_lost(self, adapter: MagicMock):
        """A refused command is not an unreachable Redis: reading it as held let
        another worker claim the expiring key and open a second stream."""
        redis = _SharedRedis()
        leases = StreamLeases(redis, holder="a")  # ty: ignore[invalid-argument-type]
        await leases.take("bot", "telegram")
        redis.expire = AsyncMock(side_effect=PermissionError("NOPERM"))  # ty: ignore[invalid-assignment]
        redis.get = AsyncMock(side_effect=ValueError("NOPERM this user has no permissions"))  # ty: ignore[invalid-assignment]

        assert await leases.renew() == ["bot"]

    async def test_a_claim_made_while_redis_was_down_closes_once_it_is_back(
        self, adapter: MagicMock
    ):
        """The shape of the 2026-10-18 conflicts (#2224): a worker claims during
        a Redis outage, which fails open, while another already holds the lease.
        At the first renewal that reaches Redis the extra copy closes, and the
        holder goes on alone."""
        redis = _FlakyRedis()
        holder, extra = StreamLeases(redis, holder="a"), StreamLeases(redis, holder="b")  # ty: ignore[invalid-argument-type]
        await holder.take("bot", "telegram")

        redis.down = True
        assert await extra.claim("bot") is True
        extra.hold("bot", "telegram")
        redis.down = False

        assert await extra.renew() == ["bot"]
        adapter.stop_polling.assert_awaited_once_with("bot")
        assert await holder.renew() == []
        assert redis.keys == {"channel:stream:bot": "a"}

    async def test_a_claimed_lease_is_checked_before_its_stream_opens(self):
        first, second, _ = _workers()
        assert await first.claim("bot")
        await second.take("bot", "telegram")

        assert await first.holds("bot") is False
        assert await second.holds("bot") is True

    async def test_a_claim_for_a_bot_that_wants_no_stream_is_given_back(self):
        first, second, redis = _workers()
        await first.claim("bot")
        first.hold("bot", "telegram")

        await first.release_one("bot")

        assert first.held == {}
        assert redis.keys == {}
        assert await second.claim("bot")


class TestWithoutRedis:
    """Duplicates, never silence: a lease that cannot be read is a lease held."""

    async def test_with_none_configured_every_worker_streams_as_before(self):
        leases = StreamLeases(None)

        assert await leases.claim("bot") is True
        assert await leases.holds("bot") is True
        await leases.take("bot", "telegram")
        assert await leases.renew() == []
        await leases.withdraw("bot")
        await leases.take("bot", "telegram")
        await leases.release_one("bot")
        await leases.take("bot", "telegram")
        await leases.release()
        assert leases.held == {}

    async def test_an_unreachable_redis_keeps_the_streams_and_raises_nothing(self):
        leases = StreamLeases(_DownRedis())  # ty: ignore[invalid-argument-type]

        assert await leases.claim("bot") is True
        assert await leases.holds("bot") is True
        await leases.take("bot", "telegram")
        leases.untaken.clear()
        assert await leases.renew() == []
        await leases.release_one("bot")
        await leases.take("bot", "telegram")
        await leases.release()
        await leases.withdraw("bot")


def test_each_lifespan_starts_a_new_holder_with_nothing_held():
    before = stream_lease.leases()
    try:
        configured = stream_lease.configure(None)
        assert stream_lease.leases() is configured
        assert configured.holder != before.holder
        assert configured.held == {}
    finally:
        stream_lease._leases = before
