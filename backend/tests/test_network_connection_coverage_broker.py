"""Process failures must stay bounded and must not expose child diagnostics."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.network_connections import broker
from app.services.network_connections.broker import BrokerFailure, TailscaleBroker
from app.services.network_connections.protocol import MAX_FRAME_BYTES, NodeState
from tests.test_network_connection_protocol import process_with_frames

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("missing", ["stdin", "stdout"])
async def test_missing_process_pipe_is_reported_and_child_is_reaped(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    process, callbacks = process_with_frames()
    setattr(process, missing, None)
    process.returncode = None
    monkeypatch.setattr(TailscaleBroker, "available", lambda _self: True)
    monkeypatch.setattr(broker.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(BrokerFailure, match="runtime_unavailable"):
        await TailscaleBroker("synthetic").run(
            connection_id=uuid4(), mode="status", state=NodeState(), callbacks=callbacks
        )
    process.wait.assert_awaited_once()
    callbacks.heartbeat.assert_not_awaited()
    with pytest.raises(BrokerFailure, match="runtime_unavailable"):
        await TailscaleBroker("synthetic")._receive(process, callbacks=callbacks, timeout=1)


async def test_spawn_failure_does_not_expose_os_details(monkeypatch: pytest.MonkeyPatch) -> None:
    process, callbacks = process_with_frames()
    monkeypatch.setattr(TailscaleBroker, "available", lambda _self: True)
    monkeypatch.setattr(
        broker.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("private path"))
    )
    with pytest.raises(BrokerFailure, match="runtime_unavailable") as caught:
        await TailscaleBroker("synthetic").run(
            connection_id=uuid4(), mode="status", state=NodeState(), callbacks=callbacks
        )
    assert "private" not in str(caught.value)
    process.wait.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [ValueError("long line"), asyncio.LimitOverrunError("long line", 1)]
)
async def test_reader_limit_errors_become_fixed_protocol_errors(error: Exception) -> None:
    process, callbacks = process_with_frames()
    process.stdout = AsyncMock()
    process.stdout.readline.side_effect = error
    with pytest.raises(BrokerFailure, match="invalid_runtime_response"):
        await TailscaleBroker("synthetic")._receive(process, callbacks=callbacks, timeout=1)
    callbacks.persist.assert_not_awaited()


async def test_oversized_child_frame_is_rejected_before_parsing() -> None:
    process, callbacks = process_with_frames()
    process.stdout = AsyncMock()
    process.stdout.readline.return_value = b"x" * (MAX_FRAME_BYTES + 1)
    with pytest.raises(BrokerFailure, match="runtime_frame_too_large"):
        await TailscaleBroker("synthetic")._receive(process, callbacks=callbacks, timeout=1)
    callbacks.persist.assert_not_awaited()


async def test_idle_read_retries_without_losing_the_next_frame() -> None:
    process, callbacks = process_with_frames()
    process.stdout = AsyncMock()
    process.stdout.readline.side_effect = [
        TimeoutError(),
        b'{"type":"complete","reason":"ready"}\n',
    ]
    assert (
        await TailscaleBroker("synthetic")._receive(process, callbacks=callbacks, timeout=1)
        == "ready"
    )
    assert process.stdout.readline.await_count == 2


async def test_control_plane_timeout_becomes_a_fixed_failure() -> None:
    callback = AsyncMock(side_effect=TimeoutError("private database diagnostic"))
    with pytest.raises(BrokerFailure, match="control_plane_unavailable") as caught:
        await TailscaleBroker._bounded(callback)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("already_gone", [False, True])
async def test_unresponsive_child_is_killed_and_reaped(already_gone) -> None:
    process, _callbacks = process_with_frames()
    process.returncode = None
    process.wait.side_effect = [TimeoutError(), 0]
    process.stdin.drain.side_effect = BrokenPipeError()
    if already_gone:
        process.kill.side_effect = ProcessLookupError()
    await TailscaleBroker._stop(process)
    process.kill.assert_called_once()
    assert process.wait.await_count == 2
    process.stdin.close.assert_called_once()
