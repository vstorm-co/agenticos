"""A retried channel delivery is answered once (#167).

Every platform delivers at-least-once: a 200 lost on the wire is followed by
a redelivery that is valid, signed and new. The claim in
`app.services.channels.dedupe` is the single defence, taken by the router at
the one point all six inbound paths cross - so the redelivery test here
asserts at the `process_channel_event` boundary, not on the claim alone.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from app.clients.redis import RedisClient
from app.services.channels import dedupe
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter
from app.worker.background.channel import process_channel_event

pytestmark = pytest.mark.anyio


def _message(**overrides: Any) -> IncomingMessage:
    defaults: dict[str, Any] = {
        "platform": "slack",
        "bot_id": "bot-1",
        "platform_user_id": "U1",
        "platform_chat_id": "C1",
        "chat_type": "channel",
        "text": "hello",
        "message_id": "1723300000.000100",
    }
    defaults.update(overrides)
    return IncomingMessage(**defaults)


class _FakeRedis:
    """The one Redis behaviour the claim depends on: atomic SET NX."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        self.ttls[key] = ttl
        return True


class _BrokenRedis:
    """A Redis that cannot be reached mid-flight."""

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        raise ConnectionError("redis unreachable")


@pytest.fixture(autouse=True)
def _unconfigured_after() -> Any:
    """Every test leaves the module the way an unstarted app finds it."""
    yield
    dedupe.configure(None)


@pytest.fixture
def fake_redis() -> _FakeRedis:
    redis = _FakeRedis()
    dedupe.configure(cast(RedisClient, redis))
    return redis


async def test_the_same_delivery_is_claimed_once(fake_redis: _FakeRedis) -> None:
    incoming = _message()

    assert await dedupe.claim_delivery(incoming) is True
    assert await dedupe.claim_delivery(incoming) is False

    # The claim expires - the keyspace tracks recent traffic, not history.
    assert list(fake_redis.ttls.values()) == [dedupe.SEEN_TTL_SECONDS]


async def test_two_concurrent_deliveries_exactly_one_proceeds(fake_redis: _FakeRedis) -> None:
    """The claim is one atomic SET NX, never a get-then-set race."""
    incoming = _message()

    results = await asyncio.gather(
        dedupe.claim_delivery(incoming),
        dedupe.claim_delivery(incoming),
    )

    assert sorted(results) == [False, True]


async def test_chats_sharing_a_message_id_do_not_collide(fake_redis: _FakeRedis) -> None:
    """Telegram numbers messages per chat and Slack's ts is per channel, so
    the chat id is part of the key - a bot-wide key would let one chat's
    message swallow another's."""
    assert await dedupe.claim_delivery(_message(platform_chat_id="C1", message_id="5")) is True
    assert await dedupe.claim_delivery(_message(platform_chat_id="C2", message_id="5")) is True


async def test_a_message_with_no_message_id_is_processed_and_logged(
    fake_redis: _FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    """The documented policy: no platform message id means no claim - both
    deliveries process, because dropping a legitimate question is worse than
    answering a redelivered one twice - and the log says the guarantee is off."""
    incoming = _message(message_id=None)

    with caplog.at_level("WARNING"):
        assert await dedupe.claim_delivery(incoming) is True
        assert await dedupe.claim_delivery(incoming) is True

    assert fake_redis.store == {}
    assert "no message_id" in caplog.text


async def test_unconfigured_dedupe_processes_rather_than_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dedupe.configure(None)

    with caplog.at_level("WARNING"):
        assert await dedupe.claim_delivery(_message()) is True

    assert "not configured" in caplog.text


async def test_a_redis_error_processes_rather_than_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dedupe.configure(cast(RedisClient, _BrokenRedis()))

    with caplog.at_level("WARNING"):
        assert await dedupe.claim_delivery(_message()) is True

    assert "channel_dedupe_redis_unavailable" in caplog.text


async def test_a_redelivered_event_reaches_the_router_once(fake_redis: _FakeRedis) -> None:
    """The acceptance boundary from #167: the same IncomingMessage delivered
    twice through `process_channel_event` produces one run - everything past
    the claim (the agent call, the spend record, the reply) happens once."""
    incoming = _message()
    inner = AsyncMock()

    @asynccontextmanager
    async def _db() -> Any:
        yield AsyncMock()

    with (
        patch("app.worker.background.channel.get_db_context", _db),
        patch.object(ChannelMessageRouter, "_route_inner", inner),
    ):
        await process_channel_event(incoming)
        await process_channel_event(incoming)

    inner.assert_awaited_once()
