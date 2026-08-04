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
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic_ai import Agent as PydanticAgent

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


@dataclass(frozen=True)
class DelegationOutcome:
    """What one delegation cost and how it ended.

    Reported to the runner so it can write the child's run row. The numbers are
    a *delta* of the run's shared ledger, measured across the delegation, rather
    than a ledger of the child's own: the child records into the parent's ledger
    by construction - which is what makes the parent's budget see a delegate's
    spend before the next request - so the only honest way to say what one
    delegation cost is what the total grew by while it ran.

    The measurement is exact only while one delegation runs at a time, and
    **`sync` mode does not guarantee that** - a correction worth stating plainly,
    because the opposite is the obvious assumption. A `sync` delegation holds its
    own tool call, but pydantic-ai executes several tool calls from one model
    response concurrently, so a parent whose model emits two `task` calls in one
    step overlaps two delegations without either of them being asynchronous. Two
    overlapping deltas then each contain some of the other's spend.

    The approximation is therefore stated rather than hidden: the parent's run row
    is the authority for a run's cost, and a child row's share is indicative -
    `docs/governance.md` says so. Splitting it exactly would need a ledger per
    agent, which is precisely the design that stops the parent's cap from binding
    at all.
    """

    subagent: str
    task_id: str
    status: DelegationStatus
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    error: str | None = None


DelegationRecorder = Callable[[DelegationOutcome], Awaitable[UUID | None]]
"""Records a finished delegation, answering with the child's run id if it wrote one.

`None` when the delegation was an inline specialist, or when there is no database
to write to. The id travels back so a surface can link a delegation panel to the
run history entry it produced.
"""


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
    ledger: SpendLedger | None = field(default=None, repr=False)

    def named(self, name: str) -> ResolvedSubagent | None:
        """The delegate the model addressed, or `None` if it invented a name."""
        return next((entry for entry in self.subagents if entry.name == name), None)
