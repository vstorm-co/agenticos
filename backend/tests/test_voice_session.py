"""A call lives exactly as long as its socket, and every way out hangs up (#54, Q3)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect
from pydantic import SecretStr
from pydantic_ai.usage import RunUsage

from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent_run import RunStatus
from app.db.models.voice_call import VoiceEndReason
from app.services.voice.session import VoiceCallSession
from app.services.voice.starter import VoiceCaller

pytestmark = pytest.mark.anyio
_M = "app.services.voice.session"
_SECRET_VALUE = "sk-live-secret-never-in-a-frame"


class FakeSocket:
    def __init__(self, frames: list[str | Exception | dict | float]):
        self._frames = frames
        self.sent: list[dict] = []
        self.closed_with: int | None = None

    async def receive(self):
        await asyncio.sleep(0)
        if not self._frames:
            await asyncio.sleep(3600)
        item = self._frames.pop(0)
        if isinstance(item, float):
            # A pause between frames, so a heartbeat can run while the call lasts.
            await asyncio.sleep(item)
            return await self.receive()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return item
        return {"type": "websocket.receive", "text": item}

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_bytes(self, data):
        self.sent.append({"type": "binary", "size": len(data)})

    async def close(self, code=1000, reason=None):
        self.closed_with = code


class FakeRealtime:
    def __init__(self, events=(), *, raises=None, hold=False, send_raises=None):
        self._events = list(events)
        self._raises = raises
        self._send_raises = send_raises
        self._hold = hold
        self.usage = RunUsage(cost=Decimal("0.02"))
        self.sent: list[str] = []
        self.interrupt = AsyncMock()

    async def send(self, content, *, respond=None):
        if self._send_raises is not None:
            raise self._send_raises
        self.sent.append(content)

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self._events:
            if isinstance(event, float):
                # A pause, so another task of the call can run between events.
                await asyncio.sleep(event)
                continue
            yield event
        if self._raises is not None:
            raise self._raises
        if self._hold:
            await asyncio.sleep(3600)


def _started(realtime: FakeRealtime, *, transport="webrtc", cap=600):
    @asynccontextmanager
    async def realtime_session(rt, *, provider_session):
        yield realtime

    prepared = SimpleNamespace(
        agent=SimpleNamespace(id=uuid4()),
        run=SimpleNamespace(id=uuid4()),
        realtime_session=realtime_session,
        answer_offer=AsyncMock(
            return_value=SimpleNamespace(sdp="answer-sdp", session=SimpleNamespace(call_id="rtc_1"))
        ),
        realtime=MagicMock(return_value=MagicMock()),
        built=SimpleNamespace(
            budget=SimpleNamespace(
                can_afford_next_request=AsyncMock(return_value=True), refresh_baselines=MagicMock()
            )
        ),
    )
    return SimpleNamespace(
        call_id=uuid4(),
        prepared=prepared,
        model=MagicMock(),
        settings={},
        cost_limit=Decimal("5"),
        cap_seconds=cap,
        minutes_left=600,
        conversation_id=uuid4(),
        secret=ApiKeySecret(api_key=SecretStr(_SECRET_VALUE)),
        resolved=SimpleNamespace(
            provider="openai",
            entry=SimpleNamespace(
                transport=transport,
                input_sample_rate=24000,
                output_sample_rate=24000,
                context_window=32000,
            ),
        ),
        bridge=MagicMock(decide=AsyncMock(return_value=True)),
        guard=SimpleNamespace(
            hits=0, screen=lambda text, speaker: SimpleNamespace(text=text, blocked=False)
        ),
        meter=MagicMock(
            total_usd=Decimal("0.02"), book_elapsed=MagicMock(), book_response=MagicMock()
        ),
        writer=SimpleNamespace(
            user_turn=AsyncMock(return_value=None), assistant_turn=AsyncMock(return_value=None)
        ),
        runner=SimpleNamespace(finish=AsyncMock()),
    )


@asynccontextmanager
async def _sessions():
    yield MagicMock(commit=AsyncMock(), rollback=AsyncMock())


_MEMBER_CTX = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
_DECIDER_CTX = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


def _caller():
    return VoiceCaller(
        ctx=AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        user_id=uuid4(),
        user_name="Ann",
        surface="web",
        anonymous=False,
        auth_token="t",
        embed_id=None,
        agent_id=uuid4(),
        conversation_id=None,
    )


_START = json.dumps(
    {"type": "start", "agent_id": str(uuid4()), "sdp_offer": "v=0\r\nm=audio 9 x 111\r\n"}
)


async def _run(
    socket,
    started,
    *,
    reauthorize=AsyncMock(return_value=_DECIDER_CTX),
    heartbeat=3600.0,
    seed=AsyncMock(return_value=[]),
    own_row=SimpleNamespace(ended_at=None),
    hang=None,
    minutes_left=None,
    end=None,
    notice_seconds=0.05,
):
    with (
        patch(f"{_M}.VoiceCallStarter.start", AsyncMock(return_value=started)),
        patch(f"{_M}.hang_up", hang or AsyncMock(return_value=True)) as hung,
        patch(f"{_M}.seed_history", seed),
        patch(
            f"{_M}.organization_repo.get_by_id",
            AsyncMock(return_value=SimpleNamespace(voice_monthly_minutes=None)),
        ),
        patch(
            f"{_M}.VoiceSettingsService.minutes_left_seconds", AsyncMock(return_value=minutes_left)
        ),
        patch(f"{_M}.voice_call_repo") as repo,
        patch(
            f"{_M}.agent_run_repo.expire_pending_approvals", AsyncMock(return_value=0)
        ) as expired,
    ):
        repo.expired = expired
        repo.end = end or AsyncMock()
        repo.mark_hung_up = AsyncMock()
        repo.heartbeat = AsyncMock()
        repo.set_provider_call_id = AsyncMock()
        repo.get = AsyncMock(return_value=own_row)
        session = VoiceCallSession(
            socket,
            _caller(),
            sessions=_sessions,
            reauthorize=reauthorize,
            heartbeat_seconds=heartbeat,
            notice_seconds=notice_seconds,
        )
        await asyncio.wait_for(session.run(), timeout=5)
    return hung, repo


@pytest.mark.parametrize(
    ("frames", "realtime", "reason", "status"),
    [
        (
            [_START, json.dumps({"type": "end"})],
            FakeRealtime(hold=True),
            VoiceEndReason.USER,
            RunStatus.COMPLETED,
        ),
        (
            [_START, WebSocketDisconnect(1001)],
            FakeRealtime(hold=True),
            VoiceEndReason.DISCONNECTED,
            RunStatus.CANCELLED,
        ),
        (
            [_START],
            FakeRealtime(raises=RuntimeError("provider went away")),
            VoiceEndReason.ERROR,
            RunStatus.FAILED,
        ),
    ],
)
async def test_every_exit_path_hangs_up_the_provider_call(frames, realtime, reason, status):
    socket = FakeSocket(frames)
    started = _started(realtime)

    hung, repo = await _run(socket, started)

    target = hung.await_args.args[0]
    assert target.provider_call_id == "rtc_1" and target.transport == "webrtc"
    assert repo.end.await_args.kwargs["reason"] is reason
    repo.mark_hung_up.assert_awaited_once()
    assert started.runner.finish.await_args.kwargs["status"] is status
    assert socket.sent[-1]["type"] == "ended" and socket.sent[-1]["reason"] == reason.value


async def test_a_cancelled_call_still_hangs_up_and_records_its_cost():
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))
    with (
        patch(f"{_M}.VoiceCallStarter.start", AsyncMock(return_value=started)),
        patch(f"{_M}.hang_up", AsyncMock(return_value=True)) as hung,
        patch(f"{_M}.seed_history", AsyncMock(return_value=[])),
        patch(f"{_M}.voice_call_repo") as repo,
    ):
        repo.end = AsyncMock()
        repo.mark_hung_up = AsyncMock()
        repo.set_provider_call_id = AsyncMock()
        task = asyncio.create_task(
            VoiceCallSession(
                socket,
                _caller(),
                sessions=_sessions,
                reauthorize=AsyncMock(return_value=_DECIDER_CTX),
            ).run()
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    hung.assert_awaited_once()
    assert repo.end.await_args.kwargs["cost_usd"] == Decimal("0.02")


async def test_a_heartbeat_that_finds_access_gone_ends_the_call():
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    hung, repo = await _run(
        socket, started, reauthorize=AsyncMock(return_value=None), heartbeat=0.01
    )

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.REVOKED
    hung.assert_awaited_once()
    assert started.runner.finish.await_args.kwargs["status"] is RunStatus.CANCELLED


async def test_a_failure_before_the_call_connects_still_closes_its_run_and_row():
    """Seeding runs after the first commit; if it fails, nothing may be left open."""
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    hung, repo = await _run(
        socket, started, seed=AsyncMock(side_effect=RuntimeError("summary failed"))
    )

    assert started.runner.finish.await_args.kwargs["status"] is RunStatus.FAILED
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.ERROR
    assert hung.await_args.args[0].provider_call_id is None  # never answered, nothing to hang up
    assert socket.sent[-1] == {"type": "ended", "reason": "error"}


async def test_a_heartbeat_that_finds_its_row_ended_by_a_reconnect_stops():
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))
    _, repo = await _run(
        socket, started, heartbeat=0.01, own_row=SimpleNamespace(ended_at=datetime.now(UTC))
    )
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.DISCONNECTED


@pytest.mark.security
async def test_a_heartbeat_rereads_the_budget_so_other_runs_spend_counts():
    socket = FakeSocket([_START])
    realtime = FakeRealtime(hold=True)
    started = _started(realtime)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    _, repo = await _run(socket, started, heartbeat=0.01)

    started.prepared.built.budget.refresh_baselines.assert_called()
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET


def _allowed_world(monkeypatch, broken: str | None):
    from app.core.exceptions import AuthenticationError

    agent = SimpleNamespace(current_version_id=uuid4(), status="published")
    org = SimpleNamespace(voice_conversations_enabled=True, voice_in_chat=True)
    member = SimpleNamespace(role="member")
    auth = AsyncMock()
    access = AsyncMock(return_value=broken != "grant")
    if broken == "token":
        auth.side_effect = AuthenticationError(message="Session revoked")
    if broken == "member":
        member = None
    if broken == "unpublished":
        agent.current_version_id = None
    if broken == "archived":
        agent.status = "archived"
    if broken == "voice_off":
        org.voice_conversations_enabled = False
    if broken == "chat_off":
        org.voice_in_chat = False
    monkeypatch.setattr(f"{_M}.authenticate_socket_token", auth)
    monkeypatch.setattr(f"{_M}.member_repo.get", AsyncMock(return_value=member))
    monkeypatch.setattr(f"{_M}.agent_repo.get", AsyncMock(return_value=agent))
    monkeypatch.setattr(f"{_M}.organization_repo.get_by_id", AsyncMock(return_value=org))
    monkeypatch.setattr(f"{_M}.resolve_access", access)
    return auth


@pytest.mark.parametrize(
    "broken", ["token", "member", "grant", "unpublished", "archived", "voice_off", "chat_off"]
)
async def test_a_call_stops_being_allowed_when_access_goes(monkeypatch, broken):
    """Review Focus 5, on the real check rather than a stub of it."""
    from app.services.voice.session import still_allowed

    _allowed_world(monkeypatch, broken)
    assert await still_allowed(MagicMock(), _caller(), agent_id=uuid4()) is None


async def test_an_aged_token_on_a_live_session_still_allows_the_call(monkeypatch):
    """The socket outlives its access token's lifetime; only a revoked session ends it (#1437)."""
    from unittest.mock import ANY

    from app.services.voice.session import still_allowed

    auth = _allowed_world(monkeypatch, None)
    caller = _caller()
    ctx = await still_allowed(MagicMock(), caller, agent_id=uuid4())
    auth.assert_awaited_once_with(ANY, "t", allow_expired=True)
    # The role as it stands now, not the one the call started with.
    assert ctx is not None and ctx.role == "member" and ctx.user_id == caller.user_id


async def test_reaching_the_time_cap_speaks_a_notice_and_ends():
    socket = FakeSocket([_START])
    realtime = FakeRealtime(hold=True)
    started = _started(realtime, cap=0)

    _, repo = await _run(socket, started)

    assert realtime.sent and "time" in realtime.sent[0].lower()
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.TIME_LIMIT


async def test_no_frame_carries_the_provider_key():
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    await _run(socket, _started(FakeRealtime(hold=True)))
    assert _SECRET_VALUE not in json.dumps(socket.sent)


@pytest.mark.security
async def test_an_approval_frame_is_decided_by_this_calls_bridge():
    socket = FakeSocket(
        [
            _START,
            json.dumps({"type": "approval", "id": "a1", "decision": "approve"}),
            json.dumps({"type": "end"}),
        ]
    )
    started = _started(FakeRealtime(hold=True))
    await _run(socket, started)
    started.bridge.decide.assert_awaited_once_with("a1", approve=True)


async def test_a_socket_that_never_sends_start_is_closed_without_a_call():
    socket = FakeSocket([])
    with patch(f"{_M}.VoiceCallStarter.start", AsyncMock()) as start:
        session = VoiceCallSession(socket, _caller(), sessions=_sessions, first_frame_seconds=0.01)
        await asyncio.wait_for(session.run(), timeout=2)
    start.assert_not_awaited()
    assert socket.sent[-1]["reason"] == "no_start"


async def test_a_refused_start_tells_the_client_why_and_holds_no_call():
    from app.services.voice.exceptions import VoiceRefused

    socket = FakeSocket([_START])
    refused = VoiceRefused("voice_off", "Voice conversations are switched off here.")
    with patch(f"{_M}.VoiceCallStarter.start", AsyncMock(side_effect=refused)):
        session = VoiceCallSession(socket, _caller(), sessions=_sessions)
        await asyncio.wait_for(session.run(), timeout=2)
        await session.closed()

    assert socket.sent == [
        {
            "type": "ended",
            "reason": "voice_off",
            "message": "Voice conversations are switched off here.",
        }
    ]


async def test_a_socket_that_goes_before_its_start_frame_holds_no_call():
    for gone in (WebSocketDisconnect(1001), {"type": "websocket.disconnect", "code": 1001}):
        socket = FakeSocket([gone])
        with patch(f"{_M}.VoiceCallStarter.start", AsyncMock()) as start:
            await asyncio.wait_for(
                VoiceCallSession(socket, _caller(), sessions=_sessions).run(), timeout=2
            )
        start.assert_not_awaited()
        assert socket.sent == []


async def test_frames_that_are_not_json_or_not_a_known_frame_are_ignored():
    socket = FakeSocket(
        [
            _START,
            {"type": "websocket.receive", "bytes": b"\x00\x01"},
            "not json",
            json.dumps({"type": "dance"}),
            json.dumps({"type": "mute", "muted": True}),
            json.dumps({"type": "ptt", "state": "down"}),
            json.dumps({"type": "end"}),
        ]
    )
    _, repo = await _run(socket, _started(FakeRealtime(hold=True)))
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.USER


async def test_a_relay_call_has_no_offer_to_answer_and_nothing_to_hang_up_by_id():
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True), transport="relay")

    hung, repo = await _run(socket, started)

    started.prepared.answer_offer.assert_not_awaited()
    assert [frame["type"] for frame in socket.sent][:1] == ["ready"]
    assert hung.await_args.args[0].provider_call_id is None


async def test_an_end_asked_for_before_the_call_connects_is_honoured():
    from app.services.voice.registry import LIVE_CALLS

    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    def seed_then_shutdown(*args, **kwargs):
        LIVE_CALLS.request_end_for(started.call_id, VoiceEndReason.SHUTDOWN)
        return []

    _, repo = await _run(socket, started, seed=AsyncMock(side_effect=seed_then_shutdown))

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.SHUTDOWN
    assert started.runner.finish.await_args.kwargs["status"] is RunStatus.CANCELLED


@pytest.mark.security
async def test_a_response_the_budget_cannot_follow_ends_the_call_with_a_notice():
    from pydantic_ai.realtime import RealtimeTurnCompleteEvent

    socket = FakeSocket([_START])
    realtime = FakeRealtime([RealtimeTurnCompleteEvent()], hold=True)
    started = _started(realtime)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    _, repo = await _run(socket, started)

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET
    assert realtime.sent and "budget" in realtime.sent[0].lower()
    assert started.runner.finish.await_args.kwargs["status"] is RunStatus.BUDGET_EXCEEDED


@pytest.mark.security
async def test_the_cost_limit_tripping_inside_the_session_ends_the_call_as_budget():
    from pydantic_ai.exceptions import UsageLimitExceeded

    socket = FakeSocket([_START])
    _, repo = await _run(socket, _started(FakeRealtime(raises=UsageLimitExceeded("cost"))))
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET


async def test_a_session_that_simply_stops_is_an_error():
    from pydantic_ai.realtime import RealtimeOutputSpeechStartEvent

    socket = FakeSocket([_START])
    _, repo = await _run(socket, _started(FakeRealtime([RealtimeOutputSpeechStartEvent()])))
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.ERROR
    assert {"type": "state", "state": "agent_speaking"} in socket.sent


async def test_a_month_out_of_minutes_ends_the_call_with_a_notice():
    socket = FakeSocket([_START])
    realtime = FakeRealtime(hold=True)

    _, repo = await _run(socket, _started(realtime), heartbeat=0.01, minutes_left=0)

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.MINUTES
    assert realtime.sent and "minutes" in realtime.sent[0].lower()


async def test_a_healthy_heartbeat_keeps_the_call_going_and_records_it():
    socket = FakeSocket([_START, 0.1, json.dumps({"type": "end"})])
    _, repo = await _run(
        socket, _started(FakeRealtime(hold=True)), heartbeat=0.01, minutes_left=600
    )
    assert repo.heartbeat.await_count >= 2
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.USER


async def test_without_a_given_check_the_heartbeat_asks_the_real_one():
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))
    with patch(f"{_M}.still_allowed", AsyncMock(return_value=None)) as allowed:
        _, repo = await _run(socket, started, reauthorize=None, heartbeat=0.01)
    assert allowed.await_args.kwargs["agent_id"] == started.prepared.agent.id
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.REVOKED


async def test_a_minute_before_the_cap_the_call_view_is_warned(monkeypatch):
    monkeypatch.setattr("app.services.voice.limits.WARN_SECONDS", 0.02)
    socket = FakeSocket([_START])
    _, repo = await _run(socket, _started(FakeRealtime(hold=True), cap=0.04))
    assert {"type": "limit", "seconds_left": 0.02} in socket.sent
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.TIME_LIMIT


async def test_a_teardown_that_fails_at_each_step_still_reaches_the_end():
    """Hang-up, the last turn, the row and the run each fail on their own; the client still hears."""
    from pydantic_ai.messages import PartEndEvent, SpeechPart

    socket = FakeSocket([_START, 0.05, json.dumps({"type": "end"})])
    started = _started(
        FakeRealtime(
            [PartEndEvent(index=1, part=SpeechPart(speaker="assistant", transcript="Bye."))],
            hold=True,
        )
    )
    started.writer.next_turn_id = lambda role: f"c:1:{role}"
    started.writer.assistant_turn = AsyncMock(side_effect=RuntimeError("db gone"))
    started.meter.book_response = MagicMock(side_effect=RuntimeError("no usage"))
    started.runner.finish = AsyncMock(side_effect=RuntimeError("db gone"))

    _, repo = await _run(
        socket,
        started,
        hang=AsyncMock(side_effect=RuntimeError("network")),
        end=AsyncMock(side_effect=RuntimeError("db gone")),
    )

    repo.mark_hung_up.assert_not_awaited()
    assert socket.sent[-1] == {"type": "ended", "reason": "user"}


async def test_a_hang_up_the_provider_did_not_confirm_is_left_for_the_reaper():
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    _, repo = await _run(
        socket, _started(FakeRealtime(hold=True)), hang=AsyncMock(return_value=False)
    )
    repo.end.assert_awaited_once()
    repo.mark_hung_up.assert_not_awaited()


async def test_a_second_reason_to_end_does_not_replace_the_first():
    session = VoiceCallSession(FakeSocket([]), _caller(), sessions=_sessions)
    session.request_end(VoiceEndReason.USER)
    session.request_end(VoiceEndReason.ERROR)
    assert session._reason is VoiceEndReason.USER


async def test_a_visitor_without_a_session_token_is_checked_on_the_agent_and_the_switch(
    monkeypatch,
):
    from app.services.voice.session import still_allowed

    auth = _allowed_world(monkeypatch, None)
    member = AsyncMock()
    monkeypatch.setattr(f"{_M}.member_repo.get", member)
    visitor = VoiceCaller(
        ctx=AuthContext(user_id=None, organization_id=uuid4(), role="member"),
        user_id=None,
        user_name=None,
        surface="embed",
        anonymous=True,
        auth_token=None,
        embed_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=None,
    )
    assert await still_allowed(MagicMock(), visitor, agent_id=uuid4()) is visitor.ctx
    auth.assert_not_awaited()
    member.assert_not_awaited()


async def test_an_answer_cut_off_by_the_end_is_still_booked():
    """Only a completed response books itself; the teardown books what the session still holds."""
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    realtime = FakeRealtime(hold=True)
    started = _started(realtime)

    _, repo = await _run(socket, started)

    started.meter.book_response.assert_called_with(realtime.usage)
    assert repo.end.await_args.kwargs["cost_usd"] == started.meter.total_usd


@pytest.mark.security
async def test_the_budget_notice_ends_when_the_agent_has_said_it_not_at_the_timeout():
    """The pump keeps running beside the notice, so it sees the agent stop speaking."""
    from pydantic_ai.realtime import (
        RealtimeOutputSpeechEndEvent,
        RealtimeOutputSpeechStartEvent,
        RealtimeTurnCompleteEvent,
    )

    socket = FakeSocket([_START])
    realtime = FakeRealtime(
        [
            RealtimeTurnCompleteEvent(),
            0.05,
            RealtimeOutputSpeechStartEvent(),
            RealtimeOutputSpeechEndEvent(),
        ],
        hold=True,
    )
    started = _started(realtime)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    loop = asyncio.get_running_loop()
    began = loop.time()
    _, repo = await _run(socket, started, notice_seconds=4.0)

    assert loop.time() - began < 2.0
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET
    assert len(realtime.sent) == 1


@pytest.mark.security
async def test_a_notice_the_spent_cost_limit_refuses_ends_the_call_on_the_budget(caplog):
    from pydantic_ai.exceptions import UsageLimitExceeded

    socket = FakeSocket([_START])
    realtime = FakeRealtime(hold=True, send_raises=UsageLimitExceeded("cost"))

    _, repo = await _run(socket, _started(realtime, cap=0))

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET
    assert "voice_call_failed" not in caplog.text


@pytest.mark.security
async def test_a_caller_who_lost_approvals_decide_stops_deciding_at_the_next_heartbeat():
    socket = FakeSocket([_START, 0.1, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))

    await _run(socket, started, reauthorize=AsyncMock(return_value=_MEMBER_CTX), heartbeat=0.01)

    started.bridge.refresh_decider.assert_called_with(None)


@pytest.mark.security
async def test_a_caller_who_still_decides_keeps_deciding():
    socket = FakeSocket([_START, 0.1, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))

    await _run(socket, started, heartbeat=0.01)

    started.bridge.refresh_decider.assert_called_with(_DECIDER_CTX)


@pytest.mark.security
async def test_a_decision_the_bridge_cannot_take_closes_the_card_and_the_call_goes_on():
    from app.core.exceptions import BadRequestError

    approval = json.dumps({"type": "approval", "id": "a1", "decision": "approve"})
    stale = json.dumps({"type": "approval", "id": "a2", "decision": "deny"})
    socket = FakeSocket([_START, approval, stale, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))
    started.bridge.decide = AsyncMock(
        side_effect=[BadRequestError(message="already expired"), False]
    )

    _, repo = await _run(socket, started)

    settled = [frame for frame in socket.sent if frame["type"] == "approval_settled"]
    assert settled == [
        {"type": "approval_settled", "id": "a1", "outcome": "expired"},
        {"type": "approval_settled", "id": "a2", "outcome": "expired"},
    ]
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.USER


@pytest.mark.security
async def test_the_teardown_expires_any_approval_the_call_left_pending():
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))

    _, repo = await _run(socket, started)

    assert repo.expired.await_args.kwargs["run_id"] == started.prepared.run.id


async def test_the_row_ends_before_the_provider_is_hung_up():
    """A reconnect on this worker waits for the row; it must not wait out the hang-up too."""
    order: list[str] = []
    socket = FakeSocket([_START, json.dumps({"type": "end"})])

    async def end(*args, **kwargs):
        order.append("end")

    async def hang(*args, **kwargs):
        order.append("hang_up")
        return True

    await _run(
        socket,
        _started(FakeRealtime(hold=True)),
        end=AsyncMock(side_effect=end),
        hang=AsyncMock(side_effect=hang),
    )

    assert order == ["end", "hang_up"]


async def test_a_second_limit_reached_during_a_notice_does_not_say_a_second_one():
    from pydantic_ai.realtime import RealtimeTurnCompleteEvent

    socket = FakeSocket([_START])
    realtime = FakeRealtime([RealtimeTurnCompleteEvent()], hold=True)
    started = _started(realtime, cap=0)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    await _run(socket, started)

    assert len(realtime.sent) == 1
    assert len([frame for frame in socket.sent if frame["type"] == "notice"]) == 1
