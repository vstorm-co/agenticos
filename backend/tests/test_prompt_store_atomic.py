"""The prompt store's atomic operations against a real Redis service, when available."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, PropertyMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.clients.redis import RedisClient
from app.services.channels import sms_prompts

pytestmark = pytest.mark.anyio


async def test_an_invalid_reservation_reply_is_refused() -> None:
    redis = RedisClient()
    with patch.object(RedisClient, "raw", new_callable=PropertyMock) as raw:
        raw.return_value.eval = AsyncMock(return_value="invalid")
        with pytest.raises(TypeError, match="invalid number reservation"):
            await redis.reserve_range("test", minimum=0, count=1, ttl=60)


@pytest.fixture
async def store() -> AsyncIterator[RedisClient]:
    redis = RedisClient()
    await redis.connect()
    try:
        try:
            await redis.raw.ping()
        except RedisConnectionError:
            pytest.skip("Redis is unavailable")
        sms_prompts.configure(redis)
        yield redis
    finally:
        sms_prompts.configure(None)
        await redis.close()


async def test_concurrent_reservations_and_prompt_writes_do_not_collide(store: RedisClient) -> None:
    bot = uuid4().hex
    key = f"channel:sms:prompt:{bot}:test"
    try:
        starts = await asyncio.gather(*(sms_prompts.reserve(bot, "test", 2) for _ in range(12)))
        assert sorted(starts) == list(range(1, 25, 2))
        await asyncio.gather(
            *(
                sms_prompts.remember(
                    bot, "test", [f"aos:p{start}:0", f"aos:p{start}:1"], start=start
                )
                for start in starts
            )
        )
        for start in starts:
            assert await sms_prompts.answer(bot, "test", str(start)) == f"aos:p{start}:0"
        await asyncio.gather(
            *(sms_prompts.settle(bot, "test", f"aos:p{start}:0") for start in starts)
        )
        assert await store.get(key) is None
        assert await sms_prompts.reserve(bot, "test", 1) == 25
    finally:
        await store.delete(key)
        await store.delete(key + ":counter")
