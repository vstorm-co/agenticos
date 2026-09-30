"""The dispatch tick: claim one outbox row, run one node attempt, advance the graph.

Three transactional phases around one that holds no transaction, each short,
so no database connection is ever held across a handler's own external call:

1. `claim` - the compare-and-swap that decides which worker, if any, owns
   this `NodeRun` right now. Its own transaction.
2. `begin_attempt` - loads the run, the graph and the node, resolves the
   node's config/input, and commits a `NodeAttempt` row `in_flight` *before*
   the handler is ever called. Its own transaction, and the row it writes is
   the one the reconciler needs to exist if the process dies in step 3.
3. The handler runs **outside any transaction** (`app.worker.tasks.
   workflow_tasks` is what actually calls it, between two `get_worker_db_context`
   blocks) - a long-running or hung external call must never hold a pooled
   connection idle. The worker renews the claim's lease meanwhile, each
   renewal a short transaction of its own (`renew_lease`).
4. `settle` - a third transaction: persists the attempt's terminal result,
   transitions the `NodeRun`, books the cost the handler reported, appends a
   `WorkflowEvent`, and - on `Completed` - advances the graph by creating the
   next `NodeRun`(s) and `DispatchOutbox` row(s), all in one commit; the flow
   submits those rows once it has. `DispatchOutbox` is a
   transactional outbox for exactly this reason: "the result is durable" and
   "the next step is scheduled" can never disagree.

Advancing is branch-aware (`_advance`): a node that branches names the port
it left by (`NodeDefinition.routes` - `logic.if`'s `true` or `false`), only
edges leaving that port are followed, and a node every one of whose incoming
edges is dead is recorded `skipped` without an attempt, which propagates the
skip down an untaken branch to the `logic.merge` that rejoins it. A node whose
policy routes its errors leaves by its `error` port when it fails for good, and
by its other ports only when it succeeds.

A `control.foreach` iterates its body one element at a time, each iteration in
its own scope path (`[..., {"loop_node_id", "index"}]`): the loop's handler
freezes the list into its first attempt, the dispatcher writes each iteration's
`loop.item` row already succeeded and advances from it, and the settle that ends
an iteration starts the next - or, after the last, collects every `loop.yield`
into the loop's output and advances the loop itself. Everything is decided under
the run's lock in the settle's own transaction, so a restart resumes at the
iteration that was next and never repeats one that ended.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, TypeGuard
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, RootModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    RetryGuarantee,
    WaitingReason,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import member as member_repo
from app.repositories import user as user_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_approval as workflow_approval_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution import budget, context, delivery, events
from app.services.workflow_execution.exceptions import (
    InvalidBindingError,
    NodeDefinitionMissingError,
    NodeHandlerMissingError,
    PrincipalRevokedError,
    WorkflowDispatchRefusedError,
    WorkflowGraphUnresolvableError,
)
from app.workflows import _registry
from app.workflows.contracts.definition import NodeDefinition, NodeHandler
from app.workflows.contracts.definition import RetryGuarantee as CallGuarantee
from app.workflows.contracts.io import (
    BindingSource,
    FileRef,
    LiteralValue,
    NodeOutputRef,
    TableIORef,
)
from app.workflows.contracts.policy import ERROR_PORT, RetryPolicy
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
    Waiting,
    WorkflowError,
)
from app.workflows.graph.model import NodeInstance, WorkflowGraph
from app.workflows.graph.validate import (
    FOREACH,
    LOOP_YIELD,
    derive_scopes,
    node_scope_map,
    owner_chain,
)
from app.workflows.nodes.control_foreach import (
    BODY_PORT,
    ForeachConfig,
    ForeachItemError,
    ForeachManifest,
    ForeachOutput,
)
from app.workflows.nodes.loop_item import LoopItemOutput

logger = logging.getLogger(__name__)

# The `NodeRun` statuses a claimed outbox row may still start an attempt for.
_DISPATCHABLE = frozenset(
    {NodeRunStatus.PENDING.value, NodeRunStatus.RUNNING.value, NodeRunStatus.WAITING.value}
)
# A node that will not run again and did not end the run: it succeeded, was
# skipped, or failed through its `error` port (or, in a loop, under `collect`).
_SETTLED = frozenset(
    {NodeRunStatus.SUCCEEDED.value, NodeRunStatus.SKIPPED.value, NodeRunStatus.FAILED.value}
)

ScopePath = list[dict[str, Any]]


def _loop_of(scope_path: ScopePath) -> UUID | None:
    """The loop whose iteration `scope_path` names - `None` at the top level."""
    return UUID(scope_path[-1]["loop_node_id"]) if scope_path else None


def _source_path(node_id: UUID, scope_path: ScopePath, node_scope: dict[UUID, UUID]) -> ScopePath:
    """Where a binding's source ran, read from inside `scope_path`.

    Publishing only lets a node bind to its own scope or an enclosing one, so the
    source's path is the reader's, cut to the source's depth.
    """
    return scope_path[: len(owner_chain(node_id, node_scope))]


@dataclass(frozen=True, slots=True)
class BegunAttempt:
    """Everything `settle` needs, carried across the handler call."""

    workflow_run_id: UUID
    node_run_id: UUID
    node_instance_id: UUID
    organization_id: UUID
    attempt_id: UUID
    attempt_no: int
    handler_config: BaseModel | None
    handler_input: BaseModel | None
    definition: NodeDefinition
    handler: NodeHandler
    dispatch_context: context.DispatchContext
    timeout_seconds: float | None
    retry_guarantee: CallGuarantee
    dispatch_token: UUID
    """The fencing token this attempt was dispatched under - `claim()`'s own
    `DispatchOutbox.claimed_by`, re-checked by `settle()` before it accepts
    this call's result. Carried across the handler call the same way the rest
    of this dataclass is, so a late settle can tell a reclaimed row from the
    one it actually still owns."""


@dataclass(frozen=True, slots=True)
class HandlerOutcome:
    """What one handler call produced: its result, and what it reported beside it."""

    result: NodeResult
    waiting_agent_run_id: UUID | None = None
    cost: Decimal = Decimal(0)
    cost_is_partial: bool = False
    run_output: dict[str, Any] | None = None


async def claim(
    db: AsyncSession, *, node_run_id: UUID, lease_seconds: float | None = None
) -> DispatchOutbox | None:
    """Phase 1: try to own this node's dispatch row.

    Returns `None` when there was nothing claimable - the row was already
    claimed by a live lease, already `done`/`cancelled`, or not yet
    `available_at`. None of those is an error: the caller (`workflow_tasks.
    workflow_dispatch_node_flow`) simply stops. The lease defaults to
    `WORKFLOW_DISPATCH_LEASE_SECONDS`, read at call time.
    """
    token = uuid4()
    seconds = settings.WORKFLOW_DISPATCH_LEASE_SECONDS if lease_seconds is None else lease_seconds
    lease_expires_at = datetime.now(UTC) + timedelta(seconds=seconds)
    return await workflow_run_repo.claim_outbox(
        db, node_run_id=node_run_id, token=token, lease_expires_at=lease_expires_at
    )


async def renew_lease(db: AsyncSession, *, node_run_id: UUID, token: UUID) -> bool:
    """Extend the claim made with `token` on `node_run_id` by another full lease.

    Returns `False` once it is no longer that open claim - reclaimed, closed
    or cancelled - and then extends nothing.
    """
    return await workflow_run_repo.renew_lease(
        db,
        node_run_id=node_run_id,
        token=token,
        lease_seconds=settings.WORKFLOW_DISPATCH_LEASE_SECONDS,
    )


async def resolve_graph(db: AsyncSession, run: WorkflowRun) -> WorkflowGraph:
    """The graph this run executes - a published version, or a draft snapshot.

    Raises:
        WorkflowGraphUnresolvableError: The version no longer resolves, or the
            stored graph no longer validates.
    """
    raw: dict[str, Any] | None = run.draft_graph_snapshot
    if run.workflow_version_id is not None:
        version = await workflow_repo.get_version(
            db, run.workflow_version_id, organization_id=run.organization_id
        )
        raw = version.graph if version is not None else None
    if raw is None:
        raise WorkflowGraphUnresolvableError(run_id=run.id)
    try:
        graph = WorkflowGraph.model_validate(raw)
    except PydanticValidationError as exc:
        raise WorkflowGraphUnresolvableError(run_id=run.id) from exc
    # Which loop owns which node is derived from the topology, never read off
    # the stored copy - the same rule publishing follows.
    return derive_scopes(graph)


async def _principal_context(db: AsyncSession, run: WorkflowRun) -> AuthContext:
    """The `AuthContext` a node handler acts with, checked again at this dispatch.

    Built from the principal pinned at admission, never from a request that
    no longer exists by the time a parked node wakes - and re-checked here on
    every dispatch, because that wake can be days later: an account removed
    from the organization, deactivated, or no longer allowed to run this
    workflow since it started the run must not keep acting through it.

    Mirrors what a request by the same person would get now: every request is
    refused an organization the caller is not an active member of
    (`app.api.deps.get_active_organization`), app admins included, so a
    principal removed from the organization is refused here too, and an
    active member acts with their current role (and `is_app_admin` if they
    hold it), as `app.api.deps.get_auth_context` builds it. The permission check is the
    admission check repeated - `workflows:run`, and `workflows:edit` as well
    for a `test` run of an unpublished draft.

    A run with no principal acts as nobody and is refused. Every route that
    admits a run requires a signed-in subject (`AuthContext.subject_id`), so
    the only way to get here without one is the account having been deleted
    since (`execution_principal_user_id` is `SET NULL`).

    Raises:
        PrincipalRevokedError: Any of the above no longer holds.
    """
    user_id = run.execution_principal_user_id
    if user_id is None:
        raise PrincipalRevokedError()
    user = await user_repo.get_by_id(db, user_id)
    if user is None or not user.is_active:
        raise PrincipalRevokedError()
    member = await member_repo.get_active(db, organization_id=run.organization_id, user_id=user_id)
    if member is None:
        raise PrincipalRevokedError()
    auth = AuthContext(
        user_id=user_id,
        organization_id=run.organization_id,
        role=member.role,
        is_app_admin=user.is_app_admin,
    )
    workflow = await workflow_repo.get(db, run.workflow_id, organization_id=run.organization_id)
    if workflow is None:
        raise PrincipalRevokedError()
    required = [Perm.WORKFLOWS_RUN]
    if run.mode == WorkflowRunMode.TEST.value:
        required.append(Perm.WORKFLOWS_EDIT)
    for perm in required:
        if not await resolve_access(db, auth, workflow, perm, resource_type=WORKFLOW):
            raise PrincipalRevokedError()
    return auth


def idempotency_key(
    *, organization_id: UUID, workflow_run_id: UUID, node_instance_id: UUID, scope_path: list[Any]
) -> str:
    """Stable across attempts of the same logical operation, distinct across
    loop iterations - what a node with `retry_guarantee="idempotent"` sends
    as its own call's dedup header.
    """
    scope = json.dumps(scope_path, sort_keys=True, separators=(",", ":"))
    return f"{organization_id}:{workflow_run_id}:{node_instance_id}:{scope}"


def _field_owner(definition: NodeDefinition, field_name: str) -> str | None:
    """Whether `field_name` belongs to the input schema or the config schema.

    Mirrors `app.workflows.graph.validate._field_type`'s own precedence
    (input checked before config) so a binding resolves to the same schema
    at dispatch time that publish-time validation checked it against.
    """
    if definition.input_schema is not None and field_name in definition.input_schema.model_fields:
        return "input"
    if definition.config_schema is not None and field_name in definition.config_schema.model_fields:
        return "config"
    return None


def _resolve_source(source: BindingSource, outputs: dict[UUID, dict[str, Any] | None]) -> Any:
    """A binding's value, from the stored result of each source node.

    A `NodeOutputRef` on a node's `error` port reads the error it failed with;
    on any other port, the output it completed with. Publishing keeps each to its
    own path, so the other half is simply absent.
    """
    if isinstance(source, LiteralValue):
        return source.value
    if isinstance(source, NodeOutputRef):
        stored = outputs.get(source.node_id) or {}
        wanted = "failed" if source.port == ERROR_PORT else "completed"
        value: Any = stored.get("error" if wanted == "failed" else "output")
        if stored.get("status") != wanted:
            value = None
        for part in source.field_path:
            value = None if value is None else value.get(part)
        return value
    if isinstance(source, FileRef | TableIORef):
        return source.model_dump(mode="json")
    raise TypeError(f"Unknown binding source: {source!r}")


def _resolve_io(
    graph: WorkflowGraph,
    node: NodeInstance,
    definition: NodeDefinition,
    *,
    outputs: dict[UUID, dict[str, Any] | None],
) -> tuple[BaseModel | None, BaseModel | None]:
    """The `(config, input)` a node's handler is called with.

    `node.config` is the base; a binding targeting a config field overrides
    it. Input has no base at all - a node with nothing bound to any input
    field is called with `handler_input=None`, exactly like a graph with no
    bindings at all today (`debug.echo`'s own smoke case).
    """
    config_overrides: dict[str, Any] = {}
    input_values: dict[str, Any] = {}
    for binding in graph.bindings:
        if binding.target_node_id != node.id:
            continue
        value = _resolve_source(binding.source, outputs)
        owner = _field_owner(definition, binding.target_field)
        if owner == "input":
            input_values[binding.target_field] = value
        elif owner == "config":
            config_overrides[binding.target_field] = value
        # `owner is None` cannot happen for a published graph - rule 9
        # (`_binding_target_field_problems`) already refused it at publish.

    config_obj = None
    if definition.config_schema is not None:
        config_obj = definition.config_schema.model_validate({**node.config, **config_overrides})
    input_obj = None
    if definition.input_schema is not None and input_values:
        input_obj = definition.input_schema.model_validate(input_values)
    return config_obj, input_obj


async def _completed_outputs(
    db: AsyncSession,
    *,
    workflow_run_id: UUID,
    node_ids: set[UUID],
    scope_path: ScopePath,
    node_scope: dict[UUID, UUID],
) -> dict[UUID, dict[str, Any] | None]:
    """The stored result of each named node, for `NodeOutputRef` binding sources.

    Looked up in the scope each source ran in - the reader's own iteration, or
    an enclosing one (`_source_path`). A skipped source has no stored result and
    reads as `None`, which a publish-valid graph never binds to: rule 4 only lets
    a node bind to what dominates it, and a dominator of a node that runs cannot
    have been skipped.
    """
    outputs: dict[UUID, dict[str, Any] | None] = {}
    for node_id in node_ids:
        source_run = await workflow_run_repo.get_node_run_by_identity(
            db,
            workflow_run_id=workflow_run_id,
            node_instance_id=node_id,
            scope_path=_source_path(node_id, scope_path, node_scope),
        )
        if source_run is None:
            outputs[node_id] = None
            continue
        latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=source_run.id)
        outputs[node_id] = latest.result if latest is not None else None
    return outputs


class SkippedStep(BaseModel):
    """What a switched-off step hands on: that it was skipped, and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skipped: Literal[True] = True


async def _skip(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    return Completed[SkippedStep](output=SkippedStep())


class PinnedOutput(RootModel[dict[str, Any]]):
    """Data a test run hands on for a pinned step, as the step's output."""


def _pinned(data: dict[str, Any]) -> NodeHandler:
    async def hand_on(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
        return Completed[PinnedOutput](output=PinnedOutput(data))

    return hand_on


@dataclass(frozen=True, slots=True)
class _ResolvedCall:
    """Everything a node's call needs that the run's own rows decide."""

    graph: WorkflowGraph
    node: NodeInstance
    definition: NodeDefinition
    handler: NodeHandler
    config: BaseModel | None
    input: BaseModel | None
    arrived_output: dict[str, Any] | None


async def _resolve_call(db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun) -> _ResolvedCall:
    """Resolve the node `node_run` names: its graph, definition, handler and bindings.

    Raises:
        WorkflowDispatchRefusedError: A subclass naming what can never resolve.
    """
    graph = await resolve_graph(db, run)
    node = graph.node_by_id.get(node_run.node_instance_id)
    if node is None:
        raise WorkflowGraphUnresolvableError(run_id=run.id)
    try:
        definition = _registry.get(node.definition_id, node.definition_version)
    except BadRequestError as exc:
        # Removed or renamed in a deploy since the graph was published.
        raise NodeDefinitionMissingError(
            node_id=node.definition_id, version=node.definition_version
        ) from exc
    if node.disabled:
        # Switched off: nothing is resolved or called. Publishing made sure nothing
        # reads this step's output, so an empty one hands the run on.
        return _ResolvedCall(
            graph=graph,
            node=node,
            definition=definition,
            handler=_skip,
            config=None,
            input=None,
            arrived_output=None,
        )
    if (
        node.pinned_output is not None
        and run.mode == WorkflowRunMode.TEST.value
        and definition.kind != "control"
    ):
        # Pinned for testing: the data stands in for the step, which is not called.
        # A step that decides the way still runs - its choice is not data to pin.
        return _ResolvedCall(
            graph=graph,
            node=node,
            definition=definition,
            handler=_pinned(node.pinned_output),
            config=None,
            input=None,
            arrived_output=None,
        )
    if definition.handler is None:
        raise NodeHandlerMissingError(node_id=node.definition_id, version=node.definition_version)

    referenced_nodes = {
        binding.source.node_id
        for binding in graph.bindings
        if binding.target_node_id == node.id and isinstance(binding.source, NodeOutputRef)
    }
    outputs = await _completed_outputs(
        db,
        workflow_run_id=run.id,
        node_ids=referenced_nodes,
        scope_path=node_run.scope_path,
        node_scope=node_scope_map(graph),
    )
    try:
        config_obj, input_obj = _resolve_io(graph, node, definition, outputs=outputs)
    except PydanticValidationError as exc:
        # `validate_graph`'s rule 9 only confirms a bound field exists; a
        # `FileRef`/`TableIORef` source is never checked against the target
        # field's own type, so this can fail on a published graph too.
        raise InvalidBindingError(node_instance_id=node.id) from exc
    arrived_output = (
        await _AdvanceState(
            db, run=run, graph=graph, scope_path=node_run.scope_path
        ).arrived_output(node.id)
        if definition.kind == "control"
        else None
    )
    return _ResolvedCall(
        graph=graph,
        node=node,
        definition=definition,
        handler=definition.handler,
        config=config_obj,
        input=input_obj,
        arrived_output=arrived_output,
    )


async def begin_attempt(
    db: AsyncSession,
    *,
    workflow_run_id: UUID,
    node_run_id: UUID,
    token: UUID,
    claim: context.ClaimState | None = None,
) -> BegunAttempt | None:
    """Phase 2: resolve this node's call and commit its `in_flight` attempt.

    `token` is the fencing token `claim` minted for this worker. It is
    re-checked against the outbox row's *current* `claimed_by` before
    anything else runs: `claimed_by` is minted fresh per claim rather than
    reused (a Prefect flow-run id, say) precisely so a worker whose lease
    expired between `claim` and here - and who is not actually dead, only
    slow - can never believe it still owns this dispatch once somebody else
    has reclaimed it. Everything below this point assumes "this worker
    currently owns `node_run_id`'s dispatch"; a token mismatch means that is
    false, and no attempt is created on the strength of a claim that is no
    longer this worker's.

    Returns `None` when no attempt is created:

    - the claim was lost to a reclaim, or its row was closed under this
      worker - nothing is touched, the row is not this worker's;
    - the run is terminal, or the node already settled or was cancelled -
      this claim is closed, and the run is marked succeeded if that leaves it
      finished;
    - the run is past its deadline or over budget, or the call can never be
      made (`WorkflowDispatchRefusedError`, a revoked principal) - the run
      ends with that error;
    - an earlier attempt is still `in_flight` - it is resolved as an orphan
      (`resolve_orphaned_attempt`).

    None of these leaves anything for `settle` to do.
    """
    run = await workflow_run_repo.get_run_by_id_for_update(db, workflow_run_id)
    node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, node_run_id)
    if run is None or node_run is None:
        logger.error(
            "workflow_dispatch_missing_row",
            extra={"workflow_run_id": str(workflow_run_id), "node_run_id": str(node_run_id)},
        )
        return None
    # Locked, not merely read: a plain read is only true at the instant it
    # runs, and this worker's own token check needs to stay true for the rest
    # of this transaction - through resolving the graph, io and auth context,
    # all before `create_attempt` commits. Holding this row's lock is what
    # makes `claim_outbox`'s reclaiming CAS `UPDATE` (which needs the same
    # row) wait for this transaction to end rather than race it.
    outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(db, node_run_id=node_run_id)

    if outbox is None or outbox.claimed_by != token:
        # Lost the claim between `claim` and here - the row now belongs to
        # whoever's token it currently carries (or to nobody, if it was
        # already closed out from under this worker), so it is not this
        # worker's to touch, let alone close.
        logger.warning(
            "workflow_dispatch_lost_claim",
            extra={"node_run_id": str(node_run_id), "token": str(token)},
        )
        return None
    if outbox.status != DispatchOutboxStatus.CLAIMED.value:
        # The token is still this worker's, but the row was closed under it -
        # the reconciler resolved the attempt it was fencing, or the run was
        # cancelled or failed. A closed row authorizes nothing, and it is
        # not this worker's to reopen or re-close.
        logger.warning(
            "workflow_dispatch_closed_claim",
            extra={"node_run_id": str(node_run_id), "outbox_status": outbox.status},
        )
        return None

    if WorkflowRunStatus(run.status).is_terminal or node_run.status not in _DISPATCHABLE:
        # A node that already settled (succeeded, failed, escalated to
        # `needs_attention`) or was cancelled must never run again, whatever
        # outbox row a racing wake left behind for it. The row is this
        # worker's own claim, so it is closed rather than left for
        # `take_stale_claims_for_resubmission` to resubmit - and closing it
        # may be what leaves the run with nothing live, so the completion
        # check `_advance` makes is made again here. Without it a stray row
        # outliving the last node's settle stranded the run in `running`.
        await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
        if not WorkflowRunStatus(run.status).is_terminal:
            await _succeed_if_finished(db, run=run)
        return None

    now = datetime.now(UTC)
    if budget.past_deadline(run, at=now):
        await _fail_run(
            db,
            run=run,
            node_run=node_run,
            outbox=outbox,
            error=WorkflowError(
                code="DEADLINE_EXCEEDED",
                message="This run's deadline passed before this node could be dispatched",
            ),
        )
        return None
    if budget.over_budget(run):
        # Terminal, not a pause: nothing resumes a run once its cap is spent
        # (raising the cap means publishing a new version and starting again).
        await _end_run_before_dispatch(
            db,
            run=run,
            node_run=node_run,
            outbox=outbox,
            run_status=WorkflowRunStatus.BUDGET_EXCEEDED,
            node_status=NodeRunStatus.CANCELLED,
            event=events.EventKind.RUN_BUDGET_EXCEEDED,
            error=WorkflowError(
                code="BUDGET_EXCEEDED",
                message="This run's budget was spent before this node could be dispatched",
            ),
        )
        return None

    latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=node_run.id)
    if latest is not None and latest.status == NodeAttemptStatus.IN_FLIGHT.value:
        # This claim reclaimed a row whose *previous* claim got past phase 2
        # (an `in_flight` attempt exists) before its process died - never
        # assumed either outcome, resolved the same way `workflow-reconcile`
        # resolves one it finds on its own schedule, not silently retried
        # here as if nothing had been tried yet.
        await resolve_orphaned_attempt(
            db, run=run, node_run=node_run, attempt=latest, outbox=outbox
        )
        return None

    try:
        auth = await _principal_context(db, run)
        call = await _resolve_call(db, run=run, node_run=node_run)
    except WorkflowDispatchRefusedError as exc:
        # Deterministic: every future attempt would fail the same way, before
        # any `NodeAttempt` exists to record it. Left to propagate, the claim
        # would roll back with the transaction and
        # `take_stale_claims_for_resubmission` would resubmit the same row on
        # every reconcile tick, for ever.
        logger.warning(
            "workflow_dispatch_refused",
            extra={"node_run_id": str(node_run.id), "code": exc.code},
        )
        await _fail_run(
            db,
            run=run,
            node_run=node_run,
            outbox=outbox,
            error=WorkflowError(code=exc.code, message=exc.message),
        )
        return None
    node = call.node
    definition = call.definition

    attempt_no = (latest.attempt_no if latest else 0) + 1
    key = idempotency_key(
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        node_instance_id=node.id,
        scope_path=node_run.scope_path,
    )
    # Per call, not only per node kind: whether `http.request` may be retried
    # depends on the method and headers this instance was configured with, so a
    # definition may answer from the resolved config. Decided here, before the
    # handler runs, and committed with the `in_flight` row, because it is what
    # the reconciler reads to decide an orphaned attempt it cannot ask about.
    guarantee = (
        definition.retry_guarantee_for(call.config)
        if definition.retry_guarantee_for is not None
        else definition.retry_guarantee
    )
    attempt = await workflow_run_repo.create_attempt(
        db,
        organization_id=run.organization_id,
        node_run_id=node_run.id,
        attempt_no=attempt_no,
        idempotency_key=key,
        retry_guarantee=guarantee,
        started_at=now,
    )
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": NodeRunStatus.RUNNING.value,
            "started_at": node_run.started_at or now,
        },
    )
    if run.status in (
        WorkflowRunStatus.WAITING_RETRY.value,
        WorkflowRunStatus.WAITING_APPROVAL.value,
    ):
        # A dispatch resumed after a retry backoff or an approval decision -
        # left alone, the run stays `waiting_*` with its old `paused_reason`
        # while this node (and whatever it advances to) is actively running,
        # so the API would keep reporting the workflow paused.
        run = await workflow_run_repo.update_run(
            db,
            run=run,
            update_data={"status": WorkflowRunStatus.RUNNING.value, "paused_reason": None},
        )
    await events.append(
        db,
        run=run,
        kind=events.EventKind.NODE_DISPATCHED,
        node_run_id=node_run.id,
        payload={"attempt_no": attempt_no, "node_definition": definition.id},
    )
    dispatch_context = context.DispatchContext(
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        node_instance_id=node.id,
        attempt_no=attempt_no,
        auth=auth,
        resumed_agent_run_id=node_run.waiting_agent_run_id,
        claim=claim if claim is not None else context.ClaimState(),
        workflow_id=run.workflow_id,
        run_input=run.input,
        triggered_by=run.triggered_by,
        arrived_output=call.arrived_output,
        idempotency_key=key,
    )
    return BegunAttempt(
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        node_instance_id=node.id,
        organization_id=run.organization_id,
        attempt_id=attempt.id,
        attempt_no=attempt_no,
        handler_config=call.config,
        handler_input=call.input,
        definition=definition,
        handler=call.handler,
        dispatch_context=dispatch_context,
        timeout_seconds=node.policy.timeout_seconds if node.policy else None,
        retry_guarantee=guarantee,
        dispatch_token=token,
    )


async def call_handler(begun: BegunAttempt) -> HandlerOutcome:
    """Phase 3's non-transactional half: run the handler under `dispatching_as`.

    Not called from inside either of `begin_attempt`/`settle`'s sessions -
    `app.worker.tasks.workflow_tasks.workflow_dispatch_node_flow` calls this
    between them, so a slow or hung handler never holds a pooled connection.
    """
    scope = context.dispatching_as(begun.dispatch_context)
    result: NodeResult
    try:
        with scope:
            async with asyncio.timeout(begun.timeout_seconds):
                result = await begun.handler(begun.handler_config, begun.handler_input)
    except TimeoutError:
        result = _timed_out(begun)
    except Exception:
        # A handler is meant to return `Failed`, never raise; one that raises
        # anyway settles as a failure here rather than crashing the flow and
        # leaving its attempt `in_flight` for the reconciler to redispatch.
        # The exception's own text goes to the log only: it is not a string
        # this repository controls, and the result is read by every viewer of
        # the workflow.
        logger.exception(
            "workflow_node_handler_raised",
            extra={"node_run_id": str(begun.node_run_id), "node_definition": begun.definition.id},
        )
        result = Failed(
            error=WorkflowError(
                code="HANDLER_ERROR",
                message="The node's handler stopped with an unexpected error",
                retryable=True,
            )
        )
    return HandlerOutcome(
        result=result,
        waiting_agent_run_id=scope.waiting_agent_run_id,
        cost=scope.cost,
        cost_is_partial=scope.cost_is_partial,
        run_output=scope.run_output,
    )


def _timed_out(begun: BegunAttempt) -> NodeResult:
    """A call past its policy's time limit, read by what repeating it could do.

    A step with no external write, or one whose call is idempotent, failed and
    may be tried again. A write that is not may have landed before the limit
    cut it off, so its outcome is unknown - never assumed either way.
    """
    limit = begun.timeout_seconds
    if begun.definition.effect_kind != "write" or begun.retry_guarantee == "idempotent":
        return Failed(
            error=WorkflowError(
                code="NODE_TIMEOUT",
                message=f"The step did not finish within {limit:g} seconds",
                details={"timeout_seconds": limit},
                retryable=True,
            )
        )
    return Uncertain(
        detail=f"The step did not finish within {limit:g} seconds; its write may have landed"
    )


async def _end_node(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    status: NodeRunStatus,
    now: datetime,
    error: WorkflowError | None = None,
) -> None:
    """Move `node_run` to a terminal status for good.

    The one way a node leaves the graph without succeeding: it clears the
    wait it may have been parked on - a woken node that fails must not keep
    pointing at the agent run it waited for - and appends the node's own
    event before whatever the caller does to the run, so a client rebuilding
    node state from the stream sees every node end.
    """
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": status.value,
            "ended_at": now,
            "waiting_reason": None,
            "waiting_agent_run_id": None,
        },
    )
    kind = (
        events.EventKind.NODE_FAILED
        if status is NodeRunStatus.FAILED
        else events.EventKind.NODE_CANCELLED
    )
    await events.append(
        db,
        run=run,
        kind=kind,
        node_run_id=node_run.id,
        payload={"error": error.code} if error is not None else {},
    )


async def _end_run(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    run_status: WorkflowRunStatus,
    node_status: NodeRunStatus,
    event: str,
    error: WorkflowError,
    now: datetime,
) -> None:
    """End `node_run` and then `run` for good.

    Terminal in every column a reader checks: the node, the run's status,
    `ended_at` and `error`, and every outbox row still live for the run, so
    nothing else is claimed for it afterwards.
    """
    await _end_node(db, run=run, node_run=node_run, status=node_status, now=now, error=error)
    # The loops enclosing a node that ends the run are still `running` - they
    # end with it.
    for live in await workflow_run_repo.list_live_node_runs(db, workflow_run_id=run.id):
        await _end_node(db, run=run, node_run=live, status=NodeRunStatus.CANCELLED, now=now)
    await workflow_run_repo.update_run(
        db,
        run=run,
        update_data={
            "status": run_status.value,
            "ended_at": now,
            "paused_reason": None,
            "error": error.model_dump(mode="json"),
        },
    )
    await events.append(
        db, run=run, kind=event, node_run_id=node_run.id, payload={"code": error.code}
    )
    await workflow_run_repo.cancel_live_outbox_for_run(db, workflow_run_id=run.id)
    await delivery.deliver_result(db, run=run)


async def _end_run_before_dispatch(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    outbox: DispatchOutbox,
    run_status: WorkflowRunStatus,
    node_status: NodeRunStatus,
    event: str,
    error: WorkflowError,
) -> None:
    """End `run` for good before `node_run` ever got an attempt, closing this claim."""
    await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
    await _end_run(
        db,
        run=run,
        node_run=node_run,
        run_status=run_status,
        node_status=node_status,
        event=event,
        error=error,
        now=datetime.now(UTC),
    )


async def _fail_run(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    outbox: DispatchOutbox,
    error: WorkflowError,
) -> None:
    await _end_run_before_dispatch(
        db,
        run=run,
        node_run=node_run,
        outbox=outbox,
        run_status=WorkflowRunStatus.FAILED,
        node_status=NodeRunStatus.FAILED,
        event=events.EventKind.RUN_FAILED,
        error=error,
    )


async def _close_node_of_ended_run(
    db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun, now: datetime
) -> None:
    """A node still live when its run ended is cancelled; one already ended keeps its status.

    A run failed for its deadline has already marked the node `failed`, and a
    late settle or an orphan resolution must not relabel it `cancelled`.
    """
    if node_run.status in _DISPATCHABLE:
        await _end_node(db, run=run, node_run=node_run, status=NodeRunStatus.CANCELLED, now=now)


def _backoff_seconds(step: int, retry: RetryPolicy | None = None) -> float:
    """The wait before the next attempt: the node's own schedule, or the base
    doubled per `step` after the first."""
    if retry is not None:
        return retry.delay_seconds(step)
    seconds = settings.WORKFLOW_RETRY_BACKOFF_BASE_SECONDS * (2 ** (max(step, 1) - 1))
    return min(seconds, settings.WORKFLOW_RETRY_BACKOFF_MAX_SECONDS)


def _retry_policy(graph: WorkflowGraph | None, node_run: NodeRun) -> RetryPolicy | None:
    node = graph.node_by_id.get(node_run.node_instance_id) if graph is not None else None
    return node.policy.retry if node is not None and node.policy is not None else None


def _attempt_ceiling(retry: RetryPolicy | None) -> int:
    return retry.max_attempts if retry is not None else settings.WORKFLOW_RETRY_CEILING


async def _graph_or_none(db: AsyncSession, run: WorkflowRun) -> WorkflowGraph | None:
    """The run's graph, or `None` if it no longer resolves - then a failure
    cannot be routed and ends the run, which is what a dispatch would do too."""
    try:
        return await resolve_graph(db, run)
    except WorkflowGraphUnresolvableError:
        return None


async def resolve_orphaned_attempt(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    attempt: NodeAttempt,
    outbox: DispatchOutbox | None,
) -> None:
    """Resolve one `in_flight` attempt nobody ever settled.

    The central rule this implements: **an interrupted attempt is never
    assumed either outcome.** `attempt` itself always settles `uncertain` -
    its real result genuinely is unknown - and what happens *next* is the
    only place `retry_guarantee` matters: `idempotent` means a duplicate call
    is provably harmless, so a fresh attempt is queued automatically;
    anything else (`at_least_once` with no dedup this dispatcher can see, or
    `none`) is never retried automatically and the node lands in
    `needs_attention` for a person to resolve.

    Shared by `begin_attempt` (an outbox row reclaimed by ordinary dispatch,
    whose previous claim already got this far - always a non-terminal run,
    since `begin_attempt` already refused a terminal one before reaching this
    call) and `app.services.workflow_execution.reconciler` (the standalone
    sweep that finds the same shape on its own schedule). The sweep also
    reaches attempts whose outbox row something else closed under them - a
    cancel while the worker was dead, a reclaim that failed the run for its
    deadline or budget - which is how a terminal run arrives here: the
    attempt still settles, and the node, if still live, is cancelled.

    A cost already booked onto the attempt by a late settle is kept.
    """
    now = datetime.now(UTC)
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.UNCERTAIN.value,
        result=None,
        cost=attempt.cost,
        cost_is_partial=attempt.cost_is_partial,
        ended_at=now,
    )
    # Only a claim still open is closed: a row a cancel or a failure already
    # closed keeps the status that records why.
    if outbox is not None and outbox.status == DispatchOutboxStatus.CLAIMED.value:
        await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
    await events.append(
        db,
        run=run,
        kind=events.EventKind.ATTEMPT_RECLAIMED,
        node_run_id=node_run.id,
        payload={"attempt_no": attempt.attempt_no, "retry_guarantee": attempt.retry_guarantee},
    )
    if WorkflowRunStatus(run.status).is_terminal:
        # A run that ended while this attempt was stranded stays as it
        # ended - the attempt still settled honestly above, but there is
        # nothing left to retry or escalate: no fresh outbox row, no
        # `needs_attention`, matching `settle`'s own terminal short-circuit.
        await _close_node_of_ended_run(db, run=run, node_run=node_run, now=now)
        return
    if attempt.retry_guarantee == RetryGuarantee.IDEMPOTENT.value:
        # The same ceiling and backoff a `Failed` result gets: a node whose
        # every attempt dies mid-call (a handler that crashes its worker) must
        # end, not be redispatched on every reconcile tick for ever.
        graph = await _graph_or_none(db, run)
        retry = _retry_policy(graph, node_run)
        failures = await workflow_run_repo.count_failed_attempts(db, node_run_id=node_run.id)
        if failures >= _attempt_ceiling(retry):
            # What this makes ready is submitted by the dispatch poll: this
            # path runs from a reclaim or the reconcile sweep, not a settle.
            await _fail_for_good(
                db,
                run=run,
                graph=graph,
                node_run=node_run,
                error=WorkflowError(
                    code="ATTEMPTS_INTERRUPTED",
                    message=(
                        "This node was interrupted or failed as many times as the retry "
                        "ceiling allows"
                    ),
                    details={"failed_attempts": failures},
                ),
                now=now,
            )
            return
        await workflow_run_repo.create_outbox(
            db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            available_at=now + timedelta(seconds=_backoff_seconds(failures, retry)),
        )
        return

    await _escalate(
        db,
        run=run,
        node_run=node_run,
        detail="Reclaimed after an interrupted attempt with no safe automatic resolution",
    )


def _still_owns(outbox: DispatchOutbox | None, token: UUID) -> TypeGuard[DispatchOutbox]:
    """Whether `outbox` is still an open claim made with `token`."""
    return (
        outbox is not None
        and outbox.claimed_by == token
        and outbox.status == DispatchOutboxStatus.CLAIMED.value
    )


def _attempt_status(result: NodeResult) -> str:
    """The `NodeAttempt` status each `NodeResult` variant settles to - the
    same on the ordinary path and on the terminal-run short-circuit, so both
    agree on what actually happened to the attempt even when the run itself
    no longer cares."""
    if isinstance(result, Completed | Waiting):
        # A `Waiting` attempt still settles `completed`: it started a real
        # effect and parked, a known and handled pause, not an error.
        return NodeAttemptStatus.COMPLETED.value
    if isinstance(result, Failed):
        return NodeAttemptStatus.FAILED.value
    if isinstance(result, Uncertain):
        return NodeAttemptStatus.UNCERTAIN.value
    raise TypeError(f"Unknown NodeResult variant: {result!r}")  # pragma: no cover - closed union


async def settle(
    db: AsyncSession, *, begun: BegunAttempt, outcome: HandlerOutcome
) -> list[tuple[UUID, UUID]]:
    """Phase 4: persist the attempt's terminal outcome and advance the run.

    What the handler reported spending is booked onto the run on every path,
    including the ones that discard its result: the money was spent either
    way, and a cost that only lands on success is a budget with a hole in it.

    Returns the `(workflow_run_id, node_run_id)` of every node this settle
    made ready. Their outbox rows are already written and stamped submitted;
    the caller submits them once this transaction has committed.
    """
    run = await workflow_run_repo.get_run_by_id_for_update(db, begun.workflow_run_id)
    node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, begun.node_run_id)
    attempt = await workflow_run_repo.get_attempt(db, begun.attempt_id)
    if run is None or node_run is None or attempt is None:
        logger.error(
            "workflow_dispatch_settle_missing_row", extra={"attempt_id": str(begun.attempt_id)}
        )
        return []
    now = datetime.now(UTC)
    result = outcome.result
    run = await _book_cost(db, run=run, outcome=outcome)

    # A stale settle: the lease expired while the handler was genuinely still
    # running, `workflow-reconcile` already resolved this same attempt (to
    # `uncertain`, possibly dispatching a fresh one in its place), and only
    # afterward does the original, still-running handler finally return. That
    # verdict must not be silently overwritten by a late result arriving for
    # an attempt that is no longer "current" - `attempt.status` moving off
    # `in_flight` is exactly what says a different settle (or the reconciler)
    # already had the last word on this attempt. Its verdict stands; only
    # the cost it ran up is added to its row and the run's (above).
    if attempt.status != NodeAttemptStatus.IN_FLIGHT.value:
        logger.warning(
            "workflow_dispatch_settle_stale_attempt",
            extra={"attempt_id": str(attempt.id), "attempt_status": attempt.status},
        )
        await _book_attempt_cost(db, attempt=attempt, outcome=outcome)
        return []

    # A run cancelled while this handler was running must stay cancelled: the
    # attempt itself still settles honestly (what actually happened is worth
    # recording), but as a terminal `NodeRun` outcome with no run-status
    # transition and no `_advance` - `cancel()` already closed every outbox
    # row, so there is nothing left to dispatch even if this had completed.
    if WorkflowRunStatus(run.status).is_terminal:
        await _record_attempt(db, attempt=attempt, outcome=outcome, now=now)
        await _close_node_of_ended_run(db, run=run, node_run=node_run, now=now)
        # Only this attempt's own, still-open claim is closed: `cancel()`
        # already marked the row `cancelled`, and that record stays as it is.
        outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(
            db, node_run_id=node_run.id
        )
        if _still_owns(outbox, begun.dispatch_token):
            await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
        return []

    # Locked, not merely read: `begin_attempt`'s own reclaim check needs this
    # same row, and a plain read here would only be true at the instant it
    # runs, not for the rest of this settle.
    outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(db, node_run_id=node_run.id)
    # Fenced against a reclaimed claim: a handler that outlives its lease can
    # have this row reclaimed by another worker's `claim()` before this
    # (stale) call ever reaches here - `attempt.status` is still `in_flight`
    # at that point (nobody has resolved it yet), so the check above does not
    # catch it. Accepting this result anyway would close a row this settle no
    # longer owns and, for a `Completed` result, `_advance` past a node the
    # reclaiming worker's own `begin_attempt` may already be re-running -
    # a duplicate attempt for a node this settle is about to mark succeeded.
    # A row still carrying this token but already closed is the same verdict
    # from the other direction: somebody else had the last word on it.
    if not _still_owns(outbox, begun.dispatch_token):
        logger.warning(
            "workflow_dispatch_settle_lost_claim",
            extra={"node_run_id": str(node_run.id), "attempt_id": str(attempt.id)},
        )
        # The reclaimer resolves this attempt `uncertain` and keeps what is
        # booked on it by then.
        await _book_attempt_cost(db, attempt=attempt, outcome=outcome)
        return []
    # Closed *before* dispatching to a `_settle_*` handler: `_settle_completed`
    # calls `_advance`, which decides the run is done by checking whether any
    # live outbox row remains - and this node's own row is still `claimed`
    # until this closes it. Checking that after closing it, rather than
    # before, is what makes "no live outbox left" actually mean it.
    await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
    await _record_attempt(db, attempt=attempt, outcome=outcome, now=now)

    if isinstance(result, Completed):
        if outcome.run_output is not None:
            run = await workflow_run_repo.update_run(
                db, run=run, update_data={"output": outcome.run_output}
            )
        return await _settle_completed(
            db, run=run, node_run=node_run, definition=begun.definition, result=result, now=now
        )
    if isinstance(result, Failed):
        return await _settle_failed(
            db, run=run, node_run=node_run, attempt=attempt, result=result, now=now
        )
    if isinstance(result, Waiting):
        await _settle_waiting(
            db,
            run=run,
            node_run=node_run,
            attempt=attempt,
            result=result,
            waiting_agent_run_id=outcome.waiting_agent_run_id,
            now=now,
        )
    elif isinstance(result, Uncertain):
        await _settle_uncertain(db, run=run, node_run=node_run, result=result)
    else:  # pragma: no cover - NodeResult is a closed discriminated union
        raise TypeError(f"Unknown NodeResult variant: {result!r}")
    return []


async def _book_cost(db: AsyncSession, *, run: WorkflowRun, outcome: HandlerOutcome) -> WorkflowRun:
    """Add what the handler reported spending to the run's total, under its lock."""
    if outcome.cost == 0 and not outcome.cost_is_partial:
        return run
    return await workflow_run_repo.update_run(
        db,
        run=run,
        update_data=budget.accumulate(
            run, cost=outcome.cost, cost_is_partial=outcome.cost_is_partial
        ),
    )


async def _book_attempt_cost(
    db: AsyncSession, *, attempt: NodeAttempt, outcome: HandlerOutcome
) -> None:
    """Add a discarded result's cost to its attempt row, leaving the verdict alone."""
    if outcome.cost == 0 and not outcome.cost_is_partial:
        return
    cost, capped = budget.saturating_add(attempt.cost, outcome.cost)
    await workflow_run_repo.book_attempt_cost(
        db,
        attempt=attempt,
        cost=cost,
        cost_is_partial=attempt.cost_is_partial or outcome.cost_is_partial or capped,
    )


async def _record_attempt(
    db: AsyncSession, *, attempt: NodeAttempt, outcome: HandlerOutcome, now: datetime
) -> None:
    """Write the attempt's terminal row: what happened, and what it cost."""
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=_attempt_status(outcome.result),
        result=outcome.result.model_dump(mode="json"),
        cost=outcome.cost,
        cost_is_partial=outcome.cost_is_partial,
        ended_at=now,
    )


async def _settle_completed(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    definition: NodeDefinition,
    result: Completed[Any],
    now: datetime,
) -> list[tuple[UUID, UUID]]:
    if definition.id == FOREACH:
        # The loop's handler only froze its list: the loop itself stays
        # `running` until its last iteration ends (`_close_loop`).
        manifest = ForeachManifest.model_validate(result.output.model_dump(mode="json"))
        return await _enter_loop(db, run=run, loop_run=node_run, items=manifest.items)
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": NodeRunStatus.SUCCEEDED.value,
            "ended_at": now,
            "waiting_reason": None,
            "resume_token": None,
            "waiting_agent_run_id": None,
        },
    )
    await events.append(db, run=run, kind=events.EventKind.NODE_COMPLETED, node_run_id=node_run.id)
    return await _advance(
        db,
        run=run,
        completed_node_instance_id=node_run.node_instance_id,
        scope_path=node_run.scope_path,
    )


async def _settle_waiting(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    attempt: NodeAttempt,
    result: Waiting,
    waiting_agent_run_id: UUID | None,
    now: datetime,
) -> None:
    if result.reason == WaitingReason.EXTERNAL_EVENT.value:
        # Nothing delivers an external event to a parked workflow node yet, so
        # parking it would strand the run for ever; a person looks at
        # `needs_attention`.
        await _escalate(
            db,
            run=run,
            node_run=node_run,
            detail="Node waited for an external event, which workflow runs cannot deliver yet",
        )
        return
    if (
        result.reason == WaitingReason.APPROVAL.value
        and waiting_agent_run_id is None
        and not await workflow_approval_repo.has_pending(db, node_run.id)
    ):
        # The one invariant that makes an approval wait durable: a handler
        # declaring `Waiting(reason="approval")` must leave something a wake can
        # find it by - the `agent_runs` row it reported through
        # `context.report_waiting_agent_run`, or the pending `workflow_approvals`
        # row a `human.approval` step wrote for this node run. Without either,
        # neither the direct wakes nor `workflow-reconcile`'s backstops have
        # anything to key off to ever find this node again. Parking it as an
        # ordinary `waiting_approval` node would be silently unrecoverable;
        # `needs_attention` at least puts it somewhere a person looks.
        await _escalate(
            db,
            run=run,
            node_run=node_run,
            detail="Node declared an approval wait with no agent run to resume it",
        )
        return

    # `resume_token` is a structural invariant, not something a handler is
    # trusted to have gotten right - it is always this NodeRun's own id.
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": NodeRunStatus.WAITING.value,
            "waiting_reason": result.reason,
            "resume_token": str(node_run.id),
            "waiting_agent_run_id": waiting_agent_run_id,
        },
    )
    await events.append(
        db,
        run=run,
        kind=events.EventKind.NODE_WAITING,
        node_run_id=node_run.id,
        payload={"reason": result.reason},
    )
    run_status = (
        WorkflowRunStatus.WAITING_APPROVAL
        if result.reason == WaitingReason.APPROVAL.value
        else WorkflowRunStatus.WAITING_RETRY
    )
    await workflow_run_repo.update_run(
        db, run=run, update_data={"status": run_status.value, "paused_reason": result.reason}
    )
    if result.reason == WaitingReason.RETRY_BACKOFF.value:
        # The wake is the outbox row itself, due once the backoff has passed -
        # the same capped schedule a retryable failure gets, stepped by the
        # attempt number. A wait does not count against the retry ceiling, so
        # only the run's deadline, budget or a cancel bounds how often a
        # handler asks for one.
        await workflow_run_repo.create_outbox(
            db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            available_at=now + timedelta(seconds=_backoff_seconds(attempt.attempt_no)),
        )


async def _escalate(db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun, detail: str) -> None:
    """Park the node and its run in `needs_attention`, for a person to resolve."""
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": NodeRunStatus.NEEDS_ATTENTION.value,
            "waiting_reason": None,
            "waiting_agent_run_id": None,
        },
    )
    await events.append(
        db,
        run=run,
        kind=events.EventKind.NODE_UNCERTAIN,
        node_run_id=node_run.id,
        payload={"detail": detail},
    )
    await workflow_run_repo.update_run(
        db,
        run=run,
        update_data={"status": WorkflowRunStatus.NEEDS_ATTENTION.value, "paused_reason": None},
    )
    await events.append(
        db, run=run, kind=events.EventKind.RUN_NEEDS_ATTENTION, node_run_id=node_run.id
    )


async def _settle_failed(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    attempt: NodeAttempt,
    result: Failed,
    now: datetime,
) -> list[tuple[UUID, UUID]]:
    """Retry a failure the node's schedule still allows, or fail the node for good.

    Retried only when the call is safe to repeat (`retry_guarantee` not `none`)
    and the node says this failure is worth another try (`retryable`) - a
    validation error or a revision conflict is not, however patient the policy -
    up to the node's own `policy.retry`, or the deployment's schedule without one.
    """
    graph = await _graph_or_none(db, run)
    retry = _retry_policy(graph, node_run)
    retryable = attempt.retry_guarantee != RetryGuarantee.NONE.value and result.error.retryable
    # Counted over failed and interrupted attempts only (this one included,
    # recorded before this runs): a wait is not a failure.
    failures = await workflow_run_repo.count_failed_attempts(db, node_run_id=node_run.id)
    if retryable and failures < _attempt_ceiling(retry):
        await workflow_run_repo.update_node_run(
            db,
            node_run=node_run,
            update_data={
                "status": NodeRunStatus.WAITING.value,
                "waiting_reason": WaitingReason.RETRY_BACKOFF.value,
                # The agent run a resumed attempt consumed is not the next
                # attempt's to resume again.
                "waiting_agent_run_id": None,
            },
        )
        await events.append(
            db,
            run=run,
            kind=events.EventKind.NODE_RETRYING,
            node_run_id=node_run.id,
            payload={
                "attempt_no": attempt.attempt_no,
                "failed_attempts": failures,
                "error": result.error.code,
            },
        )
        await workflow_run_repo.update_run(
            db,
            run=run,
            update_data={
                "status": WorkflowRunStatus.WAITING_RETRY.value,
                "paused_reason": WaitingReason.RETRY_BACKOFF.value,
            },
        )
        await workflow_run_repo.create_outbox(
            db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            available_at=now + timedelta(seconds=_backoff_seconds(failures, retry)),
        )
        return []

    return await _fail_for_good(
        db, run=run, graph=graph, node_run=node_run, error=result.error, now=now
    )


async def _fail_for_good(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    graph: WorkflowGraph | None,
    node_run: NodeRun,
    error: WorkflowError,
    now: datetime,
) -> list[tuple[UUID, UUID]]:
    """A node that will not run again failed: route it, let its loop absorb it, or end the run.

    In that order. A node whose policy routes its errors leaves by its `error`
    port and the run goes on. Inside a loop, the loop's item-error policy decides:
    `collect` records the failure in that item's place and starts the next
    iteration; `stop` fails the loop itself with this error - naming the
    iteration's scope path - which is then decided the same way one level up.
    Anything else fails the run. A failure that is not `bypassable` - revoked
    access, a spent budget - ends the run however the graph is wired.
    """
    node = graph.node_by_id.get(node_run.node_instance_id) if graph is not None else None
    if graph is None or node is None or not error.bypassable:
        await _fail_node_and_run(db, run=run, node_run=node_run, error=error, now=now)
        return []
    if node.routes_errors:
        await _end_node(
            db, run=run, node_run=node_run, status=NodeRunStatus.FAILED, now=now, error=error
        )
        return await _advance(
            db,
            run=run,
            completed_node_instance_id=node.id,
            scope_path=node_run.scope_path,
            graph=graph,
        )
    loop_id = _loop_of(node_run.scope_path)
    if loop_id is None:
        await _fail_node_and_run(db, run=run, node_run=node_run, error=error, now=now)
        return []
    await _end_node(
        db, run=run, node_run=node_run, status=NodeRunStatus.FAILED, now=now, error=error
    )
    loop_config = ForeachConfig.model_validate(graph.node_by_id[loop_id].config)
    if loop_config.item_error_policy == "collect":
        return await _iteration_ended(db, run=run, graph=graph, scope_path=node_run.scope_path)
    loop_run = await _loop_run(db, run=run, scope_path=node_run.scope_path)
    details = (
        error.details
        if "scope_path" in error.details
        else {**error.details, "scope_path": node_run.scope_path}
    )
    return await _fail_for_good(
        db,
        run=run,
        graph=graph,
        node_run=loop_run,
        error=error.model_copy(update={"details": details}),
        now=now,
    )


async def _fail_node_and_run(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    error: WorkflowError,
    now: datetime,
) -> None:
    """A node that ran and will not run again fails, and takes its run with it."""
    await _end_run(
        db,
        run=run,
        node_run=node_run,
        run_status=WorkflowRunStatus.FAILED,
        node_status=NodeRunStatus.FAILED,
        event=events.EventKind.RUN_FAILED,
        error=error,
        now=now,
    )


async def _settle_uncertain(
    db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun, result: Uncertain
) -> None:
    await _escalate(db, run=run, node_run=node_run, detail=result.detail)


async def _advance(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    completed_node_instance_id: UUID,
    scope_path: ScopePath,
    graph: WorkflowGraph | None = None,
) -> list[tuple[UUID, UUID]]:
    """After a node settles: queue what is now ready, skip what is now
    unreachable, and close out its iteration - or the run - once nothing is left.

    An edge is **live** when its source left through that edge's port: every
    output port but `error` of a node that succeeded, only the one a branching
    node chose (`NodeDefinition.routes`, read off the stored output), and only
    `error` of a node that failed through it. A target is decided once every one
    of its predecessors has settled: it runs when at least one incoming edge is
    live, and is `skipped` - with no attempt and no outbox row - when none is. A
    skip settles too, so it is decided onward the same way, which is how an
    untaken branch is skipped node by node until it reaches the `logic.merge`
    that rejoins the taken one.

    Only targets in the same scope are decided here - within one iteration, or at
    the top level. A loop's body is entered by iteration (`_start_iteration`),
    never by following its `body` edge. Called under the run's lock, so two
    settles of one run never decide the same target at once.

    Returns what it queued, for the caller to submit after commit.
    """
    graph = graph or await resolve_graph(db, run)
    node_scope = node_scope_map(graph)
    level = _loop_of(scope_path)
    decided = _AdvanceState(db, run=run, graph=graph, scope_path=scope_path)
    ready_pairs: list[tuple[UUID, UUID]] = []
    frontier = [completed_node_instance_id]
    while frontier:
        source_id = frontier.pop()
        targets = dict.fromkeys(
            edge.target_node_id
            for edge in graph.edges
            if edge.source_node_id == source_id and node_scope.get(edge.target_node_id) == level
        )
        for target_id in targets:
            if target_id not in graph.node_by_id or await decided.node_run(target_id) is not None:
                continue
            runs = await decided.runs_target(target_id)
            if runs is None:
                continue
            node_run = await _create_decided_node_run(
                db, run=run, target_id=target_id, runs=runs, scope_path=scope_path
            )
            if node_run is None:
                continue
            decided.remember(target_id, node_run)
            if runs:
                # Stamped submitted: the settling flow submits it straight after
                # this transaction commits, so the next node starts as soon as
                # its predecessor settles instead of waiting out the poll - and
                # the poll does not submit it a second time.
                await workflow_run_repo.create_outbox(
                    db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    node_run_id=node_run.id,
                    submitted=True,
                )
                ready_pairs.append((run.id, node_run.id))
            else:
                await events.append(
                    db, run=run, kind=events.EventKind.NODE_SKIPPED, node_run_id=node_run.id
                )
                frontier.append(target_id)
    if scope_path:
        return ready_pairs + await _end_iteration_if_settled(
            db, run=run, graph=graph, scope_path=scope_path
        )
    await _succeed_if_finished(db, run=run, graph=graph)
    return ready_pairs


class _AdvanceState:
    """One `_advance` call's reads of one scope's node rows and their chosen ports.

    Cached for the call, not beyond it: a target reached from several edges,
    or a predecessor shared by several targets, is read once, and a row this
    call just created is known without reading it back.
    """

    def __init__(
        self, db: AsyncSession, *, run: WorkflowRun, graph: WorkflowGraph, scope_path: ScopePath
    ) -> None:
        self._db = db
        self._run = run
        self._graph = graph
        self._scope_path = scope_path
        self._node_runs: dict[UUID, NodeRun | None] = {}
        self._ports: dict[UUID, frozenset[str] | None] = {}

    def remember(self, node_id: UUID, node_run: NodeRun) -> None:
        self._node_runs[node_id] = node_run

    async def node_run(self, node_id: UUID) -> NodeRun | None:
        if node_id not in self._node_runs:
            self._node_runs[node_id] = await workflow_run_repo.get_node_run_by_identity(
                self._db,
                workflow_run_id=self._run.id,
                node_instance_id=node_id,
                scope_path=self._scope_path,
            )
        return self._node_runs[node_id]

    async def runs_target(self, target_id: UUID) -> bool | None:
        """Whether `target_id` runs (`True`), is skipped (`False`), or cannot be
        decided yet (`None`) because a predecessor is still to settle."""
        live = False
        for edge in self._graph.edges:
            if edge.target_node_id != target_id:
                continue
            predecessor = await self.node_run(edge.source_node_id)
            if predecessor is None or predecessor.status not in _SETTLED:
                return None
            live = live or await self._leaves_by(predecessor, edge.source_port)
        return live

    async def arrived_output(self, target_id: UUID) -> dict[str, Any] | None:
        """What the one live edge `target_id` was reached through carries.

        What a `logic.merge` passes on - of its incoming branches exactly one ran,
        and rule 4 lets it bind to neither - and what an `error.handle` handles:
        the `WorkflowError` of the node that failed through its `error` port.
        `None` when no edge, or more than one, is live.
        """
        arrived: list[dict[str, Any] | None] = []
        for edge in self._graph.edges:
            if edge.target_node_id != target_id:
                continue
            predecessor = await self.node_run(edge.source_node_id)
            if predecessor is None or predecessor.status not in _SETTLED:
                continue
            if await self._leaves_by(predecessor, edge.source_port):
                arrived.append(await self._carried(predecessor))
        return arrived[0] if len(arrived) == 1 else None

    async def _leaves_by(self, node_run: NodeRun, port: str) -> bool:
        """Whether a settled node left through `port`."""
        if node_run.status == NodeRunStatus.FAILED.value:
            return port == ERROR_PORT
        if node_run.status != NodeRunStatus.SUCCEEDED.value:
            return False
        chosen = await self._chosen_ports(node_run)
        return port != ERROR_PORT if chosen is None else port in chosen

    async def _carried(self, node_run: NodeRun) -> dict[str, Any] | None:
        latest = await workflow_run_repo.get_latest_attempt(self._db, node_run_id=node_run.id)
        if latest is None or latest.result is None:
            return None
        key = "error" if node_run.status == NodeRunStatus.FAILED.value else "output"
        return latest.result.get(key)

    async def _chosen_ports(self, node_run: NodeRun) -> frozenset[str] | None:
        """The ports a succeeded node left by, or `None` for all but `error`."""
        node_id = node_run.node_instance_id
        if node_id not in self._ports:
            node = self._graph.node_by_id[node_id]
            definition = _registry.get(node.definition_id, node.definition_version)
            self._ports[node_id] = (
                None
                if definition.routes is None
                else definition.routes(await self._carried(node_run))
            )
        return self._ports[node_id]


async def _create_decided_node_run(
    db: AsyncSession, *, run: WorkflowRun, target_id: UUID, runs: bool, scope_path: ScopePath
) -> NodeRun | None:
    """Create `target_id`'s `NodeRun` in `scope_path`, `pending` or already `skipped`.

    The unique index on `(workflow_run_id, node_instance_id, scope_path)` is
    what finally decides a race to create it; the loser reads its own
    `IntegrityError` back as "already created" inside a savepoint, the shape
    `UserService.confirm_email_change` uses for its own insert race, rather
    than letting it abort the whole settle. `None` means somebody else did.
    """
    try:
        async with db.begin_nested():
            return await workflow_run_repo.create_node_run(
                db,
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                node_instance_id=target_id,
                scope_path=scope_path,
                skipped_at=None if runs else datetime.now(UTC),
            )
    except IntegrityError:
        return None


async def _succeed_if_finished(
    db: AsyncSession, *, run: WorkflowRun, graph: WorkflowGraph | None = None
) -> None:
    """Mark `run` succeeded once every top-level node has settled and nothing is
    left to dispatch.

    A loop body's rows are not counted here: a loop settles only once its last
    iteration has. A node that failed through its `error` port settled too - a
    failure that was not routed ended the run before this is ever asked.

    Called under the run's lock, both when the last node settles and when a
    stray outbox row is closed, so whichever of the two happens last ends
    the run.
    """
    if await workflow_run_repo.has_live_outbox(db, workflow_run_id=run.id):
        return
    graph = graph or await resolve_graph(db, run)
    node_scope = node_scope_map(graph)
    top_level = sum(1 for node in graph.nodes if node.id not in node_scope)
    statuses = await workflow_run_repo.list_node_run_statuses(db, workflow_run_id=run.id)
    if len(statuses) == top_level and all(status in _SETTLED for status in statuses):
        await _succeed_run(db, run=run)


# Loops


async def _enter_loop(
    db: AsyncSession, *, run: WorkflowRun, loop_run: NodeRun, items: list[Any]
) -> list[tuple[UUID, UUID]]:
    """A loop froze its list: start its first iteration, or finish at once when empty."""
    graph = await resolve_graph(db, run)
    await events.append(
        db,
        run=run,
        kind=events.EventKind.LOOP_STARTED,
        node_run_id=loop_run.id,
        payload={"count": len(items)},
    )
    if not items:
        return await _close_loop(db, run=run, graph=graph, loop_run=loop_run, count=0)
    return await _start_iteration(db, run=run, graph=graph, loop_run=loop_run, index=0, items=items)


async def _start_iteration(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    graph: WorkflowGraph,
    loop_run: NodeRun,
    index: int,
    items: list[Any],
) -> list[tuple[UUID, UUID]]:
    """Write iteration `index`'s `loop.item` already succeeded, and advance from it.

    Refused - failing the loop's run - once the iteration would take the run past
    `WORKFLOW_RUN_MAX_NODE_RUNS`, a ceiling no graph can route around.
    """
    loop_id = loop_run.node_instance_id
    node_scope = node_scope_map(graph)
    body = [node_id for node_id, owner in node_scope.items() if owner == loop_id]
    existing = await workflow_run_repo.count_node_runs(db, workflow_run_id=run.id)
    limit = settings.WORKFLOW_RUN_MAX_NODE_RUNS
    if existing + len(body) > limit:
        await _fail_node_and_run(
            db,
            run=run,
            node_run=loop_run,
            error=WorkflowError(
                code="NODE_RUN_LIMIT",
                message=f"This run would take more than {limit} steps",
                details={"limit": limit, "index": index},
                bypassable=False,
            ),
            now=datetime.now(UTC),
        )
        return []
    scope_path = [*loop_run.scope_path, {"loop_node_id": str(loop_id), "index": index}]
    item_id = next(
        edge.target_node_id
        for edge in graph.edges
        if edge.source_node_id == loop_id and edge.source_port == BODY_PORT
    )
    item_run = await _create_decided_node_run(
        db, run=run, target_id=item_id, runs=True, scope_path=scope_path
    )
    if item_run is None:  # pragma: no cover - the run's lock serializes every iteration start
        return []
    await events.append(
        db,
        run=run,
        kind=events.EventKind.ITERATION_STARTED,
        node_run_id=loop_run.id,
        payload={"index": index, "count": len(items)},
    )
    await _settle_synthetic(
        db,
        run=run,
        node_run=item_run,
        output=LoopItemOutput(item=items[index], index=index, count=len(items)),
    )
    return await _advance(
        db, run=run, completed_node_instance_id=item_id, scope_path=scope_path, graph=graph
    )


async def _end_iteration_if_settled(
    db: AsyncSession, *, run: WorkflowRun, graph: WorkflowGraph, scope_path: ScopePath
) -> list[tuple[UUID, UUID]]:
    """End the iteration once every node its loop owns directly has settled in it."""
    loop_id = _loop_of(scope_path)
    body = {node_id for node_id, owner in node_scope_map(graph).items() if owner == loop_id}
    rows = await workflow_run_repo.list_node_runs_at(
        db, workflow_run_id=run.id, scope_path=scope_path
    )
    if len(rows) < len(body) or any(row.status not in _SETTLED for row in rows):
        return []
    return await _iteration_ended(db, run=run, graph=graph, scope_path=scope_path)


async def _iteration_ended(
    db: AsyncSession, *, run: WorkflowRun, graph: WorkflowGraph, scope_path: ScopePath
) -> list[tuple[UUID, UUID]]:
    """Start the next iteration, or close the loop after its last."""
    loop_run = await _loop_run(db, run=run, scope_path=scope_path)
    items = await _frozen_items(db, loop_run)
    index = int(scope_path[-1]["index"]) + 1
    if index < len(items):
        return await _start_iteration(
            db, run=run, graph=graph, loop_run=loop_run, index=index, items=items
        )
    return await _close_loop(db, run=run, graph=graph, loop_run=loop_run, count=len(items))


async def _close_loop(
    db: AsyncSession, *, run: WorkflowRun, graph: WorkflowGraph, loop_run: NodeRun, count: int
) -> list[tuple[UUID, UUID]]:
    """Collect every iteration's result in input order, settle the loop, and advance it.

    An iteration's result is what its `loop.yield` handed back - `null` if its
    branch never reached one - and an iteration that failed under `collect` adds
    its error to `errors`. A failure a node routed through its own `error` port
    was handled inside the iteration and is not one of them.
    """
    loop_id = loop_run.node_instance_id
    node_scope = node_scope_map(graph)
    body = [node_id for node_id, owner in node_scope.items() if owner == loop_id]
    depth = len(loop_run.scope_path)
    rows = [
        row
        for row in await workflow_run_repo.list_node_runs_of(
            db, workflow_run_id=run.id, node_instance_ids=body
        )
        if row.scope_path[:depth] == loop_run.scope_path and len(row.scope_path) == depth + 1
    ]
    attempts = await workflow_run_repo.get_latest_attempts(
        db, node_run_ids=[row.id for row in rows if row.status in _SETTLED]
    )
    results: list[Any] = [None] * count
    errors: list[ForeachItemError] = []
    for row in rows:
        index = int(row.scope_path[-1]["index"])
        stored = attempts.get(row.id)
        stored_result = stored.result if stored is not None and stored.result else {}
        definition_id = graph.node_by_id[row.node_instance_id].definition_id
        if definition_id == LOOP_YIELD and row.status == NodeRunStatus.SUCCEEDED.value:
            results[index] = (stored_result.get("output") or {}).get("value")
        elif (
            row.status == NodeRunStatus.FAILED.value
            and not graph.node_by_id[row.node_instance_id].routes_errors
        ):
            error = WorkflowError.model_validate(stored_result.get("error"))
            errors.append(
                ForeachItemError(
                    index=index, code=error.code, message=error.message, details=error.details
                )
            )
    errors.sort(key=lambda error: error.index)
    await _settle_synthetic(
        db,
        run=run,
        node_run=loop_run,
        output=ForeachOutput(results=results, errors=errors, count=count),
    )
    return await _advance(
        db,
        run=run,
        completed_node_instance_id=loop_id,
        scope_path=loop_run.scope_path,
        graph=graph,
    )


async def _loop_run(db: AsyncSession, *, run: WorkflowRun, scope_path: ScopePath) -> NodeRun:
    """The row of the loop whose iteration `scope_path` names."""
    loop_id = _loop_of(scope_path)
    loop_run = (
        await workflow_run_repo.get_node_run_by_identity(
            db, workflow_run_id=run.id, node_instance_id=loop_id, scope_path=scope_path[:-1]
        )
        if loop_id is not None
        else None
    )
    if loop_run is None:  # pragma: no cover - an iteration is only ever started from its loop's row
        raise WorkflowGraphUnresolvableError(run_id=run.id)
    return loop_run


async def _frozen_items(db: AsyncSession, loop_run: NodeRun) -> list[Any]:
    """The list the loop froze into its first attempt - never the source it was bound from."""
    latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=loop_run.id)
    output = (latest.result or {}).get("output") if latest is not None else None
    return ForeachManifest.model_validate(output).items


async def _settle_synthetic(
    db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun, output: BaseModel
) -> None:
    """Record an output the dispatcher itself produced, as a completed attempt.

    A `loop.item`'s element, a loop's collected results: nothing is called, but
    the value is stored where every binding reads one - the node's latest
    attempt - so a body node resolves `loop.item` and a node after the loop
    resolves its `results` through the ordinary lookup.
    """
    now = datetime.now(UTC)
    latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=node_run.id)
    attempt = await workflow_run_repo.create_attempt(
        db,
        organization_id=run.organization_id,
        node_run_id=node_run.id,
        attempt_no=(latest.attempt_no if latest is not None else 0) + 1,
        idempotency_key=idempotency_key(
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_instance_id=node_run.node_instance_id,
            scope_path=node_run.scope_path,
        ),
        # No guarantee, because no call: what marks the attempt as the
        # dispatcher's own record rather than a try at the node's effect.
        retry_guarantee=None,
        started_at=now,
    )
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.COMPLETED.value,
        # Dumped from the concrete model: `Completed[BaseModel]` would serialize
        # through the base class and store `{}`.
        result={"status": "completed", "output": output.model_dump(mode="json")},
        cost=Decimal(0),
        cost_is_partial=False,
        ended_at=now,
    )
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": NodeRunStatus.SUCCEEDED.value,
            "started_at": node_run.started_at or now,
            "ended_at": now,
        },
    )
    await events.append(db, run=run, kind=events.EventKind.NODE_COMPLETED, node_run_id=node_run.id)


async def _succeed_run(db: AsyncSession, *, run: WorkflowRun) -> None:
    await workflow_run_repo.update_run(
        db,
        run=run,
        update_data={
            "status": WorkflowRunStatus.SUCCEEDED.value,
            "ended_at": datetime.now(UTC),
            "paused_reason": None,
        },
    )
    await events.append(db, run=run, kind=events.EventKind.RUN_SUCCEEDED)
    await delivery.deliver_result(db, run=run)


__all__ = [
    "BegunAttempt",
    "HandlerOutcome",
    "begin_attempt",
    "call_handler",
    "claim",
    "idempotency_key",
    "renew_lease",
    "resolve_graph",
    "resolve_orphaned_attempt",
    "settle",
]
