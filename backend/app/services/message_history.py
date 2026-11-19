"""Rebuilding a stored conversation into what a model reads.

Its own module rather than a section of `agent.py`, because a conversation is
replayed by everything that answers one - the chat socket, a channel, the widget
and the service that builds a thread's history - and `agent.py` reaches for
`app.api.deps`, which reaches back for `ConversationService`.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import NotRequired, TypedDict
from uuid import UUID

from pydantic import JsonValue
from pydantic_ai.messages import (
    InstructionBaselinePart,
    InstructionDeltaPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from app.agents.ephemeral_media import dump_messages
from app.schemas.conversation import HistoryCheckpointFrontier, HistoryProvenance, HistorySource

MODEL_HISTORY_MESSAGES = 200
MODEL_HISTORY_BYTES = 2 * 1024 * 1024
CHANNEL_AUTHORS = "agenticos_channel_authors"
_LEGACY_SUMMARY_PREFIX = "Summary of previous conversation:\n\n"
HISTORY_TRIMMED = (
    "Earlier conversation messages and tool results were omitted to keep history within its limits. "
    "Rediscover tools whose discovery is no longer present, and read missing evidence again when needed."
)


def without_standing_instructions(
    messages: Sequence[ModelMessage], *, channel_authors: Mapping[str, UUID] | None = None
) -> list[ModelMessage]:
    """Keep turn evidence before offloading media or after restoring stored references.

    The next run supplies its current instructions and capabilities. Drop rendered
    request instructions and SDK instruction baselines/deltas as well as system
    prompts, so repeated instructions cannot evict evidence at the storage ceiling.
    Legacy harness summaries used a system part; retain those until a new
    compaction replaces them.
    """
    history: list[ModelMessage] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            parts = [
                part
                for part in message.parts
                if not isinstance(part, (InstructionBaselinePart, InstructionDeltaPart))
                if not isinstance(part, SystemPromptPart)
                or part.content.startswith(_LEGACY_SUMMARY_PREFIX)
            ]
            if parts:
                metadata = dict(message.metadata or {})
                if channel_authors:
                    references = {
                        part.timestamp.isoformat(): str(identity)
                        for part in parts
                        if isinstance(part, UserPromptPart)
                        and (identity := channel_authors.get(part.timestamp.isoformat()))
                        is not None
                    }
                    if references:
                        metadata[CHANNEL_AUTHORS] = references
                history.append(
                    replace(message, parts=parts, instructions=None, metadata=metadata or None)
                )
        else:
            history.append(message)
    return history


def _stored_standing_instruction(part: JsonValue) -> bool:
    if not isinstance(part, dict):
        return False
    if part.get("part_kind") in ("instruction-baseline", "instruction-delta"):
        return True
    content = part.get("content")
    return (
        part.get("part_kind") == "system-prompt"
        and isinstance(content, str)
        and not content.startswith(_LEGACY_SUMMARY_PREFIX)
    )


def without_stored_standing_instructions(
    messages: Sequence[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Clean legacy checkpoints before their byte ceiling, without expanding media references."""
    history: list[dict[str, JsonValue]] = []
    for message in messages:
        parts = message.get("parts")
        if message.get("kind") != "request" or not isinstance(parts, list):
            history.append(message)
            continue
        kept = [part for part in parts if not _stored_standing_instruction(part)]
        if kept:
            history.append({**message, "parts": kept, "instructions": None})
    return history


def bounded_model_history(messages: Sequence[ModelMessage]) -> list[ModelMessage]:
    """Keep a bounded suffix without separating calls from their results.

    This is a storage ceiling, independent of the agent's token-based compaction.
    Evicted discovery expires with its evidence. Never invent a successful search
    to restore it. A single oversized exchange is omitted as a whole and the
    model is told that evidence was lost. The visible transcript stays intact.
    """
    serialized = dump_messages(messages)
    start = _bounded_history_start(serialized)
    if start == 0:
        return list(messages)
    notice = ModelRequest(parts=[UserPromptPart(content=HISTORY_TRIMMED)])
    return [notice, *messages[start:]]


def bounded_stored_history(
    messages: list[dict[str, JsonValue]], *, overhead_bytes: int = 0
) -> list[dict[str, JsonValue]]:
    """Bound the compact checkpoint before restoring potentially large media.

    Media references count at their stored size. Expanding one before applying
    this storage ceiling would discard valid images and offloaded tool results.
    """
    start = _bounded_history_start(messages, overhead_bytes=overhead_bytes)
    if start == 0:
        return messages
    notice = ModelRequest(parts=[UserPromptPart(content=HISTORY_TRIMMED)])
    return [*dump_messages([notice]), *messages[start:]]


def _bounded_history_start(
    messages: Sequence[dict[str, JsonValue]], *, overhead_bytes: int = 0
) -> int:
    sizes = [len(json.dumps(message, ensure_ascii=False).encode()) + 2 for message in messages]
    total = sum(sizes) + overhead_bytes
    if len(messages) <= MODEL_HISTORY_MESSAGES and total <= MODEL_HISTORY_BYTES:
        return 0
    notice = ModelRequest(parts=[UserPromptPart(content=HISTORY_TRIMMED)])
    budget = MODEL_HISTORY_BYTES - len(
        json.dumps(dump_messages([notice]), ensure_ascii=False).encode()
    )
    start = 0
    while start < len(messages) and (
        len(messages) - start >= MODEL_HISTORY_MESSAGES or total > budget
    ):
        total -= sizes[start]
        start += 1

    # Parallel calls may span several messages. Move the cut past every result
    # whose call would be lost, including a batch containing retained calls too.
    calls: dict[str, int] = {}
    for index, message in enumerate(messages):
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            call_id = part.get("tool_call_id")
            if not isinstance(call_id, str):
                continue
            kind = part.get("part_kind")
            if kind == "tool-call":
                calls[call_id] = index
            elif kind == "tool-return" and index >= start and calls.get(call_id, -1) < start:
                start = index + 1
    return start


CHANNEL_AUTHOR_ID = "agenticos_channel_author_identity"

REFUSED_TURN = "(A guardrail stopped the turn this message began; what it said is not repeated.)"
"""What a later turn's history holds in place of the prompt of a `guardrail_blocked` run (#2578).

The input edge screens only the newest prompt, so a refused turn read back as
history - its words and what its files added - reached the model one harmless
follow-up later. A note rather than nothing: the turns still alternate, and the
model can say a turn was stopped instead of acting as if nothing was sent. The
person's own transcript still shows what they typed.

Whichever edge stopped the run: its status does not record the edge, and a prompt
the input edge passed loses only its place in later history - the person can ask
again - where a refused one kept would undo the refusal."""


class ModelHistory(list[ModelMessage]):
    """A transcript snapshot with the refusal revision its summary may replace."""

    def __init__(
        self,
        messages: Sequence[ModelMessage],
        *,
        revision: int | None,
        frontier: HistoryCheckpointFrontier | None = None,
        provenance: HistoryProvenance | None = None,
        source: HistorySource | None = None,
        public_context: Sequence[ModelMessage] = (),
    ) -> None:
        super().__init__(messages)
        self.revision = revision
        self.frontier = frontier
        self.provenance = provenance
        self.source = source
        self.public_context = list(public_context)

    def extend_public_context(self, messages: Sequence[ModelMessage]) -> None:
        """Retain authorized channel context if private checkpoint replay is refused."""
        self.extend(messages)
        self.public_context.extend(messages)


class HistoryMessage(TypedDict):
    """One stored turn, as the replayer wants it.

    `context_used_tokens` is `NotRequired` because a surface may not have it - a
    turn from before the column existed, or a run that reached no model - and
    because a caller that only has text is still a legitimate caller.
    """

    role: str
    content: str
    context_used_tokens: NotRequired[int | None]
    channel_identity_id: NotRequired[UUID | None]


def build_message_history(history: list[HistoryMessage]) -> list[ModelRequest | ModelResponse]:
    """Convert conversation history to Pydantic AI message format.

    **An answer is replayed with the size of the request it came out of**, and the
    reason is not accounting. The compaction estimator anchors on the most recent
    response carrying provider usage: that response's `input_tokens` measured the
    whole request - the instructions, every tool schema, every prior message - so
    anchored, the estimate is the provider's own number rather than a count of
    characters. Replayed as bare text it has nothing to anchor on and falls back
    to ~4 characters per token, which on a real agent here saw 9 tokens where the
    provider had charged for 3,859. A trigger measuring that never fires, and the
    context gauge beside it - which reads the provider's number - sat at 77% while
    nothing happened.

    Absent where it was never recorded: a turn from before the columns existed, or
    one whose cost could not be read. The estimate is then what it always was.
    """
    model_history: list[ModelRequest | ModelResponse] = []

    last_user_timestamp = None
    for msg in history:
        content = msg["content"]
        # An empty text part is not history, it is a 400: Anthropic rejects one,
        # and a row with no text carries nothing to the model regardless. A
        # caption-less file is recorded as an empty user turn so the file has a
        # row to hang off (transcript.py), but the file's bytes are not in the
        # history this reconstructs - so the empty row is pure liability here.
        if not content.strip():
            continue
        if msg["role"] == "user":
            part = UserPromptPart(content=content)
            # Normalization may merge requests. Unique user-part timestamps keep
            # server-authored identity references stable across merges/resumes.
            if last_user_timestamp is not None and part.timestamp <= last_user_timestamp:
                part.timestamp = last_user_timestamp + timedelta(microseconds=1)
            last_user_timestamp = part.timestamp
            model_history.append(
                ModelRequest(
                    parts=[part],
                    metadata={CHANNEL_AUTHOR_ID: str(identity_id)}
                    if (identity_id := msg.get("channel_identity_id")) is not None
                    else None,
                )
            )
        elif msg["role"] == "assistant":
            model_history.append(
                ModelResponse(parts=[TextPart(content=content)], usage=_recorded_usage(msg))
            )
        elif msg["role"] == "system":
            model_history.append(ModelRequest(parts=[SystemPromptPart(content=content)]))

    return model_history


def _recorded_usage(msg: HistoryMessage) -> RequestUsage:
    """What the provider was sent for the request this answer came out of.

    `context_used_tokens`, and deliberately not the `input_tokens` beside it in
    the same row. That column is a run's *whole* bill - every request of a
    hundred-step tool loop summed - and the anchor is a statement about **one**
    request. Anchored on a sum, a long turn would read as several times its own
    size and compact a history that fits comfortably, on every request, for ever.

    No output. The anchor's arithmetic is `input + output`, and what the last
    response itself cost is not recorded per request; zero undercounts by the
    length of one answer, which is a few hundred tokens and errs late. The next
    real response re-anchors it exactly.

    A zeroed usage where nothing was recorded, which is what `RequestUsage()`
    already is - the estimator only anchors on a response whose `input_tokens` is
    non-zero, so an unmeasured turn is passed over rather than treated as a
    request that cost nothing.
    """
    return RequestUsage(input_tokens=int(msg.get("context_used_tokens") or 0))
