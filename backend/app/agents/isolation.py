"""Running an agent without letting it act on the world - what an eval run needs.

An eval runs the agent for real, so its tools would run for real: an agent that
sends e-mail or writes to a CRM would do it again for every case. An *isolated*
run keeps the agent whole and stops the effects at one place - tool execution -
by the same means the approval gate holds a call: a capability wrapping every
tool call, so a tool cannot forget to ask.

What it decides, per call:

* **A tool with a test connection runs.** An environment can answer a binding
  with a test system (a sandbox CRM, a test mailbox); the call goes there.
* **A read that stays inside the deployment runs** on the normal connection: a
  registry tool listed in `LIVE_IN_ISOLATION`, or an MCP tool whose server says
  it only reads (`readOnlyHint`) a closed world (`openWorldHint: false`) on a
  connection set to trust what that server says.
* **A read that reaches further is blocked and recorded.** Isolated runs execute
  text nobody has reviewed yet - an Improve search's variants, a skill proposal
  under check - and a read that dereferences a URL, queries a search engine or
  asks a remote agent sends whatever the model puts into it. Being read-only
  does not make a tool safe to run here; being on the list does.
* **A write is blocked and recorded** as an intended call - the tool and its
  arguments - which is what trajectory scoring judges. A tool that declares
  nothing writes.

A run can also be answered from a **recording** of the run a case was taken
from - its `tool_calls` rows, in the order they were made. A call is then
matched by its stable tool id, its normalized arguments and its occurrence among
calls with that same id and arguments, and answered with what the original call
returned. A call with no match is not executed and is
recorded as divergent: serving it some other call's result would fabricate the
very difference a comparison exists to measure. A read that stays inside the
deployment may run live instead where the run allows it; nothing else ever does.

Two kinds of tool would get past a guard that only wraps execution, and are
closed where the agent is assembled instead: a tool the model provider runs on
its own side (`kept_local` rebuilds the binding so the call comes here), and a
remote agent behind the delegation tool (`IsolationGuard.remote_delegates`, with
the delegate itself built so it cannot reach its endpoint).

An isolated run has no approval channel, so a gated call is never parked: a
parked run is resumed by rebuilding it, and nothing here is part of what a
resume rebuilds. A call the agent gates is held and recorded as one that needed
an approval, even when the tool only reads - so it is in the trajectory too.
"""

import json
import logging
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_core import to_jsonable_python

from app.agents.approval import refusal
from app.agents.capabilities import LOAD_CAPABILITY, CapabilityBinding
from app.agents.capabilities import get as get_capability
from app.agents.capabilities.approval import ApprovalGate
from app.agents.capabilities.knowledge import FoundPassage
from app.agents.deps import AgentDeps
from app.agents.mcp import MCP_ISOLATION
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

LIVE_IN_ISOLATION: frozenset[str] = frozenset(
    {
        "capability:artifacts.list_artifacts",
        "capability:artifacts.read_artifact",
        "capability:charts.create_chart",
        "capability:code_execution.run_python",
        "capability:context.list_context",
        "capability:context.read_context",
        "capability:conversation_search.read_conversation",
        "capability:conversation_search.search_conversations",
        "capability:knowledge.search_documents",
        "capability:memory_files.list_memory",
        "capability:memory_files.read_memory",
        "capability:memory_files.recall",
        "capability:planning.add_subtask",
        "capability:planning.add_task",
        "capability:planning.get_available_tasks",
        "capability:planning.read_plan",
        "capability:planning.remove_task",
        "capability:planning.set_dependency",
        "capability:planning.update_task_status",
        "capability:planning.update_task_statuses",
        "capability:planning.write_plan",
        "capability:sandbox.glob",
        "capability:sandbox.grep",
        "capability:sandbox.ls",
        "capability:sandbox.read_file",
        "capability:skills.load_capability",
        "capability:skills.read_skill_resource",
        "capability:subagents.answer_subagent",
        "capability:subagents.check_task",
        "capability:subagents.create_agent",
        "capability:subagents.delegate",
        "capability:subagents.hard_cancel_task",
        "capability:subagents.list_active_tasks",
        "capability:subagents.send_message_to_subagent",
        "capability:subagents.soft_cancel_task",
        "capability:subagents.task",
        "capability:subagents.wait_tasks",
        "capability:tool_output_limits.read_tool_result",
        "capability:workflows.get_workflow_run",
        "capability:workflows.list_workflows",
    }
)
"""The registry tools an isolated run executes on the normal connections.

Each one reads this deployment's own data for the run's organization, under the
run's own access, and sends nothing to a host the model can name. It is a list
rather than a reading of `read_only`, because a read can still carry data out:
`web_fetch` dereferences the URL the model wrote, `web_research` hands a query
to a search engine, and the channel readers ask a chat platform's API. A tool
declared tomorrow is held until somebody adds it here. Delegation is on it
because a delegate of this deployment runs under the same isolation; a remote
one is held by name (`IsolationGuard.remote_delegates`).
"""

_DELEGATION = "capability:subagents.task"
"""The delegation tool whose `subagent_type` may name a remote agent."""


@dataclass(frozen=True)
class ToolClass:
    """What an isolated run needs to know about one tool.

    Attributes:
        tool_id: The stable identity a recording is matched on -
            `capability:<capability>.<tool>` for a registry tool, which survives
            a binding renaming it, and `tool:<name>` for everything else.
        read_only: Whether calling it changes nothing outside the run.
        test: Whether it reaches a test system the run's environment named.
        live: Whether it may run on the normal connection in an isolated run -
            a read that stays inside the deployment.
    """

    tool_id: str
    read_only: bool
    test: bool = False
    live: bool = False


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
            tool_id = f"capability:{binding.id}.{tool.id}"
            read_only = definition.tool_is_read_only(tool)
            tools[tool.name] = ToolClass(
                tool_id=tool_id,
                read_only=read_only,
                test=test,
                live=read_only and tool_id in LIVE_IN_ISOLATION,
            )
    return tools


def classify(tool_def: ToolDefinition, tools: Mapping[str, ToolClass]) -> ToolClass:
    """What one tool is, whoever contributed it.

    An MCP tool is recognised by the origin this deployment stamped on it, never
    by its name. It is read-only only when its server says `readOnlyHint` and its
    connection trusts the server to say so, and it stays inside what the server
    reaches only when the same server also says `openWorldHint: false` - a
    missing hint means an open world, as the protocol defines it. A registry
    tool is looked up by the name the model called. Anything else - including a
    tool nothing declared - writes.
    """
    metadata = tool_def.metadata or {}
    origin = metadata.get(MCP_ISOLATION)
    if isinstance(origin, dict):
        annotations = metadata.get("annotations") or {}
        read_only = (
            annotations.get("readOnlyHint") is True and origin.get("trust_read_only_hints") is True
        )
        return ToolClass(
            tool_id=f"tool:{tool_def.name}",
            read_only=read_only,
            test=origin.get("test") is True,
            live=read_only and annotations.get("openWorldHint") is False,
        )
    known = tools.get(tool_def.name)
    if known is not None:
        return known
    framework = tool_def.name in _FRAMEWORK_READS
    return ToolClass(tool_id=f"tool:{tool_def.name}", read_only=framework, live=framework)


def kept_local(binding: CapabilityBinding) -> CapabilityBinding:
    """The binding as an isolated run builds it: with no tool the provider runs itself.

    A tool the model provider executes on its own side never reaches the guard,
    so it could neither be held nor recorded. Where the binding's configuration
    hands a tool over, the same field is set to the value that keeps the tool
    in this deployment - an ordinary call the guard then decides like any other.
    """
    definition = get_capability(binding.capability_id)
    declared = definition.provider_executed
    if declared is None or not declared.tools_for(definition.validate_config(binding.config)):
        return binding
    return replace(binding, config={**binding.config, declared.field: declared.kept_local})


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


def _external_notice(name: str) -> str:
    return (
        f"Not available in an isolated run: `{name}` would reach outside this deployment, "
        "and an evaluation sends nothing out. The call and its arguments were recorded; "
        "nothing was sent. Answer without it."
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

    `remote_delegates` names this agent's delegates that are other systems'
    agents: delegating to one sends the task over the network, so the call is
    held as reaching outside although delegation itself stays on the list.
    """

    isolation: RunIsolation
    tools: Mapping[str, ToolClass] = field(default_factory=dict)
    agent_id: UUID | None = None
    approval: ApprovalGate | None = None
    remote_delegates: frozenset[str] = frozenset()

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
        if (
            tool.tool_id == _DELEGATION
            and call.args_as_dict().get("subagent_type") in self.remote_delegates
        ):
            tool = replace(tool, live=False)
        recording = self.isolation.recording
        if recording is not None:
            # The recording holds what the model sent; validated arguments carry
            # defaults it never wrote, and would never match.
            recorded = recording.answer(tool.tool_id, call.args_as_dict())
            if recorded is not None:
                self._intercept(call, tool, InterceptionOutcome.REPLAYED)
                return recorded.result
            if not (tool.live and self.isolation.live_reads):
                self._intercept(call, tool, InterceptionOutcome.DIVERGENT)
                return _divergent_notice(tool_def.name)
        elif not tool.test:
            if not tool.read_only:
                self._intercept(call, tool, InterceptionOutcome.BLOCKED, InterceptionReason.WRITES)
                return _blocked_notice(tool_def.name)
            if not tool.live:
                self._intercept(
                    call, tool, InterceptionOutcome.BLOCKED, InterceptionReason.EXTERNAL
                )
                return _external_notice(tool_def.name)
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
