"""One realtime session's events, as frames, captions, saved turns and spend (#54).

Captions come from the transcript deltas of both sides (about 175 a minute in
the spike) and are replaced by the saved message when a turn finishes. Each
finished response is booked on the run's ledger and checked against the budget
before the next one; `UsageLimits.cost_limit` is the hard stop under that, and
can overshoot by at most one response.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import anyio
from pydantic_ai.messages import (
    AgentStreamEvent,
    DeferredToolRequestsEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    SpeechPart,
    SpeechPartDelta,
)
from pydantic_ai.realtime import (
    RealtimeInputSpeechEndEvent,
    RealtimeInputSpeechStartEvent,
    RealtimeOutputSpeechEndEvent,
    RealtimeOutputSpeechStartEvent,
    RealtimeResponseInterruptedEvent,
    RealtimeSession,
    RealtimeSessionErrorEvent,
    RealtimeTurnCompleteEvent,
)

from app.schemas.conversation import MessageRead
from app.schemas.voice import CaptionFrame, NoticeFrame, StateFrame, ToolFrame, TurnSavedFrame
from app.services.transcript import tool_result_text, tool_retry_notice
from app.services.voice.approvals import SendFrame
from app.services.voice.guard import WITHHELD
from app.services.voice.transcript import SpeechClock, SpokenToolCall, trim_to_played

if TYPE_CHECKING:
    from app.services.voice.relay import AudioRelay
    from app.services.voice.starter import StartedCall

VoiceState = Literal[
    "connecting",
    "listening",
    "user_speaking",
    "thinking",
    "agent_speaking",
    "interrupted",
    "tool_running",
    "awaiting_approval",
]

_SENTENCE_END = re.compile(r"[.!?]\s*$")


class EventPump:
    """One call's realtime events, turned into frames, captions, saved turns and spend."""

    def __init__(
        self,
        *,
        started: StartedCall,
        send: SendFrame,
        clock: SpeechClock | None = None,
        relay: AudioRelay | None = None,
    ) -> None:
        self._started = started
        self._send = send
        self._clock = clock or SpeechClock()
        self._relay = relay
        self._spoken: list[str] = []
        self._tools: dict[str, SpokenToolCall] = {}
        self._played_ms: int | None = None
        self._live_text: dict[int, str] = {}
        self._withheld: set[int] = set()
        self._part_turn: dict[int, str] = {}
        self._response_turn: str | None = None
        self.heard: str | None = None
        self.output_done = anyio.Event()
        self._completes_to_notice = 1
        self.budget_exhausted = False

    def arm_output_done(self) -> anyio.Event:
        """A fresh `output_done`, set when the agent stops speaking after a response that
        completes from now on.

        A limit notice waits on it for its own sentence. Over WebRTC the speech end
        is the browser's playback stopping, and an answer generated before the
        notice can still be playing when it is asked for: that answer's end must
        not end the call before the notice is heard. Nor must the end of one still
        being generated, whose response completes after this: the notice's is then
        the second to complete. (A response that has not spoken yet is not seen
        here; its turn starts with its speech.)
        """
        self.output_done = anyio.Event()
        self._completes_to_notice = 1 if self._response_turn is None else 2
        return self.output_done

    def _turn(self, index: int, role: Literal["user", "assistant"]) -> str:
        """The saved message's `turn_id` for a speech part, allocated when it is first seen.

        The caller's every utterance is a turn of its own; the agent's parts in
        one response are one turn, saved when the response completes. Captions
        carry this id, so the call view replaces them with the `turn_saved`
        message that has it.
        """
        known = self._part_turn.get(index)
        if known is not None:
            return known
        if role == "user":
            turn_id = self._started.writer.next_turn_id("user")
        else:
            if self._response_turn is None:
                self._response_turn = self._started.writer.next_turn_id("assistant")
            turn_id = self._response_turn
        self._part_turn[index] = turn_id
        return turn_id

    def _caption(
        self,
        index: int,
        role: Literal["user", "assistant"],
        *,
        delta: str | None = None,
        text: str | None = None,
        final: str | None = None,
    ) -> CaptionFrame:
        caption = CaptionFrame(
            type="caption", role=role, turn_id=self._turn(index, role), part=index
        )
        # Exactly one of the three is set, and only that one is sent.
        if delta is not None:
            caption.delta = delta
        if text is not None:
            caption.text = text
        if final is not None:
            caption.final = final
        return caption

    async def _state(self, state: VoiceState) -> None:
        await self._send(StateFrame(type="state", state=state))

    def note_played_ms(self, played_ms: int) -> None:
        """How much of the answer in progress was heard; trims it when it is saved.

        Only while that answer is still open: one already saved stays as it was
        saved (history is append-only, as in the library), and a time noted
        after it would otherwise trim - and mark interrupted - the *next* one.
        Over the relay a finished answer is often still playing when the caller
        cuts in, and over WebRTC the provider's playback outlasts the response.
        """
        if self._response_turn is not None:
            self._played_ms = played_ms

    async def _barge_in(self, relay: AudioRelay, session: RealtimeSession) -> bool:
        """Over the relay, cut the answer being played off at what the caller heard.

        `True` when something was cut. The time heard trims the saved answer -
        unless the provider later marks the part with its own, exact, position.
        """
        played = await relay.barge_in(session)
        if played is None:
            return False
        self.note_played_ms(played)
        return True

    async def _relay_part_start(
        self, relay: AudioRelay, speaker: Literal["user", "assistant"], session: RealtimeSession
    ) -> None:
        """A speech part starting, as the relay needs to know it.

        The first assistant part of a response is where its audio begins. A
        caller's part starting while the browser still plays the agent is a
        barge-in too: Gemini reports no speech start, and once an answer has
        finished generating no interruption either - its transcript arriving is
        the first sign the caller talked over it (later than a speech start, so
        a little more of the answer is heard before it stops).
        """
        if speaker == "assistant":
            if self._response_turn is None:
                relay.answer_started()
        elif relay.unheard and await self._barge_in(relay, session):
            await self._state("interrupted")

    async def handle(self, event: object, session: RealtimeSession) -> None:
        """Act on one event from the session: a frame, a caption, a saved turn or a booking."""
        if isinstance(event, PartStartEvent) and isinstance(event.part, SpeechPart):
            if self._relay is not None:
                await self._relay_part_start(self._relay, event.part.speaker, session)
            self._turn(event.index, event.part.speaker)
            await self._state("user_speaking" if event.part.speaker == "user" else "agent_speaking")
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, SpeechPartDelta):
            if self._relay is not None and event.delta.audio_chunk:
                await self._relay.forward(event.index, event.delta.audio_chunk)
            await self._delta(event.index, event.delta, session)
        elif isinstance(event, PartEndEvent) and isinstance(event.part, SpeechPart):
            await self._part_end(event.index, event.part)
        elif isinstance(event, RealtimeInputSpeechStartEvent):
            if self._relay is not None:
                if await self._barge_in(self._relay, session):
                    await self._state("interrupted")
            else:
                played = self._clock.input_started()
                if played is not None:
                    if self._played_ms is None:
                        self.note_played_ms(played)
                    await self._state("interrupted")
            await self._state("user_speaking")
        elif isinstance(event, RealtimeInputSpeechEndEvent):
            await self._state("thinking")
        elif isinstance(event, RealtimeOutputSpeechStartEvent):
            self._clock.output_started()
            await self._state("agent_speaking")
        elif isinstance(event, RealtimeOutputSpeechEndEvent):
            self._clock.output_ended()
            if self._completes_to_notice <= 0:
                self.output_done.set()
            await self._state("listening")
        elif isinstance(event, RealtimeResponseInterruptedEvent):
            # Gemini's barge-in: it reports no speech start, only that it stopped.
            if self._relay is not None:
                await self._barge_in(self._relay, session)
            await self._state("interrupted")
        elif isinstance(
            event, FunctionToolCallEvent | FunctionToolResultEvent | DeferredToolRequestsEvent
        ):
            await self._tool_event(event)
        elif isinstance(event, RealtimeTurnCompleteEvent):
            self._completes_to_notice -= 1
            await self._finish_response(session)
        elif isinstance(event, RealtimeSessionErrorEvent):
            await self._send(NoticeFrame(type="notice", kind="provider_error"))

    async def worker_event(self, event: AgentStreamEvent) -> None:
        """One event from the call's text twin, working on a hand-off (`app/agents/hand_off.py`).

        Its steps are the call's steps: shown as they run, and saved on the turn
        that handed the work off - the hand-off's own response completes only once
        the twin has answered, so they land in the same message, after it.
        """
        if isinstance(
            event, FunctionToolCallEvent | FunctionToolResultEvent | DeferredToolRequestsEvent
        ):
            await self._tool_event(event)

    async def _tool_event(
        self, event: FunctionToolCallEvent | FunctionToolResultEvent | DeferredToolRequestsEvent
    ) -> None:
        if isinstance(event, FunctionToolCallEvent):
            part = event.part
            self._tools[part.tool_call_id] = SpokenToolCall(
                tool_call_id=part.tool_call_id,
                tool_name=part.tool_name,
                args=part.args_as_dict(),
                started_at=datetime.now(UTC),
            )
            await self._state("tool_running")
            await self._send(ToolFrame(type="tool", name=part.tool_name, status="running"))
        elif isinstance(event, FunctionToolResultEvent):
            tool = self._tools.get(event.part.tool_call_id)
            if tool is not None:
                # As a text run stores it (`transcript._result_text`): a retry is a
                # failed call, and its text is whatever raised, so the row holds the
                # shared notice rather than a vendor's error and URL.
                if isinstance(event.part, RetryPromptPart):
                    tool.result, tool.success = tool_retry_notice(event.part), False
                else:
                    tool.result = tool_result_text(event.part.content)
                tool.completed_at = datetime.now(UTC)
                await self._send(ToolFrame(type="tool", name=tool.tool_name, status="done"))
        else:
            await self._state("awaiting_approval")

    async def _delta(self, index: int, delta: SpeechPartDelta, session: RealtimeSession) -> None:
        piece = delta.transcript_delta
        # A delta carrying only audio has nothing to caption.
        if index in self._withheld or not piece:
            return
        # A delta that names no speaker is the agent's: only the agent's speech is
        # streamed without a part the caller started.
        role: Literal["user", "assistant"] = delta.speaker or "assistant"
        if role == "assistant" and self._started.guard.screens_agent:
            # With an output guardrail the agent's captions wait for each sentence to
            # pass it: a blocked term split across deltas ("Fal" + "con") must never
            # reach the screen in pieces, and a redacted one must reach it redacted.
            # Redaction changes the length, so each frame replaces the whole caption
            # with the screened text so far rather than appending a delta.
            text = self._live_text.get(index, "") + piece
            self._live_text[index] = text
            if not _SENTENCE_END.search(text):
                return
            screened = self._started.guard.screen(text, speaker="assistant")
            if screened.blocked:
                self._withheld.add(index)
                await session.interrupt()
                await self._send(NoticeFrame(type="notice", kind="guardrail"))
                return
            await self._send(self._caption(index, "assistant", text=screened.text))
            return
        await self._send(self._caption(index, role, delta=piece))

    async def _part_end(self, index: int, part: SpeechPart) -> None:
        self._live_text.pop(index, None)
        if index in self._withheld:
            # Already screened, counted and cut off in `_delta`: not a second hit.
            text = WITHHELD
        else:
            text = self._started.guard.screen(part.transcript or "", speaker=part.speaker).text
        await self._send(self._caption(index, part.speaker, final=text))
        if part.speaker == "user":
            self.heard = text
            self._started.questions.heard(text)
            saved = await self._started.writer.user_turn(text, turn_id=self._turn(index, "user"))
            if saved is not None:
                await self._send(_saved(saved))
        else:
            if part.interrupted_at_ms is not None:
                # The provider says where the answer stopped: exact, so it wins over
                # the heuristic's estimate from speech start (amendment 10).
                self._played_ms = part.interrupted_at_ms
            self._spoken.append(text)

    async def _finish_response(self, session: RealtimeSession) -> None:
        self._started.meter.book_response(session.usage)
        await self.flush()
        if not await self._started.prepared.built.budget.can_afford_next_request():
            self.budget_exhausted = True

    async def flush(self) -> None:
        """Save the agent's answer in progress, trimmed when it was talked over."""
        text = " ".join(part for part in self._spoken if part).strip()
        interrupted = self._played_ms is not None
        if interrupted:
            text = trim_to_played(text, self._played_ms or 0)
        tools = list(self._tools.values())
        if not text and not tools:
            # Nothing to save, but the answer is still over: a notice armed after
            # it must not count it as one still coming.
            self._spoken, self._played_ms, self._response_turn = [], None, None
            return
        turn_id = self._response_turn or self._started.writer.next_turn_id("assistant")
        self._spoken, self._tools, self._played_ms, self._response_turn = [], {}, None, None
        saved = await self._started.writer.assistant_turn(
            text, turn_id=turn_id, interrupted=interrupted, tools=tools
        )
        if saved is not None:
            await self._send(_saved(saved))


def _saved(message: MessageRead) -> TurnSavedFrame:
    return TurnSavedFrame(type="turn_saved", message=message.model_dump(mode="json"))
