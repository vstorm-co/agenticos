"""Atomic attachment storage releases capacity on consumption and expiration."""

import asyncio
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient

pytestmark = pytest.mark.anyio


async def test_cache_admission_is_atomic_and_consumption_releases_exactly_once() -> None:
    redis = RedisClient()
    await redis.connect()
    key = f"test:email-capacity:{uuid4().hex}"
    try:
        decisions = await asyncio.gather(
            *(
                redis.cache_bounded_values(
                    key, values={str(i): "xxxx"}, capacity=10, ttl=60, max_items=20
                )
                for i in range(10)
            )
        )
        assert sum(decisions) == 2
        assert await redis.get(f"{key}:used") == "8"
        accepted = str(decisions.index(True))
        results = await asyncio.gather(
            *(redis.take_bounded_value(key, accepted, ttl=60) for _ in range(10))
        )
        assert results.count("xxxx") == 1
        assert await redis.get(f"{key}:used") == "4"
        assert await redis.cache_bounded_values(
            key, values={"large": "xxxxxx"}, capacity=10, ttl=60, max_items=20
        )
        assert not await redis.cache_bounded_values(
            key, values={"refused": "x"}, capacity=10, ttl=60, max_items=20
        )
        assert await redis.get(f"{key}:file:refused") is None
        assert 0 < await redis.raw.ttl(f"{key}:file:large") <= 60
        for kwargs in (
            {"capacity": 0, "ttl": 60, "max_items": 20},
            {"capacity": 10, "ttl": 0, "max_items": 20},
            {"capacity": 10, "ttl": 60, "max_items": 0},
        ):
            with pytest.raises(ValueError):
                await redis.cache_bounded_values(key, values={"bad": "x"}, **kwargs)
        with pytest.raises(ValueError):
            await redis.take_bounded_value(key, "large", ttl=0)
    finally:
        for handle in [*(str(i) for i in range(10)), "large", "refused"]:
            await redis.take_bounded_value(key, handle, ttl=60)
        await redis.close()


async def test_expired_files_release_capacity_before_the_next_delivery() -> None:
    redis = RedisClient()
    await redis.connect()
    key = f"test:email-expiry:{uuid4().hex}"
    try:
        assert await redis.cache_bounded_values(
            key, values={"old": "xxxx"}, capacity=4, ttl=60, max_items=1
        )
        # Advance this lease past expiry without a wall-clock sleep.
        await redis.raw.zadd(f"{key}:expires", {"old": 0})
        assert await redis.cache_bounded_values(
            key, values={"new": "xxxx"}, capacity=4, ttl=60, max_items=1
        )
        assert await redis.take_bounded_value(key, "old", ttl=60) is None
        assert await redis.get(f"{key}:used") == "4"
        assert await redis.take_bounded_value(key, "new", ttl=60) == "xxxx"
        assert await redis.get(f"{key}:used") is None
        assert await redis.cache_bounded_values(
            key, values={"empty": ""}, capacity=4, ttl=60, max_items=1
        )
        assert not await redis.cache_bounded_values(
            key, values={"other": ""}, capacity=4, ttl=60, max_items=1
        )
    finally:
        for handle in ("old", "new", "empty", "other"):
            await redis.take_bounded_value(key, handle, ttl=60)
        await redis.close()
