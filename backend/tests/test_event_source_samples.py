"""Live sample capture never creates runs, and is scoped to the listener's member."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.clients.redis import RedisClient
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.services.event_source_samples import EventSourceSampleService, capture_source_sample
from app.services.event_sources import EventSourceService

pytestmark = pytest.mark.anyio


@pytest.fixture
def ctx():
    return AuthContext(organization_id=uuid4(), user_id=uuid4(), role=OrgRoleName.MEMBER)


@pytest.fixture
def cache():
    import json

    values = {}
    client = AsyncMock(spec=RedisClient)

    async def get(key):
        return values.get(key)

    async def set_(key, value, *, ttl):
        assert ttl > 0
        values[key] = value

    async def update(key, *, updates, remove=(), ttl):
        mapping = json.loads(values.get(key, "{}"))
        mapping.update(updates)
        for field in remove:
            mapping.pop(field, None)
        values[key] = json.dumps(mapping)

    async def getdel(key):
        return values.pop(key, None)

    async def exists(key):
        return key in values

    client.get.side_effect = get
    client.set.side_effect = set_
    client.update_mapping.side_effect = update
    client.getdel.side_effect = getdel
    client.exists.side_effect = exists
    return client, values


@pytest.fixture
def access():
    with patch.object(EventSourceService, "require_use", AsyncMock()) as mocked:
        yield mocked


async def test_multiple_editors_capture_same_next_event_without_extra_runs(ctx, cache, access):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    first = await service.listen(ctx, source_id)
    second = await service.listen(ctx, source_id)
    await capture_source_sample(
        redis, source_id, body={"issue": {"title": "Fix"}}, delivery_id="event-1"
    )
    for listener in (first, second):
        result = await service.caught(ctx, source_id, listener.listener_id)
        assert result.state == "caught"
        assert result.delivery.model_dump() == {
            "body": {"issue": {"title": "Fix"}},
            "delivery_id": "event-1",
        }
    await capture_source_sample(redis, source_id, body={"different": True}, delivery_id="event-2")
    assert (
        await service.caught(ctx, source_id, first.listener_id)
    ).delivery.delivery_id == "event-1"


async def test_listening_expiry_does_not_turn_into_a_capture(ctx, cache, access):
    redis, values = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    assert (await service.caught(ctx, source_id, listener.listener_id)).state == "listening"
    values.pop(f"source:listener:{listener.listener_id}:open")
    await capture_source_sample(redis, source_id, body={}, delivery_id="late")
    assert (await service.caught(ctx, source_id, listener.listener_id)).state == "expired"


@pytest.mark.security
async def test_capture_cannot_be_read_by_another_member_even_with_source_access(ctx, cache, access):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    with pytest.raises(NotFoundError):
        await service.caught(replace(ctx, user_id=uuid4()), source_id, listener.listener_id)


@pytest.mark.security
async def test_revoked_source_use_blocks_polling_existing_sample(ctx, cache, access):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    access.side_effect = NotFoundError()
    with pytest.raises(NotFoundError):
        await service.caught(ctx, source_id, listener.listener_id)


async def test_large_capture_is_visible_and_never_stores_payload(ctx, cache, access):
    redis, values = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    await capture_source_sample(redis, source_id, body={"big": "s" * 64000}, delivery_id="large")
    result = await service.caught(ctx, source_id, listener.listener_id)
    assert result.state == "too_large" and result.delivery is None
    assert "s" * 100 not in values[f"source:listener:{listener.listener_id}:caught"]


async def test_cache_failure_does_not_fail_live_delivery(ctx, cache, access):
    redis, _ = cache
    redis.get.side_effect = RedisConnectionError("cache down")
    await capture_source_sample(redis, uuid4(), body={}, delivery_id="ok")


async def test_no_listener_retains_no_sample(cache):
    redis, values = cache
    await capture_source_sample(redis, uuid4(), body={}, delivery_id="unobserved")
    assert not values


async def test_expired_listener_registry_does_not_capture_later_delivery(ctx, cache, access):
    redis, values = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    values[f"source:listeners:{source_id}"] = '{"' + listener.listener_id + '":"0"}'
    await capture_source_sample(redis, source_id, body={}, delivery_id="later")
    assert f"source:listener:{listener.listener_id}:caught" not in values


@pytest.mark.parametrize("contents", ["not-json", '{"token":"not-a-timestamp"}'])
async def test_corrupt_listener_cache_does_not_fail_live_delivery(cache, contents):
    redis, values = cache
    source_id = uuid4()
    values[f"source:listeners:{source_id}"] = contents
    await capture_source_sample(redis, source_id, body={}, delivery_id="live")
