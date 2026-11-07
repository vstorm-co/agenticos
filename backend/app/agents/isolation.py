"""Running an agent without letting it act on the world - what an eval run needs.

An eval runs the agent for real, so its tools would run for real: an agent that
sends e-mail or writes to a CRM would do it again for every case. An *isolated*
run keeps the agent whole and stops the effects at one place - tool execution -
by the same means the approval gate holds a call: a capability wrapping every
tool call, so a tool cannot forget to ask.

What it decides, per call:

* **A tool with a test connection runs.** An environment can answer a binding
  with a test system (a sandbox CRM, a test mailbox); the call goes there.
* **A read-only tool runs** on the normal connection. Capability tools declare
  `read_only` in the registry. An MCP tool's `readOnlyHint` is its server's own
  claim, so it counts only on a connection set to trust it.
* **Anything else is blocked and recorded** as an intended call - the tool and
  its arguments - which is what trajectory scoring judges. A tool that declares
  nothing writes.

A run can also be answered from a **recording** of the run a case was taken
from - its `tool_calls` rows, in the order they were made. A call is then
matched by its stable tool id, its normalized arguments and its occurrence among
calls with that same id and arguments, and answered with what the original call
returned. A call with no match is not executed and is
recorded as divergent: serving it some other call's result would fabricate the
very difference a comparison exists to measure. A read-only tool may run live
instead where the run allows it; a writing one never does.

An isolated run has no approval channel, so a gated call is never parked: a
parked run is resumed by rebuilding it, and nothing here is part of what a
resume rebuilds. A call the agent gates is held and recorded as one that needed
an approval, even when the tool only reads - so it is in the trajectory too.
"""

import json
import logging
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_core import to_jsonable_python

from app.agents.approval import refusal
from app.agents.capabilities import LOAD_CAPABILITY
from app.agents.capabilities import get as get_capability
from app.agents.capabilities.approval import ApprovalGate
from app.agents.capabilities.knowledge import FoundPassage
from app.agents.deps import AgentDeps
from app.agents.mcp import MCP_ORIGIN
from app.agents.spec import AgentSpec
from app.db.models.intercepted_tool_call import InterceptionOutcome, InterceptionReason
from app.services.rag.overlay import KnowledgeOverlay

logger = logging.getLogger(__name__)

#: The most of a held call's arguments kept, serialized. A model can be told to
#: paste a document into a call, and one row must not hold it whole.
MAX_RECORDED_ARGS_CHARS = 32_000

#: Framework tools that only read. Consulted after the spec's own, so a tool
#: renamed onto one of these names keeps its own declaration.
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
    spec: AgentSpec, *, test_bindings: frozenset[str] = frozenset()
) -> dict[str, ToolClass]:
    """Every registry tool a spec offers, keyed by the name the model calls.

    `test_bindings` names the bindings whose vault key the environment swapped
    for a test one. Their tools count as reaching a test system only where the
    capability declares `test_key_isolates`: a key can stand in for a credential
    while a URL in the config still points the writes at production.
    """
    tools: dict[str, ToolClass] = {}
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = get_capability(binding.id)
        test = binding.id in test_bindings and definition.test_key_isolates
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
    by its name, and is read-only only when its server says `readOnlyHint` and its
    connection trusts the server to say so. A
    registry tool is looked up by the name the model called. Anything else -
    including a tool nothing declared - writes.
    """
    metadata = tool_def.metadata or {}
    origin = metadata.get(MCP_ORIGIN)
    if isinstance(origin, dict):
        annotations = metadata.get("annotations") or {}
        return ToolClass(
            tool_id=f"tool:{tool_def.name}",
            read_only=annotations.get("readOnlyHint") is True
            and origin.get("trust_read_only_hints") is True,
            test=origin.get("test") is True,
        )
    known = tools.get(tool_def.name)
    if known is not None:
        return known
    return ToolClass(tool_id=f"tool:{tool_def.name}", read_only=tool_def.name in _FRAMEWORK_READS)


def recorded_args(call: ToolCallPart) -> dict[str, Any]:
    """A held call's arguments as the model sent them, safe to store as JSON.

    The model's own arguments rather than the validated ones: validation turns
    them into dates and models a JSON column cannot hold, and adds defaults the
    model never wrote. Over `MAX_RECORDED_ARGS_CHARS` they are replaced by their
    size, so the trajectory still shows the call.
    """
    args = to_jsonable_python(call.args_as_dict(), fallback=str)
    size = len(json.dumps(args, ensure_ascii=False))
    if size > MAX_RECORDED_ARGS_CHARS:
        return {"truncated": True, "chars": size}
    return args


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


@dataclass(frozen=True)
class CallRow:
    """One call a run's transcript kept: what was called, with what, and the answer."""

    tool_name: str
    args: Mapping[str, Any]
    result: str


def recorded_calls(
    rows: Sequence[CallRow], *, tools: Mapping[str, ToolClass]
) -> list[RecordedCall]:
    """A run's calls, in the order given, under their stable ids.

    Names resolve through `tools`, which is the *original* version's table: a
    candidate that renamed a tool still matches the calls it made under the old
    name.
    """
    return [
        RecordedCall(
            tool_id=known.tool_id
            if (known := tools.get(row.tool_name))
            else f"tool:{row.tool_name}",
            args=normalized_args(row.args),
            result=row.result,
        )
        for row in rows
    ]


@dataclass(frozen=True)
class InterceptedCall:
    """One call an isolated run answered without executing it."""

    agent_id: UUID | None
    tool_call_id: str
    tool_name: str
    tool_id: str
    args: dict[str, Any]
    outcome: InterceptionOutcome
    reason: InterceptionReason | None = None


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
        knowledge: A system agent's knowledge, picked for this run by whoever
            started it; `None` lets it search nothing.
    """

    recording: ToolRecording | None = None
    live_reads: bool = False
    intercepted: list[InterceptedCall] = field(default_factory=list)
    improvement_run_id: UUID | None = None
    knowledge_overlay: KnowledgeOverlay | None = None
    knowledge: RunKnowledge | None = None


@dataclass
class RunKnowledge:
    """The knowledge bases one system agent run may search, and what it found there.

    A system agent binds no knowledge base of its own: the platform picks the ones
    the run is about - the graded agent's, a gap's, a generation's sources - so
    its answer draws on nothing its readers did not already have at hand.

    Attributes:
        knowledge_base_ids: The bases picked for the run; the caller's own access
            still decides which of them it searches.
        found: The passages its searches returned, filled as it runs.
    """

    knowledge_base_ids: tuple[UUID, ...]
    found: list[FoundPassage] = field(default_factory=list)


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
    rather than refused for want of somebody to approve it. `approval` is that
    gate, asked which calls it would hold: a call it gates never reaches it here,
    because the refusal it would give leaves no record.
    """

    isolation: RunIsolation
    tools: Mapping[str, ToolClass] = field(default_factory=dict)
    agent_id: UUID | None = None
    approval: ApprovalGate | None = None

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
            # The recording holds what the model sent; validated arguments carry
            # defaults it never wrote, and would never match.
            recorded = recording.answer(tool.tool_id, call.args_as_dict())
            if recorded is not None:
                self._intercept(call, tool, InterceptionOutcome.REPLAYED)
                return recorded.result
            if not (tool.read_only and self.isolation.live_reads):
                self._intercept(call, tool, InterceptionOutcome.DIVERGENT)
                return _divergent_notice(tool_def.name)
        elif not (tool.read_only or tool.test):
            self._intercept(call, tool, InterceptionOutcome.BLOCKED, InterceptionReason.WRITES)
            return _blocked_notice(tool_def.name)
        if self.approval is not None and self.approval.gates(tool_def):
            self._intercept(
                call,
                tool,
                InterceptionOutcome.BLOCKED,
                InterceptionReason.NEEDS_APPROVAL,
            )
            return refusal(tool_def.name, "an evaluation run cannot ask anyone to approve it")
        return await handler(args)

    def _intercept(
        self,
        call: ToolCallPart,
        tool: ToolClass,
        outcome: InterceptionOutcome,
        reason: InterceptionReason | None = None,
    ) -> None:
        logger.info("isolated_tool_call", extra={"tool_id": tool.tool_id, "outcome": outcome.value})
        self.isolation.intercepted.append(
            InterceptedCall(
                agent_id=self.agent_id,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                tool_id=tool.tool_id,
                args=recorded_args(call),
                outcome=outcome,
                reason=reason,
            )
        )
