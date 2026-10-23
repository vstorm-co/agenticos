"""A call's turns, saved as ordinary messages as each one finishes (#54).

Each turn is written the moment it ends, from a session of its own, so a crash
loses at most the turn in progress and the conversation can be continued by
typing afterwards. `turn_id` is `<call id>:<n>:<role>`, unique per
conversation, so a retried write cannot double a turn.

**Interrupted answers are trimmed by a heuristic over WebRTC** (spec amendment
10): the browser plays the audio, and no `RealtimeResponseInterruptedEvent`
reaches the sideband. An answer counts as interrupted when the caller starts
speaking while it is being spoken; the time heard is input start minus output
start; and the text is cut at a typical speaking rate. Captions may run ahead
of the audio - that is accepted. Over the relay the played bytes are exact and
the same `trim_to_played` is given the exact time.
"""

import time
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models.conversation import Message, ToolCall
from app.repositories import conversation_repo
from app.schemas.conversation import MessageRead

CHARS_PER_SECOND = 15
"""About 150 words a minute: how fast a realtime voice speaks, for the trim."""

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def trim_to_played(text: str, played_ms: int) -> str:
    """The part of an answer the caller heard, roughly, ending on a whole word."""
    keep = int(played_ms / 1000 * CHARS_PER_SECOND)
    if keep >= len(text):
        return text
    cut = text[:keep]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > 0 else "").rstrip(" ,;:")


class SpeechClock:
    """When the agent started and stopped speaking, to tell an interruption from a reply."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._output_started: float | None = None

    @property
    def agent_speaking(self) -> bool:
        """Whether an answer is being spoken right now."""
        return self._output_started is not None

    def output_started(self) -> None:
        self._output_started = self._now()

    def output_ended(self) -> None:
        self._output_started = None

    def input_started(self) -> int | None:
        """The milliseconds of answer heard when the caller cut in, or `None` if nobody was speaking."""
        if self._output_started is None:
            return None
        played = int((self._now() - self._output_started) * 1000)
        self._output_started = None
        return played


@dataclass
class SpokenToolCall:
    """A tool the agent ran during a spoken answer, for the inline card in the transcript."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    started_at: datetime
    result: str | None = None
    success: bool = True
    completed_at: datetime | None = None


class TurnWriter:
    """Writes one call's turns into its conversation, each from a session of its own."""

    def __init__(
        self,
        *,
        sessions: SessionFactory,
        call_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        agent_id: UUID,
        agent_version_id: UUID | None,
    ) -> None:
        self._sessions = sessions
        self._call_id = call_id
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._agent_id = agent_id
        self._agent_version_id = agent_version_id
        self._count = 0

    def next_turn_id(self, role: Literal["user", "assistant"]) -> str:
        """The id the next turn of `role` is saved under: `<call id>:<n>:<role>`.

        Allocated when a turn *starts*, so its captions carry the id its saved
        message will have and the call view can swap one for the other.
        """
        self._count += 1
        return f"{self._call_id}:{self._count}:{role}"

    async def user_turn(self, text: str, *, turn_id: str) -> MessageRead | None:
        """Write what the caller said, as transcribed. Nothing for silence."""
        if not text.strip():
            return None
        # Shielded, here and below: the pump is cancelled when a call ends, and a
        # write cut off mid-way loses the turn and hands a closed connection back
        # to the pool, where the call's own end then fails on it.
        with anyio.CancelScope(shield=True):
            async with self._sessions() as db:
                message = await conversation_repo.create_voice_turn(
                    db,
                    conversation_id=self._conversation_id,
                    role="user",
                    content=text.strip(),
                    turn_id=turn_id,
                    interrupted=False,
                    run_id=self._run_id,
                    agent_id=None,
                    agent_version_id=None,
                    parts=None,
                )
                return None if message is None else _read(message, tool_calls=[])

    async def assistant_turn(
        self, text: str, *, turn_id: str, interrupted: bool, tools: Sequence[SpokenToolCall]
    ) -> MessageRead | None:
        """Write what the agent said - trimmed when interrupted - and the tools it ran."""
        if not text.strip() and not tools:
            return None
        parts: list[dict[str, object]] = []
        if text.strip():
            parts.append({"type": "text", "text": text.strip()})
        parts.extend({"type": "tool", "tool_call_id": tool.tool_call_id} for tool in tools)
        with anyio.CancelScope(shield=True):
            async with self._sessions() as db:
                message = await conversation_repo.create_voice_turn(
                    db,
                    conversation_id=self._conversation_id,
                    role="assistant",
                    content=text.strip(),
                    turn_id=turn_id,
                    interrupted=interrupted,
                    run_id=self._run_id,
                    agent_id=self._agent_id,
                    agent_version_id=self._agent_version_id,
                    parts=parts,
                )
                if message is None:
                    return None
                rows: list[ToolCall] = []
                for tool in tools:
                    row = await conversation_repo.create_tool_call(
                        db,
                        message_id=message.id,
                        tool_call_id=tool.tool_call_id,
                        tool_name=tool.tool_name,
                        args=tool.args,
                        started_at=tool.started_at,
                    )
                    if tool.result is not None:
                        row = await conversation_repo.complete_tool_call(
                            db,
                            db_tool_call=row,
                            result=tool.result,
                            completed_at=tool.completed_at or datetime.now(UTC),
                            success=tool.success,
                        )
                    rows.append(row)
                return _read(message, tool_calls=rows)


def _read(message: Message, *, tool_calls: list[ToolCall]) -> MessageRead:
    """The saved turn as the call view replaces its caption with, built while its session is open.

    The relationships are set from what this writer wrote rather than loaded:
    the row is new, so its tool calls are exactly these and it has no files, and
    a lazy load on an async session - or on one already closed - raises instead.
    """
    set_committed_value(message, "tool_calls", tool_calls)
    set_committed_value(message, "files", [])
    return MessageRead.model_validate(message)
