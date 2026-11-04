"""Shared storage admission remains bounded across concurrent email webhook workers."""

import asyncio
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient

pytestmark = pytest.mark.anyio


async def test_capacity_reservations_are_atomic_and_rejected_work_does_not_spend() -> None:
    redis = RedisClient()
    await redis.connect()
    key = f"test:email-capacity:{uuid4().hex}"
    try:
        decisions = await asyncio.gather(
            *(redis.reserve_capacity(key, amount=4, capacity=10, ttl=60) for _ in range(10))
        )
        assert sum(decisions) == 2
        assert await redis.get(key) == "8"
        remainder = await redis.reserve_capacity(key, amount=2, capacity=10, ttl=60)
        assert remainder
        refused = await redis.reserve_capacity(key, amount=1, capacity=10, ttl=60)
        assert not refused
        assert await redis.get(key) == "10"
        assert 0 < await redis.raw.ttl(key) <= 60
        with pytest.raises(ValueError):
            await redis.reserve_capacity(key, amount=-1, capacity=10, ttl=60)
    finally:
        await redis.delete(key)
        await redis.close()
