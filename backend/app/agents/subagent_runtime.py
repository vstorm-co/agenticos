"""The seam between the runner, which may fetch, and the delegation capability,
which may not.

A capability never touches the database. Delegation needs the database more than
most: a delegate is a row, its pinned version is a row, its collections, skills
and secrets are rows, and every one of them has to be reached through
`resolve_access` before it is read. So the runner resolves the whole delegation
tree while it still has a session and an auth context, and hands the capability
this - closures it can call and data it can read, with no way to ask for more.

The same shape, and the same reason, as `WORKSPACE_BACKEND_RESOURCE`: opening a
workspace reads and writes rows, so the runner opens it and the capability
receives what was opened.

Why the resolution is a *tree* rather than a list: a delegate may itself
delegate, up to `max_depth`. The runner is the only place that can walk that
safely - it knows the pins, it can refuse a cycle, and it can stop at the depth
the config allows. A capability walking it at run time would need a session per
delegation, on a shared `AsyncSession` that is not concurrency-safe.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.tools import DeferredToolResults

from app.agents.spec import DelegationMode

if TYPE_CHECKING:
    from app.agents.capabilities.budget import SpendLedger

SUBAGENT_RUNTIME_RESOURCE = "subagent_runtime"
"""Where the runner leaves the resolved delegation tree for this run.

Absent when an agent's spec does not bind the delegation capability, and absent
in a preview or a unit test that resolved nothing - in which case the capability
offers no delegates rather than raising, exactly as the workspace capability
falls back to an in-memory backend.
"""

DelegationStatus = Literal["completed", "failed", "cancelled"]


@dataclass(frozen=True)
class ResolvedSubagent:
    """One delegate or specialist, resolved and ready to run.

    `build` is a closure rather than an already-built agent because a delegate
    the model never calls should cost nothing: constructing one resolves a model,
    builds its capabilities and instruments it. Called at most once per run and
    cached by the capability - a pydantic-ai `Agent` is stateless across runs, so
    one instance serves a fan-out of ten calls to the same delegate.

    `agent_id` and `agent_version_id` are set for a published delegate and `None`
    for an inline specialist. That is the only place in the runtime where the
    difference matters, and it decides exactly one thing: whether this delegation
    gets an `AgentRun` row of its own. A specialist has no agent to attribute one
    to, so its cost is the parent's and the tool call in the transcript is the
    record.
    """

    name: str
    description: str
    build: Callable[[], PydanticAgent[Any, Any]]
    max_steps: int | None = None
    preferred_mode: DelegationMode | None = None
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    collection_names: tuple[str, ...] = ()
    """The knowledge collections *this* delegate may search.

    Carried as data beside the agent, rather than left on the deps the build
    produced, because the library decides what deps a delegation runs with: it
    calls `ctx.deps.clone_for_subagent(...)` on the **parent's** deps and hands
    the result to the child's run, so the `AgentDeps` our factory built for the
    child - collections and all - is discarded before its first request.

    That is a silent failure rather than a loud one, which is why it is worth this
    field. A delegate configured with a collection would resolve it, be handed
    deps without it, and answer "No active knowledge bases selected" to every
    search - a specialist that looks correctly configured, publishes cleanly, and
    is simply unable to read the thing it exists to read.

    The clone deliberately does not inherit the parent's collections (see
    `AgentDeps.clone_for_subagent`), so the two halves are complementary: the
    parent's are dropped, and these are put back. Applied by the delegation
    capability to the cloned deps, which is the only place that holds both.
    """


class DynamicSpecialistBuilder(Protocol):
    """Builds the specialist a model asked for, on a model this deployment holds.

    A protocol rather than a `Callable` alias because every argument is
    keyword-only and named: the three of them are a name, a system prompt and a
    model, all of which arrive as free text from a model's tool call, and
    positional order is not something to get wrong there.
    """

    def __call__(self, *, name: str, instructions: str, model: str) -> PydanticAgent[Any, Any]: ...


@dataclass(frozen=True)
class DynamicSpecialists:
    """Permission for a run's model to invent a specialist, and the means to build one.

    `None` on the runtime - the default - is what the delegation capability reads
    as "this agent may not", and it is then not offered `create_agent` or
    `delegate` at all. The runner sets this from `SubagentsConfig.allow_dynamic`,
    so the setting has exactly one reader and the capability cannot disagree with
    it.

    Why the runner and not the capability: a specialist a model invents is still
    an agent of this platform's, which means a model profile out of the
    organization's own catalog, its credential out of the vault, the run's
    approval channel and - the whole reason this phase exists - the run's shared
    budget guard. All four are database facts, and the capability holds no
    session. Left to the library, a dynamic specialist is built from
    `SubAgentCapability.default_model`: an agent on a provider the organization
    may hold no key for, priced by nothing and metered by nothing, which is an
    unmetered model request and the one thing this platform exists to refuse.

    Nothing here is persisted, and that is deliberate rather than unfinished.
    Keeping a specialist means publishing an agent, which is a person's action; one
    invented at run time is held in a registry the delegation library creates per
    built agent, so it lasts as long as that agent does and no longer.

    Which is *not* the same as "for the run", and the difference is worth stating
    because it is visible to a model: a run that parks on an approval is built again
    when it is continued, so a specialist created before the park is gone after it,
    and the transcript still carries the library's "created successfully". The model
    is told so in `create_agent`'s description, and `task` answers "unknown
    subagent" rather than doing something surprising - see agenticos#175.
    """

    build: DynamicSpecialistBuilder
    allowed_models: tuple[str, ...]
    """The labels of the organization's model profiles, as the model may name them.

    Derived from the profiles rather than accepted as free text, because a model
    naming `openai:gpt-4.1` in an organization that holds no OpenAI key writes a
    run that dies at its first request with a provider error - and the model that
    named it had no way to know. A label is what the Builder shows an author and
    what `uq_credential_profile_label` makes unique inside an organization, so it
    is the one handle a model can be given and a profile can be found by.

    Never empty while a run is delegating: the delegating agent's own profile
    resolved before this was assembled, so the catalog holds at least it. That is
    what makes a second publish rule for `allow_dynamic` unnecessary - publish
    validation already refuses a spec with no `model_profile_id`, and one whose
    profile is gone, so "an organization with no usable model" is not a state a
    run reaches.
    """


@dataclass(frozen=True)
class DelegationOutcome:
    """What one delegation cost and how it ended.

    Reported to the runner so it can write the child's run row. The numbers are
    this delegation's **share of the run's one shared ledger**: the requests its
    own agent made, and only those. There is still one ledger per run - a delegate
    records into the parent's by construction, which is what makes the parent's
    budget see a delegate's spend before the next request - but every entry in it
    carries the delegation that booked it, so the share is filtered out of the
    ledger rather than inferred from it. See
    :func:`app.agents.capabilities.budget.booked_to`.

    Exact in both modes and at every depth, which the arithmetic that came before
    it was not (agenticos#180). It measured the *growth* of the shared total across
    the delegation, and that number is only the delegation's while nothing else in
    the run spends inside the window - which a background delegation violates by
    definition, and which `sync` does not guarantee either, because pydantic-ai
    executes several tool calls from one model response concurrently. A mid-tree
    delegate's window also contained what its own delegates spent, and their rows
    record that again, so `monthly_spend` for a delegate that delegates counted its
    grandchildren.

    What is still true of the delta reasoning: **the parent's row is the authority
    for what a run cost.** Its `cost_usd` is the whole ledger, delegates included,
    which is what the organization is billed for; the child rows divide the same
    money by agent. `agent_run_repo.sum_cost_since` is where that division lives
    and `docs/governance.md` explains it.

    `cost_is_partial` is per share rather than per run for the same reason: a
    parent on a model `genai-prices` does not know makes the *parent's* total a
    floor, and says nothing about a delegate that ran on a priced one.

    **A delegation that parked is more than one share.** Its turns ran in different
    processes against different ledgers, so what is reported here is every segment
    added together - this turn's share plus :class:`DelegationSpend`, which the park
    kept, `cost_is_partial` included. One `AgentRun` row is written, once, by the
    turn that finishes the delegation.

    `started_at` and `ended_at` are the delegation's *own* span, read off the task
    handle the library stamps when the delegate starts and when it reaches a
    terminal status. They are not the moment the delegation was settled, which for
    a background one is arbitrarily later - the poll that collected it - and gave
    every background row a duration of zero placed at the wrong time
    (agenticos#191). `None` when the handle carried no start: a delegation the
    library refused before it began a task never ran, and the recorder falls back
    rather than write a null into a non-null column.
    """

    subagent: str
    task_id: str
    status: DelegationStatus
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    cost_is_partial: bool = False
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    error: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


DelegationRecorder = Callable[[DelegationOutcome], Awaitable[UUID | None]]
"""Records a finished delegation, answering with the child's run id if it wrote one.

`None` when the delegation was an inline specialist, or when there is no database
to write to. The id travels back so a surface can link a delegation panel to the
run history entry it produced.
"""


@dataclass(frozen=True)
class DelegationSpend:
    """What one delegation has spent across every turn it has run in.

    A delegate that stops for a person has usually spent most of its money
    already - it did the work and then asked permission to act on the result. The
    run that continues it is a different process, whose ledger starts empty, so
    what the delegate spent before the park is recoverable only if the park keeps
    it. Kept on :attr:`ParkedDelegation.spent`, handed back through
    :attr:`DelegationStash.spent`, and added to whatever the continuing turn
    measures - which is why the field is a *running total* rather than one turn's
    reading, and why a delegation that parked twice adds three segments together.

    Without it the child `AgentRun` row, the delegate's monthly total and any
    budget alert on that delegate all recorded only the spend *after* the last
    resume, and did it silently: the money was still in the parent's row, so
    nothing anywhere failed to add up.

    Plain scalars, for the reason everything on :class:`ParkedDelegation` is plain
    data: this is written into `agent_runs.paused_state` as JSON and read back in
    another process, possibly the next day.
    """

    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    has_unpriced_models: bool = False
    """Whether any segment of this delegation made a request `genai-prices` could not
    price - the total is then a floor, not a cost.

    Carried across the park for the same reason the money is, and OR'd rather than
    replaced when the segments are added. `cost_is_partial` is read per share now
    rather than off the whole run, so a delegate that went unpriced *before* the
    approval and resumed onto a priced model would otherwise have its row claim an
    exact cost for money nobody priced - the one number on a delegated row nothing
    downstream can re-derive.
    """


@dataclass(frozen=True)
class ParkedDelegation:
    """A delegation whose delegate stopped for a person, kept so it can be continued.

    The reason this exists rather than the parent simply delegating again: the
    parent parks on its own `task` call, while the approval a person decides was
    raised by the *delegate's* gate against the delegate's tool call. Re-running
    the delegation would present the parent's `task` id to a granted approval that
    names something else, start the delegate's conversation from nothing, and let
    the model call a different tool the second time round - so what a reviewer
    approved would not be what executed. Nothing raises; the run just answers
    differently.

    Everything here is **plain data**, and that is a constraint rather than a
    preference. This outlives the tool call it was made in and is written into
    `agent_runs.paused_state`, while `request_approval` closes over a service
    holding the request's `AsyncSession` and `get_db_context()` closes when the
    turn ends. Messages and ids, never a live object.

    Attributes:
        tool_call_id: The `task` call in the **delegating** agent's transcript.
            What identifies this delegation on the replay: the same call is
            presented again, and that is when the delegate is continued instead of
            started.
        task_id: The library's id for the delegation, which the child's run row
            and the streamed frames both carry.
        parent_task_id: The delegation this one was made *inside*, or `None` when
            the run's own agent made it. It is what nests the frames without
            guessing, and it is read where the delegation opens rather than where
            it parks, because by then this level's own delegation is the current
            one.
        child_run_id: Pydantic AI's run id for the delegate's suspended run, for a
            trace that has to be joined to the one that continues it.
        messages: The delegate's conversation as of the stop, in Pydantic AI's
            message format. **Empty means the delegate's place could not be
            kept** - telemetry on the library's task handle is best-effort - and
            then the delegation is re-run from the start rather than continued.
            The `task` call is still answered on the replay either way, because a
            parked call left without a result makes the whole run unresumable.
        spent: What this delegation had cost by the moment it stopped, so the turn
            that continues it records the whole of it rather than the tail. Kept
            even when `messages` is empty: the two answer different questions -
            *how* to continue, which is best-effort, and *what it already cost*,
            which is known either way - and a delegation re-run from the start
            still spent that money once.
    """

    tool_call_id: str
    task_id: str
    parent_task_id: str | None
    subagent: str
    agent_id: UUID | None
    agent_version_id: UUID | None
    child_run_id: str | None
    messages: list[dict[str, Any]]
    spent: DelegationSpend


@dataclass(frozen=True)
class ResumedDelegation:
    """A parked delegate's place, and the verdicts it was waiting on.

    Handed back by the runner rather than assembled by the capability: which
    approval row decided what is a database question, and the capability holds no
    session.
    """

    messages: list[ModelMessage]
    results: DeferredToolResults
    """The decisions for the calls *this* delegate parked, and only those.

    Pydantic AI refuses a resume whose results name a call the replayed response
    does not contain, so one run's worth of verdicts cannot be handed to every
    level - each level gets its own, and a nested delegate's are reached the same
    way one level further in.
    """


@dataclass
class DelegationStash:
    """Where a run's parked delegations are left, and where a resume finds them.

    One object per run, shared by every level of the tree, because a delegation
    three levels down parks the run somebody started and is continued from that
    run's stored state. Each level's journal writes into `parked` and reads out of
    `resuming`; the runner does the opposite, which is what keeps the two
    directions from being one ambiguous field.

    The default is empty on both sides, which is a preview, a unit test, or a run
    that never delegated - and in each case nothing parks and nothing resumes.
    """

    parked: list[ParkedDelegation] = field(default_factory=list)
    """Filled during the run, read once when it ends. Appended to under the GIL
    from a coroutine that never awaits, so overlapping delegations cannot
    interleave inside it - the same property the delegation recorder's queue
    relies on."""

    resuming: dict[str, ResumedDelegation] = field(default_factory=dict)
    """Keyed by the `task` call the delegation was made from, which is the only
    thing the toolset knows about a delegation before it starts one."""

    spent: dict[str, DelegationSpend] = field(default_factory=dict)
    """What each delegation being continued had already cost, on the same key.

    A second mapping rather than a field on :class:`ResumedDelegation`, because the
    two are not available together. A place to continue from exists only when the
    library kept the delegate's conversation; what the delegation already spent is
    known whatever happened to that conversation, and a delegation re-run from the
    start has still spent it. Folding the weaker guarantee onto the stronger fact
    would drop the pre-park cost of exactly the delegations whose place was lost.
    """

    def already_spent(self, tool_call_id: str | None) -> DelegationSpend:
        """What the delegation this `task` call opens has spent in earlier turns.

        Zero for a delegation this run is starting rather than continuing, which is
        every delegation on a run that was never parked - and zero for one made
        without a tool call to name it, which is a caller driving the toolset
        directly rather than a model calling `task`.

        Not consumed on read, for the reason `resuming` is not: the key is the
        `task` call, so a second delegation to the same delegate later in the run
        has a different one and starts from zero, while the library's own retry of
        *this* delegation is the same delegation and carries the same total.
        """
        if tool_call_id is None:
            return DelegationSpend()
        return self.spent.get(tool_call_id, DelegationSpend())


@dataclass
class SubagentRuntime:
    """Everything a run needs in order to delegate.

    Mutable, and one field is filled *after* the agent is built: `ledger`. The
    ledger does not exist until `build_agent` has constructed the budget guard,
    and this object has to be passed *into* `build_agent` as a resource, so there
    is no ordering in which the constructor could take it. The runner assigns it
    immediately after the build and before the run starts - the same shape, and
    the same reason, as `prepared.deps.ask_user`, which only a live surface can
    supply and which is therefore assigned after `prepare`.

    A `None` ledger is not an error: it means nothing is measuring, so a
    delegation reports zero cost and the runner writes no child row. That is the
    honest answer in a preview or a unit test, and it keeps the capability free
    of a code path that only runs in production.
    """

    subagents: tuple[ResolvedSubagent, ...] = ()
    record: DelegationRecorder | None = None
    depth_remaining: int = 0
    depth: int = 0
    """How many delegations deep the agent holding this runtime already is.

    Told rather than computed. It used to be derived as `max_depth -
    depth_remaining`, which is only correct while every agent in the tree
    configures the same `max_depth`: those two numbers come from *different*
    specs - the ceiling is the delegating agent's own setting, the remainder is
    what the tree has left - so a delegate that set a different one reported the
    wrong depth and a surface nested its panel under the wrong parent.
    """

    dynamic: DynamicSpecialists | None = None
    """Whether the agent holding this runtime may invent specialists, and how.

    `None` - the default - is an agent that may only address the delegates it was
    given, which is every agent unless its author switched `allow_dynamic` on.
    Resolved by the runner for the same reason `ResolvedSubagent` is: building one
    needs a model profile out of the database and the run's budget guard, and a
    capability may reach neither.
    """

    stash: DelegationStash = field(default_factory=DelegationStash, repr=False)
    """The run's parked delegations, shared by every level of the tree.

    A default rather than a required argument for the same reason `record` and
    `ledger` are optional: a preview or a unit test resolves a runtime with
    nothing behind it, and a stash of its own is the honest answer there. The
    runner passes one object to every level, which is what lets a resume load a
    grandchild's place and have the grandchild's own journal find it.
    """

    ledger: SpendLedger | None = field(default=None, repr=False)

    def named(self, name: str) -> ResolvedSubagent | None:
        """The delegate the model addressed, or `None` if it invented a name."""
        return next((entry for entry in self.subagents if entry.name == name), None)
