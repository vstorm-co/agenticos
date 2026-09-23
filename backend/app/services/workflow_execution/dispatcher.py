"""The dispatch tick: claim one outbox row, run one node attempt, advance the graph.

Three phases, deliberately split across three separate, short transactions -
see `docs/plans/1788-durable-execution.md`'s "Prefect: a flow per dispatch
tick" section for why:

1. `claim` - the compare-and-swap that decides which worker, if any, owns
   this `NodeRun` right now. Its own transaction.
2. `begin_attempt` - loads the run, the graph and the node, resolves the
   node's config/input, and commits a `NodeAttempt` row `in_flight` *before*
   the handler is ever called. Its own transaction, and the row it writes is
   the one the reconciler needs to exist if the process dies in step 3.
3. The handler runs **outside any transaction** (`app.worker.tasks.
   workflow_tasks` is what actually calls it, between two `get_worker_db_context`
   blocks) - a long-running or hung external call must never hold a pooled
   connection idle.
4. `settle` - a third transaction: persists the attempt's terminal result,
   transitions the `NodeRun`, accumulates cost, appends a `WorkflowEvent`, and
   - on `Completed` - advances the graph by creating the next `NodeRun`(s)
   and `DispatchOutbox` row(s), all in one commit. `DispatchOutbox` is a
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
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.workflow_run import (
    DispatchOutbox,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    RetryGuarantee,
    WaitingReason,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import member as member_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import budget, context, events
from app.workflows import _registry
from app.workflows.contracts.definition import NodeDefinition
from app.workflows.contracts.io import (
    BindingSource,
    FileRef,
    LiteralValue,
    NodeOutputRef,
    TableIORef,
)
from app.workflows.contracts.results import Completed, Failed, NodeResult, Uncertain, Waiting
from app.workflows.graph.model import NodeInstance, WorkflowGraph

logger = logging.getLogger(__name__)


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
    dispatch_context: context.DispatchContext


async def claim(
    db: AsyncSession,
    *,
    node_run_id: UUID,
    lease_seconds: float = settings.WORKFLOW_DISPATCH_LEASE_SECONDS,
) -> DispatchOutbox | None:
    """Phase 1: try to own this node's dispatch row.

    Returns `None` when there was nothing claimable - the row was already
    claimed by a live lease, already `done`/`cancelled`, or not yet
    `available_at`. None of those is an error: the caller (`workflow_tasks.
    workflow_dispatch_node_flow`) simply stops.
    """
    token = uuid4()
    lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    return await workflow_run_repo.claim_outbox(
        db, node_run_id=node_run_id, token=token, lease_expires_at=lease_expires_at
    )


async def resolve_graph(db: AsyncSession, run: WorkflowRun) -> WorkflowGraph:
    """The graph this run executes - a published version, or a draft snapshot."""
    if run.workflow_version_id is not None:
        version = await workflow_repo.get_version(
            db, run.workflow_version_id, organization_id=run.organization_id
        )
        if version is None:
            raise RuntimeError(
                f"WorkflowRun {run.id} names workflow_version_id {run.workflow_version_id}, "
                "which no longer resolves"
            )
        return WorkflowGraph.model_validate(version.graph)
    if run.draft_graph_snapshot is None:
        raise RuntimeError(f"WorkflowRun {run.id} has neither a version nor a draft snapshot")
    return WorkflowGraph.model_validate(run.draft_graph_snapshot)


async def _auth_context_for(db: AsyncSession, run: WorkflowRun) -> AuthContext:
    """The `AuthContext` a node handler acts with - built from the principal
    pinned at admission, never from a request that no longer exists by the
    time a parked node wakes.
    """
    role = ""
    if run.execution_principal_user_id is not None:
        member = await member_repo.get_active(
            db, organization_id=run.organization_id, user_id=run.execution_principal_user_id
        )
        if member is not None:
            role = member.role
    return AuthContext(
        user_id=run.execution_principal_user_id, organization_id=run.organization_id, role=role
    )


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


async def begin_attempt(
    db: AsyncSession, *, workflow_run_id: UUID, node_run_id: UUID, token: UUID
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

    Returns `None` when dispatch is refused *before* any attempt is created -
    the claim was lost to a reclaim, the run is already terminal or
    cancelled (a race with `cancel`), past its deadline, or over budget. Each
    of those short-circuits does its own bookkeeping (closing the outbox
    row, transitioning the run) and leaves nothing for `settle` to do.
    """
    run = await workflow_run_repo.get_run_by_id_for_update(db, workflow_run_id)
    node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, node_run_id)
    if run is None or node_run is None:
        logger.error(
            "workflow_dispatch_missing_row",
            extra={"workflow_run_id": str(workflow_run_id), "node_run_id": str(node_run_id)},
        )
        return None
    outbox = await workflow_run_repo.get_outbox_for_node_run(db, node_run_id=node_run_id)

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

    if WorkflowRunStatus(run.status).is_terminal or node_run.status in (
        NodeRunStatus.CANCELLED.value,
        NodeRunStatus.SKIPPED.value,
    ):
        # `outbox` is never `None` past the token check above - only ever
        # closing the row this worker was just confirmed to still own.
        await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
        return None

    now = datetime.now(UTC)
    if budget.past_deadline(run, at=now):
        await _fail_run(
            db,
            run=run,
            node_run=node_run,
            outbox=outbox,
            code="DEADLINE_EXCEEDED",
            message="This run's deadline passed before this node could be dispatched",
        )
        return None
    if budget.over_budget(run):
        await workflow_run_repo.update_run(
            db, run=run, update_data={"status": WorkflowRunStatus.BUDGET_EXCEEDED.value}
        )
        await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
        await events.append(
            db, run=run, kind=events.EventKind.RUN_BUDGET_EXCEEDED, node_run_id=node_run.id
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

    graph = await resolve_graph(db, run)
    node = graph.node_by_id[node_run.node_instance_id]
    definition = _registry.get(node.definition_id, node.definition_version)

    referenced_nodes = {
        binding.source.node_id
        for binding in graph.bindings
        if binding.target_node_id == node.id and isinstance(binding.source, NodeOutputRef)
    }
    outputs = await _completed_outputs(db, workflow_run_id=run.id, node_ids=referenced_nodes)
    config_obj, input_obj = _resolve_io(graph, node, definition, outputs=outputs)

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
    auth = await _auth_context_for(db, run)
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
    )
    return BegunAttempt(
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        node_instance_id=node.id,
        organization_id=run.organization_id,
        attempt_id=attempt.id,
        attempt_no=attempt_no,
        handler_config=config_obj,
        handler_input=input_obj,
        definition=definition,
        dispatch_context=dispatch_context,
    )


async def call_handler(begun: BegunAttempt) -> tuple[NodeResult, UUID | None]:
    """Phase 3's non-transactional half: run the handler under `dispatching_as`.

    Not called from inside either of `begin_attempt`/`settle`'s sessions -
    `app.worker.tasks.workflow_tasks.workflow_dispatch_node_flow` calls this
    between them, so a slow or hung handler never holds a pooled connection.
    """
    if begun.definition.handler is None:
        raise RuntimeError(f"Node definition {begun.definition.id!r} has no handler registered")
    scope = context.dispatching_as(begun.dispatch_context)
    with scope:
        result = await begun.definition.handler(begun.handler_config, begun.handler_input)
    return result, scope.waiting_agent_run_id


async def _fail_run(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    outbox: DispatchOutbox,
    code: str,
    message: str,
) -> None:
    now = datetime.now(UTC)
    await workflow_run_repo.update_run(
        db,
        run=run,
        update_data={
            "status": WorkflowRunStatus.FAILED.value,
            "ended_at": now,
            "error": {"code": code, "message": message, "details": {}, "retryable": False},
        },
    )
    await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
    await events.append(
        db,
        run=run,
        kind=events.EventKind.RUN_FAILED,
        node_run_id=node_run.id,
        payload={"code": code},
    )
    await workflow_run_repo.cancel_live_outbox_for_run(db, workflow_run_id=run.id)


def _backoff_seconds(attempt_no: int) -> float:
    seconds = settings.WORKFLOW_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt_no - 1))
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
    whose previous claim already got this far) and
    `app.services.workflow_execution.reconciler` (the standalone sweep that
    finds the same shape on its own schedule, with no dispatch trigger at
    all).
    """
    now = datetime.now(UTC)
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.UNCERTAIN.value,
        result=None,
        cost=Decimal(0),
        cost_is_partial=False,
        ended_at=now,
    )
    if outbox is not None:
        await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
    await events.append(
        db,
        run=run,
        kind=events.EventKind.ATTEMPT_RECLAIMED,
        node_run_id=node_run.id,
        payload={"attempt_no": attempt.attempt_no, "retry_guarantee": attempt.retry_guarantee},
    )
    if attempt.retry_guarantee == RetryGuarantee.IDEMPOTENT.value:
        await workflow_run_repo.create_outbox(
            db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            available_at=now,
        )
        return

    await workflow_run_repo.update_node_run(
        db, node_run=node_run, update_data={"status": NodeRunStatus.NEEDS_ATTENTION.value}
    )
    await events.append(
        db,
        run=run,
        kind=events.EventKind.NODE_UNCERTAIN,
        node_run_id=node_run.id,
        payload={
            "detail": "Reclaimed after an interrupted attempt with no safe automatic resolution"
        },
    )
    await workflow_run_repo.update_run(
        db, run=run, update_data={"status": WorkflowRunStatus.NEEDS_ATTENTION.value}
    )
    await events.append(
        db, run=run, kind=events.EventKind.RUN_NEEDS_ATTENTION, node_run_id=node_run.id
    )


def _terminal_attempt_status(result: NodeResult) -> str:
    """The `NodeAttempt` status each `NodeResult` variant settles to, on its
    own - shared by the ordinary path and the two short-circuits below, so
    all three agree on what actually happened to the attempt even when the
    run itself no longer cares."""
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
    db: AsyncSession, *, begun: BegunAttempt, result: NodeResult, waiting_agent_run_id: UUID | None
) -> None:
    """Phase 4: persist the attempt's terminal outcome and advance the run."""
    run = await workflow_run_repo.get_run_by_id_for_update(db, begun.workflow_run_id)
    node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, begun.node_run_id)
    attempt = await workflow_run_repo.get_attempt(db, begun.attempt_id)
    if run is None or node_run is None or attempt is None:
        logger.error(
            "workflow_dispatch_settle_missing_row", extra={"attempt_id": str(begun.attempt_id)}
        )
        return
    now = datetime.now(UTC)

    # A stale settle: the lease expired while the handler was genuinely still
    # running, `workflow-reconcile` already resolved this same attempt (to
    # `uncertain`, possibly dispatching a fresh one in its place), and only
    # afterward does the original, still-running handler finally return. That
    # verdict must not be silently overwritten by a late result arriving for
    # an attempt that is no longer "current" - `attempt.status` moving off
    # `in_flight` is exactly what says a different settle (or the reconciler)
    # already had the last word on this attempt.
    if attempt.status != NodeAttemptStatus.IN_FLIGHT.value:
        logger.warning(
            "workflow_dispatch_settle_stale_attempt",
            extra={"attempt_id": str(attempt.id), "attempt_status": attempt.status},
        )
        return

    # A run cancelled while this handler was running must stay cancelled: the
    # attempt itself still settles honestly (what actually happened is worth
    # recording), but as a terminal `NodeRun` outcome with no run-status
    # transition and no `_advance` - `cancel()` already closed every outbox
    # row, so there is nothing left to dispatch even if this had completed.
    if WorkflowRunStatus(run.status).is_terminal:
        await workflow_run_repo.settle_attempt(
            db,
            attempt=attempt,
            status=_terminal_attempt_status(result),
            result=result.model_dump(mode="json"),
            cost=Decimal(0),
            cost_is_partial=False,
            ended_at=now,
        )
        await workflow_run_repo.update_node_run(
            db,
            node_run=node_run,
            update_data={"status": NodeRunStatus.CANCELLED.value, "ended_at": now},
        )
        outbox = await workflow_run_repo.get_outbox_for_node_run(db, node_run_id=node_run.id)
        if outbox is not None:
            await workflow_run_repo.mark_outbox_done(db, outbox=outbox)
        return

    outbox = await workflow_run_repo.get_outbox_for_node_run(db, node_run_id=node_run.id)
    # Closed *before* dispatching to a `_settle_*` handler: `_settle_completed`
    # calls `_advance`, which decides the run is done by checking whether any
    # live outbox row remains - and this node's own row is still `claimed`
    # until this closes it. Checking that after closing it, rather than
    # before, is what makes "no live outbox left" actually mean it.
    if outbox is not None:
        await workflow_run_repo.mark_outbox_done(db, outbox=outbox)

    if isinstance(result, Completed):
        await _settle_completed(
            db, run=run, node_run=node_run, attempt=attempt, result=result, now=now
        )
    elif isinstance(result, Waiting):
        await _settle_waiting(
            db,
            run=run,
            node_run=node_run,
            attempt=attempt,
            result=result,
            waiting_agent_run_id=waiting_agent_run_id,
            now=now,
        )
    elif isinstance(result, Failed):
        await _settle_failed(
            db, run=run, node_run=node_run, attempt=attempt, result=result, now=now
        )
    elif isinstance(result, Uncertain):
        await _settle_uncertain(
            db, run=run, node_run=node_run, attempt=attempt, result=result, now=now
        )
    else:  # pragma: no cover - NodeResult is a closed discriminated union
        raise TypeError(f"Unknown NodeResult variant: {result!r}")


async def _settle_completed(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    attempt: NodeAttempt,
    result: Completed[Any],
    now: datetime,
) -> None:
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.COMPLETED.value,
        result=result.model_dump(mode="json"),
        cost=Decimal(0),
        cost_is_partial=False,
        ended_at=now,
    )
    await workflow_run_repo.update_node_run(
        db,
        node_run=node_run,
        update_data={
            "status": NodeRunStatus.SUCCEEDED.value,
            "ended_at": now,
            "waiting_reason": None,
            "resume_token": None,
        },
    )
    await events.append(db, run=run, kind=events.EventKind.NODE_COMPLETED, node_run_id=node_run.id)
    await _advance(db, run=run, completed_node_instance_id=node_run.node_instance_id)


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
    # The attempt itself succeeded - it started a real effect and parked, a
    # known and handled pause, not an error - so it settles `completed`.
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.COMPLETED.value,
        result=result.model_dump(mode="json"),
        cost=Decimal(0),
        cost_is_partial=False,
        ended_at=now,
    )

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
        await workflow_run_repo.update_node_run(
            db, node_run=node_run, update_data={"status": NodeRunStatus.NEEDS_ATTENTION.value}
        )
        await events.append(
            db,
            run=run,
            kind=events.EventKind.NODE_UNCERTAIN,
            node_run_id=node_run.id,
            payload={"detail": "Node declared an approval wait with no agent run to resume it"},
        )
        await workflow_run_repo.update_run(
            db, run=run, update_data={"status": WorkflowRunStatus.NEEDS_ATTENTION.value}
        )
        await events.append(
            db, run=run, kind=events.EventKind.RUN_NEEDS_ATTENTION, node_run_id=node_run.id
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


async def _settle_failed(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    attempt: NodeAttempt,
    result: Failed,
    now: datetime,
) -> None:
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.FAILED.value,
        result=result.model_dump(mode="json"),
        cost=Decimal(0),
        cost_is_partial=False,
        ended_at=now,
    )
    # #1790 owns the real policy; the minimal placeholder this design calls
    # for is "idempotent/at_least_once nodes get a fixed small ceiling of
    # backoff retries, none gets zero" - narrowed further by the node's own
    # `WorkflowError.retryable`, since a node is in a better position than
    # this generic dispatcher to say a given failure (a validation error, say)
    # is not worth trying again even when its kind usually is.
    retryable = attempt.retry_guarantee != "none" and result.error.retryable
    if retryable and attempt.attempt_no < settings.WORKFLOW_RETRY_CEILING:
        await workflow_run_repo.update_node_run(
            db,
            node_run=node_run,
            update_data={
                "status": NodeRunStatus.WAITING.value,
                "waiting_reason": WaitingReason.RETRY_BACKOFF.value,
            },
        )
        await events.append(
            db,
            run=run,
            kind=events.EventKind.NODE_RETRYING,
            node_run_id=node_run.id,
            payload={"attempt_no": attempt.attempt_no, "error": result.error.code},
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
            available_at=now + timedelta(seconds=_backoff_seconds(attempt.attempt_no)),
        )
        return

    # Retries exhausted, or this failure was never retryable in the first
    # place - #1790 owns the real ceiling and any error-routing policy; this
    # is the minimal placeholder the design calls for.
    await workflow_run_repo.update_node_run(
        db, node_run=node_run, update_data={"status": NodeRunStatus.FAILED.value, "ended_at": now}
    )
    await events.append(
        db,
        run=run,
        kind=events.EventKind.NODE_FAILED,
        node_run_id=node_run.id,
        payload={"error": result.error.code},
    )
    await workflow_run_repo.update_run(
        db,
        run=run,
        update_data={
            "status": WorkflowRunStatus.FAILED.value,
            "ended_at": now,
            "error": result.error.model_dump(mode="json"),
        },
    )
    await events.append(db, run=run, kind=events.EventKind.RUN_FAILED, node_run_id=node_run.id)
    await workflow_run_repo.cancel_live_outbox_for_run(db, workflow_run_id=run.id)


async def _settle_uncertain(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run: NodeRun,
    attempt: NodeAttempt,
    result: Uncertain,
    now: datetime,
) -> None:
    await workflow_run_repo.settle_attempt(
        db,
        attempt=attempt,
        status=NodeAttemptStatus.UNCERTAIN.value,
        result=result.model_dump(mode="json"),
        cost=Decimal(0),
        cost_is_partial=False,
        ended_at=now,
    )
    await workflow_run_repo.update_node_run(
        db, node_run=node_run, update_data={"status": NodeRunStatus.NEEDS_ATTENTION.value}
    )
    await events.append(
        db,
        run=run,
        kind=events.EventKind.NODE_UNCERTAIN,
        node_run_id=node_run.id,
        payload={"detail": result.detail},
    )
    await workflow_run_repo.update_run(
        db, run=run, update_data={"status": WorkflowRunStatus.NEEDS_ATTENTION.value}
    )
    await events.append(
        db, run=run, kind=events.EventKind.RUN_NEEDS_ATTENTION, node_run_id=node_run.id
    )


async def _advance(db: AsyncSession, *, run: WorkflowRun, completed_node_instance_id: UUID) -> None:
    """After a node succeeds: dispatch what is now ready, or close out the run.

    Every graph this dispatches is a single chain (module docstring), so
    "ready" reduces to "every predecessor of this edge's target has
    succeeded" - no branch, no fan-in beyond a chain's own single edge.
    """
    graph = await resolve_graph(db, run)
    downstream_edges = [
        edge for edge in graph.edges if edge.source_node_id == completed_node_instance_id
    ]
    if not downstream_edges:
        if not await workflow_run_repo.has_live_outbox(db, workflow_run_id=run.id):
            await _succeed_run(db, run=run)
        return

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
        await workflow_run_repo.create_outbox(
            db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            available_at=datetime.now(UTC),
        )


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
    "begin_attempt",
    "call_handler",
    "claim",
    "idempotency_key",
    "resolve_graph",
    "resolve_orphaned_attempt",
    "settle",
]
