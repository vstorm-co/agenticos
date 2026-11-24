"""The recorder's native and socket seams fail closed without exposing page output."""

import asyncio
import json
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.agents.capabilities.browser_use._teaching_page import BrowserProcedureTeachingPage
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
)
from app.services.browser_procedure_teaching import _lease
from tests.test_browser_procedure_teaching_contracts import ORIGIN, SECRET

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class Native:
    def __init__(self):
        self.calls = []
        self.changed = False
        self.error = None
        self.value = {
            "origin": ORIGIN,
            "human_required": False,
            "target": {
                "role": "textbox",
                "structure": [{"tag": "input", "position": 1}, {"tag": "form", "position": 2}],
            },
        }
        self.exception = None
        self.tree_reads = 0

    async def __call__(self, method, params):
        self.calls.append((method, params))
        if self.error is not None:
            raise self.error
        if method == "Page.getFrameTree":
            self.tree_reads += 1
            return {
                "frameTree": {
                    "frame": {
                        "id": "frame",
                        "loaderId": "changed"
                        if self.changed and self.tree_reads > 1
                        else "document",
                        "url": ORIGIN + "/" + SECRET,
                    }
                }
            }
        if method == "Page.createIsolatedWorld":
            return {"executionContextId": 7}
        assert method == "Runtime.callFunctionOn"
        return {"result": {"value": self.value}, "exceptionDetails": self.exception}


async def test_native_capture_returns_only_origin_fixed_role_and_structural_hash():
    native = Native()
    result = await BrowserProcedureTeachingPage(native).observe("point", x=50, y=25)
    assert result.origin == ORIGIN
    assert result.target.role == "textbox"
    assert result.target.fingerprint.startswith("sha256:")
    assert len(result.target.fingerprint) == 71
    assert SECRET not in result.model_dump_json()
    assert "structure" not in result.model_dump_json()
    assert [method for method, _ in native.calls] == [
        "Page.getFrameTree",
        "Page.createIsolatedWorld",
        "Runtime.callFunctionOn",
        "Page.getFrameTree",
    ]
    world = native.calls[1][1]
    assert world["grantUniveralAccess"] is False
    call = native.calls[2][1]
    assert call["silent"] and call["returnByValue"] and not call["userGesture"]
    assert call["arguments"] == [{"value": "point"}, {"value": 50}, {"value": 25}]
    for forbidden in (".value", "textContent", "innerText", "innerHTML", 'getAttribute("name")'):
        assert forbidden not in call["functionDeclaration"]
    assert await BrowserProcedureTeachingPage(Native()).observe("point", x=50, y=25) == result


@pytest.mark.parametrize("human", [False, True])
async def test_origin_and_authentication_descriptors_have_no_target(human):
    native = Native()
    native.value = {"origin": ORIGIN, "human_required": human, "target": None}
    result = await BrowserProcedureTeachingPage(native).observe("focus")
    assert result.human_required is human and result.target is None


@pytest.mark.parametrize(
    "failure",
    [
        "native_error",
        "timeout",
        "changed",
        "exception",
        "value",
        "role",
        "structure",
        "origin",
        "auth_target",
        "coordinates",
    ],
)
async def test_native_failures_return_a_fixed_reason_without_raw_response_or_exception(
    caplog, failure
):
    native = Native()
    x = 0
    if failure == "native_error":
        native.error = RuntimeError(SECRET)
    elif failure == "timeout":
        native.error = TimeoutError(SECRET)
    elif failure == "changed":
        native.changed = True
    elif failure == "exception":
        native.exception = {"text": SECRET}
    elif failure == "value":
        native.value["value"] = SECRET
    elif failure == "role":
        native.value["target"]["role"] = SECRET
    elif failure == "structure":
        native.value["target"]["structure"] = [{"tag": SECRET, "position": 1}]
    elif failure == "origin":
        native.value["origin"] = ORIGIN + "?token=" + SECRET
    elif failure == "auth_target":
        native.value["human_required"] = True
    else:
        x = 5000
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await BrowserProcedureTeachingPage(native).observe("point", x=x)
    assert caught.value.reason == BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
    assert SECRET not in str(caught.value) + caplog.text


async def test_cancelled_native_capture_is_not_retried_or_converted_to_a_page_error():
    started = asyncio.Event()

    async def command(*args):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(BrowserProcedureTeachingPage(command).observe("origin"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class Redis:
    def __init__(self):
        self.raw = self
        self.values = {}
        self.failure = False

    def check(self):
        if self.failure:
            raise RedisError(SECRET)

    async def get(self, key):
        self.check()
        return self.values.get(key)

    async def set(self, key, value, *, ttl, nx=False):
        self.check()
        assert ttl == _lease.LEASE_SECONDS
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, keys, key, value, *args):
        self.check()
        assert keys == 1
        if self.values.get(key) != value:
            return 0
        if "expire" in script:
            assert args == (_lease.LEASE_SECONDS,)
        else:
            self.values.pop(key)
        return 1


def identity():
    return _lease.BrowserProcedureTeachingTakeover(
        organization_id=uuid4(),
        run_id=uuid4(),
        agent_id=uuid4(),
        user_id=uuid4(),
        controller_id=uuid4(),
        tab_id="tab",
        call_id="call",
        connection_id=uuid4(),
        takeover_id=uuid4(),
    )


async def connect(redis, held):
    return await _lease.open_connection(
        redis, str(held.run_id), held.call_id, held.connection_id, str(held.user_id)
    )


async def test_only_the_exact_live_socket_and_takeover_can_be_discovered_and_renewed():
    redis, held = Redis(), identity()
    assert await connect(redis, held)
    assert not await connect(redis, held)
    lease = _lease.BrowserProcedureTeachingLease(redis, held)
    await lease.acquire()
    assert await _lease.discover(redis, held.run_id, held.call_id) == held
    assert await _lease.discover(redis, uuid4(), held.call_id) is None
    assert await _lease.discover(redis, held.run_id, "other-call") is None
    assert await _lease.renew_connection(
        redis, str(held.run_id), held.call_id, held.connection_id, str(held.user_id)
    )
    await lease.check()
    await _lease.close_connection(
        redis, str(held.run_id), held.call_id, held.connection_id, str(uuid4())
    )
    await lease.check()
    await _lease.close_connection(
        redis, str(held.run_id), held.call_id, held.connection_id, str(held.user_id)
    )
    assert await _lease.discover(redis, held.run_id, held.call_id) is None
    with pytest.raises(BrowserProcedureTeachingRefused):
        await lease.check()
    assert await connect(redis, held)
    with pytest.raises(BrowserProcedureTeachingRefused):
        await lease.check()
    with pytest.raises(BrowserProcedureTeachingRefused):
        await lease.acquire()
    await lease.close()
    await lease.close()
    assert await _lease.discover(redis, held.run_id, held.call_id) is None


@pytest.mark.parametrize(
    "failure",
    [
        "unconnected",
        "occupied",
        "changed",
        "oversize",
        "malformed",
        "wrong_run",
        "wrong_call",
        "redis",
    ],
)
async def test_lease_identity_or_storage_failure_never_establishes_capture(caplog, failure):
    redis, held = Redis(), identity()
    if failure != "unconnected":
        await connect(redis, held)
    lease = _lease.BrowserProcedureTeachingLease(redis, held)
    key = _lease._key(held.run_id, held.call_id)
    if failure in {"unconnected", "occupied", "redis"}:
        if failure == "occupied":
            redis.values[key] = identity().model_dump_json()
        elif failure == "redis":
            redis.failure = True
        with pytest.raises(BrowserProcedureTeachingRefused):
            await lease.acquire()
    else:
        await lease.acquire()
        raw = held.model_dump(mode="json")
        if failure == "changed":
            redis.values[
                _lease.connection_key(str(held.run_id), held.call_id, held.connection_id)
            ] = str(uuid4())
        elif failure == "oversize":
            redis.values[key] = SECRET * 300
        elif failure == "malformed":
            redis.values[key] = SECRET
        else:
            raw["run_id" if failure == "wrong_run" else "call_id"] = str(uuid4())
            redis.values[key] = json.dumps(raw)
        assert await _lease.discover(redis, held.run_id, held.call_id) is None
    await lease.close()
    assert SECRET not in caplog.text


async def test_redis_failures_are_fixed_refusals_and_cleanup_does_not_replace_a_new_owner(caplog):
    redis, held = Redis(), identity()
    await connect(redis, held)
    lease = _lease.BrowserProcedureTeachingLease(redis, held)
    await lease.acquire()
    redis.failure = True
    assert await _lease.discover(redis, held.run_id, held.call_id) is None
    assert not await connect(redis, held)
    assert not await _lease.renew_connection(
        redis, str(held.run_id), held.call_id, held.connection_id, str(held.user_id)
    )
    await _lease.close_connection(
        redis, str(held.run_id), held.call_id, held.connection_id, str(held.user_id)
    )
    with pytest.raises(BrowserProcedureTeachingRefused):
        await lease.check()
    await lease.close()
    assert SECRET not in caplog.text
    redis.failure = False
    replacement = identity().model_dump_json()
    redis.values[_lease._key(held.run_id, held.call_id)] = replacement
    await _lease.BrowserProcedureTeachingLease(redis, held).close()
    assert redis.values[_lease._key(held.run_id, held.call_id)] == replacement
