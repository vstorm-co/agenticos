"""What a surface hears while a delegation is running.

A delegated run is a second agent's whole conversation happening inside one turn
of the first. Left alone it is invisible: the parent's transcript records a tool
call named `task` and, some seconds later, a paragraph of text that a specialist
wrote. Nobody can see which specialist is working, what it is calling, or why a
turn has gone quiet.

So the delegation streams, and these are the frames it streams. Three properties
are what make them readable rather than noise, and all three are structural:

*Every frame names its task.* A fan-out is three specialists writing at once, and
text deltas from three children interleaved into one paragraph are worse than no
streaming at all. `task_id` is what lets a surface keep three panels instead.

*Every frame carries its depth.* A specialist that delegates further is legal up
to `max_depth`, and a reader needs to know whether the researcher is talking or
the researcher's own assistant is.

*They are a separate channel, never the parent's.* A child's text is not the
parent's answer. Inlining it would put words in the parent's mouth that its own
model never generated, and the conversation would be persisted with them.

The sink itself is `AgentDeps.subagent_events`, set by surfaces that can show a
delegation in progress and `None` everywhere else - the same shape, and the same
reasoning, as `ask_user` and `request_approval`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _SubagentFrame(BaseModel):
    """What every delegation frame carries, whatever it reports."""

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(description="The library's task id, unique per delegation")
    subagent: str = Field(description="The delegate or specialist name the author gave it")
    depth: int = Field(
        ge=0,
        description=(
            "How far inside the parent this delegation is. 0 is a specialist the "
            "run's own agent called; 1 is one that specialist called."
        ),
    )


class SubagentStarted(_SubagentFrame):
    """A delegation began.

    Carries `mode` because a background delegation's frames arrive *after* the
    parent's answer, and a surface that tears its panels down on the terminal
    frame would drop the last thing a specialist said. Knowing which kind it is
    at the start is what lets a surface keep the panel open.
    """

    kind: Literal["subagent_start"] = "subagent_start"
    mode: Literal["sync", "async"]
    prompt: str = Field(description="What the parent asked this delegate to do")


class SubagentTextDelta(_SubagentFrame):
    """A fragment of the delegate's answer, as it is generated."""

    kind: Literal["subagent_text_delta"] = "subagent_text_delta"
    delta: str


class SubagentThinkingDelta(_SubagentFrame):
    """A fragment of the delegate's reasoning, where the model exposes it."""

    kind: Literal["subagent_thinking_delta"] = "subagent_thinking_delta"
    delta: str


class SubagentToolCall(_SubagentFrame):
    """The delegate called one of its own tools.

    The delegate's tools, not the parent's - a delegate runs on its own spec and
    its own bindings, so this is the only place a reader learns that the
    researcher searched a collection the parent cannot even see.
    """

    kind: Literal["subagent_tool_call"] = "subagent_tool_call"
    tool_name: str
    tool_call_id: str


class SubagentToolResult(_SubagentFrame):
    """One of the delegate's tool calls answered."""

    kind: Literal["subagent_tool_result"] = "subagent_tool_result"
    tool_name: str
    tool_call_id: str
    ok: bool = Field(description="False when the tool raised, so a surface can mark it")


class SubagentFinished(_SubagentFrame):
    """A delegation ended, however it ended.

    `cost_usd` is what this delegation added to the parent run's ledger, which is
    the number that makes delegation's cost legible: a fan-out of five is six
    model conversations against one budget, and a reader who cannot see the split
    has no way to tell an expensive specialist from a cheap one.

    `run_id` is present for a delegation to a *published* agent, which gets an
    `AgentRun` row of its own, and absent for an inline specialist, which has no
    agent to attribute one to.
    """

    kind: Literal["subagent_complete"] = "subagent_complete"
    status: Literal["completed", "failed", "cancelled"]
    run_id: UUID | None = None
    cost_usd: Decimal | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = Field(
        default=None,
        description="Why it failed, for a surface to show instead of an empty panel",
    )


SubagentEvent = Annotated[
    SubagentStarted
    | SubagentTextDelta
    | SubagentThinkingDelta
    | SubagentToolCall
    | SubagentToolResult
    | SubagentFinished,
    Field(discriminator="kind"),
]
"""One frame from inside a delegation.

Tagged on `kind` rather than modelled as one class with optional fields, because
a surface has to switch on it: a text delta appends, a tool call opens a row, a
terminal frame closes the panel and writes the cost. A single shape with six
nullable payloads makes every one of those branches read the same field and check
whether it happens to be set.
"""

SubagentEventSink = Callable[[SubagentEvent], Awaitable[None]]
"""Where a delegation's frames go, on a surface that can show them.

Awaitable because the only implementation that matters writes to a WebSocket.
"""
