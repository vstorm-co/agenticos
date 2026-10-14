"""Turning a realtime session's events into what the call view and the transcript need (#54)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    SpeechPart,
    SpeechPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.realtime import (
    RealtimeInputSpeechStartEvent,
    RealtimeOutputSpeechEndEvent,
    RealtimeOutputSpeechStartEvent,
    RealtimeTurnCompleteEvent,
)
from pydantic_ai.usage import RunUsage

from app.services.voice.guard import TranscriptGuard
from app.services.voice.pump import EventPump
from app.services.voice.transcript import SpeechClock

pytestmark = pytest.mark.anyio


class _Clock:
    t = 10.0

    def __call__(self):
        return self.t


class _Writer:
    """The writer's id scheme, with the writes themselves mocked."""

    def __init__(self) -> None:
        self.count = 0
        self.user_turn = AsyncMock(return_value=None)
        self.assistant_turn = AsyncMock(return_value=None)

    def next_turn_id(self, role):
        self.count += 1
        return f"call:{self.count}:{role}"


def _pump(*, guard=None, affordable=True):
    frames: list[tuple[str, dict]] = []

    async def send(kind, payload):
        frames.append((kind, payload))

    started = SimpleNamespace(
        call_id=uuid4(),
        writer=_Writer(),
        guard=guard or TranscriptGuard(None),
        meter=MagicMock(book_response=MagicMock(return_value=Decimal("0.01"))),
        prepared=SimpleNamespace(
            built=SimpleNamespace(
                budget=SimpleNamespace(can_afford_next_request=AsyncMock(return_value=affordable))
            )
        ),
    )
    clock = _Clock()
    pump = EventPump(started=started, send=send, clock=SpeechClock(now=clock))
    return pump, frames, started, clock


_SESSION = SimpleNamespace(usage=RunUsage(cost=Decimal("0.01")), interrupt=AsyncMock())


async def test_both_sides_are_captioned_word_by_word_and_finalised():
    pump, frames, started, _ = _pump()
    await pump.handle(
        PartStartEvent(index=0, part=SpeechPart(speaker="user", transcript="")), _SESSION
    )
    await pump.handle(
        PartDeltaEvent(
            index=0,
            delta=SpeechPartDelta(
                speaker="user", transcript_delta=" Weather", transcript=" Weather"
            ),
        ),
        _SESSION,
    )
    await pump.handle(
        PartEndEvent(index=0, part=SpeechPart(speaker="user", transcript="Weather in Warsaw?")),
        _SESSION,
    )

    captions = [payload for kind, payload in frames if kind == "caption"]
    assert captions[0]["delta"] == " Weather" and captions[0]["role"] == "user"
    assert (
        captions[-1]["final"] == "Weather in Warsaw?"
        and captions[-1]["turn_id"] == captions[0]["turn_id"]
    )
    started.writer.user_turn.assert_awaited_once_with(
        "Weather in Warsaw?", turn_id=captions[0]["turn_id"]
    )
    assert captions[0]["turn_id"] == "call:1:user"
    assert pump.heard == "Weather in Warsaw?"


@pytest.mark.security
async def test_a_finished_response_is_booked_saved_with_its_tools_and_checked_against_the_budget():
    pump, frames, started, _ = _pump()
    await pump.handle(
        FunctionToolCallEvent(
            part=ToolCallPart(tool_name="get_weather", args={"city": "Warsaw"}, tool_call_id="c1")
        ),
        _SESSION,
    )
    await pump.handle(
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="get_weather", content="18C", tool_call_id="c1")
        ),
        _SESSION,
    )
    await pump.handle(
        PartEndEvent(
            index=2, part=SpeechPart(speaker="assistant", transcript="Eighteen and cloudy.")
        ),
        _SESSION,
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    started.meter.book_response.assert_called_once_with(_SESSION.usage)
    (text,) = started.writer.assistant_turn.await_args.args
    kwargs = started.writer.assistant_turn.await_args.kwargs
    assert text == "Eighteen and cloudy." and kwargs["interrupted"] is False
    assert [t.tool_name for t in kwargs["tools"]] == ["get_weather"] and kwargs["tools"][
        0
    ].result == "18C"
    assert ("state", {"state": "tool_running"}) in frames
    assert not pump.budget_exhausted


@pytest.mark.security
async def test_a_response_the_budget_cannot_follow_marks_the_call_for_ending():
    pump, _, _, _ = _pump(affordable=False)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    assert pump.budget_exhausted


async def test_speaking_over_the_agent_trims_the_saved_answer_and_marks_it_interrupted():
    pump, frames, started, clock = _pump()
    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(
        PartEndEvent(
            index=3,
            part=SpeechPart(
                speaker="assistant",
                transcript="It is eighteen degrees and cloudy in Warsaw, with rain expected by the evening.",
            ),
        ),
        _SESSION,
    )
    clock.t += 2.0
    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"
    assert started.writer.assistant_turn.await_args.kwargs["interrupted"] is True
    assert ("state", {"state": "interrupted"}) in frames


async def test_a_blocked_answer_is_cut_off_mid_sentence_and_withheld():
    from app.agents.spec import AgentSpec, CapabilityBindingSpec

    guard = TranscriptGuard.for_spec(
        AgentSpec(
            name="a",
            capabilities=[
                CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_out": "Falcon"})
            ],
        )
    )
    pump, frames, _, _ = _pump(guard=guard)
    session = SimpleNamespace(usage=RunUsage(), interrupt=AsyncMock())
    await pump.handle(
        PartStartEvent(index=4, part=SpeechPart(speaker="assistant", transcript="")), session
    )
    await pump.handle(
        PartDeltaEvent(
            index=4,
            delta=SpeechPartDelta(
                speaker="assistant",
                transcript_delta="The codename is Falcon.",
                transcript="The codename is Falcon.",
            ),
        ),
        session,
    )

    session.interrupt.assert_awaited_once()
    assert ("notice", {"kind": "guardrail"}) in frames
    assert not any(kind == "caption" and "Falcon" in str(payload) for kind, payload in frames)


async def test_a_blocked_term_split_across_deltas_never_reaches_a_caption():
    from app.agents.spec import AgentSpec, CapabilityBindingSpec

    guard = TranscriptGuard.for_spec(
        AgentSpec(
            name="a",
            capabilities=[
                CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_out": "Falcon"})
            ],
        )
    )
    pump, frames, _, _ = _pump(guard=guard)
    session = SimpleNamespace(usage=RunUsage(), interrupt=AsyncMock())
    text = ""
    for piece in ("The codename ", "is Fal", "con."):
        text += piece
        await pump.handle(
            PartDeltaEvent(
                index=6,
                delta=SpeechPartDelta(speaker="assistant", transcript_delta=piece, transcript=text),
            ),
            session,
        )

    session.interrupt.assert_awaited_once()
    assert not any(kind == "caption" and "Fal" in str(payload) for kind, payload in frames)


async def test_with_an_output_guardrail_the_agents_captions_arrive_a_sentence_at_a_time():
    from app.agents.spec import AgentSpec, CapabilityBindingSpec

    guard = TranscriptGuard.for_spec(
        AgentSpec(
            name="a",
            capabilities=[
                CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_out": "Falcon"})
            ],
        )
    )
    pump, frames, _, _ = _pump(guard=guard)
    text = ""
    for piece in ("It is ", "sunny. ", "Warm", " too."):
        text += piece
        await pump.handle(
            PartDeltaEvent(
                index=7,
                delta=SpeechPartDelta(speaker="assistant", transcript_delta=piece, transcript=text),
            ),
            _SESSION,
        )

    assert [p["text"] for k, p in frames if k == "caption"] == [
        "It is sunny. ",
        "It is sunny. Warm too.",
    ]


async def test_an_answer_the_provider_marks_interrupted_is_trimmed_to_its_mark():
    pump, _, started, _ = _pump()
    await pump.handle(
        PartEndEvent(
            index=8,
            part=SpeechPart(
                speaker="assistant",
                interrupted_at_ms=2000,
                transcript="It is eighteen degrees and cloudy in Warsaw, with rain expected by the evening.",
            ),
        ),
        _SESSION,
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"
    assert started.writer.assistant_turn.await_args.kwargs["interrupted"] is True


async def test_the_agent_stopping_sets_the_event_spoken_notices_wait_on():
    pump, _, _, _ = _pump()
    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(RealtimeOutputSpeechEndEvent(), _SESSION)
    assert pump.output_done.is_set()


async def test_an_ended_call_still_saves_the_answer_in_progress():
    pump, _, started, _ = _pump()
    await pump.handle(
        PartEndEvent(index=5, part=SpeechPart(speaker="assistant", transcript="Goodbye.")), _SESSION
    )
    await pump.flush()
    assert started.writer.assistant_turn.await_args.args[0] == "Goodbye."


async def test_speech_while_nobody_is_talking_is_not_an_interruption():
    from pydantic_ai.realtime import RealtimeInputSpeechEndEvent

    pump, frames, _, _ = _pump()
    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), _SESSION)
    await pump.handle(RealtimeInputSpeechEndEvent(item_id="i1"), _SESSION)

    assert [p["state"] for k, p in frames if k == "state"] == ["user_speaking", "thinking"]


async def test_the_relays_exact_playback_wins_over_the_estimate():
    pump, _, started, _ = _pump()
    pump.note_played_ms(2000)
    await pump.handle(
        PartEndEvent(
            index=9,
            part=SpeechPart(
                speaker="assistant",
                transcript="It is eighteen degrees and cloudy in Warsaw, with rain expected by the evening.",
            ),
        ),
        _SESSION,
    )
    await pump.flush()
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"


async def test_provider_events_become_states_and_notices():
    from pydantic_ai.messages import DeferredToolRequestsEvent
    from pydantic_ai.realtime import RealtimeResponseInterruptedEvent, RealtimeSessionErrorEvent
    from pydantic_ai.tools import DeferredToolRequests

    pump, frames, _, _ = _pump()
    await pump.handle(RealtimeResponseInterruptedEvent(), _SESSION)
    await pump.handle(DeferredToolRequestsEvent(requests=DeferredToolRequests()), _SESSION)
    await pump.handle(RealtimeSessionErrorEvent(message="boom", type="server_error"), _SESSION)
    await pump.handle(object(), _SESSION)

    assert frames == [
        ("state", {"state": "interrupted"}),
        ("state", {"state": "awaiting_approval"}),
        ("notice", {"kind": "provider_error"}),
    ]


async def test_a_result_for_a_tool_the_call_never_saw_start_is_ignored():
    pump, frames, _, _ = _pump()
    await pump.handle(
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="x", content="y", tool_call_id="unknown")
        ),
        _SESSION,
    )
    assert frames == []


async def test_an_audio_only_delta_has_no_caption():
    pump, frames, _, _ = _pump()
    await pump.handle(
        PartDeltaEvent(
            index=0, delta=SpeechPartDelta(speaker="assistant", audio_chunk=b"\x00\x01")
        ),
        _SESSION,
    )
    assert frames == []


def _message(role: str, turn_id: str):
    from datetime import UTC, datetime

    from app.schemas.conversation import MessageRead

    return MessageRead(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content="x",
        turn_id=turn_id,
        created_at=datetime.now(UTC),
    )


async def test_every_frame_the_pump_sends_matches_the_published_contract():
    """`ServerFrame` is what the call view reads; a frame outside it is a contract break."""
    from pydantic import TypeAdapter

    from app.schemas.voice import ServerFrame

    pump, frames, started, _ = _pump()
    started.writer.user_turn.return_value = _message("user", "call:1:user")
    started.writer.assistant_turn.return_value = _message("assistant", "call:2:assistant")
    for event in (
        PartStartEvent(index=0, part=SpeechPart(speaker="user", transcript="")),
        PartDeltaEvent(
            index=0, delta=SpeechPartDelta(speaker="user", transcript_delta=" Hi", transcript=" Hi")
        ),
        PartEndEvent(index=0, part=SpeechPart(speaker="user", transcript="Hi")),
        RealtimeOutputSpeechStartEvent(),
        FunctionToolCallEvent(
            part=ToolCallPart(tool_name="get_weather", args={"city": "W"}, tool_call_id="c1")
        ),
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="get_weather", content="18C", tool_call_id="c1")
        ),
        PartEndEvent(index=1, part=SpeechPart(speaker="assistant", transcript="Sunny.")),
        RealtimeOutputSpeechEndEvent(),
        RealtimeTurnCompleteEvent(),
    ):
        await pump.handle(event, _SESSION)

    adapter = TypeAdapter(ServerFrame)
    kinds = {adapter.validate_python({"type": kind, **payload}).type for kind, payload in frames}
    assert {"state", "caption", "tool", "turn_saved"} <= kinds


async def test_a_caption_and_its_saved_turn_share_one_id():
    """The call view swaps a turn's captions for its saved message by this id."""
    pump, frames, started, _ = _pump()
    started.writer.assistant_turn.return_value = _message("assistant", "call:1:assistant")
    for event in (
        PartStartEvent(index=3, part=SpeechPart(speaker="assistant", transcript="")),
        PartDeltaEvent(
            index=3,
            delta=SpeechPartDelta(
                speaker="assistant", transcript_delta="Sunny.", transcript="Sunny."
            ),
        ),
        PartEndEvent(index=3, part=SpeechPart(speaker="assistant", transcript="Sunny.")),
        PartEndEvent(index=4, part=SpeechPart(speaker="assistant", transcript="Warm too.")),
        RealtimeTurnCompleteEvent(),
    ):
        await pump.handle(event, _SESSION)

    caption_ids = {p["turn_id"] for k, p in frames if k == "caption"}
    saved = [p["message"]["turn_id"] for k, p in frames if k == "turn_saved"]
    assert caption_ids == {"call:1:assistant"} and saved == ["call:1:assistant"]
    assert started.writer.assistant_turn.await_args.kwargs["turn_id"] == "call:1:assistant"
    assert {p["part"] for k, p in frames if k == "caption"} == {3, 4}


async def test_a_redacted_answer_is_captioned_redacted():
    from app.agents.spec import AgentSpec, CapabilityBindingSpec

    guard = TranscriptGuard.for_spec(
        AgentSpec(
            name="a",
            capabilities=[CapabilityBindingSpec(id="guardrails", config={"redact_pii_out": True})],
        )
    )
    pump, frames, _, _ = _pump(guard=guard)
    text = ""
    for piece in ("Write to ann@", "example.com today."):
        text += piece
        await pump.handle(
            PartDeltaEvent(
                index=7,
                delta=SpeechPartDelta(speaker="assistant", transcript_delta=piece, transcript=text),
            ),
            _SESSION,
        )
    await pump.handle(
        PartEndEvent(index=7, part=SpeechPart(speaker="assistant", transcript=text)), _SESSION
    )

    captions = [p for k, p in frames if k == "caption"]
    assert captions and not any("ann@" in str(p) for p in captions)
    assert "text" in captions[0] and "final" in captions[-1]


async def test_a_blocked_answer_counts_one_guardrail_hit():
    from app.agents.spec import AgentSpec, CapabilityBindingSpec

    guard = TranscriptGuard.for_spec(
        AgentSpec(
            name="a",
            capabilities=[
                CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_out": "Falcon"})
            ],
        )
    )
    pump, frames, _, _ = _pump(guard=guard)
    session = SimpleNamespace(usage=RunUsage(), interrupt=AsyncMock())
    said = "The codename is Falcon."
    await pump.handle(
        PartDeltaEvent(
            index=4,
            delta=SpeechPartDelta(speaker="assistant", transcript_delta=said, transcript=said),
        ),
        session,
    )
    await pump.handle(
        PartEndEvent(index=4, part=SpeechPart(speaker="assistant", transcript=said)), session
    )

    assert guard.hits == 1
    assert [p["final"] for k, p in frames if k == "caption"] == ["[withheld by a guardrail]"]


async def test_a_delta_with_no_speaker_is_screened_as_the_agents():
    from app.agents.spec import AgentSpec, CapabilityBindingSpec

    guard = TranscriptGuard.for_spec(
        AgentSpec(
            name="a",
            capabilities=[
                CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_out": "Falcon"})
            ],
        )
    )
    pump, frames, _, _ = _pump(guard=guard)
    session = SimpleNamespace(usage=RunUsage(), interrupt=AsyncMock())
    said = "Falcon."
    await pump.handle(
        PartDeltaEvent(index=5, delta=SpeechPartDelta(transcript_delta=said, transcript=said)),
        session,
    )
    session.interrupt.assert_awaited_once()


async def test_a_response_with_nothing_said_and_no_tools_saves_nothing():
    pump, _, started, _ = _pump()
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    started.writer.assistant_turn.assert_not_awaited()
