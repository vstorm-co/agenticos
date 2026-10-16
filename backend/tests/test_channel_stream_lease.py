"""One stream per polling bot, however many workers the deployment runs (#2168).

Every API worker ran the lifespan and opened a stream for every polling bot, so
with two workers Telegram terminated one `getUpdates` loop after the other,
about fourteen times a minute. Each process here is a `StreamLeases` against one
shared Redis, the way two workers on one deployment are.
"""

from __future__ import annotations

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

    async def expire_if_equal(self, key: str, value: str, ttl: int) -> bool:
        return self.keys.get(key) == value

    async def delete_if_equal(self, key: str, value: str) -> bool:
        if self.keys.get(key) != value:
            return False
        del self.keys[key]
        return True


class _DownRedis:
    """A Redis nobody can reach."""

    def __getattr__(self, _name: str) -> AsyncMock:
        return AsyncMock(side_effect=ConnectionError("redis is down"))


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


class TestWithoutRedis:
    """Duplicates, never silence: a lease that cannot be read is a lease held."""

    async def test_with_none_configured_every_worker_streams_as_before(self):
        leases = StreamLeases(None)

        assert await leases.claim("bot") is True
        await leases.take("bot", "telegram")
        assert await leases.renew() == []
        await leases.withdraw("bot")
        await leases.take("bot", "telegram")
        await leases.release()
        assert leases.held == {}

    async def test_an_unreachable_redis_keeps_the_streams_and_raises_nothing(self):
        leases = StreamLeases(_DownRedis())  # ty: ignore[invalid-argument-type]

        assert await leases.claim("bot") is True
        await leases.take("bot", "telegram")
        assert await leases.renew() == []
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
