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
agent, with nothing in this repository saying so. It is also where a tool the
library adds unconditionally can be withheld from the model without being taken off
the list a person approves against - see :data:`UNREACHABLE_TOOLS`.

What is deliberately *not* wrapped: the toolset's own task management, the
cancellation of background *tasks* in `wrap_run`, and the retry behaviour. Those
are the library's job and it does them; re-implementing them here would be a second
copy to keep in step. `Delegation.wrap_run` adds to that cancellation rather than
replacing it - what the library's own sweep cannot reach is a `sync` delegation,
which has a handle and no task - and it says what the sweep does not guarantee.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import UsageLimits
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.capabilities import WrapperCapability, WrapRunHandler
from pydantic_ai.tools import RunContext, ToolDefinition
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
from subagents_pydantic_ai.registry import DynamicAgentRegistry

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities.subagents._journal import DelegationJournal, enclosing_tool_call_id
from app.agents.capabilities.subagents._toolset import DelegatingToolset
from app.agents.deps import AgentDeps
from app.agents.factory import DEFAULT_MAX_STEPS
from app.agents.spec import DelegationMode
from app.agents.subagent_runtime import (
    DynamicSpecialists,
    RegisteredSpecialist,
    ResolvedSubagent,
    ResumedDelegation,
    SubagentRuntime,
)

logger = logging.getLogger(__name__)

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
    # rather than acting on anything outside it - and it is declared here and
    # never offered to a model, for the reason in `UNREACHABLE_TOOLS`.
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

Declared rather than derived, and all ten rather than the seven a non-dynamic
configuration offers, because a tool absent from this list cannot be gated by the
approval policy or renamed by a binding - and the dangerous half of that is
silent. Which of the ten a given agent's model is actually offered is decided in
three places: `create_agent` and `delegate` by whether the runner resolved a
`DynamicSpecialists`, `answer_subagent` by :data:`UNREACHABLE_TOOLS`, and the six
background-lifecycle tools by whether any delegation this run could make might run
in the background - :data:`BACKGROUND_LIFECYCLE_TOOLS`.

Eight of the descriptions are **imported, not rewritten**. A tool's description is
the strongest prompt in the product, and `TASK_TOOL_DESCRIPTION` is two hundred
lines of hard-won guidance about when delegating is worth it and when it is not;
replacing it with a one-line label for a Builder form would be a downgrade
wearing consistency as an excuse. The two dynamic ones are written here because
the library's describe a configuration this platform does not offer - see
:data:`DELEGATE_DESCRIPTION`. What is declared here is what the model reads,
exactly - see the `descriptions` argument in `build_delegation`.
"""

UNREACHABLE_TOOLS: frozenset[str] = frozenset({"answer_subagent"})
"""Declared for the Builder and the approval policy, and offered to no model.

`answer_subagent` replies to a question a *background* delegate parked on, and no
delegate here parks on one. A `sync` delegate now can ask - agenticos#184, when its
author set `allow_questions` and its mode is sync - but a sync question is answered
by `ctx.deps.ask_user`, a person holding the parent's tool call, and never through
this tool: the library only routes a question here for an `async` delegation, which
parks in `TaskStatus.WAITING_FOR_ANSWER` awaiting the parent's own model. And an
`async` delegate cannot ask: :func:`_config_for` grants `can_ask_questions` only for
a sync-configured one, and `TaskStatus.WAITING_FOR_ANSWER` is therefore never
reached. So this tool still has nothing it could ever answer.

*Filtered rather than left out of* :data:`DELEGATION_TOOLS`, because those are two
different failures and only one of them is loud. A tool the model is offered and
cannot use costs a description in every turn's context - the strongest prompt
surface in this product - and invites a call whose only possible answer is "that
delegation is not waiting for an answer". A tool absent from the declaration cannot
be gated by the approval policy or renamed by a binding, and *that* half is silent.
So it stays declared and stops being offered, which is the same shape the two
dynamic entry points had while they were declared and unwired.

*Opening this tool is the background half of the same question, and it is the
harder half.* Which channel answers is decided by the mode: agenticos#184 opened
the sync half above, answered by a person and never here. This tool becomes
reachable only for a *background* delegation, whose question the parent's own model
answers through a future the library's task manager holds - and the delegate blocks
for up to `ask_timeout_seconds` holding a fan-out slot while nothing obliges the
parent to look, and `wrap_run` cancels every background task when the turn ends:
money spent on a question nobody was asked. So the set is emptied only when that
half is answered too, which is why the two were one issue with two halves.
"""


BACKGROUND_LIFECYCLE_TOOLS: frozenset[str] = frozenset(
    {
        "check_task",
        "wait_tasks",
        "list_active_tasks",
        "send_message_to_subagent",
        "soft_cancel_task",
        "hard_cancel_task",
    }
)
"""The six tools that only make sense once a delegation runs in the background.

Every one of them takes, or reports on, a task id: `check_task` and `wait_tasks`
collect a background delegation's result, `list_active_tasks` lists what is still
running, and the three that act - `send_message_to_subagent` and the two cancels -
steer or stop one mid-run. A `sync` delegation hands the model none of that: the
library returns the delegate's answer and a `chat_trace_id` and nothing else, so
there is no id to pass to the five that take one, and `list_active_tasks` would
answer about a delegation that finished before the call returned.

So an agent that can make *no* background delegation is offered none of these -
:func:`_can_delegate_in_background` is the predicate, and `sync` being the default
mode is what makes that the common configuration rather than a corner. `task` is
never in this set: a sync agent still delegates, it just does not manage tasks.

Filtered rather than left out of :data:`DELEGATION_TOOLS`, for the same reason
`answer_subagent` is - see :data:`UNREACHABLE_TOOLS`. A tool absent from the
declaration can be neither gated by the approval policy nor renamed by a binding,
and that half is silent; withheld from the offered set, it stops costing a
description in every turn's context while staying declarable. The difference from
`answer_subagent` is that this set is withheld *per run*: the same agent offers all
six under `async`, `auto`, or a delegate that prefers either, so the decision
belongs in :meth:`Delegation.get_toolset` where the run's configuration is, not in
a module-level constant.
"""


def _can_delegate_in_background(journal: DelegationJournal) -> bool:
    """Whether any delegation this run could make might run in the background.

    The narrowing that :data:`BACKGROUND_LIFECYCLE_TOOLS` turns on happens only when
    this answers `False`, so the predicate is written to err toward `True`: getting
    it wrong in the narrowing direction removes a tool an agent needs mid-turn, which
    is a worse failure than offering one it will not use.

    Three ways a background delegation is reachable, and the run configuration fixes
    all three before the first request:

    - **The configured mode is not `sync`.** `async` backgrounds every delegation and
      `auto` backgrounds the ones the model describes as long-running - and `auto` is
      resolved per delegation from what the model says about the task, so an `auto`
      agent can go either way and keeps all six regardless.
    - **The agent may invent specialists.** `create_agent` and `delegate` produce
      delegations resolved per call rather than from a set that exists now, so the
      widest configuration withholds nothing there rather than reasoning about work
      that has not been asked for yet.
    - **A pinned delegate prefers `async` or `auto`.** `DelegationJournal._mode_for`
      resolves `delegate.preferred_mode or self.mode`, so one delegate overriding a
      `sync` agent is enough to make a task id reachable for that delegation.
    """
    if journal.mode != "sync":
        return True
    if journal.runtime.dynamic is not None:
        return True
    return any(
        delegate.preferred_mode in ("async", "auto") for delegate in journal.runtime.subagents
    )


def _hidden_tools(journal: DelegationJournal) -> frozenset[str]:
    """Every tool this run declares and withholds from its model.

    Two reasons a declared tool is withheld, and they compose. `answer_subagent` is
    unreachable under *every* configuration (:data:`UNREACHABLE_TOOLS`); the six
    background-lifecycle tools are unreachable under *this* one when it can make no
    background delegation (:data:`BACKGROUND_LIFECYCLE_TOOLS`).
    """
    if _can_delegate_in_background(journal):
        return UNREACHABLE_TOOLS
    return UNREACHABLE_TOOLS | BACKGROUND_LIFECYCLE_TOOLS


def _offered(hidden: frozenset[str]) -> Callable[[RunContext[AgentDeps], ToolDefinition], bool]:
    """A filter that shows the model every tool but the ones this run withholds.

    Reads the tool's name off the library's own toolset, which is where the stable
    id is still the name: a binding's rename wraps the *capability*, outside this, so
    a withheld tool cannot be smuggled back into the offered set under a new name.
    """

    def is_offered(_ctx: RunContext[AgentDeps], tool: ToolDefinition) -> bool:
        return tool.name not in hidden

    return is_offered


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

The *configured* mode, which is not the mode of every delegation - see
:data:`_DELEGATE_MODE_NOTE`.
"""

_DELEGATE_MODE_NOTE: dict[DelegationMode, str] = {
    "sync": "this one blocks until it answers",
    "async": (
        "this one runs in the background: `task` answers with a task id, and "
        "`check_task` or `wait_tasks` collects the result"
    ),
    "auto": (
        "this one blocks for simple work and runs in the background for longer "
        "work, collected with `check_task` or `wait_tasks`"
    ),
}
"""How a delegate that overrides the agent's mode is explained, beside its name.

The mode is per *delegation*, not per run: `_mode_for` prefers
`ResolvedSubagent.preferred_mode`, which is exactly what that field is for. So an
agent configured `sync` with one delegate pinned `async` used to be told "each
delegation blocks until the specialist answers" and then handed a task id for that
delegate - the instruction and the behaviour disagreeing, silently, on the one
delegation the author had singled out. The ceiling note still states the
configured mode, because it is what every other delegation uses, including a
specialist the model invents and a name it made up.
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

        Also minus the ones this run cannot reach. The library adds every tool to
        its toolset unconditionally, so filtering the offered set is the only place
        those decisions can be made: `answer_subagent` under every configuration
        (:data:`UNREACHABLE_TOOLS`), and the six background-lifecycle tools under a
        `sync`-only one that can make no background delegation
        (:data:`BACKGROUND_LIFECYCLE_TOOLS`). The withheld set is read from the
        journal here rather than a module constant because the second half of it is
        a fact about *this run's* mode and delegates - see :func:`_hidden_tools`.

        Memoised because the wrapper carries no state of its own but the journal
        it points at does, and because `BuiltAgent.capabilities` is introspected -
        two wrappers over one toolset would answer the same question twice.
        """
        if self._delegating is None:
            # `get_toolset` is optional on the capability protocol and
            # `SubAgentCapability` always returns one: it constructs its toolset
            # in `__post_init__` and holds it for the life of the instance.
            wrapped = cast(AbstractToolset[AgentDeps], super().get_toolset())
            self._delegating = DelegatingToolset(wrapped=wrapped, journal=self.journal).filtered(
                _offered(_hidden_tools(self.journal))
            )
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

        A delegate whose `preferred_mode` overrides the agent's carries that here,
        beside its own name, because that is where the model reads about it and
        because :meth:`_ceiling_note` can only state one mode - see
        :data:`_DELEGATE_MODE_NOTE`.
        """
        delegates = self.journal.runtime.subagents
        if not delegates:
            return ""
        listed = "\n".join(
            f"- **{entry.name}**: {entry.description}{self._override_note(entry)}"
            for entry in delegates
        )
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

    def _override_note(self, delegate: ResolvedSubagent) -> str:
        """How this delegate runs, when that is not how the agent's other ones do.

        Nothing for a delegate that pinned no mode of its own, and nothing for one
        that pinned the mode the agent is already configured with - a parenthesis
        repeating the sentence two lines below it is context paid for on every turn
        for no information.
        """
        preferred = delegate.preferred_mode
        if preferred is None or preferred == self.journal.mode:
            return ""
        return f" ({_DELEGATE_MODE_NOTE[preferred]})"

    def _ceiling_note(self) -> str:
        """The mode every other delegation uses, and the fan-out that bounds them all.

        "Every other" because a delegate may pin its own, and one sentence cannot
        state two modes; those are marked in the list above, and this says so rather
        than contradicting them. The mode named here is still the one the model
        needs: it is what a specialist it invents and a name it made up will run
        with.
        """
        excepted = (
            " A specialist marked otherwise above runs the way its own note says."
            if any(self._override_note(entry) for entry in self.journal.runtime.subagents)
            else ""
        )
        return (
            f"{_MODE_NOTE[self.journal.mode]}{excepted} At most {self.journal.max_fanout} "
            "delegations run at once; asking for more is refused until one finishes."
        )

    async def wrap_run(
        self, ctx: RunContext[AgentDeps], *, handler: WrapRunHandler
    ) -> AgentRunResult[Any]:
        """Run the agent, then account for whatever was still delegating.

        The last moment a delegation can be recorded, and the moment that matters:
        a run that launched a background delegation and answered without collecting
        it would otherwise leave that delegation's spend attributed to nothing at
        all. Two steps, in this order:

        *Everything still in flight is finished as cancelled* -
        :meth:`DelegationJournal.cancel_in_flight`. This is not a formality the
        library has already performed. Its own `wrap_run`, which this defers to,
        cancels every background task and then **waits at most
        `cancel_grace_seconds`**, after which it logs and leaves the task running;
        and it never touches a *sync* delegation at all, because that one has a
        handle and no task. A `stop` mid-delegation on the default mode therefore
        left the handle `RUNNING` and the delegation unrecorded until this ran
        first.

        *Then whatever those cancellations produced is settled and reported.*

        What is **not** guaranteed is that every delegation has *stopped* by the
        time this returns: the grace period expires, it does not conclude. A
        delegate whose cleanup outlasts it is still executing while the row is
        written - writing into a workspace `finish` closed, appending to a ledger
        whose `cost_usd` was already persisted, and spending against a budget
        nothing will check again. Nothing here can stop it, so
        `cancel_in_flight` names it in a warning instead, and this docstring says
        so rather than claiming the terminal status is a certainty.

        *And the kept specialists are snapshotted*, so a run that parks on an
        approval carries them into `PausedRunState` and finds them again on the
        replay - the library's registry is per built agent and a resume builds a
        fresh one, which is what lost a specialist across a park until now
        (agenticos#175, agenticos#254). This runs at every level: a nested delegate's
        wrap_run executes inside its enclosing `delegating` block, so its snapshot is
        keyed by that block's `task` call and rides on its own frame. A no-op unless
        this level may invent one; see `DelegationJournal.record_created_specialists`.
        """
        try:
            return await super().wrap_run(ctx, handler=handler)
        finally:
            self.journal.cancel_in_flight()
            await self.journal.settle_background(ctx.deps.subagent_events)
            self.journal.record_created_specialists()


def build_delegation(
    *,
    runtime: SubagentRuntime,
    mode: DelegationMode,
    allow_questions: bool,
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
        allow_questions: Whether a delegate whose configured mode is sync may ask
            the person waiting on this agent a question. The author's decision; off
            for a specialist the model invents, and inert for a background or `auto`
            delegation.
        max_fanout: How many delegations may run at once.
        depth: How far inside the run's own agent these delegations are, which is
            what a surface needs to nest their panels.
        max_result_chars: How much of a finished delegation's answer the
            `wait_tasks` listing carries before pointing at `check_task`.
    """
    journal = DelegationJournal(
        runtime=runtime,
        mode=mode,
        allow_questions=allow_questions,
        max_fanout=max_fanout,
        depth=depth,
    )
    dynamic = runtime.dynamic
    # The registry `create_agent` writes into, owned here rather than left to the
    # library so this platform can read it back when the run ends and seed it when a
    # run resumes. A resume fills `stash.to_register`, keyed by the `task` call each
    # level was delegated from: `None` for the run's own agent, the enclosing call for
    # a nested delegate - which is the current delegation here, because a nested level
    # is built from inside its enclosing `delegating` block. Each level seeds only its
    # own key, so a nested delegate rebuilds its own specialists rather than the run's
    # own agent's (agenticos#254). `None` when the agent may not invent one, and then
    # the library needs no registry either.
    key = None if depth == 0 else enclosing_tool_call_id()
    registry = (
        None
        if dynamic is None
        else _seeded_registry(dynamic, journal, runtime.stash.specialists_to_register(key))
    )
    capability = SubAgentCapability(
        subagents=[_config_for(delegate, journal) for delegate in runtime.subagents],
        # Passed because the library's own default is `True`, not because anything
        # here can ask for it: this is a fact about somebody else's default, and
        # the one place it is stated. The delegate it would add is the library's
        # unspecialised one - resolved from no profile of this organization's,
        # unsealed from no credential in its vault, wrapped by no budget guard -
        # not one this platform can account for, so there is no setting for it and
        # never was one an author could reach. subagents-pydantic-ai 0.2.18 fixed
        # the upstream half of this (agenticos#174): with no `default_model` and no
        # `default_agent_factory` the library now refuses to build the delegate
        # rather than compiling it from a model of its own choosing, so leaving
        # this `True` would raise here instead of quietly running a tenant's work
        # on a deployment-wide credential. Either way it is not offered; an author
        # who wants a catch-all writes an inline specialist, whose instructions
        # somebody read.
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
        # only; a `delegate` call registers nothing. Read only when no `registry` is
        # passed: the one above carries its own ceiling, set to the same constant.
        max_agents=0 if dynamic is None else MAX_DYNAMIC_SPECIALISTS,
        # Owned here rather than created inside the library, so its registrations
        # can be snapshotted when the run parks and re-seeded when it resumes.
        registry=registry,
        # `default_model` is left unset - which since 0.2.18 is the library's own
        # default too - because this platform has no default model anywhere: a
        # specialist that names none is refused in `DelegatingToolset._refuse_dynamic`
        # before it reaches the library, and the general-purpose delegate that would
        # otherwise be built from a default is switched off above. The field is
        # unread here; unset, the library now refuses a modelless dynamic call of its
        # own accord too, only later and less specifically than the refusal above.
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
    # The registry `create_agent` writes into, so `record_created_specialists` can
    # snapshot it when the run ends. `None` for an agent that may not invent one.
    journal.registry = registry
    return Delegation(wrapped=capability, journal=journal)


def _seeded_registry(
    dynamic: DynamicSpecialists,
    journal: DelegationJournal,
    specialists: Sequence[RegisteredSpecialist],
) -> DynamicAgentRegistry:
    """The library registry `create_agent` writes into, with a resume's kept ones in it.

    Empty on a fresh run - `specialists` is empty unless a resume filled the stash -
    and re-populated on a resume, so a specialist kept before an approval park is
    reachable through `task` after it (agenticos#175). Each one is registered the way
    `create_agent` would have: a `_LazyAgent` whose build goes through
    `DynamicSpecialists.build`, the same door an inline specialist and a pinned
    delegate come through, so it reaches `build_agent` with the run's shared budget
    guard and meters against the run's ledger like every other delegation.

    Built *lazily*, which is the one place a re-registration departs from
    :func:`_specialist_factory`: the factory builds at once, and the run's budget
    guard is a product of `build_agent` that the runner assigns *after* this
    capability is built - so a seeded specialist built here would be handed no guard
    and meter nothing, the one property agenticos#175 was careful not to break. The
    build is deferred to the first `task`, by when the guard is in place, exactly as
    a resolved delegate's is.

    A model this deployment no longer holds is skipped rather than raised: a profile
    can be deleted between the park and the resume, and one gone specialist must not
    fail the whole continuation - the model reads "unknown subagent" for that one
    name and can create it again, which is the pre-fix behaviour for it alone.
    """
    registry = DynamicAgentRegistry(max_agents=MAX_DYNAMIC_SPECIALISTS)
    for specialist in specialists:
        if specialist.model not in dynamic.allowed_models:
            logger.warning(
                "dynamic_specialist_not_re_registered_model_gone",
                extra={"subagent": specialist.name, "model": specialist.model},
            )
            continue
        config = SubAgentConfig(
            name=specialist.name,
            description=specialist.description,
            instructions=specialist.instructions,
            model=specialist.model,
            # As `_autonomously` set it at creation: a specialist here never asks the
            # parent a question. See `_toolset._autonomously` and `UNREACHABLE_TOOLS`.
            can_ask_questions=False,
        )
        # `s=specialist` binds the loop variable into the closure, so every lazy
        # build resolves its own specialist rather than the last of the loop.
        agent = _LazyAgent(
            ResolvedSubagent(
                name=specialist.name,
                description=specialist.description,
                build=lambda s=specialist: dynamic.build(
                    name=s.name, instructions=s.instructions, model=s.model
                ),
            ),
            journal,
        )
        registry.register(config, agent)
    return registry


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

    `can_ask_questions` is set explicitly rather than left to the library's `True`
    default, and this is where the author's `allow_questions` reaches a delegate.
    The library injects `ask_parent` into a delegate whose agent this platform
    supplied - every one here - only when the config asks for it, so absent this
    line a delegate would inherit the default and every one of them would gain the
    tool. It is granted only for a delegate whose *configured* mode is sync: the
    library answers a sync question from `ctx.deps.ask_user`, the parent's own
    channel and the person already holding the parent's tool call, whereas a
    background one has handed back a task id with nobody left to answer and `auto`
    may become one. So the mode gates it as much as the flag does.
    """
    configured_mode = delegate.preferred_mode or journal.mode
    return SubAgentConfig(
        name=delegate.name,
        description=delegate.description,
        instructions="",
        can_ask_questions=journal.allow_questions and configured_mode == "sync",
        agent=_LazyAgent(delegate, journal),
    )


def _specialist_factory(dynamic: DynamicSpecialists, journal: DelegationJournal) -> AgentFactory:
    """How a specialist a model invented becomes an agent of this platform's.

    The whole point of the phase, and it is one line of substance: the library is
    given a factory, so it never builds a dynamic specialist itself. Left to its
    own devices it would build `Agent(default_model, system_prompt=...)` - an agent
    on a model string of its own choosing, with no credential from this
    organization's vault, no price attached to its requests and **no budget
    guard**; that was an unmetered model request on a provider the organization may
    hold no key for. Since 0.2.18, with `default_model` unset, it refuses to build
    one at all rather than pick a model - but a refusal is not a specialist either,
    and giving it the factory is why both entry points could move from declared and
    not offered to offered.

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
        # Both entry points that invent a specialist - `create_agent` and
        # `delegate` - build through this factory, so this is the one place that
        # sees every dynamic specialist's definition. Recorded here so the opening
        # frame of the delegation to it carries it, the only window a surface has to
        # offer promoting a specialist nothing else keeps.
        journal.record_dynamic_definition(
            name=config["name"],
            description=config["description"],
            instructions=config["instructions"],
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
