"""Turning a delegate's own stream into frames a surface can show.

A delegated run is a second agent's whole conversation happening inside one turn
of the first, and Pydantic AI reports it in the same events it reports any run
with. Those events are not what a surface can render *next to* the parent's:
nothing in them says which delegation they came from, and three specialists
streaming at once interleave into one paragraph.

So this is the translation, and it is deliberately the only thing in this module.
Every frame is stamped with the same :class:`FrameLabels` - the library's task id,
the delegate's name, how deep the delegation is - resolved once when the
delegation starts, in `_journal.py`. Reading a label off an event would mean
guessing; carrying it means a fan-out of three renders as three panels.

What is *not* translated is as deliberate: a delegate's `FinalResultEvent`, its
part-end events and its enqueued messages say nothing a reader of the panel
needs, and every frame pushed is a WebSocket write.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelResponsePart,
    ModelResponsePartDelta,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from app.agents.subagent_events import (
    SubagentEvent,
    SubagentTextDelta,
    SubagentThinkingDelta,
    SubagentToolCall,
    SubagentToolResult,
)

UNNAMED_TOOL = "unknown"
"""What a tool result is attributed to when the part does not name one.

`RetryPromptPart.tool_name` is optional, so a result frame either invents a name
or is dropped - and dropping it leaves a row open in the panel forever, which
reads as a delegate still working on something that already failed.
"""


@dataclass(frozen=True)
class FrameLabels:
    """Which delegation a frame belongs to, resolved once when it starts.

    Frozen and passed rather than re-derived per event: the three values are
    fixed for the life of a delegation, and a label computed per event is a
    label that can disagree with itself halfway through a fan-out.
    """

    task_id: str
    subagent: str
    depth: int


def frame_for(event: AgentStreamEvent, labels: FrameLabels) -> SubagentEvent | None:
    """The frame this delegation event becomes, or `None` if it becomes nothing.

    `None` is the common case rather than an error: a run emits far more events
    than a delegation panel can use, and forwarding the rest would cost a socket
    write each to show a reader nothing.
    """
    if isinstance(event, PartStartEvent):
        return _from_part(event.part, labels)
    if isinstance(event, PartDeltaEvent):
        return _from_delta(event.delta, labels)
    if isinstance(event, FunctionToolCallEvent):
        return SubagentToolCall(
            task_id=labels.task_id,
            subagent=labels.subagent,
            depth=labels.depth,
            tool_name=event.part.tool_name,
            tool_call_id=event.part.tool_call_id,
        )
    if isinstance(event, FunctionToolResultEvent):
        return SubagentToolResult(
            task_id=labels.task_id,
            subagent=labels.subagent,
            depth=labels.depth,
            tool_name=event.part.tool_name or UNNAMED_TOOL,
            tool_call_id=event.tool_call_id,
            # A `RetryPromptPart` is how a tool that raised comes back, so this
            # is the one thing that tells a panel a step went wrong.
            ok=not isinstance(event.part, RetryPromptPart),
        )
    return None


def _from_part(part: ModelResponsePart, labels: FrameLabels) -> SubagentEvent | None:
    """The first fragment of a part, which arrives with the part rather than after it.

    Skipping this loses the opening of every answer a provider sends in one
    chunk - the panel then shows the delegate's second sentence onwards.
    """
    if isinstance(part, TextPart) and part.content:
        return SubagentTextDelta(
            task_id=labels.task_id,
            subagent=labels.subagent,
            depth=labels.depth,
            delta=part.content,
        )
    if isinstance(part, ThinkingPart) and part.content:
        return SubagentThinkingDelta(
            task_id=labels.task_id,
            subagent=labels.subagent,
            depth=labels.depth,
            delta=part.content,
        )
    return None


def _from_delta(delta: ModelResponsePartDelta, labels: FrameLabels) -> SubagentEvent | None:
    """A continuation fragment of the delegate's answer or its reasoning."""
    if isinstance(delta, TextPartDelta):
        return SubagentTextDelta(
            task_id=labels.task_id,
            subagent=labels.subagent,
            depth=labels.depth,
            delta=delta.content_delta,
        )
    if isinstance(delta, ThinkingPartDelta) and delta.content_delta:
        return SubagentThinkingDelta(
            task_id=labels.task_id,
            subagent=labels.subagent,
            depth=labels.depth,
            delta=delta.content_delta,
        )
    return None
