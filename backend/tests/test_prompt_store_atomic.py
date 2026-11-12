"""The prompt store's atomic operations against a real Redis service, when available."""

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, PropertyMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.clients.redis import RedisClient
from app.services.channels import sms_prompts
from app.services.channels.exceptions import ChannelNotConfigured

pytestmark = pytest.mark.anyio


async def test_an_invalid_reservation_reply_is_refused() -> None:
    redis = RedisClient()
    with patch.object(RedisClient, "raw", new_callable=PropertyMock) as raw:
        raw.return_value.eval = AsyncMock(return_value="invalid")
        with pytest.raises(TypeError, match="invalid number reservation"):
            await redis.reserve_numbers(
                "test:counter",
                issued="test:issued",
                pending="test",
                count=1,
                highest=999,
                quarantine=60,
                answerable=60,
                ttl=60,
            )


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
        await _clear(store, key)


async def _clear(store: RedisClient, key: str) -> None:
    for suffix in ("", ":counter", ":issued"):
        await store.delete(key + suffix)


async def _age(store: RedisClient, key: str, number: int, seconds: int) -> None:
    """Make `number` look handed out `seconds` ago, by the Redis clock."""
    now, _micro = await store.raw.time()
    await store.raw.zadd(key + ":issued", {str(number): now - seconds})


async def test_a_number_from_a_quiet_week_does_not_decide_a_newer_request(
    store: RedisClient,
) -> None:
    bot = uuid4().hex
    key = f"channel:sms:prompt:{bot}:test"
    try:
        first = await sms_prompts.reserve(bot, "test", 1)
        await sms_prompts.remember(bot, "test", ["aos:old:0"], start=first)
        # A day and more later the prompt has lapsed, and so has the chat's place in the
        # numbering: still, its number is not handed to the next request.
        await _age(store, key, first, sms_prompts.TTL_SECONDS + 60)
        await store.delete(key)
        await store.delete(key + ":counter")

        later = await sms_prompts.reserve(bot, "test", 1)
        await sms_prompts.remember(bot, "test", ["aos:new:0"], start=later)

        assert later != first
        assert await sms_prompts.answer(bot, "test", str(first)) is None
        assert await sms_prompts.answer(bot, "test", str(later)) == "aos:new:0"
    finally:
        await _clear(store, key)


async def test_a_prompt_stops_answering_a_day_after_its_number_was_handed_out(
    store: RedisClient,
) -> None:
    bot = uuid4().hex
    key = f"channel:sms:prompt:{bot}:test"
    try:
        old = await sms_prompts.reserve(bot, "test", 1)
        await sms_prompts.remember(bot, "test", ["aos:old:0"], start=old)
        await _age(store, key, old, sms_prompts.TTL_SECONDS + 60)
        # A newer prompt keeps the chat's prompts alive; the old one still lapses alone.
        new = await sms_prompts.reserve(bot, "test", 1)
        await sms_prompts.remember(bot, "test", ["aos:new:0"], start=new)

        assert await sms_prompts.answer(bot, "test", str(old)) is None
        assert await sms_prompts.answer(bot, "test", str(new)) == "aos:new:0"
    finally:
        await _clear(store, key)


async def test_numbering_wraps_past_999_and_refuses_only_when_nothing_is_free(
    store: RedisClient,
) -> None:
    bot = uuid4().hex
    key = f"channel:sms:prompt:{bot}:test"
    try:
        await store.raw.set(key + ":counter", 998)
        assert await sms_prompts.reserve(bot, "test", 2) == 1
        now, _micro = await store.raw.time()
        await store.raw.zadd(key + ":issued", {str(number): now for number in range(1, 1000)})

        with pytest.raises(ChannelNotConfigured, match="console"):
            await sms_prompts.reserve(bot, "test", 1)
        assert int(await store.raw.get(key + ":counter")) == 2
    finally:
        await _clear(store, key)


async def test_an_ignored_prompt_lets_its_numbers_go_once_lapsed_and_quarantined(
    store: RedisClient,
) -> None:
    bot = uuid4().hex
    key = f"channel:sms:prompt:{bot}:test"
    try:
        ignored = await sms_prompts.reserve(bot, "test", 1)
        await sms_prompts.remember(bot, "test", ["aos:old:0"], start=ignored)
        await _age(store, key, ignored, sms_prompts.TTL_SECONDS + 60)
        # The chat stays busy, which keeps its prompts alive, but not the lapsed one.
        newer = await sms_prompts.reserve(bot, "test", 1)
        await sms_prompts.remember(bot, "test", ["aos:new:0"], start=newer)

        assert str(ignored) not in json.loads(await store.get(key))
        assert await sms_prompts.answer(bot, "test", str(ignored)) is None

        await _age(store, key, ignored, sms_prompts.QUARANTINE_SECONDS + 60)
        await store.raw.set(key + ":counter", ignored - 1)
        assert await sms_prompts.reserve(bot, "test", 1) == ignored
    finally:
        await _clear(store, key)


async def test_a_prompt_from_before_numbers_were_stamped_lapses_like_any_other(
    store: RedisClient,
) -> None:
    bot = uuid4().hex
    key = f"channel:sms:prompt:{bot}:test"
    try:
        await store.raw.set(key, json.dumps({"7": "aos:legacy:0"}))
        await sms_prompts.reserve(bot, "test", 1)
        assert await store.raw.zscore(key + ":issued", "7") is not None
        assert await sms_prompts.answer(bot, "test", "7") == "aos:legacy:0"
    finally:
        await _clear(store, key)
