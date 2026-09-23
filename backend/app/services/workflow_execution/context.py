"""Execution context available to a node handler while the dispatcher calls it.

`app.workflows.contracts.definition.NodeHandler` is frozen by #1786 at
`(config, input) -> NodeResult`, and #1788 does not change it - a handler
that needs to know *which* run and node instance it is executing as (a later
issue's `agent.run` handler, to build an `ApprovalChannel` whose resume token
the dispatcher can find its way back to) reads it from here instead, the same
way `app.agents.capabilities.budget.booked_to`/`_active_ledger` already give a
tool call its ledger without a second parameter every other tool would have
to ignore.

Two directions, both scoped to one dispatch call by `dispatching_as`:

- **In** - `current()` is what a handler is executing *as*: which run, which
  node, which attempt, and the `AuthContext` to act with (built from
  `WorkflowRun.execution_principal_user_id`, never a request that no longer
  exists by the time a parked node wakes).
- **Out** - `report_waiting_agent_run` is how a handler that parks on
  `ApprovalGate` tells the dispatcher which `agent_runs` row `NodeRun.
  waiting_agent_run_id` must point at. `NodeResult.Waiting` carries no such
  field (56-shared-contracts.md fixes its shape), so there is no channel for
  this in the return value at all - it has to travel beside it.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from app.core.permissions import AuthContext


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Everything a node handler may need to know about where it is running."""

    organization_id: UUID
    workflow_run_id: UUID
    node_run_id: UUID
    node_instance_id: UUID
    attempt_no: int
    auth: AuthContext
    resumed_agent_run_id: UUID | None
    """The `agent_runs.id` this node previously parked on, when this attempt
    is a wake rather than a first try - `NodeRun.waiting_agent_run_id` as it
    stood when this attempt was dispatched. A handler that calls
    `AgentRunnerService` reads this to choose `resume` over `run`: calling
    `run` again on a wake would silently drop an approved call by re-sending
    the original prompt to a fresh agent."""


@dataclass(slots=True)
class _Outbox:
    """What a handler reports back, out of band, during one dispatch call."""

    waiting_agent_run_id: UUID | None = None


_current: ContextVar[DispatchContext | None] = ContextVar("workflow_dispatch_context", default=None)
_outbox: ContextVar[_Outbox | None] = ContextVar("workflow_dispatch_outbox", default=None)


class DispatchScope:
    """The context manager `dispatching_as` returns.

    A class rather than `@contextmanager` because the dispatcher needs to
    read `waiting_agent_run_id` *after* the block has run the handler but
    before the context variables are gone - a generator-based manager has
    nothing left to read from once it has resumed past its `yield`.
    """

    __slots__ = ("_context", "_context_token", "_outbox", "_outbox_token")

    def __init__(self, context: DispatchContext) -> None:
        self._context = context
        self._outbox = _Outbox()
        self._context_token: Token[DispatchContext | None] | None = None
        self._outbox_token: Token[_Outbox | None] | None = None

    def __enter__(self) -> DispatchScope:
        self._context_token = _current.set(self._context)
        self._outbox_token = _outbox.set(self._outbox)
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if self._context_token is not None:
            _current.reset(self._context_token)
        if self._outbox_token is not None:
            _outbox.reset(self._outbox_token)

    @property
    def waiting_agent_run_id(self) -> UUID | None:
        return self._outbox.waiting_agent_run_id


def dispatching_as(context: DispatchContext) -> DispatchScope:
    """Make `context` available to whatever a node handler calls, for its duration."""
    return DispatchScope(context)


def current() -> DispatchContext:
    """The context of the node handler currently running.

    Raises:
        RuntimeError: Called outside `dispatching_as` - a programming error,
            since only the dispatcher ever calls a node handler.
    """
    context = _current.get()
    if context is None:
        raise RuntimeError("No workflow dispatch context is active")
    return context


def report_waiting_agent_run(agent_run_id: UUID) -> None:
    """A handler that parks on `ApprovalGate` calls this before returning
    `Waiting(reason="approval", ...)`, so the dispatcher can link the
    `NodeRun` it is settling to the `agent_runs` row the wake-up needs to
    find. A no-op outside `dispatching_as` rather than a `RuntimeError`: a
    handler under test with no dispatcher around it should not have to stub
    this out to exercise its own approval path.
    """
    outbox = _outbox.get()
    if outbox is not None:
        outbox.waiting_agent_run_id = agent_run_id
