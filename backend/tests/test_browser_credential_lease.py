"""Lease fencing and normalized discovery do not confer browser authority to another owner."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.services.browser_credentials import _lease

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ORIGIN = "https://portal.example.test"


class MemoryRedis:
    def __init__(self) -> None:
        self.raw = self
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.fail: str | None = None

    async def get(self, key):
        if self.fail == "get":
            raise RedisError("Synthetic private provider detail")
        return self.values.get(key)

    async def set(self, key, value, ttl=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiries[key] = ttl
        if self.fail == "set":
            raise RedisError("Synthetic private provider detail")
        if self.fail == "cancel":
            raise asyncio.CancelledError
        return True

    async def eval(self, script, count, *args):
        if self.fail == "eval":
            raise RedisError("Synthetic private provider detail")
        keys, values = args[:count], args[count:]
        if self.values.get(keys[0]) != values[0]:
            return 0
        if script == _lease._RENEW:
            self.expiries[keys[0]] = values[1]
        elif script == _lease._OBSERVE:
            self.values[keys[1]] = values[1]
            self.expiries[keys[1]] = values[2]
        else:
            assert script == _lease._RELEASE
            for key in keys:
                self.values.pop(key, None)
        return 1


def identity() -> _lease.LiveBrowserIdentity:
    return _lease.LiveBrowserIdentity(
        organization_id=uuid4(),
        run_id=uuid4(),
        agent_id=uuid4(),
        user_id=uuid4(),
        tab_id="main",
        call_id="call",
        controller_id=uuid4(),
        credential_ids=(uuid4(),),
    )


async def test_a_live_owner_publishes_bounded_origin_and_close_removes_only_its_lease() -> None:
    redis, owner = MemoryRedis(), identity()
    lease = _lease.BrowserWriterLease(redis, owner)
    assert await _lease.discover(redis, owner.run_id, owner.call_id) is None
    assert await _lease.observed_origin(redis, owner) is None
    await lease.acquire()
    assert await _lease.discover(redis, owner.run_id, owner.call_id) == owner
    assert redis.expiries[lease._key] == 90
    await lease.observe(ORIGIN)
    assert await _lease.observed_origin(redis, owner) == ORIGIN
    assert redis.expiries[lease._key + ":origin"] == 5
    await lease.check()
    competing = _lease.BrowserWriterLease(
        redis, owner.model_copy(update={"controller_id": uuid4()})
    )
    with pytest.raises(BrowserFillRefused):
        await competing.acquire()
    with pytest.raises(BrowserFillRefused):
        await lease.acquire()
    await competing.close()
    assert await _lease.discover(redis, owner.run_id, owner.call_id) == owner
    await lease.close()
    await lease.close()
    assert redis.values == {}
    assert lease._heartbeat.done()
    with pytest.raises(BrowserFillRefused):
        await lease.acquire()
    with pytest.raises(BrowserFillRefused):
        await lease.check()
    with pytest.raises(BrowserFillRefused):
        await lease.observe(ORIGIN)


async def test_loss_is_terminal_and_old_cleanup_cannot_delete_the_new_owner() -> None:
    redis, owner = MemoryRedis(), identity()
    lease = _lease.BrowserWriterLease(redis, owner)
    await lease.acquire()
    replacement = owner.model_copy(update={"controller_id": uuid4()})
    redis.values[lease._key] = replacement.model_dump_json()
    with pytest.raises(BrowserFillRefused) as refused:
        await lease.check()
    assert refused.value.reason == BrowserFillReason.OWNERSHIP_LOST
    with pytest.raises(BrowserFillRefused):
        await lease.observe(ORIGIN)
    await lease.close()
    assert await _lease.discover(redis, owner.run_id, owner.call_id) == replacement
    assert lease._heartbeat.done()


@pytest.mark.parametrize("failure", ["set", "cancel"])
async def test_uncertain_acquire_cleans_up_even_if_the_set_already_succeeded(failure) -> None:
    redis, owner = MemoryRedis(), identity()
    redis.fail = failure
    lease = _lease.BrowserWriterLease(redis, owner)
    exception = asyncio.CancelledError if failure == "cancel" else BrowserFillRefused
    with pytest.raises(exception) as refused:
        await lease.acquire()
    assert "Synthetic private provider detail" not in str(refused.value)
    assert not redis.values and lease._heartbeat is None


@pytest.mark.parametrize("operation", ["check", "observe"])
async def test_a_transport_failure_loses_authority_without_exposing_provider_details(
    operation,
) -> None:
    redis, owner = MemoryRedis(), identity()
    lease = _lease.BrowserWriterLease(redis, owner)
    await lease.acquire()
    redis.fail = "eval"
    with pytest.raises(BrowserFillRefused) as refused:
        await (lease.check() if operation == "check" else lease.observe(ORIGIN))
    assert "Synthetic private provider detail" not in str(refused.value)
    assert lease._lost
    await lease.close()
    assert lease._heartbeat.done()


async def test_an_origin_publication_refuses_an_obsolete_owner() -> None:
    redis, owner = MemoryRedis(), identity()
    lease = _lease.BrowserWriterLease(redis, owner)
    await lease.acquire()
    redis.values.clear()
    with pytest.raises(BrowserFillRefused):
        await lease.observe(ORIGIN)
    await lease.close()


@pytest.mark.parametrize("bad", ["malformed", "huge", "wrong_run", "wrong_call", "transport"])
async def test_discovery_never_accepts_a_malformed_or_misbound_identity(bad) -> None:
    redis, owner = MemoryRedis(), identity()
    key = _lease._key(owner.run_id, owner.call_id)
    raw = owner.model_dump_json()
    if bad == "malformed":
        raw = "{}"
    elif bad == "huge":
        raw = "x" * 8193
    elif bad == "wrong_run":
        raw = owner.model_copy(update={"run_id": uuid4()}).model_dump_json()
    elif bad == "wrong_call":
        raw = owner.model_copy(update={"call_id": "different"}).model_dump_json()
    else:
        redis.fail = "get"
    redis.values[key] = raw
    assert await _lease.discover(redis, owner.run_id, owner.call_id) is None


@pytest.mark.parametrize(
    "bad", ["malformed", "huge", "wrong_controller", "wrong_tab", "private", "transport"]
)
async def test_origin_discovery_does_not_accept_unscoped_or_untrusted_metadata(bad) -> None:
    redis, owner = MemoryRedis(), identity()
    key = _lease._key(owner.run_id, owner.call_id) + ":origin"
    payload = _lease.ObservedOrigin(
        controller_id=owner.controller_id, tab_id=owner.tab_id, origin=ORIGIN
    )
    if bad == "malformed":
        raw = "{}"
    elif bad == "huge":
        raw = "x" * 2049
    elif bad == "wrong_controller":
        raw = payload.model_copy(update={"controller_id": uuid4()}).model_dump_json()
    elif bad == "wrong_tab":
        raw = payload.model_copy(update={"tab_id": "other"}).model_dump_json()
    elif bad == "private":
        raw = payload.model_copy(update={"origin": "https://127.0.0.1"}).model_dump_json()
    else:
        raw, redis.fail = payload.model_dump_json(), "get"
    redis.values[key] = raw
    assert await _lease.observed_origin(redis, owner) is None


async def test_heartbeat_stops_on_loss_and_cleanup_is_bounded(monkeypatch) -> None:
    redis, owner = MemoryRedis(), identity()
    lease = _lease.BrowserWriterLease(redis, owner)
    monkeypatch.setattr(_lease, "RENEW_SECONDS", 0)
    monkeypatch.setattr(
        lease, "check", AsyncMock(side_effect=BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST))
    )
    await lease._maintain()
    lease.check.assert_awaited_once()
    await lease.close()
