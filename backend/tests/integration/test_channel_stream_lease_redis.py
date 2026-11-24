"""The lease's give-back and expiry against a real Redis (#2168).

A mock can only say the client sent a script; whether Redis gives a lease back
for its holder alone, and refuses everyone else, is Redis's to answer.
"""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient

pytestmark = pytest.mark.anyio


@pytest.fixture
async def redis() -> AsyncGenerator[RedisClient]:
    client = RedisClient()
    await client.connect()
    if not await client.ping():
        await client.close()
        pytest.skip("No Redis reachable")
    yield client
    await client.close()


async def test_only_the_holder_gives_back_a_lease(redis: RedisClient) -> None:
    key = f"test:lease:{uuid4().hex}"
    await redis.set(key, "first", ttl=5)
    try:
        assert await redis.expire(key, 60) is True
        assert await redis.raw.ttl(key) > 5

        assert await redis.delete_if_equal(key, "second") is False
        assert await redis.get(key) == "first"
        assert await redis.delete_if_equal(key, "first") is True
        assert await redis.get(key) is None
        assert await redis.expire(key, 60) is False
    finally:
        await redis.delete(key)


async def test_pending_operation_cannot_be_overwritten_or_revived_after_consumption(
    redis: RedisClient,
) -> None:
    key = f"test:pending-cas:{uuid4()}"
    try:
        assert not await redis.replace_if_equal(key, "old", "new", ttl=30)
        await redis.set(key, "old", ttl=30)
        assert not await redis.replace_if_equal(key, "another", "new", ttl=30)
        assert await redis.get(key) == "old"
        assert await redis.replace_if_equal(key, "old", "new", ttl=30)
        assert await redis.get(key) == "new"
        assert await redis.delete_if_equal(key, "new")
        assert not await redis.replace_if_equal(key, "new", "revived", ttl=30)
    finally:
        await redis.delete(key)


async def test_renewal_never_extends_a_successors_lease(redis: RedisClient) -> None:
    key = f"test:lease:renew:{uuid4().hex}"
    try:
        await redis.set(key, "first", ttl=5)
        assert await redis.expire_if_equals(key, "wrong", 60) is False
        assert await redis.raw.ttl(key) <= 5
        assert await redis.expire_if_equals(key, "first", 60) is True
        assert await redis.raw.ttl(key) > 5
        await redis.set(key, "second", ttl=5)
        assert await redis.expire_if_equals(key, "first", 60) is False
        assert await redis.get(key) == "second" and await redis.raw.ttl(key) <= 5
        await redis.delete(key)
        assert await redis.expire_if_equals(key, "first", 60) is False
    finally:
        await redis.delete(key)


async def test_active_comparison_renews_redis_exclusion_past_the_initial_ttl(redis: RedisClient):
    from app.services import rate_limit

    caller = f"test:comparison:{uuid4().hex}"
    key = f"inflight:eval_comparison:{caller}"
    previous = rate_limit._redis
    rate_limit.configure(redis)
    try:
        async with rate_limit.one_in_flight(
            "eval_comparison", caller, ttl_seconds=1, message="Busy", renew=True
        ):
            await asyncio.sleep(1.1)
            assert await redis.set(key, "contender", ttl=1, nx=True) is False
        assert await redis.get(key) is None
    finally:
        rate_limit.configure(previous)
        await redis.delete(key)
