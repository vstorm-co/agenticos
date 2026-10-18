"""Turning a realtime session's events into what the call view and the transcript need (#54)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    DeferredToolRequestsEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    SpeechPart,
    SpeechPartDelta,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.realtime import (
    RealtimeInputSpeechStartEvent,
    RealtimeOutputSpeechEndEvent,
    RealtimeOutputSpeechStartEvent,
    RealtimeTurnCompleteEvent,
)
from pydantic_ai.tools import DeferredToolRequests
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


def _pump(*, guard=None, affordable=True, relay=None):
    frames: list[tuple[str, dict]] = []

    async def send(frame):
        # As the wire carries it: the kind, then only the fields the frame was built with.
        frames.append(
            (frame.type, frame.model_dump(mode="json", exclude_unset=True, exclude={"type"}))
        )

    started = SimpleNamespace(
        call_id=uuid4(),
        writer=_Writer(),
        guard=guard or TranscriptGuard(None),
        meter=MagicMock(book_response=MagicMock(return_value=Decimal("0.01"))),
        questions=MagicMock(),
        prepared=SimpleNamespace(
            built=SimpleNamespace(
                budget=SimpleNamespace(can_afford_next_request=AsyncMock(return_value=affordable))
            )
        ),
    )
    clock = _Clock()
    pump = EventPump(started=started, send=send, clock=SpeechClock(now=clock), relay=relay)
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


async def test_the_text_twins_steps_are_shown_and_saved_on_the_turn_that_handed_off():
    pump, frames, started, _ = _pump()
    hand_off = ToolCallPart(tool_name="hand_off", args={"task": "Draft it"}, tool_call_id="h1")
    step = ToolCallPart(tool_name="write_file", args={"path": "a.md"}, tool_call_id="w1")
    await pump.handle(FunctionToolCallEvent(part=hand_off), _SESSION)
    await pump.worker_event(FunctionToolCallEvent(part=step))
    await pump.worker_event(
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="write_file", content="written", tool_call_id="w1")
        )
    )
    await pump.worker_event(PartStartEvent(index=0, part=TextPart(content="Done")))
    await pump.handle(
        FunctionToolResultEvent(
            part=ToolReturnPart(tool_name="hand_off", content="Wrote a.md", tool_call_id="h1")
        ),
        _SESSION,
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    tools = started.writer.assistant_turn.await_args.kwargs["tools"]
    assert [(t.tool_name, t.result) for t in tools] == [
        ("hand_off", "Wrote a.md"),
        ("write_file", "written"),
    ]
    assert ("tool", {"name": "write_file", "status": "running"}) in frames
    assert ("tool", {"name": "write_file", "status": "done"}) in frames


async def test_a_twin_waiting_on_an_approval_says_so():
    pump, frames, _, _ = _pump()
    await pump.worker_event(DeferredToolRequestsEvent(requests=DeferredToolRequests()))
    assert frames[-1] == ("state", {"state": "awaiting_approval"})


async def test_what_the_caller_says_answers_an_open_questions_card():
    pump, _, started, _ = _pump()
    await pump.handle(
        PartEndEvent(index=0, part=SpeechPart(speaker="user", transcript="The second one")),
        _SESSION,
    )
    started.questions.heard.assert_called_once_with("The second one")


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


async def test_the_agent_stopping_after_the_notices_response_sets_the_event_it_waits_on():
    """An earlier answer's playback ending is not the notice said; the end after its response is."""
    pump, _, _, _ = _pump()
    done = pump.arm_output_done()

    await pump.handle(RealtimeOutputSpeechEndEvent(), _SESSION)
    assert not done.is_set()

    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    await pump.handle(RealtimeOutputSpeechEndEvent(), _SESSION)
    assert done.is_set() and pump.output_done is done


async def test_a_notice_asked_for_while_an_answer_is_still_coming_waits_past_that_answer():
    """RR-c06's last case: an answer still being generated when the notice is armed
    completes after arming, so its playback end is not the notice heard either."""
    pump, _, _, _ = _pump()
    await pump.handle(
        PartStartEvent(index=1, part=SpeechPart(speaker="assistant", transcript="")), _SESSION
    )
    await pump.handle(
        PartEndEvent(index=1, part=SpeechPart(speaker="assistant", transcript="Your order left.")),
        _SESSION,
    )
    done = pump.arm_output_done()

    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    await pump.handle(RealtimeOutputSpeechEndEvent(), _SESSION)
    assert not done.is_set()

    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    await pump.handle(RealtimeOutputSpeechEndEvent(), _SESSION)
    assert done.is_set()


@pytest.mark.security
async def test_a_tool_that_asked_for_a_retry_is_saved_as_failed_without_its_raw_text():
    """A retry is a failed call, and its text is whatever raised - a vendor's URL and
    query string included - so the row holds the shared notice, as a text run's does."""
    pump, _, started, _ = _pump()
    await pump.handle(
        FunctionToolCallEvent(
            part=ToolCallPart(tool_name="web_search", args={"q": "x"}, tool_call_id="c1")
        ),
        _SESSION,
    )
    await pump.handle(
        FunctionToolResultEvent(
            part=RetryPromptPart(
                tool_name="web_search",
                content="401 Unauthorized for url 'https://api.example.com/search?key=k'",
                tool_call_id="c1",
            )
        ),
        _SESSION,
    )
    await pump.handle(
        PartEndEvent(index=2, part=SpeechPart(speaker="assistant", transcript="No luck.")),
        _SESSION,
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    (tool,) = started.writer.assistant_turn.await_args.kwargs["tools"]
    assert tool.success is False
    assert tool.result is not None and "api.example.com" not in tool.result


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
    pump.note_played_ms(2000)
    await pump.flush()
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"


async def test_provider_events_become_states_and_notices():
    from pydantic_ai.realtime import RealtimeResponseInterruptedEvent, RealtimeSessionErrorEvent

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


async def test_a_notice_after_a_silent_answer_waits_only_for_its_own_response():
    """An answer that started but said nothing completes and saves nothing; it is
    over, so a notice armed after it is ended by the next response, not the one after."""
    pump, _, started, _ = _pump()
    await pump.handle(
        PartStartEvent(index=1, part=SpeechPart(speaker="assistant", transcript="")), _SESSION
    )
    await pump.handle(
        PartEndEvent(index=1, part=SpeechPart(speaker="assistant", transcript="")), _SESSION
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    started.writer.assistant_turn.assert_not_awaited()
    done = pump.arm_output_done()

    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    await pump.handle(RealtimeOutputSpeechEndEvent(), _SESSION)
    assert done.is_set()


_ANSWER = "It is eighteen degrees and cloudy in Warsaw, with rain expected by the evening."


def _relay(played_ms):
    return MagicMock(barge_in=AsyncMock(return_value=played_ms), answer_started=MagicMock())


async def _spoken_answer(pump, index=4):
    await pump.handle(
        PartStartEvent(index=index, part=SpeechPart(speaker="assistant", transcript="")), _SESSION
    )
    await pump.handle(
        PartEndEvent(index=index, part=SpeechPart(speaker="assistant", transcript=_ANSWER)),
        _SESSION,
    )


async def test_over_the_relay_speaking_over_the_agent_cuts_at_what_the_browser_played():
    """The relay's exact position, not the WebRTC estimate. Fakes only: not verified live."""
    relay = _relay(2000)
    pump, frames, started, _ = _pump(relay=relay)
    await _spoken_answer(pump)
    await pump.handle(
        PartStartEvent(index=5, part=SpeechPart(speaker="assistant", transcript="")), _SESSION
    )

    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    relay.barge_in.assert_awaited_once_with(_SESSION)
    relay.answer_started.assert_called_once()  # once per response, not per part
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"
    assert started.writer.assistant_turn.await_args.kwargs["interrupted"] is True
    assert [p["state"] for k, p in frames if k == "state"][-2:] == ["interrupted", "user_speaking"]


async def test_over_the_relay_speech_after_the_answer_was_heard_cuts_nothing():
    pump, frames, started, _ = _pump(relay=_relay(None))
    await _spoken_answer(pump)

    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    assert started.writer.assistant_turn.await_args.args[0] == _ANSWER
    assert started.writer.assistant_turn.await_args.kwargs["interrupted"] is False
    assert ("state", {"state": "interrupted"}) not in frames


async def test_geminis_own_interruption_flushes_the_relay():
    """Gemini reports no speech start: its interruption event is the barge-in."""
    from pydantic_ai.realtime import RealtimeResponseInterruptedEvent

    relay = _relay(2000)
    pump, frames, started, _ = _pump(relay=relay)
    await _spoken_answer(pump)

    await pump.handle(RealtimeResponseInterruptedEvent(), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    relay.barge_in.assert_awaited_once_with(_SESSION)
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"
    assert ("state", {"state": "interrupted"}) in frames


def _real_relay(**profile):
    from app.services.voice.relay import AudioRelay

    sent: list[bytes] = []
    frames: list[tuple[str, dict]] = []

    async def send_bytes(data):
        sent.append(data)
        return True

    async def send(frame):
        # As the wire carries it: the kind, then only the fields the frame was built with.
        frames.append(
            (frame.type, frame.model_dump(mode="json", exclude_unset=True, exclude={"type"}))
        )

    relay = AudioRelay(
        send_bytes=send_bytes, send=send, input_sample_rate=24000, output_sample_rate=24000
    )
    session = SimpleNamespace(
        usage=RunUsage(cost=Decimal("0.01")),
        interrupt=AsyncMock(),
        profile={"supports_interruption": True, "supports_output_truncation": True, **profile},
    )
    return relay, sent, frames, session


_SECOND = 48_000


async def _answer_with_audio(pump, session, index, seconds, *, complete=True):
    await pump.handle(
        PartStartEvent(index=index, part=SpeechPart(speaker="assistant", transcript="")), session
    )
    await pump.handle(
        PartDeltaEvent(
            index=index,
            delta=SpeechPartDelta(
                speaker="assistant", audio_chunk=b"\x00" * int(seconds * _SECOND)
            ),
        ),
        session,
    )
    if complete:
        await pump.handle(
            PartEndEvent(index=index, part=SpeechPart(speaker="assistant", transcript=_ANSWER)),
            session,
        )
        await pump.handle(RealtimeTurnCompleteEvent(), session)


async def test_cutting_in_on_a_saved_answer_still_playing_trims_neither_it_nor_the_next():
    """Review blocker 1: a barge-in after the answer was saved must not leak into the next one."""
    relay, _, relay_frames, session = _real_relay()
    pump, frames, started, _ = _pump(relay=relay)
    await _answer_with_audio(pump, session, 4, 3)
    assert started.writer.assistant_turn.await_args.args[0] == _ANSWER
    relay.heard(_SECOND)

    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), session)
    await _answer_with_audio(pump, session, 6, 1)

    assert relay_frames == [("clear_playback", {})]
    assert ("state", {"state": "interrupted"}) in frames
    assert started.writer.assistant_turn.await_args.args[0] == _ANSWER
    assert started.writer.assistant_turn.await_args.kwargs["interrupted"] is False


async def test_over_webrtc_speech_after_the_answer_was_saved_does_not_trim_the_next():
    """The provider's playback outlasts the response: the same leak, on the heuristic's path."""
    pump, frames, started, clock = _pump()
    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(
        PartEndEvent(index=3, part=SpeechPart(speaker="assistant", transcript=_ANSWER)), _SESSION
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    clock.t += 2.0

    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), _SESSION)
    await pump.handle(
        PartEndEvent(index=5, part=SpeechPart(speaker="assistant", transcript=_ANSWER)), _SESSION
    )
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)

    assert ("state", {"state": "interrupted"}) in frames
    assert started.writer.assistant_turn.await_args.args[0] == _ANSWER
    assert started.writer.assistant_turn.await_args.kwargs["interrupted"] is False


async def test_the_answer_start_is_counted_in_event_order_not_when_the_pump_got_round_to_it():
    """Review 2: audio is forwarded by the pump itself, so a slow write cannot shift the start."""
    relay, sent, _, session = _real_relay()
    pump, _, started, _ = _pump(relay=relay)
    started.writer.user_turn = AsyncMock(side_effect=lambda *a, **k: None)
    await _answer_with_audio(pump, session, 1, 1)
    await _answer_with_audio(pump, session, 3, 3, complete=False)
    relay.heard(_SECOND + 2 * _SECOND)  # the first answer, then two seconds of the second

    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), session)
    await pump.handle(
        PartEndEvent(index=3, part=SpeechPart(speaker="assistant", transcript=_ANSWER)), session
    )
    await pump.handle(RealtimeTurnCompleteEvent(), session)

    session.interrupt.assert_awaited_once_with(played_ms=2000)
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"
    assert sum(len(chunk) for chunk in sent) == 4 * _SECOND


async def test_audio_of_the_part_a_barge_in_cut_never_reaches_the_browser():
    relay, sent, _, session = _real_relay()
    pump, _, _, _ = _pump(relay=relay)
    await _answer_with_audio(pump, session, 2, 2, complete=False)
    relay.heard(_SECOND)
    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), session)

    await pump.handle(
        PartDeltaEvent(
            index=2, delta=SpeechPartDelta(speaker="assistant", audio_chunk=b"\x00" * 960)
        ),
        session,
    )

    assert sum(len(chunk) for chunk in sent) == 2 * _SECOND


async def test_on_gemini_the_callers_words_arriving_over_a_playing_answer_flush_it():
    """Gemini reports no speech start, and no interruption once an answer finished generating."""
    relay, _, relay_frames, session = _real_relay(
        supports_interruption=False, supports_output_truncation=False
    )
    pump, frames, _, _ = _pump(relay=relay)
    await _answer_with_audio(pump, session, 2, 2)

    await pump.handle(
        PartStartEvent(index=3, part=SpeechPart(speaker="user", transcript="")), session
    )

    session.interrupt.assert_not_awaited()
    assert relay_frames == [("clear_playback", {})]
    assert ("state", {"state": "interrupted"}) in frames
    # Once flushed, the caller's next part is not a second barge-in.
    await pump.handle(
        PartStartEvent(index=5, part=SpeechPart(speaker="user", transcript="")), session
    )
    assert relay_frames == [("clear_playback", {})]


async def test_the_providers_mark_wins_over_a_later_estimate():
    pump, _, started, clock = _pump()
    await pump.handle(RealtimeOutputSpeechStartEvent(), _SESSION)
    await pump.handle(
        PartEndEvent(
            index=8,
            part=SpeechPart(speaker="assistant", interrupted_at_ms=2000, transcript=_ANSWER),
        ),
        _SESSION,
    )
    clock.t += 30.0
    await pump.handle(RealtimeInputSpeechStartEvent(item_id="i1"), _SESSION)
    await pump.handle(RealtimeTurnCompleteEvent(), _SESSION)
    assert started.writer.assistant_turn.await_args.args[0] == "It is eighteen degrees and"
