"""Approvals in a call: decided by the person on it, through the socket (#54)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import DeferredToolRequests, ToolApproved, ToolDenied

from app.agents.approval import ApprovalGranted, ApprovalPending, ApprovalRequest
from app.services.agent_runner import ApprovalChannel
from app.services.voice.approvals import VoiceApprovalBridge

# The module name is in `test_security_marker.py`'s net, and every test here is
# about who may decide what a call runs: the whole module is a security index.
pytestmark = [pytest.mark.anyio, pytest.mark.security]
_MODULE = "app.services.voice.approvals"


@asynccontextmanager
async def _sessions():
    yield MagicMock()


def _channel() -> ApprovalChannel:
    return ApprovalChannel(organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4())


async def _park(channel: ApprovalChannel, tool_call_id: str, args: dict) -> None:
    decision = await channel(
        ApprovalRequest(
            capability_id="email",
            tool_name="send_invoice",
            tool_call_id=tool_call_id,
            tool_args=args,
        )
    )
    assert isinstance(decision, ApprovalPending)


def _requests(tool_call_id: str, args: dict) -> DeferredToolRequests:
    return DeferredToolRequests(
        approvals=[ToolCallPart(tool_name="send_invoice", args=args, tool_call_id=tool_call_id)]
    )


def _bridge(channel, *, decider=SimpleNamespace(), timeout=5.0):
    frames: list[tuple[str, dict]] = []

    async def send(kind, payload):
        frames.append((kind, payload))

    bridge = VoiceApprovalBridge(
        sessions=_sessions,
        decider=decider,
        send=send,
        heard=lambda: "send an invoice for 120 euros to Ahmad",
        timeout=timeout,
    )
    bridge.attach(channel)
    return bridge, frames


@pytest.fixture(autouse=True)
def _rows():
    with (
        patch(f"{_MODULE}.ApprovalService.request", new=AsyncMock()),
        patch(f"{_MODULE}.ApprovalService.decide", new=AsyncMock()) as decided,
        patch(f"{_MODULE}.ApprovalService.expire_now", new=AsyncMock()) as expired,
    ):
        yield SimpleNamespace(decided=decided, expired=expired)


async def test_an_approval_grants_exactly_the_shown_arguments_once():
    channel = _channel()
    args = {"customer": "Ahmad", "amount_eur": 120}
    await _park(channel, "call_1", args)
    bridge, frames = _bridge(channel)

    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", args)))
    await asyncio.sleep(0)
    shown = frames[0][1]
    assert frames[0][0] == "approval_required"
    assert shown["args"] == args and shown["tool"] == "send_invoice"
    assert shown["said"] == "send an invoice for 120 euros to Ahmad"

    assert await bridge.decide(shown["id"], approve=True)
    results = await handler

    assert isinstance(results.approvals["call_1"], ToolApproved)
    granted = await channel(
        ApprovalRequest(
            capability_id="email", tool_name="send_invoice", tool_call_id="call_1", tool_args=args
        )
    )
    assert granted == ApprovalGranted(args)
    again = await channel(
        ApprovalRequest(
            capability_id="email", tool_name="send_invoice", tool_call_id="call_2", tool_args=args
        )
    )
    assert isinstance(again, ApprovalPending)


async def test_the_parked_call_is_written_by_the_bridge_not_again_by_finish():
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)
    await bridge.decide(frames[0][1]["id"], approve=False)
    results = await handler

    assert isinstance(results.approvals["call_1"], ToolDenied)
    assert channel.requested == [] and channel.parked == {}


async def test_no_decision_in_time_is_expired_with_nobody_named(_rows):
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel, timeout=0.01)

    results = await bridge(MagicMock(), _requests("call_1", {"a": 1}))

    assert isinstance(results.approvals["call_1"], ToolDenied)
    _rows.expired.assert_awaited_once()
    assert frames[-1] == ("approval_settled", {"id": frames[0][1]["id"], "outcome": "expired"})


async def test_a_caller_who_cannot_approve_is_told_at_once_and_the_tool_is_denied(_rows):
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel, decider=None)

    results = await bridge(MagicMock(), _requests("call_1", {"a": 1}))

    assert isinstance(results.approvals["call_1"], ToolDenied)
    assert "text chat" in results.approvals["call_1"].message
    assert frames == [("approval_unavailable", {"tool": "send_invoice", "args": {"a": 1}})]
    _rows.expired.assert_awaited_once()


async def test_a_decision_for_an_approval_this_call_is_not_waiting_on_is_ignored(_rows):
    bridge, _ = _bridge(_channel())
    assert await bridge.decide(str(uuid4()), approve=True) is False
    _rows.decided.assert_not_awaited()


async def test_hanging_up_while_waiting_expires_the_approval(_rows):
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, _ = _bridge(channel)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)

    handler.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler
    _rows.expired.assert_awaited_once()


async def test_a_bridge_that_was_never_attached_runs_nothing():
    frames: list[tuple[str, dict]] = []

    async def send(kind, payload):
        frames.append((kind, payload))

    bridge = VoiceApprovalBridge(
        sessions=_sessions, decider=SimpleNamespace(), send=send, heard=lambda: None
    )

    results = await bridge(MagicMock(), _requests("call_1", {"a": 1}))

    assert isinstance(results.approvals["call_1"], ToolDenied)
    assert frames == []


async def test_a_call_the_gate_never_parked_runs_nothing(_rows):
    bridge, frames = _bridge(_channel())

    results = await bridge(MagicMock(), _requests("call_unknown", {"a": 1}))

    assert isinstance(results.approvals["call_unknown"], ToolDenied)
    assert frames == []
    _rows.expired.assert_not_awaited()


async def test_a_decision_written_while_the_minute_runs_out_wins_once(_rows):
    """Exactly one outcome: the row says approved, so the tool runs."""

    async def slow_write(*args, **kwargs):
        await asyncio.sleep(0.2)

    _rows.decided.side_effect = slow_write
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel, timeout=0.05)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)

    decision = asyncio.create_task(bridge.decide(frames[0][1]["id"], approve=True))
    results = await handler

    assert await decision is True
    assert isinstance(results.approvals["call_1"], ToolApproved)
    _rows.expired.assert_not_awaited()
    assert frames[-1][1]["outcome"] == "approved"


async def test_a_decision_after_the_minute_ran_out_is_not_taken(_rows):
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel, timeout=0.01)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)
    approval_id = frames[0][1]["id"]

    results = await handler

    assert await bridge.decide(approval_id, approve=True) is False
    assert isinstance(results.approvals["call_1"], ToolDenied)
    _rows.decided.assert_not_awaited()
    _rows.expired.assert_awaited_once()


async def test_a_decision_the_row_refused_does_not_run_the_tool(_rows):
    from app.core.exceptions import BadRequestError

    _rows.decided.side_effect = BadRequestError(message="This request was already expired")
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)

    with pytest.raises(BadRequestError):
        await bridge.decide(frames[0][1]["id"], approve=True)
    results = await handler

    assert isinstance(results.approvals["call_1"], ToolDenied)
    _rows.expired.assert_awaited_once()


async def test_a_caller_who_lost_the_permission_mid_call_cannot_decide(_rows):
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel, timeout=0.05)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)

    bridge.refresh_decider(None)

    assert await bridge.decide(frames[0][1]["id"], approve=True) is False
    assert isinstance((await handler).approvals["call_1"], ToolDenied)
    _rows.decided.assert_not_awaited()


async def test_hanging_up_while_a_decision_is_being_written_leaves_it_to_the_decision(_rows):
    async def slow_write(*args, **kwargs):
        await asyncio.sleep(0.05)

    _rows.decided.side_effect = slow_write
    channel = _channel()
    await _park(channel, "call_1", {"a": 1})
    bridge, frames = _bridge(channel)
    handler = asyncio.create_task(bridge(MagicMock(), _requests("call_1", {"a": 1})))
    await asyncio.sleep(0)
    decision = asyncio.create_task(bridge.decide(frames[0][1]["id"], approve=False))
    await asyncio.sleep(0)

    handler.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler
    assert await decision is True
    _rows.decided.assert_awaited_once()
