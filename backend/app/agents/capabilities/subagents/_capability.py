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
    HARD_CANCEL_TASK_DESCRIPTION,
    LIST_ACTIVE_TASKS_DESCRIPTION,
    SOFT_CANCEL_TASK_DESCRIPTION,
    TASK_TOOL_DESCRIPTION,
    WAIT_TASKS_DESCRIPTION,
    SubAgentCapability,
    SubAgentConfig,
    UsageLimitsFactory,
)
from subagents_pydantic_ai.dynamic_agent import AgentFactory
from subagents_pydantic_ai.prompts import SEND_MESSAGE_TO_SUBAGENT_DESCRIPTION

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities.subagents._journal import DelegationJournal
from app.agents.capabilities.subagents._toolset import DelegatingToolset
from app.agents.deps import AgentDeps
from app.agents.factory import DEFAULT_MAX_STEPS
from app.agents.spec import DelegationMode
from app.agents.subagent_runtime import (
    DynamicSpecialists,
    ResolvedSubagent,
    ResumedDelegation,
    SubagentRuntime,
)

MAX_DYNAMIC_SPECIALISTS = 5
"""How many specialists one run may **keep** before `create_agent` is refused.

Precisely that, because it is the library's `DynamicAgentRegistry` ceiling and
the registry is what `create_agent` writes into. It is not a bound on how many a
model may invent altogether: a `delegate` call registers nothing, so one-shot
specialists are bounded by `max_fanout` on how many run at once and by the
agent's own `max_steps` on how many calls a turn can make at all.

A constant rather than a setting, because there is no author decision to make
here that those two do not already cover - a model that has asked to *keep* six
different specialists is not pacing badly, it is failing to reuse the ones it
has. The library's own default is ten, halved because every one of them is an
agent nobody reviewed.
"""

CREATE_AGENT_DESCRIPTION = """\
Create a specialist agent and delegate to it by name with the `task` tool, as \
many times as you need.

Use this for a specialist you will hand several pieces of work to. For one job, \
`delegate` creates and runs one in a single call. A specialist you create lasts \
for this reply: if `task` later answers that it is unknown, create it again.

## Parameters
- **name**: How you will address it in `task` (letters, numbers and hyphens)
- **description**: What it is for, in one line
- **instructions**: Its system prompt. This is the whole of its behaviour
- **model**: Required. One of the models listed in the Delegation instructions

A specialist you create has **no tools, no knowledge and no delegates** - it \
reads its instructions and the task you give it, and answers. Work needing a \
tool goes to one of the specialists this agent was given, or is done here.
"""
"""What the model reads before inventing a specialist it will reuse.

Written here rather than imported, for the reason the imported ones are
imported: this text has to be true. The library composes its own from the models
and capabilities a deployment configured, and would describe `model` as optional
and `capabilities` as available - neither of which holds here.
"""

DELEGATE_DESCRIPTION = """\
Create a specialist agent and hand it one piece of work, in a single call. It is \
not kept: it cannot be addressed again afterwards.

Use this for a one-off job that needs its own instructions. For a specialist you \
will use repeatedly, `create_agent` keeps one you can address by name.

## Parameters
- **description**: The work for it to do. It cannot see this conversation, so \
put everything it needs here
- **instructions**: Its system prompt. This is the whole of its behaviour
- **name**: A label for it, used in logs and progress (letters, numbers, hyphens)
- **model**: Required. One of the models listed in the Delegation instructions

A specialist you create has **no tools, no knowledge and no delegates** - it \
reads its instructions and the work you give it, and answers. Work needing a \
tool goes to one of the specialists this agent was given, or is done here.
"""
"""The same, for the one-shot entry point.

`DELEGATE_TOOL_DESCRIPTION` is deliberately *not* imported, which is the one
place this module departs from "the descriptions are the library's". Its
parameter list describes `model` as an optional override, `capabilities` as
attachable and `mode` as the model's choice, and all three are false here: the
model is required, capabilities are refused, and the mode is the author's. A tool
description is the strongest prompt in the product, so three false sentences in
one is worse than writing our own.
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
    # The two dynamic entry points, offered only to an agent whose author
    # switched `allow_dynamic` on. Side-effecting, which is the one place
    # delegation and *dynamic* delegation part company: `task` is not, because
    # what a delegate does is gated by the delegate's own reviewed spec, and
    # there is no reviewed spec here - the instructions were written by a model
    # a moment ago. So a person sees the specialist before it runs, unless the
    # author says otherwise with `tool_approval`.
    CapabilityToolInfo(
        id="create_agent", description=CREATE_AGENT_DESCRIPTION, side_effecting=True
    ),
    CapabilityToolInfo(id="delegate", description=DELEGATE_DESCRIPTION, side_effecting=True),
)
"""Every tool delegation has, declared once.

Declared rather than derived, and all ten rather than the eight a non-dynamic
configuration offers, because a tool absent from this list cannot be gated by the
approval policy or renamed by a binding - and the dangerous half of that is
silent.

Eight of the descriptions are **imported, not rewritten**. A tool's description is
the strongest prompt in the product, and `TASK_TOOL_DESCRIPTION` is two hundred
lines of hard-won guidance about when delegating is worth it and when it is not;
replacing it with a one-line label for a Builder form would be a downgrade
wearing consistency as an excuse. The two dynamic ones are written here because
the library's describe a configuration this platform does not offer - see
:data:`DELEGATE_DESCRIPTION`. What is declared here is what the model reads,
exactly - see the `descriptions` argument in `build_delegation`.
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

    Three jobs, and each exists because of how the library drives a delegation.

    *Built late.* Building one resolves a model profile, assembles its
    capabilities and instruments it, so a delegate the model never calls should
    cost nothing. The library compiles every `SubAgentConfig` when its toolset is
    constructed - before any delegation has happened - so an already-built agent
    handed over as `SubAgentConfig["agent"]` would mean building all of them for
    every run that binds this capability. This stands in until one is needed.

    *Run on the deps this platform decides, not the ones the library cloned.* See
    `_own_deps`.

    *Continued rather than restarted, when this delegation already stopped for a
    person.* See `_continued`. Both entry points, because which one the library
    takes depends on whether the surface streams.

    Everything else is plain forwarding, which is enough because the library
    documents that only `run` and `iter` are called on the object it was given -
    and reads `event_stream_handler` off it, which is why the forwarding is
    generic rather than a fixed pair of methods.
    """

    def __init__(self, delegate: ResolvedSubagent, journal: DelegationJournal) -> None:
        self._delegate = delegate
        self._journal = journal
        self._agent: PydanticAgent[Any, Any] | None = None

    # `Any` because this forwards whatever the library asks for, on an object
    # whose useful members (`run`, `iter`) are generic in both their deps and
    # their output type. Narrowing it would mean naming the members here, which
    # is the coupling this class exists to avoid.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._built(), name)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the delegate once, on its own deps. Returns the library's coroutine."""
        resumed = self._journal.resuming()
        if resumed is None:
            return self._built().run(*args, **self._own_deps(kwargs))
        return self._built().run(None, **self._own_deps(self._continuing(kwargs, resumed)))

    def iter(self, *args: Any, **kwargs: Any) -> Any:
        """The same, for the streamed path. Returns the library's async context manager."""
        resumed = self._journal.resuming()
        if resumed is None:
            return self._built().iter(*args, **self._own_deps(kwargs))
        return self._built().iter(None, **self._own_deps(self._continuing(kwargs, resumed)))

    @staticmethod
    def _continuing(kwargs: dict[str, Any], resumed: ResumedDelegation) -> dict[str, Any]:
        """The run arguments for a delegate that already stopped for a person.

        A delegation the run parked on is *the same delegation*, and continuing it
        is the only way a person's decision applies to the call they were shown. So
        the task prompt the library composed is dropped - the prompt is already the
        first message of the stored conversation, and asking again would put the
        work to the delegate twice - and the verdicts on the calls it parked travel
        as `deferred_tool_results`. That is exactly how a top-level parked run is
        continued, one level further in.

        Both entry points, and not for symmetry: the library drives a delegation
        through `iter` whenever the surface streams and through `run` when it does
        not, so a substitution on one path only would work in Slack and lose the
        approval in web chat.
        """
        return {
            **kwargs,
            "message_history": resumed.messages,
            "deferred_tool_results": resumed.results,
        }

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
                request_approval=(
                    None if self._journal.in_background() else clone.request_approval
                ),
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

        The models a dynamic specialist may run on belong here too, rather than in
        `create_agent`'s description. A description is what the catalog declares
        and the Builder shows, so one that grew a per-run list would be a
        description no page could render - and `ReinjectSystemPrompt` keeps this
        visible through a long conversation, which is where a model otherwise
        forgets the list and starts inventing model names.
        """
        return "## Delegation\n\n" + "\n\n".join(
            part
            for part in (self._delegates_note(), self._dynamic_note(), self._ceiling_note())
            if part
        )

    def _delegates_note(self) -> str:
        """The specialists this agent was given, or nothing when it was given none.

        Empty for an agent that only invents its own, which is a complete
        configuration: an empty bulleted list under "delegate to one of these"
        reads as a mistake, and leaves the model wondering what it cannot see.
        """
        delegates = self.journal.runtime.subagents
        if not delegates:
            return ""
        listed = "\n".join(f"- **{entry.name}**: {entry.description}" for entry in delegates)
        return (
            "Hand a self-contained piece of work to one of these specialists with "
            f"the `task` tool:\n\n{listed}\n\n"
            "A specialist cannot see this conversation, so put everything it needs in "
            "the description, and synthesise what comes back rather than relaying it."
        )

    def _dynamic_note(self) -> str:
        """The models an invented specialist may run on, when this agent may invent one.

        Named here because a model cannot otherwise know them: the organization's
        profiles are resolved per run, and a specialist naming a model this
        deployment does not hold is refused. Telling the model the list is what
        turns that refusal from something it discovers into something it avoids.
        """
        dynamic = self.journal.runtime.dynamic
        if dynamic is None:
            return ""
        models = ", ".join(f"`{label}`" for label in dynamic.allowed_models)
        return (
            "You may define a specialist of your own - `delegate` for one job, "
            "`create_agent` for one you will reuse. Give it a model from this list, "
            f"exactly as written: {models}. It gets no tools, no knowledge and no "
            "delegates of its own, so work needing any of those stays with you or "
            "goes to a specialist you were given."
        )

    def _ceiling_note(self) -> str:
        return (
            f"{_MODE_NOTE[self.journal.mode]} At most {self.journal.max_fanout} "
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
    max_result_chars: int,
) -> Delegation:
    """Assemble the capability from a resolved runtime and its configuration.

    Whether the two dynamic entry points are offered is read off the runtime
    rather than taken as an argument, and that is deliberate: `allow_dynamic` is
    a setting the *runner* acts on, because acting on it means resolving the
    organization's model profiles and holding the run's budget guard. One reader
    means the switch and the tools cannot disagree.

    Args:
        runtime: The delegates the runner resolved for this run, the recorder it
            wants outcomes reported to, the nesting budget left, and whether this
            agent may invent specialists of its own.
        mode: Whether delegations block, run in the background, or are decided per
            task.
        max_fanout: How many delegations may run at once.
        depth: How far inside the run's own agent these delegations are, which is
            what a surface needs to nest their panels.
        max_result_chars: How much of a finished delegation's answer the
            `wait_tasks` listing carries before pointing at `check_task`.
    """
    journal = DelegationJournal(runtime=runtime, mode=mode, max_fanout=max_fanout, depth=depth)
    dynamic = runtime.dynamic
    capability = SubAgentCapability(
        subagents=[_config_for(delegate, journal) for delegate in runtime.subagents],
        # Passed because the library's own default is `True`, not because anything
        # here can ask for it: this is a fact about somebody else's default, and
        # the one place it is stated. The delegate it would add is compiled at
        # construction from `default_model` - a model string of the library's
        # choosing, resolved from no profile of this organization's, unsealed from
        # no credential in its vault and wrapped by no budget guard - so on a
        # deployment holding no such key the build raises, and on one that has that
        # key in its environment a tenant's work runs on a deployment-wide
        # credential. Neither is a delegate this platform can account for, so there
        # is no setting for it and never was one an author could reach
        # (agenticos#174 tracks fixing it upstream). An author who wants a
        # catch-all writes an inline specialist, whose instructions somebody read.
        include_general_purpose=False,
        max_result_chars=max_result_chars,
        # Which entry points exist at all. `default` is `task` alone;
        # `persisted_and_oneshot` adds `create_agent` and `delegate` - and the
        # library refuses `allowed_models` and `default_agent_factory` under any
        # configuration that would leave them unread, so those three move together.
        delegation_configuration="default" if dynamic is None else "persisted_and_oneshot",
        allowed_models=None if dynamic is None else list(dynamic.allowed_models),
        default_agent_factory=None if dynamic is None else _specialist_factory(dynamic, journal),
        # `0` rejects every registration, which is the honest ceiling for an agent
        # that may not create one at all - `is not None`, not truthiness, is how the
        # library reads it, so this is not "unlimited". It bounds `create_agent`
        # only; a `delegate` call registers nothing.
        max_agents=0 if dynamic is None else MAX_DYNAMIC_SPECIALISTS,
        # `default_model` is left at the library's own, and this platform has no
        # default model anywhere: a specialist that names none is refused in
        # `DelegatingToolset._refuse_dynamic`, before either entry point reaches
        # the fallback, and the general-purpose delegate that would otherwise be
        # compiled from it at construction is switched off above. So the field is
        # unread here, and an unusable sentinel in its place would buy a second
        # spelling of a refusal that already has one - as an exception rather than
        # a tool result the model can act on.
        # The nesting budget the runner had left after resolving this level. The
        # library subtracts one per delegation and passes it to
        # `AgentDeps.clone_for_subagent`, which is where a delegate learns whether
        # it may delegate further.
        max_nesting_depth=runtime.depth_remaining,
        usage_limits=_limits_for(runtime),
        event_stream_handler_factory=journal.stream_for,
        # So the description the catalog declares is exactly the text the model
        # reads. Left alone, the library appends the delegate list to `task`'s
        # description and the allowed models to the other two - and the
        # instructions above already carry both, where `ReinjectSystemPrompt`
        # keeps them visible through a long conversation. Two copies of one list
        # is context paid for twice on every turn, and the catalog would show
        # neither of them.
        descriptions={
            "task": TASK_TOOL_DESCRIPTION,
            "create_agent": CREATE_AGENT_DESCRIPTION,
            "delegate": DELEGATE_DESCRIPTION,
        },
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

    The stand-in is given the journal rather than a bound predicate, because both
    of the questions it asks - is this delegation a background one, and is it one
    the run already parked on - are about *the delegation now executing* rather
    than about this delegate. A delegate can be delegated to twice in one run, once
    each way, and once from a stashed position.
    """
    return SubAgentConfig(
        name=delegate.name,
        description=delegate.description,
        instructions="",
        agent=_LazyAgent(delegate, journal),
    )


def _specialist_factory(dynamic: DynamicSpecialists, journal: DelegationJournal) -> AgentFactory:
    """How a specialist a model invented becomes an agent of this platform's.

    The whole point of the phase, and it is one line of substance: the library is
    given a factory, so it never builds a dynamic specialist itself. Left to its
    own devices it constructs `Agent(default_model, system_prompt=...)` - an agent
    on a model string of the library's choosing, with no credential from this
    organization's vault, no price attached to its requests and **no budget
    guard**. That is an unmetered model request on a provider the organization may
    hold no key for, and it is the reason both entry points were declared and not
    offered for two phases.

    What the factory produces instead goes through `build_agent` with the run's
    `shared_budget`, which is the same door an inline specialist and a pinned
    delegate come through - so its requests are checked against the total the
    parent is adding to and recorded into it.

    Built eagerly rather than lazily, unlike a resolved delegate: the model asked
    for this one, so the cost of building it is a cost it has already chosen, and
    building here is what lets `create_agent` answer "created" only when the agent
    genuinely exists. The `_LazyAgent` wrapper is still what runs it, for its other
    two jobs - the deps a delegation actually runs with, and continuing one the run
    already parked on, neither of which a bare agent would do.

    A build that raises does not reach the model as an error: `build_dynamic_agent`
    contains every exception and answers with `Error creating agent: ...`, which
    lands in the model's context and in no log line. That is the library's choice
    and it is the right one for a tool call - the model can try something else -
    but it means a misconfiguration here is visible only in a transcript.
    """

    def factory(config: SubAgentConfig) -> _LazyAgent:
        built = dynamic.build(
            name=config["name"],
            instructions=config["instructions"],
            # Present because `DelegatingToolset._refuse_dynamic` refuses a call
            # that named no model, and one of `dynamic.allowed_models` because
            # `subagents_pydantic_ai.dynamic_agent.validate_model` checked it
            # against exactly that list before this factory was reached.
            model=str(config["model"]),
        )
        return _LazyAgent(
            ResolvedSubagent(
                name=config["name"],
                description=config["description"],
                build=lambda: built,
                # No collections, because a specialist nobody granted one has
                # none - which is also what `_own_deps` writes back over the
                # parent's, so an invented specialist cannot inherit a knowledge
                # base by being invented inside an agent that has one.
            ),
            journal,
        )

    return factory


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
            # A delegate whose spec said nothing, a specialist the model invented
            # (which no runtime resolved and whose spec nobody wrote a step limit
            # into), or a name that resolves to nothing at all and is refused a
            # moment later. All three get the platform default, which is the same
            # ceiling a top-level run gets.
            return UsageLimits(request_limit=DEFAULT_MAX_STEPS)
        return UsageLimits(request_limit=delegate.max_steps)

    return limits
