"""A call lives exactly as long as its socket, and every way out hangs up (#54, Q3)."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anyio
import pytest
from fastapi import WebSocketDisconnect
from pydantic import SecretStr
from pydantic_ai.usage import RunUsage

from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent_run import RunStatus
from app.db.models.voice_call import VoiceEndReason
from app.schemas.voice import ApprovalUnavailableFrame
from app.services.voice.session import NOTICES, VoiceCallSession
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
        self.audio_in: list[bytes] = []
        self.profile = {"supports_interruption": True, "supports_output_truncation": True}

    async def send_audio(self, data):
        self.audio_in.append(data)

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


def _started(
    realtime: FakeRealtime,
    *,
    transport="webrtc",
    cap=600,
):
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
        hand_off=None,
    )
    return SimpleNamespace(
        call_id=uuid4(),
        prepared=prepared,
        model=MagicMock(),
        settings={},
        cost_limit=Decimal("5"),
        cap_seconds=cap,
        resume_token="resume-token-of-this-connection",
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
        questions=MagicMock(answer=MagicMock(return_value=True)),
        guard=SimpleNamespace(
            hits=0, screen=lambda text, speaker: SimpleNamespace(text=text, blocked=False)
        ),
        meter=MagicMock(
            total_usd=Decimal("0.02"), book_elapsed=MagicMock(), book_response=MagicMock()
        ),
        writer=SimpleNamespace(
            user_turn=AsyncMock(return_value=None),
            assistant_turn=AsyncMock(return_value=None),
            next_turn_id=lambda role: f"call:1:{role}",
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
    end=None,
    notice_seconds=0.05,
    caller=None,
    expire=None,
    start_clock=None,
    during_start=None,
    connect_seconds=60.0,
    mark=None,
    deadline=5.0,
):
    held: list[VoiceCallSession] = []

    async def start(*_args, **_kwargs):
        # Whatever the test does to the session while its starter still runs.
        if during_start is not None:
            during_start(held[0])
        return started

    with (
        patch(f"{_M}.VoiceCallStarter.start", AsyncMock(side_effect=start)),
        patch(f"{_M}.hang_up", hang or AsyncMock(return_value=True)) as hung,
        patch(f"{_M}.seed_history", seed),
        patch(f"{_M}.voice_call_repo") as repo,
        patch(
            f"{_M}.agent_run_repo.expire_pending_approvals", expire or AsyncMock(return_value=0)
        ) as expired,
        patch(f"{_M}.agent_run_repo.record_live_cost", AsyncMock()) as live_cost,
    ):
        repo.expired = expired
        repo.live_cost = live_cost
        repo.end = end or AsyncMock()
        repo.mark_hung_up = mark or AsyncMock()
        repo.heartbeat = AsyncMock()
        repo.start_clock = start_clock or AsyncMock()
        repo.set_provider_call_id = AsyncMock()
        repo.get = AsyncMock(return_value=own_row)
        session = VoiceCallSession(
            socket,
            caller or _caller(),
            sessions=_sessions,
            reauthorize=reauthorize,
            heartbeat_seconds=heartbeat,
            notice_seconds=notice_seconds,
            connect_seconds=connect_seconds,
        )
        held.append(session)
        await asyncio.wait_for(session.run(), timeout=deadline)
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
        patch(f"{_M}.agent_run_repo.record_live_cost", AsyncMock()),
    ):
        repo.end = AsyncMock()
        repo.mark_hung_up = AsyncMock()
        repo.set_provider_call_id = AsyncMock()
        repo.heartbeat = AsyncMock()
        repo.start_clock = AsyncMock()
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


_PUBLISHER = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")


_EMBED_AGENT = uuid4()
"""The agent the visitors' embed in `_allowed_world` points at."""


def _allowed_world(monkeypatch, broken: str | None):
    from app.core.exceptions import AuthenticationError

    agent = SimpleNamespace(current_version_id=uuid4(), status="published")
    member = SimpleNamespace(role="member")
    embed = SimpleNamespace(
        agent_id=_EMBED_AGENT,
        is_active=True,
        config={"kind": "page", "voice_conversation": True},
        owner_user_id=uuid4(),
    )
    auth = AsyncMock(return_value=SimpleNamespace(is_app_admin=False))
    access = AsyncMock(return_value=broken != "grant")
    if broken == "token":
        auth.side_effect = AuthenticationError(message="Session revoked")
    if broken == "member":
        member = None
    if broken == "unpublished":
        agent.current_version_id = None
    if broken == "archived":
        agent.status = "archived"
    if broken == "embed_gone":
        embed = None
    if broken == "embed_paused":
        embed.is_active = False
    if broken == "embed_voice_off":
        embed.config = {"kind": "page", "voice_conversation": False}
    if broken == "embed_repointed":
        embed.agent_id = uuid4()
    monkeypatch.setattr(f"{_M}.agent_embed_repo.get", AsyncMock(return_value=embed))
    monkeypatch.setattr(f"{_M}.publisher_context", AsyncMock(return_value=_PUBLISHER))
    monkeypatch.setattr(f"{_M}.authenticate_socket_token", auth)
    monkeypatch.setattr(f"{_M}.member_repo.get", AsyncMock(return_value=member))
    monkeypatch.setattr(f"{_M}.agent_repo.get", AsyncMock(return_value=agent))
    monkeypatch.setattr(f"{_M}.resolve_access", access)
    return auth


@pytest.mark.parametrize("broken", ["token", "member", "grant", "unpublished", "archived"])
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


async def test_an_app_admin_revoked_mid_call_loses_the_flag_at_the_next_heartbeat(monkeypatch):
    """Codex on #2204: the flag from the handshake granted every permission until hang-up."""
    from dataclasses import replace

    from app.services.voice.session import still_allowed

    _allowed_world(monkeypatch, None)
    caller = _caller()
    caller = replace(caller, ctx=replace(caller.ctx, is_app_admin=True))

    ctx = await still_allowed(MagicMock(), caller, agent_id=uuid4())

    assert ctx is not None and ctx.is_app_admin is False


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
    refused = VoiceRefused("no_agent", "Pick an agent to call.")
    with patch(f"{_M}.VoiceCallStarter.start", AsyncMock(side_effect=refused)):
        session = VoiceCallSession(socket, _caller(), sessions=_sessions)
        await asyncio.wait_for(session.run(), timeout=2)
        await session.closed()

    assert socket.sent == [
        {
            "type": "ended",
            "reason": "no_agent",
            "message": "Pick an agent to call.",
        }
    ]


@pytest.mark.security
@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("not_configured", "This agent's voice key is gone. Choose another on its Voice card."),
        ("not_priced", "This model's price is unknown, so its budget could not be enforced."),
        ("budget", "There is not enough budget left for a call."),
    ],
)
async def test_a_visitor_refused_for_the_operators_reasons_is_not_told_them(reason, message):
    """The words are written for the people who run the agent - its Voice card, its price,
    the organization's budget. A visitor gets the reason code their page turns
    into its own copy, and words that say only that calls are not available."""
    from app.services.voice.exceptions import VoiceRefused

    socket = FakeSocket([_START])
    with patch(
        f"{_M}.VoiceCallStarter.start", AsyncMock(side_effect=VoiceRefused(reason, message))
    ):
        await asyncio.wait_for(
            VoiceCallSession(socket, _visitor(), sessions=_sessions).run(), timeout=2
        )

    # The code too: `budget` said the organization had run out to anyone reading
    # the page's frames.
    assert socket.sent == [
        {"type": "ended", "reason": "unavailable", "message": "Calls are not available right now."}
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


def _stalling_relay() -> SimpleNamespace:
    """A relay call whose upstream connection never opens."""
    started = _started(FakeRealtime(hold=True), transport="relay")

    @asynccontextmanager
    async def realtime_session(rt, *, provider_session):
        await anyio.sleep_forever()
        yield FakeRealtime(hold=True)

    started.prepared.realtime_session = realtime_session
    return started


async def test_a_relay_call_is_not_ready_until_its_connection_opens_and_can_be_ended_meanwhile():
    """Codex on #2204: entered after `ready`, a stalled relay read as a live call nobody
    could end, with no heartbeat - the setup's watchers now guard the connection too."""
    socket = FakeSocket([_START, 0.05, json.dumps({"type": "end"})])

    _, repo = await _run(socket, _stalling_relay())

    assert "ready" not in [frame["type"] for frame in socket.sent]
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.USER
    assert socket.sent[-1]["type"] == "ended"


async def test_a_relay_connection_that_never_opens_fails_the_call_at_the_deadline():
    socket = FakeSocket([_START])

    _, repo = await _run(socket, _stalling_relay(), connect_seconds=0.05)

    assert [frame["type"] for frame in socket.sent] == ["ended"]
    assert socket.sent[-1]["reason"] == "error"
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.ERROR


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


async def test_an_end_asked_for_once_ready_has_gone_is_honoured_as_the_session_opens():
    """Between setup and the live call - while its clock is stamped - an end has no
    task group to cancel yet; the live call starts cancelled instead."""
    from app.services.voice.registry import LIVE_CALLS

    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    async def stamp_then_shutdown(*args, **kwargs):
        LIVE_CALLS.request_end_for(started.call_id, VoiceEndReason.SHUTDOWN)

    _, repo = await _run(socket, started, start_clock=AsyncMock(side_effect=stamp_then_shutdown))

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.SHUTDOWN
    assert [frame["type"] for frame in socket.sent][-2:] == ["ready", "ended"]


@pytest.mark.security
async def test_a_response_the_budget_cannot_follow_ends_the_call_with_a_notice():
    from pydantic_ai.realtime import RealtimeTurnCompleteEvent

    socket = FakeSocket([_START])
    realtime = FakeRealtime([RealtimeTurnCompleteEvent()], hold=True)
    started = _started(realtime)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    _, repo = await _run(socket, started)

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET
    assert realtime.sent and "not available right now" in realtime.sent[0]
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


async def test_a_healthy_heartbeat_keeps_the_call_going_and_records_it():
    socket = FakeSocket([_START, 0.1, json.dumps({"type": "end"})])
    _, repo = await _run(socket, _started(FakeRealtime(hold=True)), heartbeat=0.01)
    assert repo.heartbeat.await_count >= 2
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.USER


@pytest.mark.security
async def test_a_heartbeat_writes_the_calls_spend_onto_its_run_for_other_runs_budgets():
    """Baselines sum the runs' cost: a call's spend must be there while it lasts, not only after."""
    socket = FakeSocket([_START, 0.1, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))

    _, repo = await _run(socket, started, heartbeat=0.01)

    assert repo.live_cost.await_args.kwargs == {
        "run_id": started.prepared.run.id,
        "cost_usd": Decimal("0.02"),
    }


async def test_without_a_given_check_the_heartbeat_asks_the_real_one():
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))
    with patch(f"{_M}.still_allowed", AsyncMock(return_value=None)) as allowed:
        _, repo = await _run(socket, started, reauthorize=None, heartbeat=0.01)
    assert allowed.await_args.kwargs["agent_id"] == started.prepared.agent.id
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.REVOKED


async def test_a_minute_before_the_cap_the_call_view_is_warned(monkeypatch):
    monkeypatch.setattr("app.services.voice.limits.WARN_SECONDS", 1)
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True), cap=1.05)  # warned in 0.05 s
    _, repo = await _run(socket, started)
    assert {"type": "limit", "seconds_left": 1} in socket.sent
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


async def test_a_hung_up_call_whose_end_was_not_written_is_left_for_the_reaper():
    """Codex on #2204: stamped hung up, the row left the sweep with its final
    seconds and cost never written."""
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    _, repo = await _run(
        socket, _started(FakeRealtime(hold=True)), end=AsyncMock(side_effect=RuntimeError("db"))
    )
    repo.mark_hung_up.assert_not_awaited()


async def test_a_hung_up_call_whose_run_did_not_close_is_left_for_the_reaper():
    """Codex on #2204: the sweep closes the run from the row; stamped hung up, the
    stale-run sweep failed it six hours later instead."""
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))
    started.runner.finish = AsyncMock(side_effect=RuntimeError("commit failed"))

    _, repo = await _run(socket, started)

    repo.end.assert_awaited_once()
    repo.mark_hung_up.assert_not_awaited()
    assert socket.sent[-1] == {"type": "ended", "reason": "user"}


async def test_a_hang_up_stamp_that_cannot_be_written_still_ends_the_call():
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    mark = AsyncMock(side_effect=RuntimeError("db"))

    await _run(socket, _started(FakeRealtime(hold=True)), mark=mark)

    mark.assert_awaited_once()
    assert socket.sent[-1] == {"type": "ended", "reason": "user"}


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
    # The publisher's role as it stands now, not the one the call started under.
    assert await still_allowed(MagicMock(), visitor, agent_id=_EMBED_AGENT) is _PUBLISHER
    auth.assert_not_awaited()
    member.assert_not_awaited()


def _visitor() -> VoiceCaller:
    return VoiceCaller(
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


@pytest.mark.parametrize(
    "broken", ["embed_gone", "embed_paused", "embed_voice_off", "embed_repointed"]
)
async def test_a_visitors_call_ends_when_its_embed_is_paused_or_its_calls_switched_off(
    monkeypatch, broken
):
    """Or pointed at another agent: the page now offers that one, and a visitor still
    talking to the old one would be on an agent the page no longer runs."""
    from app.services.voice.session import still_allowed

    _allowed_world(monkeypatch, broken)
    assert await still_allowed(MagicMock(), _visitor(), agent_id=_EMBED_AGENT) is None


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
            RealtimeTurnCompleteEvent(),  # the notice's own response
            RealtimeOutputSpeechEndEvent(),
        ],
        hold=True,
    )
    started = _started(realtime)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    # A notice timeout far above the bound asserted below: ending at speech end
    # takes milliseconds and waiting out the timeout takes 30 s, so a loaded
    # runner cannot push one case into the other (it did with 4 s against 2 s).
    # The helper's own deadline sits between the two, so a slow runner reaches
    # the assertion and a call waiting out the notice fails there instead.
    loop = asyncio.get_running_loop()
    began = loop.time()
    _, repo = await _run(socket, started, notice_seconds=30.0, deadline=15.0)

    assert loop.time() - began < 10.0
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


async def test_answers_to_the_questions_card_reach_the_calls_questions():
    answers = json.dumps({"type": "answers", "id": "q1", "answers": [{"selected": ["Yes"]}]})
    stale = json.dumps({"type": "answers", "id": "q2", "answers": []})
    socket = FakeSocket([_START, answers, stale, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))
    started.questions.answer = MagicMock(side_effect=[True, False])

    await _run(socket, started)

    assert started.questions.answer.call_args_list[0].args == ("q1", [{"selected": ["Yes"]}])
    # A card answered aloud first, or after its wait, is closed rather than left open.
    settled = [frame for frame in socket.sent if frame["type"] == "questions_settled"]
    assert settled == [{"type": "questions_settled", "id": "q2"}]


async def test_the_calls_text_twin_reports_its_steps_to_the_calls_pump():
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))
    started.prepared.hand_off = SimpleNamespace(watch=None)
    sessions: list[VoiceCallSession] = []

    await _run(socket, started, during_start=sessions.append)

    pump = sessions[0]._pump
    assert pump is not None and started.prepared.hand_off.watch == pump.worker_event


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


async def test_a_relay_call_carries_audio_both_ways_and_ends_by_closing_its_session():
    """Slice 1: PCM through the socket. Fakes only - Gemini, xAI and Azure are not verified live."""
    socket = FakeSocket(
        [
            _START,
            {"type": "websocket.receive", "bytes": b"\x01\x02" * 80},
            json.dumps({"type": "played", "bytes": 480}),
            json.dumps({"type": "mute", "muted": True}),
            {"type": "websocket.receive", "bytes": b"\x01\x02" * 80},
            "not a frame",
            0.05,
            json.dumps({"type": "end"}),
        ]
    )
    from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, SpeechPart, SpeechPartDelta

    audio = PartDeltaEvent(
        index=1, delta=SpeechPartDelta(speaker="assistant", audio_chunk=b"\x00" * 960)
    )
    realtime = FakeRealtime(
        [
            PartStartEvent(index=1, part=SpeechPart(speaker="assistant", transcript="")),
            audio,
            audio,
        ],
        hold=True,
    )
    started = _started(realtime, transport="relay")

    hung, repo = await _run(socket, started)

    started.prepared.answer_offer.assert_not_awaited()
    assert "answer" not in [frame["type"] for frame in socket.sent]
    assert realtime.audio_in == [b"\x01\x02" * 80, b"\x00" * 160]
    assert {"type": "binary", "size": 960} in socket.sent
    assert hung.await_args.args[0].transport == "relay"
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.USER


async def test_a_webrtc_call_ignores_audio_frames_on_its_socket():
    """Over WebRTC the browser's audio goes to the provider, never through us."""
    socket = FakeSocket(
        [
            _START,
            {"type": "websocket.receive", "bytes": b"\x01\x02" * 80},
            json.dumps({"type": "played", "bytes": 480}),
            json.dumps({"type": "end"}),
        ]
    )
    realtime = FakeRealtime(hold=True)
    await _run(socket, _started(realtime))
    assert realtime.audio_in == []


async def test_a_relay_call_whose_audio_is_not_a_microphone_is_ended_and_says_why(monkeypatch):
    """Review 4: audio far faster than real time ends the call; fakes only, not verified live."""
    from app.services.voice.session import FLOODED

    monkeypatch.setattr(
        "app.services.voice.relay.AudioRelay.inbound", AsyncMock(return_value=False)
    )
    socket = FakeSocket([_START, {"type": "websocket.receive", "bytes": b"\x00\x00" * 80}])
    started = _started(FakeRealtime(hold=True), transport="relay")

    _, repo = await _run(socket, started)

    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.ERROR
    assert socket.sent[-1] == {"type": "ended", "reason": "error", "message": FLOODED}
    assert started.runner.finish.await_args.kwargs["error"] == FLOODED


@pytest.mark.security
async def test_a_visitors_call_ends_when_the_publishers_role_no_longer_runs_the_agent(
    monkeypatch,
):
    """A publisher deactivated mid-call falls back to `viewer`, which the agent may not admit."""
    from app.services.voice.session import still_allowed

    _allowed_world(monkeypatch, "grant")
    assert await still_allowed(MagicMock(), _visitor(), agent_id=_EMBED_AGENT) is None


@pytest.mark.parametrize(
    ("reason", "why"),
    [
        (VoiceEndReason.TIME_LIMIT, "time limit"),
        (VoiceEndReason.BUDGET, "not available right now"),
    ],
)
def test_a_limit_notice_asks_the_agent_to_say_why_the_call_ends(reason, why):
    """The caller heard "the call is ending now" and nothing about why."""
    notice = NOTICES[reason]
    assert "why" in notice
    assert why in notice


def _visitor(*, kind="widget", config=None):
    embed = SimpleNamespace(id=uuid4(), kind=kind, config=config or {})
    return VoiceCaller(
        ctx=_MEMBER_CTX,
        user_id=None,
        user_name=None,
        surface="embed",
        anonymous=True,
        auth_token=None,
        embed_id=embed.id,
        agent_id=uuid4(),
        conversation_id=None,
        embed=embed,
    )


def _tool_turn():
    """One answer that looked an order up: the call, its arguments, and the raw row it returned."""
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.realtime import RealtimeTurnCompleteEvent

    from app.schemas.conversation import MessageRead

    events = [
        FunctionToolCallEvent(
            part=ToolCallPart(tool_name="find_order", args={"q": "SECRET ARGS"}, tool_call_id="c1")
        ),
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="find_order", content="SECRET ROW", tool_call_id="c1")
        ),
        RealtimeTurnCompleteEvent(),
    ]
    now = datetime.now(UTC)
    message_id = uuid4()
    saved = MessageRead.model_validate(
        {
            "id": message_id,
            "conversation_id": uuid4(),
            "role": "assistant",
            "content": "It ships on Monday.",
            "turn_id": "call:1:assistant",
            "created_at": now,
            "parts": [
                {"type": "text", "text": "It ships on Monday."},
                {"type": "tool", "tool_call_id": "c1"},
            ],
            "tool_calls": [
                {
                    "id": uuid4(),
                    "message_id": message_id,
                    "tool_call_id": "c1",
                    "tool_name": "find_order",
                    "args": {"q": "SECRET ARGS"},
                    "result": "SECRET ROW",
                    "status": "completed",
                    "started_at": now,
                }
            ],
        }
    )
    return events, saved


@pytest.mark.security
async def test_a_widget_visitor_never_receives_what_a_tool_was_called_with_or_returned():
    """A widget shows steps but not results (the schema's defaults), and devtools reads every frame."""
    events, saved = _tool_turn()
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(events, hold=True), cap=0)
    started.writer.assistant_turn = AsyncMock(return_value=saved)

    await _run(socket, started, caller=_visitor())

    wire = json.dumps(socket.sent)
    assert "SECRET ROW" not in wire and "SECRET ARGS" not in wire
    assert {"type": "tool", "name": "find_order", "status": "done"} in socket.sent
    (turn,) = [frame["message"] for frame in socket.sent if frame["type"] == "turn_saved"]
    assert turn["content"] == "It ships on Monday."


@pytest.mark.security
async def test_a_page_showing_no_steps_never_names_a_tool_or_says_one_ran():
    events, saved = _tool_turn()
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(events, hold=True), cap=0)
    started.writer.assistant_turn = AsyncMock(return_value=saved)
    page = {"kind": "page", "show_tool_steps": False, "show_tool_results": True}

    await _run(socket, started, caller=_visitor(kind="page", config=page))

    wire = json.dumps(socket.sent)
    assert "find_order" not in wire and "SECRET ROW" not in wire and "SECRET ARGS" not in wire
    assert not [frame for frame in socket.sent if frame["type"] == "tool"]
    assert {"type": "state", "state": "tool_running"} not in socket.sent
    (turn,) = [frame["message"] for frame in socket.sent if frame["type"] == "turn_saved"]
    assert "tool_calls" not in turn and "parts" not in turn


async def test_a_members_call_carries_the_whole_saved_turn():
    events, saved = _tool_turn()
    saved.run_id, saved.agent_id = uuid4(), uuid4()
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(events, hold=True), cap=0)
    started.writer.assistant_turn = AsyncMock(return_value=saved)

    await _run(socket, started, caller=_caller())

    (turn,) = [frame["message"] for frame in socket.sent if frame["type"] == "turn_saved"]
    assert turn["tool_calls"][0]["result"] == "SECRET ROW"
    assert turn["tool_calls"][0]["args"] == {"q": "SECRET ARGS"}
    assert turn["run_id"] == str(saved.run_id)


@pytest.mark.security
@pytest.mark.parametrize(
    "config",
    [
        None,
        {"kind": "page", "show_tool_steps": False, "show_tool_results": False},
        {"kind": "page", "show_tool_steps": True, "show_tool_results": True},
    ],
    ids=["widget", "page-showing-nothing", "page-showing-everything"],
)
async def test_a_visitor_is_sent_only_what_their_page_draws_of_a_saved_turn(config):
    """The widget and the hosted page draw a saved turn's words and nothing else; the
    run, the agent, its version and the turn's cost are the organization's, as `ready`
    keeps the run's id from a visitor, whatever the page shows of tools."""
    events, saved = _tool_turn()
    saved.run_id, saved.agent_id, saved.agent_version_id = uuid4(), uuid4(), uuid4()
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(events, hold=True), cap=0)
    started.writer.assistant_turn = AsyncMock(return_value=saved)
    caller = _visitor() if config is None else _visitor(kind="page", config=config)

    await _run(socket, started, caller=caller)

    (turn,) = [frame["message"] for frame in socket.sent if frame["type"] == "turn_saved"]
    assert turn == {
        "id": str(saved.id),
        "role": "assistant",
        "content": "It ships on Monday.",
        "interrupted": False,
        "turn_id": "call:1:assistant",
    }


@pytest.mark.security
async def test_a_visitor_told_a_tool_needs_approval_is_not_sent_its_arguments():
    socket = FakeSocket([])
    session = VoiceCallSession(socket, _visitor(), sessions=_sessions)

    await session._send(
        ApprovalUnavailableFrame(
            type="approval_unavailable", tool="send_invoice", args={"to": "SECRET"}
        )
    )

    assert socket.sent == [{"type": "approval_unavailable", "tool": "send_invoice", "args": {}}]


async def test_a_visitor_is_warned_before_the_calls_own_time_limit(monkeypatch):
    """The cap is the agent's longest call, not the organization's allowance, so a
    visitor is told it and warned a minute ahead like anyone else."""
    monkeypatch.setattr("app.services.voice.limits.WARN_SECONDS", 1)
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True), cap=1.05)  # warned in 0.05 s

    _, repo = await _run(socket, started, caller=_visitor())

    ready = next(frame for frame in socket.sent if frame["type"] == "ready")
    assert ready["cap_seconds"] == 1
    assert {"type": "limit", "seconds_left": 1} in socket.sent
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.TIME_LIMIT


async def test_a_shutdown_asked_for_while_the_call_starts_opens_no_provider_call():
    """`end_all` reaches a call whose starter is still running, before there is a
    scope to cancel: the reason is kept, and honoured before any offer is answered."""
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    _, repo = await _run(
        socket, started, during_start=lambda s: s.request_end(VoiceEndReason.SHUTDOWN)
    )

    started.prepared.answer_offer.assert_not_awaited()
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.SHUTDOWN


async def test_an_offer_the_provider_never_answers_ends_the_call(monkeypatch):
    """Shielded so a provider call is never orphaned midway, the answer is still
    bounded: End, a closed tab and shutdown are not held off for minutes."""
    monkeypatch.setattr(f"{_M}.OFFER_SECONDS", 0.05)
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    async def never(realtime, sdp):
        await asyncio.sleep(10)

    started.prepared.answer_offer = never

    began = time.monotonic()
    _, repo = await _run(socket, started)

    assert time.monotonic() - began < 2
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.ERROR


class _TimedSocket(FakeSocket):
    """Records when each kind of frame was first sent."""

    def __init__(self, frames):
        super().__init__(frames)
        self.first_sent: dict[str, float] = {}

    async def send_text(self, text):
        await super().send_text(text)
        self.first_sent.setdefault(self.sent[-1]["type"], time.monotonic())


async def test_a_call_never_ends_before_its_callers_timer_reaches_the_cap():
    """The caller's timer starts when `ready` arrives, so the call's clock must not
    start before `ready` has gone - not even by a slow write of its `started_at`."""
    socket = _TimedSocket([_START])
    started = _started(FakeRealtime(hold=True), cap=0.6)

    async def slow_write(*args, **kwargs):
        await asyncio.sleep(0.3)

    await _run(socket, started, start_clock=AsyncMock(side_effect=slow_write))

    assert socket.first_sent["notice"] - socket.first_sent["ready"] >= 0.6


async def test_time_spent_setting_a_call_up_counts_toward_neither_its_cap_nor_its_seconds():
    """The caller's timer starts at `ready`, so the call's clock does: a slow setup
    (a long thread's summary) must not end the call early by its own length."""
    socket = _TimedSocket([_START])
    started = _started(FakeRealtime(hold=True), cap=0.6)

    async def slow_seed(own, *, conversation_id, context_window, summarise):
        await asyncio.sleep(1.2)
        return []

    _, repo = await _run(socket, started, seed=slow_seed)

    assert socket.first_sent["notice"] - socket.first_sent["ready"] >= 0.6
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.TIME_LIMIT
    assert repo.end.await_args.kwargs["seconds"] == 0
    assert started.meter.book_elapsed.call_args.args[0] < 1.2
    # The row's `started_at`, which the month's minutes count from, is the same moment.
    stamped = repo.start_clock.await_args_list[-1]
    assert stamped.args[1] == started.call_id
    assert stamped.kwargs["at"] <= repo.end.await_args.kwargs["at"]


async def test_a_call_that_never_became_ready_lasted_no_time():
    """Its seconds are 0, and its row's start is its end, so the minutes count none either."""
    socket = FakeSocket([_START])
    started = _started(FakeRealtime(hold=True))

    async def failing_seed(own, *, conversation_id, context_window, summarise):
        await asyncio.sleep(0.3)
        raise RuntimeError("summary failed")

    _, repo = await _run(socket, started, seed=failing_seed, heartbeat=0.1)

    ended = repo.end.await_args.kwargs
    assert ended["reason"] is VoiceEndReason.ERROR and ended["seconds"] == 0
    assert repo.start_clock.await_args.kwargs["at"] == ended["at"]
    # Setup's beats carried no seconds either.
    assert {beat.kwargs["seconds"] for beat in repo.heartbeat.await_args_list} == {0}


async def test_a_start_that_fails_on_something_other_than_a_refusal_still_answers_ended(caplog):
    """A key that cannot be unsealed, say: the client hears why in safe words, not a dead socket."""
    from app.core.exceptions import BadRequestError

    socket = FakeSocket([_START])
    failed = BadRequestError(message="Secret envelope could not be opened")
    with patch(f"{_M}.VoiceCallStarter.start", AsyncMock(side_effect=failed)):
        session = VoiceCallSession(socket, _caller(), sessions=_sessions)
        await asyncio.wait_for(session.run(), timeout=2)

    assert socket.sent == [
        {"type": "ended", "reason": "error", "message": "The call could not be started."}
    ]
    assert "voice_call_not_started" in caplog.text


@pytest.mark.security
async def test_an_approval_finish_writes_from_the_channel_is_expired_too():
    """`finish` writes what is still parked as pending; the call is over, so it must not stay so."""
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))
    order: list[str] = []
    started.runner.finish = AsyncMock(side_effect=lambda *a, **k: order.append("finish"))

    async def expire(db, **kwargs):
        order.append("expire")
        return 0

    await _run(socket, started, expire=AsyncMock(side_effect=expire))

    assert order[-2:] == ["finish", "expire"]


@pytest.mark.security
async def test_a_notice_is_not_cut_off_by_the_end_of_the_answer_before_it():
    """Over WebRTC the earlier answer's playback can stop after the notice is asked for."""
    from pydantic_ai.realtime import (
        RealtimeOutputSpeechEndEvent,
        RealtimeOutputSpeechStartEvent,
        RealtimeTurnCompleteEvent,
    )

    socket = FakeSocket([_START])
    realtime = FakeRealtime(
        [
            RealtimeOutputSpeechStartEvent(),
            RealtimeTurnCompleteEvent(),
            0.05,  # the answer is still playing when the notice is asked for
            RealtimeOutputSpeechEndEvent(),
        ],
        hold=True,
    )
    started = _started(realtime)
    started.prepared.built.budget.can_afford_next_request = AsyncMock(return_value=False)

    began = time.monotonic()
    _, repo = await _run(socket, started, notice_seconds=0.5)

    assert time.monotonic() - began >= 0.45
    assert repo.end.await_args.kwargs["reason"] is VoiceEndReason.BUDGET


async def test_a_call_proves_it_is_alive_while_a_slow_summary_seeds_it():
    """A long summary of the history must not leave the row looking dead to the sweep:
    the row is beaten for while the summary runs, not only once it is done. The sweep
    itself against real rows is `integration/test_voice_setup_heartbeat.py`."""
    # The end comes once the summary is done: one during setup would cancel it.
    socket = FakeSocket([_START, 0.6, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))
    beats_while_seeding: list[int] = []

    async def slow_seed(own, *, conversation_id, context_window, summarise):
        from app.services.voice import session as module

        await asyncio.sleep(0.35)
        beats_while_seeding.append(module.voice_call_repo.heartbeat.await_count)
        return []

    _, repo = await _run(socket, started, heartbeat=0.1, seed=slow_seed)

    assert beats_while_seeding[0] >= 2
    assert all(beat.args[1] == started.call_id for beat in repo.heartbeat.await_args_list)


@pytest.mark.parametrize(
    ("hang_up", "reason"),
    [
        (json.dumps({"type": "end"}), VoiceEndReason.USER),
        (WebSocketDisconnect(1001), VoiceEndReason.DISCONNECTED),
    ],
    ids=["end", "tab-closed"],
)
async def test_a_caller_gone_while_the_call_is_set_up_never_opens_the_provider_session(
    hang_up, reason
):
    """A long summary seeds the call before `ready`; an End pressed or a tab closed
    meanwhile stops it there, not after the paid provider session has been opened."""
    # A frame that is not the caller's to send yet is read past, not obeyed.
    socket = FakeSocket([_START, 0.05, json.dumps({"type": "mute", "muted": True}), hang_up])
    started = _started(FakeRealtime(hold=True))
    opened = MagicMock()

    @asynccontextmanager
    async def realtime_session(rt, *, provider_session):
        opened()
        yield FakeRealtime(hold=True)

    started.prepared.realtime_session = realtime_session

    async def slow_seed(own, *, conversation_id, context_window, summarise):
        await anyio.sleep_forever()

    _, repo = await _run(socket, started, seed=slow_seed)

    opened.assert_not_called()
    started.prepared.answer_offer.assert_not_awaited()
    assert "ready" not in [frame["type"] for frame in socket.sent]
    assert repo.end.await_args.kwargs["reason"] is reason
    assert repo.end.await_args.kwargs["seconds"] == 0


@pytest.mark.parametrize(
    "hang_up",
    [json.dumps({"type": "end"}), WebSocketDisconnect(1001)],
    ids=["end", "tab-closed"],
)
async def test_a_caller_gone_while_the_offer_is_answered_still_has_the_provider_call_hung_up(
    hang_up,
):
    """The provider may have created its call before answering the offer, so the
    request is never cut off midway: it finishes, its call id is recorded, and the
    teardown hangs up by that id rather than leave the call billing to its limit."""
    socket = FakeSocket([_START, 0.05, hang_up])
    started = _started(FakeRealtime(hold=True))
    opened = MagicMock()

    @asynccontextmanager
    async def realtime_session(rt, *, provider_session):
        opened()
        yield FakeRealtime(hold=True)

    started.prepared.realtime_session = realtime_session
    answered = MagicMock()

    async def slow_answer(realtime, sdp):
        await asyncio.sleep(0.3)
        answered()
        return SimpleNamespace(sdp="answer-sdp", session=SimpleNamespace(call_id="rtc_mid"))

    started.prepared.answer_offer = slow_answer

    hung, repo = await _run(socket, started)

    answered.assert_called_once()
    assert repo.set_provider_call_id.await_args.kwargs["provider_call_id"] == "rtc_mid"
    assert hung.await_args.args[0].provider_call_id == "rtc_mid"
    opened.assert_not_called()
    assert [frame["type"] for frame in socket.sent] == ["ended"]


def test_push_to_talk_is_not_a_frame_the_server_reads():
    """The browser's alone: a disabled track is silence, so the protocol carries no `ptt`."""
    from pydantic import TypeAdapter, ValidationError

    from app.schemas.voice import ClientFrame

    with pytest.raises(ValidationError):
        TypeAdapter(ClientFrame).validate_python({"type": "ptt", "state": "down"})


async def test_every_frame_a_call_sends_matches_the_published_contract():
    """`ServerFrame` is what the call view reads: `ready`, `answer`, `notice`, `ended` included."""
    from pydantic import TypeAdapter

    from app.schemas.voice import ServerFrame

    events, saved = _tool_turn()
    approval = json.dumps({"type": "approval", "id": "a1", "decision": "approve"})
    socket = FakeSocket([_START, approval])
    started = _started(FakeRealtime(events, hold=True), cap=0)
    started.writer.assistant_turn = AsyncMock(return_value=saved)
    started.bridge.decide = AsyncMock(return_value=False)

    await _run(socket, started)

    adapter = TypeAdapter(ServerFrame)
    kinds = {adapter.validate_python(frame).type for frame in socket.sent}
    assert {"answer", "ready", "tool", "turn_saved", "notice", "approval_settled", "ended"} <= kinds


@pytest.mark.security
@pytest.mark.parametrize("visitor", [True, False])
async def test_ready_gives_the_caller_its_resume_token_and_a_visitor_no_run_id(visitor):
    """A reconnect proves it is the caller with the token only `ready` carries; the
    run's id is a member's, and a public page never reads it."""
    socket = FakeSocket([_START, json.dumps({"type": "end"})])
    started = _started(FakeRealtime(hold=True))

    await _run(socket, started, caller=_visitor() if visitor else _caller())

    ready = next(frame for frame in socket.sent if frame["type"] == "ready")
    assert ready["resume_token"] == started.resume_token
    if visitor:
        assert "run_id" not in ready
    else:
        assert ready["run_id"] == str(started.prepared.run.id)


@pytest.mark.parametrize("loop", ["keep_alive", "heartbeat"])
async def test_a_beat_already_writing_finishes_when_its_loop_is_cancelled(loop):
    """Cut off mid-write, a pooled connection is closed but handed back to the pool,
    and the call's own end then fails on it (`voice_call_row_end_failed`): so a beat
    that has started writing is let finish, and the cancel lands between beats."""
    finished: list[bool] = []

    async def slow_beat(db, started):
        await asyncio.sleep(0.2)
        finished.append(True)

    session = VoiceCallSession(
        FakeSocket([]),
        _caller(),
        sessions=_sessions,
        reauthorize=AsyncMock(return_value=None),
        heartbeat_seconds=0.01,
    )
    session._beat = slow_beat  # type: ignore[method-assign]
    started = _started(FakeRealtime(hold=True))
    with anyio.move_on_after(0.1):
        if loop == "keep_alive":
            await session._keep_alive(started)
        else:
            await session._heartbeat(started, MagicMock(), MagicMock())

    assert finished == [True]


@pytest.mark.security
def test_a_visitor_is_told_a_budget_notice_as_calls_being_unavailable():
    """The reason is the operator's to know: a visitor reading the page's frames sees
    `unavailable`, for a notice as for the end itself."""
    from app.schemas.voice import NoticeFrame
    from app.services.voice.session import VISITOR_REASON, _visible

    shown = _visible(NoticeFrame(type="notice", kind="budget"), frozenset())

    assert isinstance(shown, NoticeFrame) and shown.kind == VISITOR_REASON
    guardrail = _visible(NoticeFrame(type="notice", kind="guardrail"), frozenset())
    assert isinstance(guardrail, NoticeFrame) and guardrail.kind == "guardrail"
