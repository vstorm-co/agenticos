"""Running an agent without letting it act on the world - what an eval run needs.

An eval runs the agent for real, so its tools would run for real: an agent that
sends e-mail or writes to a CRM would do it again for every case. An *isolated*
run keeps the agent whole and stops the effects at one place - tool execution -
by the same means the approval gate holds a call: a capability wrapping every
tool call, so a tool cannot forget to ask.

What it decides, per call:

* **A tool with a test connection runs.** An environment can answer a binding
  with a test system (a sandbox CRM, a test mailbox); the call goes there.
* **A read-only tool runs** on the normal connection. MCP tools say so with the
  server's `readOnlyHint`; capability tools declare `read_only` in the registry.
* **Anything else is blocked and recorded** as an intended call - the tool and
  its arguments - which is what trajectory scoring judges. A tool that declares
  nothing writes.

A run can also be answered from a **recording** of the run a case was taken
from. A call is then matched by its stable tool id, its normalized arguments and
its occurrence among calls with that same id and arguments, and answered with
what the original call returned. A call with no match is not executed and is
recorded as divergent: serving it some other call's result would fabricate the
very difference a comparison exists to measure. A read-only tool may run live
instead where the run allows it; a writing one never does.

An isolated run has no approval channel, so a gated call is refused rather than
parked: a parked run is resumed by rebuilding it, and nothing here is part of
what a resume rebuilds.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.tools import ToolDefinition

from app.agents.capabilities import LOAD_CAPABILITY
from app.agents.capabilities import get as get_capability
from app.agents.deps import AgentDeps
from app.agents.mcp import MCP_ORIGIN
from app.agents.spec import AgentSpec
from app.db.models.intercepted_tool_call import InterceptionOutcome

logger = logging.getLogger(__name__)

#: Tools the framework adds that only read: opening a skill, and searching the
#: deferred tools. Consulted after the spec's own tools, so a binding that
#: renamed a writing tool onto one of these names is still classified by what
#: it declared.
_FRAMEWORK_READS = frozenset({LOAD_CAPABILITY, "search_tools"})


@dataclass(frozen=True)
class ToolClass:
    """What an isolated run needs to know about one tool.

    Attributes:
        tool_id: The stable identity a recording is matched on -
            `capability:<capability>.<tool>` for a registry tool, which survives
            a binding renaming it, and `tool:<name>` for everything else.
        read_only: Whether calling it changes nothing outside the run.
        test: Whether it reaches a test system the run's environment named.
    """

    tool_id: str
    read_only: bool
    test: bool = False


def capability_tools(
    spec: AgentSpec, *, test_secret_ids: frozenset[UUID] = frozenset()
) -> dict[str, ToolClass]:
    """Every registry tool a spec offers, keyed by the name the model calls.

    A binding whose secret is one of `test_secret_ids` authenticates against a
    test system, so its tools count as reaching one.
    """
    tools: dict[str, ToolClass] = {}
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = get_capability(binding.id)
        test = binding.secret_id is not None and binding.secret_id in test_secret_ids
        for tool in definition.effective_tools(binding.tool_overrides):
            tools[tool.name] = ToolClass(
                tool_id=f"capability:{binding.id}.{tool.id}",
                read_only=definition.tool_is_read_only(tool),
                test=test,
            )
    return tools


def classify(tool_def: ToolDefinition, tools: Mapping[str, ToolClass]) -> ToolClass:
    """What one tool is, whoever contributed it.

    An MCP tool is recognised by the origin this deployment stamped on it, never
    by its name, and is read-only only when its server says `readOnlyHint`. A
    registry tool is looked up by the name the model called. Anything else -
    including a tool nothing declared - writes.
    """
    metadata = tool_def.metadata or {}
    origin = metadata.get(MCP_ORIGIN)
    if isinstance(origin, dict):
        annotations = metadata.get("annotations") or {}
        return ToolClass(
            tool_id=f"tool:{tool_def.name}",
            read_only=annotations.get("readOnlyHint") is True,
            test=origin.get("test") is True,
        )
    known = tools.get(tool_def.name)
    if known is not None:
        return known
    return ToolClass(tool_id=f"tool:{tool_def.name}", read_only=tool_def.name in _FRAMEWORK_READS)


def normalized_args(args: Mapping[str, Any]) -> str:
    """Arguments as one comparable string: key order and spacing do not count."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


@dataclass(frozen=True)
class RecordedCall:
    """One call the original run made, and what it returned."""

    tool_id: str
    args: str
    result: Any


@dataclass
class ToolRecording:
    """The original run's calls, each answerable once.

    Matched per stable id and normalized arguments, in the order the original
    run made them: the second identical call is answered with the second
    recorded result, and a third with nothing.
    """

    calls: Sequence[RecordedCall]
    _queues: dict[tuple[str, str], deque[RecordedCall]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._queues = {}
        for call in self.calls:
            self._queues.setdefault((call.tool_id, call.args), deque()).append(call)

    def answer(self, tool_id: str, args: Mapping[str, Any]) -> RecordedCall | None:
        """The next unanswered recording of this exact call, or `None`."""
        queue = self._queues.get((tool_id, normalized_args(args)))
        return queue.popleft() if queue else None


def recorded_calls(
    messages: list[dict[str, Any]],
    *,
    since: datetime | None,
    tools: Mapping[str, ToolClass],
) -> list[RecordedCall]:
    """The calls a run made, from the messages its manifest recorded.

    The manifest holds the whole history the last request carried, earlier turns
    included, so only responses from `since` onwards are this run's. A call that
    never returned - parked, or failed and retried - has nothing to answer with
    and is left out. Names resolve to stable ids through `tools`, which is the
    *original* version's table: a candidate that renamed a tool still matches.
    """
    parsed = ModelMessagesTypeAdapter.validate_python(messages)
    returned = {
        part.tool_call_id: part.content
        for message in parsed
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    calls: list[RecordedCall] = []
    for message in parsed:
        if not isinstance(message, ModelResponse) or (
            since is not None and message.timestamp < since
        ):
            continue
        for part in message.parts:
            if not isinstance(part, ToolCallPart) or part.tool_call_id not in returned:
                continue
            known = tools.get(part.tool_name)
            calls.append(
                RecordedCall(
                    tool_id=known.tool_id if known is not None else f"tool:{part.tool_name}",
                    args=normalized_args(part.args_as_dict()),
                    result=returned[part.tool_call_id],
                )
            )
    return calls


@dataclass(frozen=True)
class InterceptedCall:
    """One call an isolated run answered without executing it."""

    agent_id: UUID | None
    tool_name: str
    tool_id: str
    args: dict[str, Any]
    outcome: InterceptionOutcome


@dataclass
class RunIsolation:
    """How one run treats its tools: isolated, and optionally answered from a recording.

    Handed to the runner by whoever starts an eval run, and shared by every agent
    of the run's delegation tree, so a delegate's write is held as its parent's
    is. `intercepted` is filled as the run goes and written when it finishes.

    Attributes:
        recording: Answer calls from this recording instead of executing them.
        live_reads: With a recording, let a read-only call the recording does not
            hold run live rather than be recorded as divergent.
        intercepted: What the run did not execute, in the order it was asked.
    """

    recording: ToolRecording | None = None
    live_reads: bool = False
    intercepted: list[InterceptedCall] = field(default_factory=list)


def _blocked_notice(name: str) -> str:
    return (
        f"Not executed: this is an evaluation run, and `{name}` would change something "
        "outside it. The call and its arguments were recorded; nothing was sent."
    )


def _divergent_notice(name: str) -> str:
    return (
        "Not executed: this evaluation answers tools from a recorded conversation, and "
        f"it holds no matching call to `{name}` with these arguments."
    )


@dataclass
class IsolationGuard(AbstractCapability[AgentDeps]):
    """Executes only what an isolated run may, and records the rest.

    Attached before the approval gate, so a blocked call is recorded as intended
    rather than refused for want of somebody to approve it.
    """

    isolation: RunIsolation
    tools: Mapping[str, ToolClass] = field(default_factory=dict)
    agent_id: UUID | None = None

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        """Run, replay or hold one call, by what the tool is and what the run allows."""
        tool = classify(tool_def, self.tools)
        recording = self.isolation.recording
        if recording is not None:
            recorded = recording.answer(tool.tool_id, args)
            if recorded is not None:
                self._intercept(tool_def.name, tool, args, InterceptionOutcome.REPLAYED)
                return recorded.result
            if tool.read_only and self.isolation.live_reads:
                return await handler(args)
            self._intercept(tool_def.name, tool, args, InterceptionOutcome.DIVERGENT)
            return _divergent_notice(tool_def.name)
        if tool.read_only or tool.test:
            return await handler(args)
        self._intercept(tool_def.name, tool, args, InterceptionOutcome.BLOCKED)
        return _blocked_notice(tool_def.name)

    def _intercept(
        self, name: str, tool: ToolClass, args: dict[str, Any], outcome: InterceptionOutcome
    ) -> None:
        logger.info("isolated_tool_call", extra={"tool_id": tool.tool_id, "outcome": outcome.value})
        self.isolation.intercepted.append(
            InterceptedCall(
                agent_id=self.agent_id,
                tool_name=name,
                tool_id=tool.tool_id,
                args=dict(args),
                outcome=outcome,
            )
        )
