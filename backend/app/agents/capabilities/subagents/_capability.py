"""Delegation, as this platform offers it, over the library that implements it.

`subagents-pydantic-ai` provides the tools, the task lifecycle and the background
execution. This wraps its `SubAgentCapability` rather than registering it, and the
three reasons are worth stating because "just register theirs" is what `thinking`
does and is usually right:

*The reference docs are generated from these docstrings.* A capability whose
behaviour is only documented in another repository is a capability nobody here can
answer a question about - and what an agent may do is exactly the question a
client asks.

*`get_instructions` has to describe **our** delegates.* The library lists the
`SubAgentConfig`s it was given; what an author published is a pinned agent version
or an inline specialist, with a description written for the parent's model, plus
the mode and fan-out this deployment will actually enforce. Two lists that mostly
agree are worse than one, because the disagreement is silent.

*An adapter is what keeps a library release from changing what an agent can do.*
`SubAgentCapability` is a dataclass of twenty fields with defaults - one of them
`include_general_purpose=True`, which this platform inverts. Registering it
directly would mean a field added upstream arrives switched on, in every published
agent, with nothing in this repository saying so.

What is deliberately *not* wrapped: the toolset's own task management, the
background task cancellation in `wrap_run`, and the retry behaviour. Those are the
library's job and it does them; re-implementing them here would be a second copy
to keep in step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, cast

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import UsageLimits
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.capabilities import WrapperCapability, WrapRunHandler
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import AbstractToolset, AgentToolset
from subagents_pydantic_ai import (
    ANSWER_SUBAGENT_DESCRIPTION,
    CHECK_TASK_DESCRIPTION,
    DELEGATE_TOOL_DESCRIPTION,
    HARD_CANCEL_TASK_DESCRIPTION,
    LIST_ACTIVE_TASKS_DESCRIPTION,
    SOFT_CANCEL_TASK_DESCRIPTION,
    TASK_TOOL_DESCRIPTION,
    WAIT_TASKS_DESCRIPTION,
    SubAgentCapability,
    SubAgentConfig,
    UsageLimitsFactory,
)
from subagents_pydantic_ai.prompts import SEND_MESSAGE_TO_SUBAGENT_DESCRIPTION

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities.subagents._journal import DelegationJournal
from app.agents.capabilities.subagents._toolset import DelegatingToolset
from app.agents.deps import AgentDeps
from app.agents.factory import DEFAULT_MAX_STEPS
from app.agents.spec import DelegationMode
from app.agents.subagent_runtime import ResolvedSubagent, SubagentRuntime

CREATE_AGENT_DESCRIPTION = (
    "Create a reusable specialized agent at run time. It is stored for the rest of "
    "this run and can be delegated to repeatedly with the task tool."
)
"""The one tool description this repository writes rather than imports.

The library composes `create_agent`'s text from the models and capabilities a
deployment allows, which is configuration this platform does not pass it, so
there is no constant to import - only the sentence the catalog needs.
"""

DELEGATION_TOOLS: tuple[CapabilityToolInfo, ...] = (
    # `task` is not side-effecting, which reads wrong for two seconds and is
    # right: what a delegate *does* is gated by the delegate's own spec, through
    # the same approval gate this run uses. Gating the delegation as well would
    # ask a person to approve every delegation before the work that might need
    # approving has even been proposed, and an author who does want that has one
    # `tool_approval` override.
    CapabilityToolInfo(id="task", description=TASK_TOOL_DESCRIPTION, side_effecting=False),
    CapabilityToolInfo(id="check_task", description=CHECK_TASK_DESCRIPTION, side_effecting=False),
    CapabilityToolInfo(id="wait_tasks", description=WAIT_TASKS_DESCRIPTION, side_effecting=False),
    CapabilityToolInfo(
        id="list_active_tasks", description=LIST_ACTIVE_TASKS_DESCRIPTION, side_effecting=False
    ),
    # A reply to a question a delegate asked, inside this run. It unblocks work
    # rather than acting on anything outside it.
    CapabilityToolInfo(
        id="answer_subagent", description=ANSWER_SUBAGENT_DESCRIPTION, side_effecting=False
    ),
    # The three that act. Steering changes what a delegate is doing mid-run, and
    # either cancel destroys work that was paid for and not delivered - a person
    # may want to see those before they happen.
    CapabilityToolInfo(
        id="send_message_to_subagent",
        description=SEND_MESSAGE_TO_SUBAGENT_DESCRIPTION,
        side_effecting=True,
    ),
    CapabilityToolInfo(
        id="soft_cancel_task", description=SOFT_CANCEL_TASK_DESCRIPTION, side_effecting=True
    ),
    CapabilityToolInfo(
        id="hard_cancel_task", description=HARD_CANCEL_TASK_DESCRIPTION, side_effecting=True
    ),
    # Declared, deliberately not yet offered - see the README. An agent nobody
    # published and nobody reviewed is the thing `allow_dynamic` exists to hold
    # back, so both dynamic entry points are side-effecting when they arrive.
    CapabilityToolInfo(
        id="create_agent", description=CREATE_AGENT_DESCRIPTION, side_effecting=True
    ),
    CapabilityToolInfo(id="delegate", description=DELEGATE_TOOL_DESCRIPTION, side_effecting=True),
)
"""Every tool delegation has, declared once, with the library's own text.

Declared rather than derived, and all ten rather than the eight a default
configuration offers, because a tool absent from this list cannot be gated by the
approval policy or renamed by a binding - and the dangerous half of that is
silent.

The descriptions are **imported, not rewritten**. A tool's description is the
strongest prompt in the product, and `TASK_TOOL_DESCRIPTION` is two hundred lines
of hard-won guidance about when delegating is worth it and when it is not;
replacing it with a one-line label for a Builder form would be a downgrade
wearing consistency as an excuse. What is declared here is also what the model
reads, exactly - see the `descriptions` argument in `build_delegation`.
"""

_MODE_NOTE: dict[DelegationMode, str] = {
    "sync": "Each delegation blocks until the specialist answers.",
    "async": (
        "Delegations run in the background: `task` answers with a task id, and "
        "`check_task` or `wait_tasks` collects the result."
    ),
    "auto": (
        "Simple work runs while you wait; longer independent work runs in the "
        "background and is collected with `check_task` or `wait_tasks`."
    ),
}
"""How each configured mode is explained to the model.

A table rather than three branches: what the model is told and what the platform
enforces come from one place, so an instruction cannot describe a mode the run
will not use.
"""


class _LazyAgent:
    """A delegate's agent: built when it is first delegated to, and run on its own deps.

    Two jobs, and both exist because of how the library drives a delegation.

    *Built late.* Building one resolves a model profile, assembles its
    capabilities and instruments it, so a delegate the model never calls should
    cost nothing. The library compiles every `SubAgentConfig` when its toolset is
    constructed - before any delegation has happened - so an already-built agent
    handed over as `SubAgentConfig["agent"]` would mean building all of them for
    every run that binds this capability. This stands in until one is needed.

    *Run on the deps this platform decides, not the ones the library cloned.* See
    `_own_deps`. Everything else is plain forwarding, which is enough because the
    library documents that only `run` and `iter` are called on the object it was
    given - and reads `event_stream_handler` off it, which is why the forwarding
    is generic rather than a fixed pair of methods.
    """

    def __init__(self, delegate: ResolvedSubagent, in_background: Callable[[], bool]) -> None:
        self._delegate = delegate
        self._in_background = in_background
        self._agent: PydanticAgent[Any, Any] | None = None

    # `Any` because this forwards whatever the library asks for, on an object
    # whose useful members (`run`, `iter`) are generic in both their deps and
    # their output type. Narrowing it would mean naming the members here, which
    # is the coupling this class exists to avoid.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._built(), name)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the delegate once, on its own deps. Returns the library's coroutine."""
        return self._built().run(*args, **self._own_deps(kwargs))

    def iter(self, *args: Any, **kwargs: Any) -> Any:
        """The same, for the streamed path. Returns the library's async context manager."""
        return self._built().iter(*args, **self._own_deps(kwargs))

    def _built(self) -> PydanticAgent[Any, Any]:
        """This delegate's agent, built at most once per run."""
        if self._agent is None:
            self._agent = self._delegate.build()
        return self._agent

    def _own_deps(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """The two fields this platform decides about the deps a delegation runs with.

        This looks redundant and is not. The library decides what deps a
        delegation runs with: it calls `clone_for_subagent` on the **parent's**
        deps and passes the result here, so the `AgentDeps` the runner built for
        this delegate is discarded before its first request. The clone is
        *replaced field by field* rather than swapped for the deps the build
        produced, because everything else on it is right and deliberately so: the
        organization and user a delegation acts for, the parent's `agent_id` and
        `run_id` - which key the shared workspace, so a researcher and a writer
        see the same files - and the parent's `ask_user` and `subagent_events`
        channels.

        *The collections are the delegate's own.* `clone_for_subagent` drops them
        on purpose - inheriting the parent's would hand a specialist a collection
        nobody granted it - so the ones resolved from this delegate's spec go back
        on here. Left alone, a delegate configured with a collection answers "No
        active knowledge bases selected" to every search: it publishes cleanly,
        looks correctly configured, and cannot read the one thing it exists to
        read. Nothing raises (agenticos#166). Written back unconditionally,
        including the empty list a delegate with no collections already had, so a
        published delegate and an inline specialist behave the same way.

        *A background delegation gets no approval channel.* The parent's channel
        writes an approval row and parks the run, and neither is available to a
        background delegation: the tool call that started it returned a task id
        long ago, so there is no caller left to hand a parked call back to, and the
        write would land on the request's `AsyncSession` from a task the parent is
        still sharing it with - a session that is not concurrency-safe. So the
        gate is handed `None`, which is the case it is already written for: it
        refuses the call, tells the model a person could not be asked, and the
        delegation goes on to answer or to say it could not. The alternative was
        the library's own route, which is worse in both halves - the row is
        written *before* the run suspends, and the suspension itself cannot be
        delivered to a caller that has gone. An author who wants that tool
        approved delegates the work with `mode="sync"`, which the library's own
        message says too.
        """
        clone: AgentDeps = kwargs["deps"]
        return {
            **kwargs,
            "deps": replace(
                clone,
                kb_collection_names=list(self._delegate.collection_names),
                request_approval=None if self._in_background() else clone.request_approval,
            ),
        }


@dataclass
class Delegation(WrapperCapability[AgentDeps]):
    """Hands an agent the delegates its spec pinned, and accounts for what they cost.

    The capability is built per run, because the delegates are: each one is a
    published agent version or an inline specialist that the runner resolved
    against the caller's access before the run started. That is also why there is
    nothing to configure here beyond what the journal holds - a delegate this
    object has not been given is a delegate no model can reach.
    """

    journal: DelegationJournal

    _delegating: AbstractToolset[AgentDeps] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AgentToolset[AgentDeps] | None:
        """The library's delegation tools, with this platform's accounting around them.

        Memoised because the wrapper carries no state of its own but the journal
        it points at does, and because `BuiltAgent.capabilities` is introspected -
        two wrappers over one toolset would answer the same question twice.
        """
        if self._delegating is None:
            # `get_toolset` is optional on the capability protocol and
            # `SubAgentCapability` always returns one: it constructs its toolset
            # in `__post_init__` and holds it for the life of the instance.
            wrapped = cast(AbstractToolset[AgentDeps], super().get_toolset())
            self._delegating = DelegatingToolset(wrapped=wrapped, journal=self.journal)
        return self._delegating

    def get_instructions(self) -> str:
        """Who this agent may delegate to, and what the platform will allow.

        Replaces the library's own listing rather than adding to it. Two lists of
        the same delegates in one system prompt is duplicated context every turn,
        and the library's cannot say what this deployment enforces - the mode is
        forced from the spec and the fan-out is a ceiling the model will otherwise
        discover by being refused.
        """
        delegates = "\n".join(
            f"- **{delegate.name}**: {delegate.description}"
            for delegate in self.journal.runtime.subagents
        )
        return (
            "## Delegation\n\n"
            "Hand a self-contained piece of work to one of these specialists with "
            f"the `task` tool:\n\n{delegates}\n\n"
            "A specialist cannot see this conversation, so put everything it needs "
            "in the description, and synthesise what comes back rather than relaying "
            f"it. {_MODE_NOTE[self.journal.mode]} At most {self.journal.max_fanout} "
            "delegations run at once; asking for more is refused until one finishes."
        )

    async def wrap_run(
        self, ctx: RunContext[AgentDeps], *, handler: WrapRunHandler
    ) -> AgentRunResult[Any]:
        """Run the agent, then account for whatever was still delegating.

        The library's own `wrap_run` - which this defers to - cancels every
        background task this run started and waits for each to unwind, so by the
        time it returns every delegation has reached a terminal status. This is
        therefore the last moment one can be recorded, and it is the moment that
        matters: a run that launched a background delegation and answered without
        collecting it would otherwise leave that delegation's spend attributed to
        nothing at all.
        """
        try:
            return await super().wrap_run(ctx, handler=handler)
        finally:
            await self.journal.settle_background(ctx.deps.subagent_events)


def build_delegation(
    *,
    runtime: SubagentRuntime,
    mode: DelegationMode,
    max_fanout: int,
    depth: int,
    include_general_purpose: bool,
    max_result_chars: int,
) -> Delegation:
    """Assemble the capability from a resolved runtime and its configuration.

    Args:
        runtime: The delegates the runner resolved for this run, the recorder it
            wants outcomes reported to, and the nesting budget left.
        mode: Whether delegations block, run in the background, or are decided per
            task.
        max_fanout: How many delegations may run at once.
        depth: How far inside the run's own agent these delegations are, which is
            what a surface needs to nest their panels.
        include_general_purpose: Whether the library's own unspecialised delegate
            is offered alongside the resolved ones. See `SubagentsConfig`.
        max_result_chars: How much of a finished delegation's answer the
            `wait_tasks` listing carries before pointing at `check_task`.
    """
    journal = DelegationJournal(runtime=runtime, mode=mode, max_fanout=max_fanout, depth=depth)
    capability = SubAgentCapability(
        subagents=[_config_for(delegate, journal) for delegate in runtime.subagents],
        include_general_purpose=include_general_purpose,
        max_result_chars=max_result_chars,
        # The nesting budget the runner had left after resolving this level. The
        # library subtracts one per delegation and passes it to
        # `AgentDeps.clone_for_subagent`, which is where a delegate learns whether
        # it may delegate further.
        max_nesting_depth=runtime.depth_remaining,
        usage_limits=_limits_for(runtime),
        event_stream_handler_factory=journal.stream_for,
        # So the description the catalog declares is exactly the text the model
        # reads. Left alone, the library appends the delegate list to `task`'s
        # description - and the instructions above already carry it, where
        # `ReinjectSystemPrompt` keeps it visible through a long conversation.
        # Two copies of one list is context paid for twice on every turn, and the
        # catalog would show neither of them.
        descriptions={"task": TASK_TOOL_DESCRIPTION},
    )
    # Late-bound, like `SubagentRuntime.ledger`: the task manager is created
    # inside the capability the journal was passed into, so this is the first
    # moment both exist.
    journal.tasks = capability.task_manager
    return Delegation(wrapped=capability, journal=journal)


def _config_for(delegate: ResolvedSubagent, journal: DelegationJournal) -> SubAgentConfig:
    """One resolved delegate, in the shape the library takes.

    `instructions` is required by the library's `TypedDict` and unread here: a
    config carrying `agent` skips the library's own construction entirely, and a
    delegate's instructions came from its own spec when the runner built it. An
    empty string is the honest value; anything else would look like a prompt that
    does something.

    The journal is handed over as one predicate rather than as itself: the only
    thing the stand-in asks it is whether the delegation now executing is a
    background one, and a delegate can be delegated to both ways within one run -
    so the answer has to be resolved per delegation, not stored per delegate.
    """
    return SubAgentConfig(
        name=delegate.name,
        description=delegate.description,
        instructions="",
        agent=_LazyAgent(delegate, journal.in_background),
    )


def _limits_for(runtime: SubagentRuntime) -> UsageLimitsFactory:
    """A per-delegation request ceiling, resolved from the delegate's own spec.

    A factory rather than one `UsageLimits` for every delegate, because
    `max_steps` is a per-agent statement: a three-step summariser and a
    twenty-step researcher under one ceiling means either the researcher cannot
    finish or the summariser can loop.

    This is the only thing between a delegation and a loop that delegates to a
    loop. A delegate with no `max_steps` of its own gets the same default a
    top-level run gets, from one constant, so raising the platform's ceiling
    raises it in both places.
    """

    def limits(_ctx: RunContext[AgentDeps], config: SubAgentConfig) -> UsageLimits:
        delegate = runtime.named(config["name"])
        if delegate is None or delegate.max_steps is None:
            # A delegate whose spec said nothing, or the library's own
            # general-purpose subagent, which no runtime resolved.
            return UsageLimits(request_limit=DEFAULT_MAX_STEPS)
        return UsageLimits(request_limit=delegate.max_steps)

    return limits
