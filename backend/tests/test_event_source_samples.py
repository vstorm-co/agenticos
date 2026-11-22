"""Live sample capture never creates runs, and is scoped to the listener's member."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import anyio
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

    async def replace_if_equal(key, *, expected, value, ttl):
        if values.get(key) != expected:
            return False
        await set_(key, value, ttl=ttl)
        return True

    client.get.side_effect = get
    client.set.side_effect = set_
    client.update_mapping.side_effect = update
    client.replace_if_equal.side_effect = replace_if_equal
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
        redis,
        source_id,
        body={"issue": {"title": "Fix"}},
        delivery_id="event-1",
        received_at=datetime.now(UTC),
    )
    for listener in (first, second):
        result = await service.caught(ctx, source_id, listener.listener_id)
        assert result.state == "caught"
        assert result.delivery.model_dump() == {
            "body": {"issue": {"title": "Fix"}},
            "delivery_id": "event-1",
        }
    await capture_source_sample(
        redis,
        source_id,
        body={"different": True},
        delivery_id="event-2",
        received_at=datetime.now(UTC),
    )
    assert (
        await service.caught(ctx, source_id, first.listener_id)
    ).delivery.delivery_id == "event-1"


async def test_listening_expiry_does_not_turn_into_a_capture(ctx, cache, access):
    redis, values = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    assert (await service.caught(ctx, source_id, listener.listener_id)).state == "listening"
    values.pop(f"source:listener:{listener.listener_id}:state")
    await capture_source_sample(
        redis, source_id, body={}, delivery_id="late", received_at=datetime.now(UTC)
    )
    assert (await service.caught(ctx, source_id, listener.listener_id)).state == "expired"


async def test_delivery_received_before_a_listener_opened_leaves_it_listening(ctx, cache, access):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    earlier = await service.listen(ctx, source_id)
    received_at = datetime.now(UTC)
    later = await service.listen(ctx, source_id)
    await capture_source_sample(
        redis, source_id, body={}, delivery_id="previous", received_at=received_at
    )
    assert (await service.caught(ctx, source_id, earlier.listener_id)).state == "caught"
    assert (await service.caught(ctx, source_id, later.listener_id)).state == "listening"
    await capture_source_sample(
        redis, source_id, body={}, delivery_id="next", received_at=datetime.now(UTC)
    )
    sample = await service.caught(ctx, source_id, later.listener_id)
    assert sample.delivery is not None and sample.delivery.delivery_id == "next"


async def test_poll_overlapping_capture_never_reports_expired(ctx, cache, access):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    token = (await service.listen(ctx, source_id)).listener_id
    get = redis.get.side_effect
    observed = anyio.Event()
    captured = anyio.Event()

    async def pause_poll_after_state_read(key):
        value = await get(key)
        if key.startswith(f"source:listener:{token}:") and not key.endswith(":owner"):
            observed.set()
            await captured.wait()
        return value

    async def deliver_during_poll():
        await observed.wait()
        await capture_source_sample(
            redis, source_id, body={}, delivery_id="first", received_at=datetime.now(UTC)
        )
        captured.set()

    redis.get.side_effect = pause_poll_after_state_read
    with anyio.fail_after(2):
        async with anyio.create_task_group() as group:
            group.start_soon(deliver_during_poll)
            assert (await service.caught(ctx, source_id, token)).state in {"listening", "caught"}
    assert (await service.caught(ctx, source_id, token)).delivery.delivery_id == "first"


async def test_compact_array_that_fits_a_pin_is_available_as_a_live_sample(ctx, cache, access):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    token = (await service.listen(ctx, source_id)).listener_id
    body = {"values": [0] * 22_000}
    await capture_source_sample(
        redis, source_id, body=body, delivery_id="array", received_at=datetime.now(UTC)
    )
    sample = await service.caught(ctx, source_id, token)
    assert sample.state == "caught"
    assert sample.delivery.body == body


@pytest.mark.security
@pytest.mark.parametrize("mismatch", ["member", "organization", "source"])
async def test_capture_is_bound_to_the_member_organization_and_source(ctx, cache, access, mismatch):
    redis, _ = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    await capture_source_sample(
        redis, source_id, body={"private": True}, delivery_id="one", received_at=datetime.now(UTC)
    )
    if mismatch == "member":
        ctx = replace(ctx, user_id=uuid4())
    elif mismatch == "organization":
        ctx = replace(ctx, organization_id=uuid4())
    else:
        source_id = uuid4()
    with pytest.raises(NotFoundError):
        await service.caught(ctx, source_id, listener.listener_id)


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
    await capture_source_sample(
        redis,
        source_id,
        body={"big": "s" * 64000},
        delivery_id="large",
        received_at=datetime.now(UTC),
    )
    result = await service.caught(ctx, source_id, listener.listener_id)
    assert result.state == "too_large" and result.delivery is None
    assert "s" * 100 not in values[f"source:listener:{listener.listener_id}:state"]


async def test_cache_failure_does_not_fail_live_delivery(ctx, cache, access):
    redis, _ = cache
    redis.get.side_effect = RedisConnectionError("cache down")
    await capture_source_sample(
        redis, uuid4(), body={}, delivery_id="ok", received_at=datetime.now(UTC)
    )


async def test_no_listener_retains_no_sample(cache):
    redis, values = cache
    await capture_source_sample(
        redis, uuid4(), body={}, delivery_id="unobserved", received_at=datetime.now(UTC)
    )
    assert not values


async def test_expired_listener_registry_does_not_capture_later_delivery(ctx, cache, access):
    redis, values = cache
    service = EventSourceSampleService(AsyncMock(), redis)
    source_id = uuid4()
    listener = await service.listen(ctx, source_id)
    values[f"source:listeners:{source_id}"] = '{"' + listener.listener_id + '":"0"}'
    await capture_source_sample(
        redis, source_id, body={}, delivery_id="later", received_at=datetime.now(UTC)
    )
    assert (await service.caught(ctx, source_id, listener.listener_id)).state == "listening"


@pytest.mark.parametrize("contents", ["not-json", '{"token":"not-a-timestamp"}'])
async def test_corrupt_listener_cache_does_not_fail_live_delivery(cache, contents):
    redis, values = cache
    source_id = uuid4()
    values[f"source:listeners:{source_id}"] = contents
    await capture_source_sample(
        redis, source_id, body={}, delivery_id="live", received_at=datetime.now(UTC)
    )
