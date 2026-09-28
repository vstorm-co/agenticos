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

Every valid graph in this module's practical scope is a single linear chain:
#1786 ships no `control`-kind node, and rule 8 (`app.workflows.graph.validate.
_rule_8_no_parallel_fanout`) forbids a non-control node from fanning its
output out to more than one edge - so "advance the graph" here never needs to
reason about branch/skip semantics. That is #1790's `control.foreach`/
`logic.if` machinery, co-designed with the concrete nodes it dispatches; this
module implements the DAG-general mechanism those nodes will run on top of,
not their branch-local skip rules.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeGuard
from uuid import UUID, uuid4

from pydantic import BaseModel
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
from app.repositories import workflow_run as workflow_run_repo
from app.services.access import WORKFLOW, resolve_access
from app.services.workflow_execution import budget, context, events
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
from app.workflows.contracts.io import (
    BindingSource,
    FileRef,
    LiteralValue,
    NodeOutputRef,
    TableIORef,
)
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
    Waiting,
    WorkflowError,
)
from app.workflows.graph.model import NodeInstance, WorkflowGraph

logger = logging.getLogger(__name__)

# The `NodeRun` statuses a claimed outbox row may still start an attempt for.
_DISPATCHABLE = frozenset(
    {NodeRunStatus.PENDING.value, NodeRunStatus.RUNNING.value, NodeRunStatus.WAITING.value}
)


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
        return WorkflowGraph.model_validate(raw)
    except PydanticValidationError as exc:
        raise WorkflowGraphUnresolvableError(run_id=run.id) from exc


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
    if isinstance(source, LiteralValue):
        return source.value
    if isinstance(source, NodeOutputRef):
        value: Any = outputs.get(source.node_id)
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
    db: AsyncSession, *, workflow_run_id: UUID, node_ids: set[UUID]
) -> dict[UUID, dict[str, Any] | None]:
    """The stored `Completed.output` of each named node, for `NodeOutputRef` binding sources.

    Looked up by `(workflow_run_id, node_instance_id, scope_path=[])` - every
    graph this module dispatches is a single top-level chain (see the module
    docstring), so there is never more than one live scope to disambiguate.
    """
    outputs: dict[UUID, dict[str, Any] | None] = {}
    for node_id in node_ids:
        source_run = await workflow_run_repo.get_node_run_by_identity(
            db, workflow_run_id=workflow_run_id, node_instance_id=node_id, scope_path=[]
        )
        if source_run is None:
            outputs[node_id] = None
            continue
        latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=source_run.id)
        if (
            latest is None
            or latest.status != NodeAttemptStatus.COMPLETED.value
            or latest.result is None
        ):
            outputs[node_id] = None
            continue
        outputs[node_id] = latest.result.get("output")
    return outputs


@dataclass(frozen=True, slots=True)
class _ResolvedCall:
    """Everything a node's call needs that the run's own rows decide."""

    node: NodeInstance
    definition: NodeDefinition
    handler: NodeHandler
    config: BaseModel | None
    input: BaseModel | None


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
    if definition.handler is None:
        raise NodeHandlerMissingError(node_id=node.definition_id, version=node.definition_version)

    referenced_nodes = {
        binding.source.node_id
        for binding in graph.bindings
        if binding.target_node_id == node.id and isinstance(binding.source, NodeOutputRef)
    }
    outputs = await _completed_outputs(db, workflow_run_id=run.id, node_ids=referenced_nodes)
    try:
        config_obj, input_obj = _resolve_io(graph, node, definition, outputs=outputs)
    except PydanticValidationError as exc:
        # `validate_graph`'s rule 9 only confirms a bound field exists; a
        # `FileRef`/`TableIORef` source is never checked against the target
        # field's own type, so this can fail on a published graph too.
        raise InvalidBindingError(node_instance_id=node.id) from exc
    return _ResolvedCall(
        node=node,
        definition=definition,
        handler=definition.handler,
        config=config_obj,
        input=input_obj,
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
    # Always the definition's own static value: `NodeAttempt.retry_guarantee`
    # is nullable in the schema for a per-*call* override the design allows
    # ("a guarantee is sometimes a property of the call, not the node kind" -
    # `http.request`'s safety to retry depends on the method actually bound,
    # not on `http.request` as a node kind) - but writing one needs a channel
    # from the handler back to this row that no #1788-scope node (`debug.echo`,
    # always `idempotent`) exercises, and the frozen `NodeHandler`/`NodeResult`
    # contract (#1786) has no field to carry it. Left for whichever future
    # node first needs it to add, the same way `context.report_waiting_agent_run`
    # added a channel for `Waiting(reason="approval")` without touching that
    # contract - not stubbed speculatively here.
    attempt = await workflow_run_repo.create_attempt(
        db,
        organization_id=run.organization_id,
        node_run_id=node_run.id,
        attempt_no=attempt_no,
        idempotency_key=key,
        retry_guarantee=definition.retry_guarantee,
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
            result = await begun.handler(begun.handler_config, begun.handler_input)
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


def _backoff_seconds(step: int) -> float:
    """The wait before the next attempt: the base, doubled per `step` after the first."""
    seconds = settings.WORKFLOW_RETRY_BACKOFF_BASE_SECONDS * (2 ** (max(step, 1) - 1))
    return min(seconds, settings.WORKFLOW_RETRY_BACKOFF_MAX_SECONDS)


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
        failures = await workflow_run_repo.count_failed_attempts(db, node_run_id=node_run.id)
        if failures >= settings.WORKFLOW_RETRY_CEILING:
            await _fail_node_and_run(
                db,
                run=run,
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
            available_at=now + timedelta(seconds=_backoff_seconds(failures)),
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
        return await _settle_completed(db, run=run, node_run=node_run, now=now)
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
    elif isinstance(result, Failed):
        await _settle_failed(
            db, run=run, node_run=node_run, attempt=attempt, result=result, now=now
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
    db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun, now: datetime
) -> list[tuple[UUID, UUID]]:
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
    return await _advance(db, run=run, completed_node_instance_id=node_run.node_instance_id)


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
    if result.reason == WaitingReason.APPROVAL.value and waiting_agent_run_id is None:
        # The one invariant that makes an approval wait durable: a handler
        # declaring `Waiting(reason="approval")` must also report the
        # `agent_runs` row through `context.report_waiting_agent_run` -
        # without it, `NodeRun.waiting_agent_run_id` stays null and neither
        # the direct wake (`find_node_run_waiting_on_agent_run`) nor
        # `workflow-reconcile`'s backstop (`list_stale_approval_waits`) has
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
) -> None:
    # #1790 owns the real policy; the minimal placeholder this design calls
    # for is "idempotent/at_least_once nodes get a fixed small ceiling of
    # backoff retries, none gets zero" - narrowed further by the node's own
    # `WorkflowError.retryable`, since a node is in a better position than
    # this generic dispatcher to say a given failure (a validation error, say)
    # is not worth trying again even when its kind usually is.
    retryable = attempt.retry_guarantee != RetryGuarantee.NONE.value and result.error.retryable
    # Counted over failed and interrupted attempts only (this one included,
    # recorded before this runs): a wait is not a failure.
    failures = await workflow_run_repo.count_failed_attempts(db, node_run_id=node_run.id)
    if retryable and failures < settings.WORKFLOW_RETRY_CEILING:
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
            available_at=now + timedelta(seconds=_backoff_seconds(failures)),
        )
        return

    # Retries exhausted, or this failure was never retryable in the first
    # place - #1790 owns the real ceiling and any error-routing policy; this
    # is the minimal placeholder the design calls for.
    await _fail_node_and_run(db, run=run, node_run=node_run, error=result.error, now=now)


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
    db: AsyncSession, *, run: WorkflowRun, completed_node_instance_id: UUID
) -> list[tuple[UUID, UUID]]:
    """After a node succeeds: queue what is now ready, or close out the run.

    Every graph this dispatches is a single chain (module docstring), so
    "ready" reduces to "every predecessor of this edge's target has
    succeeded" - no branch, no fan-in beyond a chain's own single edge.
    Returns what it queued, for the caller to submit after commit.
    """
    ready_pairs: list[tuple[UUID, UUID]] = []
    graph = await resolve_graph(db, run)
    downstream_edges = [
        edge for edge in graph.edges if edge.source_node_id == completed_node_instance_id
    ]
    if not downstream_edges:
        await _succeed_if_finished(db, run=run, graph=graph)
        return ready_pairs

    for edge in downstream_edges:
        target = graph.node_by_id.get(edge.target_node_id)
        if target is None:
            continue
        if await workflow_run_repo.get_node_run_by_identity(
            db, workflow_run_id=run.id, node_instance_id=target.id, scope_path=[]
        ):
            continue  # already created by a concurrent settle of a sibling edge
        predecessor_ids = {e.source_node_id for e in graph.edges if e.target_node_id == target.id}
        ready = True
        for predecessor_id in predecessor_ids:
            predecessor_run = await workflow_run_repo.get_node_run_by_identity(
                db, workflow_run_id=run.id, node_instance_id=predecessor_id, scope_path=[]
            )
            if predecessor_run is None or predecessor_run.status not in (
                NodeRunStatus.SUCCEEDED.value,
                NodeRunStatus.SKIPPED.value,
            ):
                ready = False
                break
        if not ready:
            continue
        # A target with more than one predecessor can be found "ready" by two
        # sibling settle transactions at once - each already checked the row
        # does not exist yet, above, in its own snapshot. The unique index on
        # `(workflow_run_id, node_instance_id, scope_path)` is what actually
        # decides; the loser reads its own `IntegrityError` back as "the other
        # transaction already created it" inside a savepoint, the same shape
        # `UserService.confirm_email_change` uses for its own insert race,
        # rather than letting it escape and abort this whole settle.
        try:
            async with db.begin_nested():
                node_run = await workflow_run_repo.create_node_run(
                    db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    node_instance_id=target.id,
                    scope_path=[],
                )
        except IntegrityError:
            continue
        # Stamped submitted: the settling flow submits it straight after this
        # transaction commits, so a chain's next node starts as soon as its
        # predecessor settles instead of waiting out the poll - and the poll
        # does not submit it a second time.
        await workflow_run_repo.create_outbox(
            db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            submitted=True,
        )
        ready_pairs.append((run.id, node_run.id))
    return ready_pairs


async def _succeed_if_finished(
    db: AsyncSession, *, run: WorkflowRun, graph: WorkflowGraph | None = None
) -> None:
    """Mark `run` succeeded if every node of its graph has, and nothing is left to dispatch.

    Called under the run's lock, both when the last node settles and when a
    stray outbox row is closed, so whichever of the two happens last ends
    the run.
    """
    if await workflow_run_repo.has_live_outbox(db, workflow_run_id=run.id):
        return
    graph = graph or await resolve_graph(db, run)
    statuses = await workflow_run_repo.list_node_run_statuses(db, workflow_run_id=run.id)
    finished = {NodeRunStatus.SUCCEEDED.value, NodeRunStatus.SKIPPED.value}
    if len(statuses) == len(graph.nodes) and all(status in finished for status in statuses):
        await _succeed_run(db, run=run)


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
