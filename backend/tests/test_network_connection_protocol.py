"""Private broker framing, persistence ordering and fail-closed process control."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.services.network_connections import broker
from app.services.network_connections.broker import BrokerFailure, TailscaleBroker
from app.services.network_connections.protocol import (
    FRAME_ADAPTER,
    MAX_FRAME_BYTES,
    MAX_STATE_BYTES,
    NodeState,
    StateFrame,
    StatusFrame,
)

pytestmark = pytest.mark.anyio


def status(**changes):
    return StatusFrame(type="status", backend_state="NeedsLogin", **changes)


@pytest.mark.security
@pytest.mark.parametrize(
    "url",
    [
        "http://login.tailscale.com/a/token",
        "https://evil.example/a/token",
        "https://login.tailscale.com.evil.example/a/token",
        "https://login.tailscale.com@evil.example/a/token",
        "https://user:password@login.tailscale.com/a/token",
        "https://login.tailscale.com:444/a/token",
        "https://login.tailscale.com:bad/a/token",
        "https://login.tailscale.com/a/token#fragment",
        "https://login.tailscale.com/other/token",
        "https://login.tailscale.com/a/to\nken",
        "https://login.tailscale.com/a/tökén",
        "https://login.tailscale.com/a/" + "x" * 4096,
    ],
)
def test_only_a_bounded_provider_login_address_is_accepted(url):
    with pytest.raises(ValidationError):
        status(auth_url=url)


@pytest.mark.security
def test_login_and_node_material_are_masked_outside_the_private_pipe():
    url = "https://login.tailscale.com/a/private-login-token"
    frame = status(auth_url=url)
    state = NodeState(state={"identity": SecretStr(base64.b64encode(b"node-key").decode())})
    assert url not in repr(frame)
    assert "private-login-token" not in frame.model_dump_json()
    assert "bm9kZS1rZXk=" not in repr(state)
    assert state.wire_state() == {"identity": "bm9kZS1rZXk="}
    assert status(auth_url="").auth_url is None
    assert status(auth_url=None).auth_url is None


@pytest.mark.security
@pytest.mark.parametrize(
    "state",
    [
        {"": "YQ=="},
        {"x" * 257: "YQ=="},
        {"é" * 129: "YQ=="},
        {"node": "not valid base64!"},
        {"node": base64.b64encode(b"x" * (MAX_STATE_BYTES + 1)).decode()},
        {str(index): "YQ==" for index in range(257)},
    ],
)
def test_unbounded_or_malformed_node_state_is_refused(state):
    with pytest.raises(ValidationError):
        StateFrame(type="state", sequence=1, state=state)


def test_an_empty_state_can_record_deletion_of_the_last_key():
    assert StateFrame(type="state", sequence=1, state={}).state == {}
    assert NodeState().wire_state() == {}


@pytest.mark.security
@pytest.mark.parametrize(
    "payload",
    [
        {"type": "dial", "address": "127.0.0.1:22"},
        {"type": "complete", "reason": "ready", "auth_url": "secret"},
        {"type": "state", "sequence": 0, "state": {}},
        {
            "type": "status",
            "backend_state": "Running",
            "peers": [
                {"id": "node", "online": True, "ips": ["not-an-ip"]},
            ],
        },
    ],
)
def test_the_pipe_has_no_extra_commands_or_unvalidated_peer_addresses(payload):
    with pytest.raises(ValidationError):
        FRAME_ADAPTER.validate_python(payload)


def process_with_frames(*frames):
    reader = asyncio.StreamReader(limit=MAX_FRAME_BYTES)
    for frame in frames:
        reader.feed_data(frame if isinstance(frame, bytes) else json.dumps(frame).encode() + b"\n")
    reader.feed_eof()
    writer = MagicMock()
    writer.drain = AsyncMock()
    process = SimpleNamespace(
        stdin=writer,
        stdout=reader,
        returncode=0,
        wait=AsyncMock(return_value=0),
        kill=MagicMock(),
    )
    callbacks = SimpleNamespace(heartbeat=AsyncMock(), persist=AsyncMock(), observe=AsyncMock())
    return process, callbacks


async def test_a_state_ack_follows_successful_durable_persistence():
    process, callbacks = process_with_frames(
        {"type": "state", "sequence": 1, "state": {"identity": "YQ=="}},
        {"type": "status", "backend_state": "NeedsMachineAuth"},
        {"type": "complete", "reason": "ready"},
    )
    order = []
    callbacks.persist.side_effect = lambda _frame: order.append("committed")
    process.stdin.write.side_effect = lambda data: order.append(json.loads(data)["type"])
    result = await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=1)
    assert result == "ready"
    assert order.index("committed") < order.index("ack")
    callbacks.observe.assert_awaited_once()
    callbacks.heartbeat.assert_awaited_once()


@pytest.mark.security
async def test_a_failed_commit_is_never_acknowledged():
    process, callbacks = process_with_frames({"type": "state", "sequence": 1, "state": {}})
    callbacks.persist.side_effect = BrokerFailure("lease_lost")
    with pytest.raises(BrokerFailure, match="lease_lost"):
        await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=1)
    assert [json.loads(call.args[0])["type"] for call in process.stdin.write.call_args_list] == [
        "heartbeat"
    ]


@pytest.mark.security
@pytest.mark.parametrize("sequences", [[2], [1, 1], [1, 3]])
async def test_duplicate_and_out_of_order_state_writes_are_refused(sequences):
    process, callbacks = process_with_frames(
        *[{"type": "state", "sequence": sequence, "state": {}} for sequence in sequences]
    )
    with pytest.raises(BrokerFailure, match="invalid_runtime_sequence"):
        await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=1)
    assert callbacks.persist.await_count == (0 if sequences[0] == 2 else 1)


@pytest.mark.security
@pytest.mark.parametrize(
    "frame,code",
    [
        (b'{"type":"state","state":"private-node-key"}\n', "invalid_runtime_response"),
        (b"not-json-private-node-key\n", "invalid_runtime_response"),
        ({"type": "error", "code": "private_node_key"}, "runtime_failed"),
    ],
)
async def test_bad_child_output_cannot_become_a_public_exception(frame, code):
    process, callbacks = process_with_frames(frame)
    with pytest.raises(BrokerFailure) as caught:
        await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=1)
    assert caught.value.code == code
    assert "private" not in str(caught.value)
    assert caught.value.__suppress_context__ or code == "runtime_failed"


@pytest.mark.security
async def test_lost_authority_stops_before_reading_another_child_frame():
    process, callbacks = process_with_frames({"type": "state", "sequence": 1, "state": {}})
    callbacks.heartbeat.side_effect = BrokerFailure("authority_revoked")
    with pytest.raises(BrokerFailure, match="authority_revoked"):
        await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=1)
    callbacks.persist.assert_not_awaited()
    process.stdin.write.assert_not_called()


async def test_eof_and_overall_timeout_are_bounded_failures():
    process, callbacks = process_with_frames()
    with pytest.raises(BrokerFailure, match="runtime_disconnected"):
        await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=1)
    with pytest.raises(BrokerFailure, match="runtime_timeout"):
        await TailscaleBroker("unused")._receive(process, callbacks=callbacks, timeout=0)


@pytest.mark.security
async def test_startup_renews_authority_and_strips_platform_credentials(monkeypatch, tmp_path):
    executable = tmp_path / "broker.exe"
    executable.write_bytes(b"synthetic")
    monkeypatch.setattr(broker.os, "access", lambda *_args: True)
    process, callbacks = process_with_frames({"type": "complete", "reason": "ready"})
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(broker.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setenv("TAILSCALE_AUTHKEY", "must-not-leak")
    monkeypatch.setenv("TS_AUTHKEY", "must-not-leak")
    monkeypatch.setenv("POSTGRES_PASSWORD", "must-not-leak")
    monkeypatch.setenv("VAULT_MASTER_KEY", "must-not-leak")
    order = []
    callbacks.heartbeat.side_effect = lambda: order.append("lease")
    process.stdin.write.side_effect = lambda data: order.append(json.loads(data)["type"])
    await TailscaleBroker(str(executable)).run(
        connection_id=uuid4(),
        mode="enroll",
        state=NodeState(state={"key": "YQ=="}),
        callbacks=callbacks,
    )
    assert order.index("lease") < order.index("start")
    environment = spawn.call_args.kwargs["env"]
    assert not set(environment) & {
        "TS_AUTHKEY",
        "TAILSCALE_AUTHKEY",
        "POSTGRES_PASSWORD",
        "VAULT_MASTER_KEY",
    }
    assert environment["TS_NO_LOGS_NO_SUPPORT"] == "true"
    first = json.loads(process.stdin.write.call_args_list[0].args[0])
    assert first["state"] == {"key": "YQ=="}
    assert first["hostname"].startswith("t3os-")


@pytest.mark.security
async def test_a_lease_lost_during_spawn_never_hands_identity_to_the_child(monkeypatch):
    process, callbacks = process_with_frames()
    callbacks.heartbeat.side_effect = BrokerFailure("lease_lost")
    monkeypatch.setattr(TailscaleBroker, "available", lambda _self: True)
    monkeypatch.setattr(broker.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(BrokerFailure, match="lease_lost"):
        await TailscaleBroker("synthetic").run(
            connection_id=uuid4(),
            mode="enroll",
            state=NodeState(),
            callbacks=callbacks,
        )
    process.stdin.write.assert_not_called()


async def test_an_absent_binary_refuses_before_spawning(monkeypatch):
    spawn = AsyncMock()
    monkeypatch.setattr(broker.asyncio, "create_subprocess_exec", spawn)
    _process, callbacks = process_with_frames()
    with pytest.raises(BrokerFailure, match="runtime_unavailable"):
        await TailscaleBroker("").run(
            connection_id=uuid4(),
            mode="status",
            state=NodeState(),
            callbacks=callbacks,
        )
    spawn.assert_not_awaited()


async def test_stop_closes_only_its_own_child_pipe():
    process, _callbacks = process_with_frames()
    process.returncode = None
    await TailscaleBroker._stop(process)
    process.stdin.close.assert_called_once()
    process.wait.assert_awaited_once()
    process.kill.assert_not_called()


@pytest.mark.security
async def test_an_overlarge_write_never_reaches_the_pipe():
    process, _callbacks = process_with_frames()
    with pytest.raises(BrokerFailure, match="runtime_frame_too_large"):
        await TailscaleBroker._write(process.stdin, "x" * MAX_FRAME_BYTES)
    process.stdin.write.assert_not_called()


async def test_a_broken_private_pipe_is_a_controlled_failure():
    process, _callbacks = process_with_frames()
    process.stdin.drain.side_effect = BrokenPipeError("sensitive OS detail")
    with pytest.raises(BrokerFailure, match="runtime_disconnected") as caught:
        await TailscaleBroker._write(process.stdin, "{}")
    assert "sensitive" not in str(caught.value)
