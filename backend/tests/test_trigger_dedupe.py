"""The once-only claim on an event-trigger delivery.

The value is entirely in the degradation: the claim must dedup a redelivery when
Redis answers, and fire rather than drop the event when it does not. Both are
asserted here against a mocked client, since the guarantee is the client's and the
fail-open is this module's.
"""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient
from app.services import trigger_dedupe

pytestmark = pytest.mark.anyio


class _FakeRedis:
    """The one Redis behaviour the claim rests on: an atomic `SET NX`.

    A dict guarded by no lock is enough to model `SET NX` under cooperative
    concurrency - the operation never awaits between reading the key and writing
    it, so two `claim_event_delivery` coroutines interleave only at the `await`
    boundary and exactly one finds the key absent, which is the exclusivity the
    mocked-return tests below cannot show.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        return int(self.store.pop(key, None) is not None)


@pytest.fixture
def fake_redis():
    redis = _FakeRedis()
    trigger_dedupe.configure(cast(RedisClient, redis))
    yield redis
    trigger_dedupe.configure(None)


async def test_of_two_concurrent_claims_on_one_delivery_exactly_one_proceeds(fake_redis):
    """The claim goes through `SET NX`, so two deliveries of the same event racing
    at once resolve to one winner and one loser - never two fires for one event."""
    trigger_id = uuid4()

    results = await asyncio.gather(
        trigger_dedupe.claim_event_delivery(trigger_id=trigger_id, delivery_id="d1"),
        trigger_dedupe.claim_event_delivery(trigger_id=trigger_id, delivery_id="d1"),
    )

    assert sorted(results) == [False, True]


@pytest.fixture
def redis():
    client = AsyncMock()
    trigger_dedupe.configure(client)
    yield client
    trigger_dedupe.configure(None)


async def test_a_claim_with_no_redis_fails_open():
    trigger_dedupe.configure(None)
    assert await trigger_dedupe.claim_event_delivery(trigger_id=uuid4(), delivery_id="d1") is True


async def test_a_first_claim_is_granted_and_keyed_by_trigger_and_delivery(redis):
    redis.set = AsyncMock(return_value=True)
    trigger_id = uuid4()
    assert (
        await trigger_dedupe.claim_event_delivery(trigger_id=trigger_id, delivery_id="d1") is True
    )
    key = redis.set.call_args.args[0]
    assert str(trigger_id) in key and "d1" in key
    assert redis.set.call_args.kwargs["nx"] is True


async def test_a_second_claim_on_the_same_delivery_is_refused(redis):
    redis.set = AsyncMock(return_value=False)
    assert await trigger_dedupe.claim_event_delivery(trigger_id=uuid4(), delivery_id="d1") is False


async def test_a_claim_fails_open_when_redis_is_unreachable(redis):
    redis.set = AsyncMock(side_effect=RuntimeError("redis down"))
    assert await trigger_dedupe.claim_event_delivery(trigger_id=uuid4(), delivery_id="d1") is True


async def test_a_release_deletes_the_claim(redis):
    redis.delete = AsyncMock()
    trigger_id = uuid4()
    await trigger_dedupe.release_event_delivery(trigger_id=trigger_id, delivery_id="d1")
    key = redis.delete.call_args.args[0]
    assert str(trigger_id) in key and "d1" in key


async def test_a_release_with_no_redis_is_a_noop():
    trigger_dedupe.configure(None)
    await trigger_dedupe.release_event_delivery(trigger_id=uuid4(), delivery_id="d1")


async def test_a_release_swallows_a_redis_error(redis):
    redis.delete = AsyncMock(side_effect=RuntimeError("redis down"))
    await trigger_dedupe.release_event_delivery(trigger_id=uuid4(), delivery_id="d1")
