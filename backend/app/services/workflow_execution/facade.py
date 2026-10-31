"""`WorkflowExecutionService` - start, cancel, read and tail a workflow run.

The public facade routes call. Mirrors `WorkflowRegistryService`'s own split:
authorization and lifecycle checks happen here, against the *workflow* (a
run has no owner/visibility of its own - it inherits its workflow's), before
anything about the run itself is touched.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import (
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    ResourceRefKind,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
    WorkflowRunTrigger,
)
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_file as workflow_file_repo
from app.repositories import workflow_log_entry as workflow_log_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import StoredWorkflowSettings
from app.schemas.workflow_log_entry import (
    LogFilters,
    WorkflowLogDay,
    WorkflowLogEntryList,
    WorkflowLogEntryRead,
    WorkflowLogSummary,
    WorkflowRecentLogEntry,
    WorkflowRecentLogs,
)
from app.schemas.workflow_run import (
    WorkflowEventList,
    WorkflowEventRead,
    WorkflowFileList,
    WorkflowFileRead,
    WorkflowNodeRunList,
    WorkflowNodeRunRead,
    WorkflowRunFilters,
    WorkflowRunGraph,
    WorkflowRunList,
    WorkflowRunRead,
    WorkflowStepResolve,
    WorkflowStepTest,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.services.workflow_execution import (
    admission,
    budget,
    cleanup,
    delivery,
    dispatch_queue,
    dispatcher,
    events,
    limits,
)
from app.services.workflow_execution.exceptions import (
    WorkflowArchivedError,
    WorkflowBudgetHeldError,
    WorkflowGraphUnresolvableError,
    WorkflowInlineStorageLimitError,
    WorkflowNotRunnableError,
    WorkflowRunAlreadyTerminalError,
    WorkflowRunInputInvalidError,
    WorkflowRunInputTooLargeError,
    WorkflowRunNotFoundError,
    WorkflowRunNotRetryableError,
    WorkflowStepNotFoundError,
    WorkflowStepNotResolvableError,
    WorkflowTriggerMismatchError,
)
from app.services.workflow_execution.run_status import refresh_run_status
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.payload import json_byte_size
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import WorkflowGraph, jsonb_value_fits
from app.workflows.graph.step import step_subgraph
from app.workflows.graph.validate import file_binding_problems, graph_file_refs, validate_graph
from app.workflows.nodes.core_input._handler import TriggerInputConfig, input_problems
from app.workflows.triggers import (
    BY_HAND,
    CHAT,
    DECLARES_FIELDS,
    WORKFLOW_CALL,
    entry_graph,
    entry_nodes,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Causation:
    """Where a run sits in a chain of runs one started another through.

    A table trigger's run is caused by the run whose step wrote the record, or by
    nothing when a person did. `visited_trigger_ids` is every trigger the chain
    has passed through, this one included, which is what lets a trigger that
    would start itself again - directly or round a loop - be refused.
    `public_origin` is the causing run's stored flag: a run an outsider's chain
    causes has no person behind it either.
    """

    root_run_id: UUID | None
    causation_run_id: UUID | None
    visited_trigger_ids: list[str]
    depth: int
    public_origin: bool = False
    impersonated: bool = False
    """The causing run started under impersonation - the chain it starts did too."""


def causes_public(run: WorkflowRun) -> bool:
    """Whether a run `run` causes is stored public: its own stored flag, or a door
    it came through.

    The door half fails closed across a deploy: a door run admitted by code older
    than the stored flag reads false, and without it its chain would not.
    """
    return run.public_origin or run.triggered_by in dispatcher.PUBLIC_TRIGGERS


def _checked_input(run_input: dict[str, Any] | None) -> dict[str, Any]:
    """`run_input` as a run stores it, refused when it is over the size limit.

    Raises:
        WorkflowRunInputTooLargeError: Over `WORKFLOW_RUN_MAX_INPUT_BYTES` as
            compact JSON.
    """
    payload = run_input or {}
    try:
        jsonb_value_fits(payload)
        size = len(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise WorkflowRunInputInvalidError(
            problems=[
                {
                    "field": "input",
                    "message": "Use valid JSON without NUL or unpaired surrogates",
                    "type": "json_invalid",
                }
            ]
        ) from exc
    if size > settings.WORKFLOW_RUN_MAX_INPUT_BYTES:
        raise WorkflowRunInputTooLargeError(limit=settings.WORKFLOW_RUN_MAX_INPUT_BYTES, size=size)
    return payload


def _check_declared_input(graph: WorkflowGraph, payload: dict[str, Any]) -> None:
    """Refuse `payload` when the graph's entry declares fields it does not fit: a Manual,
    API, Form or Called by a workflow trigger.

    Raises:
        WorkflowRunInputInvalidError: A declared field is missing or of the
            wrong type, or the payload has one that is not declared.
    """
    entry = graph.node_by_id[graph.entry_node_id]
    if entry.definition_id not in DECLARES_FIELDS:
        return
    # The graph passed `validate_graph` - at publish, or just now for a draft -
    # so its config fits.
    # Only the fields: a Form trigger's config carries its page's words beside them.
    fields = TriggerInputConfig.model_validate({"fields": entry.config.get("fields", [])})
    problems = input_problems(fields, payload)
    if problems:
        raise WorkflowRunInputInvalidError(problems=problems)


# What a retry starts from: a run that ended without finishing its work.
_RETRYABLE = frozenset(
    {
        WorkflowRunStatus.FAILED.value,
        WorkflowRunStatus.CANCELLED.value,
        WorkflowRunStatus.BUDGET_EXCEEDED.value,
    }
)


def _read(run: WorkflowRun, *, can_cancel: bool = False) -> WorkflowRunRead:
    return WorkflowRunRead(
        can_cancel=can_cancel,
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_version_id=run.workflow_version_id,
        mode=run.mode,
        status=run.status,
        triggered_by=run.triggered_by,
        budget_limit=float(run.budget_limit) if run.budget_limit is not None else None,
        spent_cost=float(budget.total_cost(run)),
        own_cost=float(run.spent_cost),
        cost_is_partial=run.cost_is_partial,
        deadline_at=run.deadline_at,
        paused_reason=run.paused_reason,
        error=run.error,
        output=run.output,
        root_run_id=run.root_run_id,
        causation_run_id=run.causation_run_id,
        retry_of_run_id=run.retry_of_run_id,
        depth=run.depth,
        started_at=run.started_at,
        ended_at=run.ended_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


# The triggers each door a member stands at starts in `real` mode. A version
# whose entry is no trigger starts by hand, as Manual and API do. The unattended
# doors - webhook, schedule, table - run only the version that switched them on.
_DOOR_TRIGGERS: dict[WorkflowRunTrigger, frozenset[str | None]] = {
    WorkflowRunTrigger.API: frozenset({None, *BY_HAND}),
    WorkflowRunTrigger.WEBSOCKET: frozenset({None, *BY_HAND}),
    WorkflowRunTrigger.CHAT: frozenset({CHAT}),
    # An agent's `run_workflow` tool: what a member may start by hand, and what is
    # published to be called, since an agent's call is the same request.
    WorkflowRunTrigger.AGENT: frozenset({None, *BY_HAND, WORKFLOW_CALL}),
    # A page's declared action, started by the member viewing it: only what a person
    # starts by hand. No `None` - a page names a workflow with a trigger.
    WorkflowRunTrigger.APP: frozenset(BY_HAND),
}


class WorkflowExecutionService:
    """Start, cancel, read and tail runs of a workflow."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def start(
        self,
        ctx: AuthContext,
        workflow_id: UUID,
        *,
        mode: WorkflowRunMode = WorkflowRunMode.REAL,
        triggered_by: WorkflowRunTrigger = WorkflowRunTrigger.API,
        run_input: dict[str, Any] | None = None,
        deadline_seconds: int | None = None,
        reply_conversation_id: UUID | None = None,
        step: WorkflowStepTest | None = None,
        entry_node_id: UUID | None = None,
        source_artifact_id: UUID | None = None,
        source_version_number: int | None = None,
        impersonated: bool = False,
    ) -> WorkflowRunRead:
        """Admit a new run of `workflow_id`'s current published version (or,
        in `test` mode, a snapshot of its current draft).

        `step` narrows a test run to one step of the draft: the snapshot keeps
        the step and what leads to it, with the known outputs pinned
        (`app.workflows.graph.step.step_subgraph`), so nothing after it runs.

        `impersonated` says the caller's run started under impersonation, which the run
        stores when the request that started it cannot say so itself (an agent run).

        `run_input` is what `core.input` hands the graph, frozen on the run
        row; it is refused before anything else is checked when it is over
        `WORKFLOW_RUN_MAX_INPUT_BYTES`.

        `deadline_seconds` sets the run's wall-clock deadline from now: a node
        not yet dispatched when it passes is refused and the run fails with
        `DEADLINE_EXCEEDED`. It is checked when a node is dispatched, so a node
        already running, or parked on an approval, is not interrupted by it.

        `reply_conversation_id` is where a chat-started run answers: the
        caller's own conversation, which the chat surface checked belongs to
        them. The run's result is written there when it ends.

        `source_artifact_id` and `source_version_number` record the page and the
        version of it a run started from (`triggered_by = app`).

        Raises:
            NotFoundError: The workflow does not exist, or this caller may
                not reach it.
            AuthorizationError: The caller lacks `workflows:run`.
            WorkflowArchivedError: The workflow is archived - `ARCHIVED`
                keeps a workflow's history and its past runs but refuses new
                ones, in both `real` and `test` mode.
            WorkflowNotRunnableError: `real` mode with no published version,
                or `test` mode with no valid, structurally sound draft graph.
            StepNotTestableError: `step` names a step the draft does not have,
                or one inside a loop.
            WorkflowTriggerMismatchError: `real` mode through a door the live
                version's trigger is not - the API or a WebSocket for a workflow
                that starts from anything but Manual or API, the chat for one
                that does not start from a chat message.
            WorkflowRunInputTooLargeError: `run_input` is over
                `WORKFLOW_RUN_MAX_INPUT_BYTES`.
            WorkflowRunInputInvalidError: The version being run starts from
                Manual or API with declared fields, and `run_input` does not
                fit them.
            WorkflowInlineStorageLimitError: Input and snapshot reservations exceed
                the retained-payload allowance; no run is created.
            WorkflowAdmissionQuotaError: Admitting this run would push the
                organization's or the caller's outstanding node work past its
                ceiling; retried once running work drains.
        """
        payload = _checked_input(run_input)
        workflow = await self._authorize(ctx, workflow_id, Perm.WORKFLOWS_RUN)
        if workflow.status == WorkflowStatus.ARCHIVED.value:
            raise WorkflowArchivedError(
                workflow_id=workflow.id, message="This workflow is archived and cannot be run"
            )
        # `test` mode executes the *draft*, not something an editor already
        # reviewed and froze into a version - `workflows:run` alone (as
        # widened by a mere `USE` grant, `_PERM_MIN_GRANT`) would let a
        # caller who can never edit or even necessarily view this workflow
        # trigger unreviewed, unpublished side effects. `publish` requires
        # the same `workflows:edit`; a test run of the thing `publish` would
        # freeze is held to the same bar.
        if mode is WorkflowRunMode.TEST and not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        graph, workflow_version_id, draft_snapshot, budget_limit = await self._resolve_start_graph(
            ctx, workflow, mode=mode
        )
        candidates = entry_nodes(graph)
        if mode is WorkflowRunMode.REAL:
            allowed = _DOOR_TRIGGERS[triggered_by]
            candidates = [
                node
                for node in candidates
                if node.definition_id in allowed
                or (node.id == graph.entry_node_id and workflow.live_trigger in allowed)
            ]
        if step is not None and entry_node_id is None:
            candidates = [
                node
                for node in candidates
                if step.node_id in entry_graph(graph, node.id).node_by_id
            ]
        selected = next(
            (node for node in candidates if entry_node_id is None or node.id == entry_node_id), None
        )
        if selected is None:
            raise WorkflowTriggerMismatchError(
                workflow_id=workflow.id, trigger=workflow.live_trigger, door=triggered_by.value
            )
        if len(entry_nodes(graph)) > 1 or selected.id != graph.entry_node_id:
            graph = entry_graph(graph, selected.id)
            if mode is WorkflowRunMode.TEST:
                draft_snapshot = graph.model_dump(mode="json")
        if step is not None:
            graph = step_subgraph(graph, step.node_id, step.outputs)
            draft_snapshot = graph.model_dump(mode="json")
        _check_declared_input(graph, payload)
        run, _entry = await self._admit(
            ctx,
            workflow,
            graph=graph,
            workflow_version_id=workflow_version_id,
            draft_snapshot=draft_snapshot,
            budget_limit=budget_limit,
            mode=mode,
            triggered_by=triggered_by,
            payload=payload,
            deadline_seconds=deadline_seconds,
            reply_conversation_id=reply_conversation_id,
            source_artifact_id=source_artifact_id,
            source_version_number=source_version_number,
            impersonated=impersonated,
        )
        return _read(run)

    async def admit_pinned(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        *,
        triggered_by: WorkflowRunTrigger,
        run_input: dict[str, Any],
        causation: Causation | None = None,
        entry_node_id: UUID | None = None,
    ) -> tuple[WorkflowRun, UUID]:
        """Admit a run of one pinned version as `ctx` - a webhook's, a schedule's, a
        table trigger's or a failure's fire. `causation` places it in a chain of runs.

        The exposure layer has already decided `ctx` may run `workflow` and that
        it is not archived; this is the rest of `start`, on the version the
        exposure pinned rather than the workflow's current one. Returns the run
        and its entry node run, whose first dispatch is queued in the caller's own
        transaction: it starts when that commits.

        Raises:
            WorkflowRunInputTooLargeError: `run_input` is over
                `WORKFLOW_RUN_MAX_INPUT_BYTES`.
            WorkflowAdmissionQuotaError: The organization's or the principal's
                outstanding node work would pass its ceiling.
        """
        graph = WorkflowGraph.model_validate(version.graph)
        if entry_node_id is None:
            kind = (
                "trigger.table_record"
                if triggered_by
                in {
                    WorkflowRunTrigger.TABLE_CREATED,
                    WorkflowRunTrigger.TABLE_UPDATED,
                    WorkflowRunTrigger.TABLE_DELETED,
                }
                else f"trigger.{triggered_by.value}"
            )
            entry_node_id = next(
                (node.id for node in entry_nodes(graph) if node.definition_id == kind), None
            )
        if entry_node_id is not None:
            graph = entry_graph(graph, entry_node_id)
        return await self._admit(
            ctx,
            workflow,
            graph=graph,
            workflow_version_id=version.id,
            draft_snapshot=None,
            budget_limit=version.budget_limit,
            mode=WorkflowRunMode.REAL,
            triggered_by=triggered_by,
            payload=_checked_input(run_input),
            deadline_seconds=None,
            reply_conversation_id=None,
            causation=causation,
        )

    async def admit_call(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        *,
        run_input: dict[str, Any],
        causation: Causation,
        parent_node_run_id: UUID,
        retry_of_run_id: UUID | None = None,
    ) -> WorkflowRun:
        """Admit a run of `version` that a `workflow.run` step calls, as `ctx` - the
        calling run's principal - its first dispatch is queued in the step's own
        transaction. The step is woken when the run ends.

        Raises:
            WorkflowRunInputTooLargeError: `run_input` is over the size limit.
            WorkflowRunInputInvalidError: The called workflow declares fields
                `run_input` does not fit.
            WorkflowAdmissionQuotaError: As `start`.
        """
        graph = WorkflowGraph.model_validate(version.graph)
        call_entry = next(
            (node for node in entry_nodes(graph) if node.definition_id == WORKFLOW_CALL), None
        )
        if call_entry is not None:
            graph = entry_graph(graph, call_entry.id)
        payload = _checked_input(run_input)
        _check_declared_input(graph, payload)
        await hold_subject(self.db, LockScope.WORKFLOW_FILE_BYTES, ctx.organization_id)
        await hold_subject(self.db, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, ctx.organization_id)
        parent_step = await workflow_run_repo.get_node_run_by_id(self.db, parent_node_run_id)
        parent = (
            await workflow_run_repo.get_run_by_id_for_update(self.db, parent_step.workflow_run_id)
            if parent_step is not None
            else None
        )
        if parent is None or parent.organization_id != ctx.organization_id:
            raise WorkflowNotRunnableError(workflow_id=workflow.id)
        if WorkflowRunStatus(parent.status).is_terminal:
            raise WorkflowRunAlreadyTerminalError(run_id=parent.id, status=parent.status)
        available = await budget.unreserved(self.db, parent)
        if available is not None:
            # The calling step's own hold moves onto the called run, so it counts as free
            # to it; a sibling that began in between sees both until the step settles.
            calling = await workflow_run_repo.get_latest_attempt(
                self.db, node_run_id=parent_node_run_id
            )
            if (
                calling is not None
                and calling.status == NodeAttemptStatus.IN_FLIGHT.value
                and calling.reserved_usd is not None
            ):
                available += calling.reserved_usd
            if available <= 0:
                raise WorkflowBudgetHeldError(run_id=parent.id)
        child_budget = version.budget_limit
        if available is not None:
            child_budget = available if child_budget is None else min(available, child_budget)
        run, _entry = await self._admit(
            ctx,
            workflow,
            graph=graph,
            workflow_version_id=version.id,
            draft_snapshot=None,
            budget_limit=child_budget,
            mode=WorkflowRunMode.REAL,
            triggered_by=WorkflowRunTrigger.WORKFLOW_CALL,
            payload=payload,
            deadline_seconds=None,
            reply_conversation_id=None,
            causation=causation,
            parent_node_run_id=parent_node_run_id,
            retry_of_run_id=retry_of_run_id,
        )
        if parent.deadline_at is not None and (
            run.deadline_at is None or parent.deadline_at < run.deadline_at
        ):
            run = await workflow_run_repo.update_run(
                self.db, run=run, update_data={"deadline_at": parent.deadline_at}
            )
        return run

    async def _admit(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        *,
        graph: WorkflowGraph,
        workflow_version_id: UUID | None,
        draft_snapshot: dict[str, Any] | None,
        budget_limit: Decimal | None,
        mode: WorkflowRunMode,
        triggered_by: WorkflowRunTrigger,
        payload: dict[str, Any],
        deadline_seconds: int | None,
        reply_conversation_id: UUID | None,
        causation: Causation | None = None,
        retry_of_run_id: UUID | None = None,
        parent_node_run_id: UUID | None = None,
        public_origin: bool = False,
        impersonated: bool = False,
        source_artifact_id: UUID | None = None,
        source_version_number: int | None = None,
    ) -> tuple[WorkflowRun, UUID]:
        """One admitted run: its row, its references, its entry node and first outbox row.

        Every surface ends here, so a run started from the console, the API, a
        webhook, a schedule or the chat is the same row with the same
        governance - the admission quota, the pinned principal, the frozen input.
        The run is stored public when `public_origin` says so (a retry of a
        public run), when it came through an external door, or when a public
        run caused it.
        """
        await hold_subject(self.db, LockScope.WORKFLOW_FILE_BYTES, ctx.organization_id)
        await hold_subject(self.db, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, ctx.organization_id)
        problems = await file_binding_problems(self.db, ctx, graph)
        if problems:
            raise GraphValidationError(problems)
        # Charge this run's node work against the organization's and the caller's
        # outstanding-node-work ceilings before anything is written, so a caller
        # cannot start many wide graphs below the per-minute run limit and grow a
        # backlog on the shared runner that starves other tenants (#1907).
        await admission.enforce_admission_quota(
            self.db,
            organization_id=ctx.organization_id,
            principal_user_id=ctx.subject_id,
            requested_node_count=len(graph.nodes),
        )

        now = datetime.now(UTC)
        settings = StoredWorkflowSettings.model_validate(workflow.settings)
        await limits.enforce_workflow_limits(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            settings=settings,
            mode=mode,
            now=now,
        )
        budget_limit = limits.run_budget(budget_limit, settings)
        if deadline_seconds is None:
            # Nothing that started the run named a deadline: the workflow's own.
            deadline_seconds = settings.default_deadline_seconds
        deadline_at = (
            now + timedelta(seconds=deadline_seconds) if deadline_seconds is not None else None
        )
        initial_bytes = sum(
            json_byte_size(value, limit=(1 << 63) - 1)
            for value in (payload, draft_snapshot)
            if value is not None
        )
        storage_scope = await admission.inline_storage_scope(
            self.db, organization_id=ctx.organization_id, run_bytes=0, requested=initial_bytes
        )
        if storage_scope is not None:
            raise WorkflowInlineStorageLimitError(scope=storage_scope)
        run = await workflow_run_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            workflow_version_id=workflow_version_id,
            draft_graph_snapshot=draft_snapshot,
            entry_node_id=graph.entry_node_id,
            mode=mode.value,
            triggered_by=triggered_by.value,
            source_artifact_id=source_artifact_id,
            source_version_number=source_version_number,
            public_origin=(
                public_origin
                or ctx.api_key_id is not None
                or triggered_by in dispatcher.PUBLIC_TRIGGERS
                or (causation is not None and causation.public_origin)
            ),
            # Asked here, on the request that admits the run: a worker and a spawned
            # task no longer know. A chain keeps it, and so does a retry.
            impersonated=(
                impersonated
                or current_impersonator() is not None
                or (causation is not None and causation.impersonated)
            ),
            execution_principal_user_id=ctx.subject_id,
            execution_api_key_id=ctx.api_key_id,
            key_scopes=(
                None if ctx.key_scopes is None else sorted(scope.value for scope in ctx.key_scopes)
            ),
            budget_limit=budget_limit,
            node_count=len(graph.nodes),
            deadline_at=deadline_at,
            timezone=settings.timezone,
            root_run_id=causation.root_run_id if causation else None,
            causation_run_id=causation.causation_run_id if causation else None,
            visited_trigger_ids=causation.visited_trigger_ids if causation else [],
            depth=causation.depth if causation else 0,
            started_at=now,
            run_input=payload,
            inline_result_bytes=initial_bytes,
            reply_conversation_id=reply_conversation_id,
            retry_of_run_id=retry_of_run_id,
            parent_node_run_id=parent_node_run_id,
        )
        await self._record_resource_refs(run, graph)
        entry_node_run = await workflow_run_repo.create_node_run(
            self.db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_instance_id=graph.entry_node_id,
            scope_path=[],
        )
        # The first dispatch's job commits with the run, so it starts the moment
        # the admitting transaction does.
        await dispatch_queue.queue_dispatch(self.db, run=run, node_run_id=entry_node_run.id)
        run = await workflow_run_repo.update_run(
            self.db, run=run, update_data={"status": WorkflowRunStatus.RUNNING.value}
        )
        await events.append(self.db, run=run, kind=events.EventKind.RUN_STARTED)
        return run, entry_node_run.id

    async def cancel(self, ctx: AuthContext, run_id: UUID) -> WorkflowRunRead:
        """Stop a run: no further node ever dispatches for it.

        Who may: the person who started the run, while they may still run its
        workflow (`workflows:run`), or anyone who may edit the workflow
        (`workflows:edit`). Holding `workflows:run` alone - a Member on an
        organization-visible workflow, a `use` grant - lets a caller start
        their own runs, not stop a colleague's.

        Closes everything the run had under way (`cleanup.stop_run_work`): every
        dispatch row and queued job, every pending approval request, the agent
        run each parked step waits on, and every live step, which becomes
        `cancelled`. A step whose attempt is executing at that moment finishes
        on its own; its result is recorded and nothing follows from it.

        Raises:
            WorkflowRunNotFoundError: No such run, or this caller may not see
                it - the same answer either way.
            AuthorizationError: The caller may see the run but not cancel it.
            WorkflowRunAlreadyTerminalError: The run already ended.
        """
        # Authorized on an unlocked, scoped read before any row is locked: a
        # caller who may not see the run must not wait on - or hold - its
        # lock, which would tell a busy run from a missing one by timing.
        run = await workflow_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        workflow = (
            await self._reachable(ctx, run.workflow_id, Perm.WORKFLOWS_VIEW)
            if run is not None
            else None
        )
        if (
            run is None
            or workflow is None
            or (ctx.api_key_id is not None and not run.public_origin)
        ):
            raise WorkflowRunNotFoundError(run_id=run_id)
        if not await self._may_cancel(ctx, run, workflow):
            raise AuthorizationError(
                message="Only the person who started this run, or an editor of its "
                "workflow, may cancel it",
                details={"run_id": run.id},
            )
        # Scoped, not `get_run_by_id_for_update` - that lookup is for the
        # dispatcher and reconciler, which act on ids they already trust.
        run = await workflow_run_repo.get_run_for_update(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if run is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        if WorkflowRunStatus(run.status).is_terminal:
            raise WorkflowRunAlreadyTerminalError(run_id=run.id, status=run.status)

        ended_at = datetime.now(UTC)
        await cleanup.stop_run_work(self.db, run=run, now=ended_at)
        run = await workflow_run_repo.update_run(
            self.db,
            run=run,
            update_data={
                "status": WorkflowRunStatus.CANCELLED.value,
                "ended_at": ended_at,
                "paused_reason": None,
            },
        )
        await events.append(self.db, run=run, kind=events.EventKind.RUN_CANCELLED)
        await delivery.deliver_result(self.db, run=run)
        return _read(run, can_cancel=True)

    async def resolve_step(
        self, ctx: AuthContext, run_id: UUID, node_run_id: UUID, body: WorkflowStepResolve
    ) -> WorkflowRunRead:
        """Decide what becomes of a step that needs attention, on the run it is in.

        Who may: as for `cancel` - the person who started the run, or an editor of its
        workflow - and for a test run, only an editor. Only this step is touched:
        sibling steps, approvals, timers and called runs go on as they were.

        The choices (`WorkflowStepResolve`): `run_again` queues the step for a new try;
        `use_error_route` treats it as failed and takes its error route; `fail_run`
        ends the run with the step marked failed; `use_late_result` takes the result
        the step reported after its try was given up on. The decision is recorded in
        the audit log with the step, the try and the choice - never the step's data.

        Raises:
            WorkflowRunNotFoundError: No such run, or this caller may not see it.
            WorkflowStepNotFoundError: No such step in this run.
            AuthorizationError: The caller may see the run but not resolve its steps.
            WorkflowRunAlreadyTerminalError: The run already ended.
            WorkflowStepNotResolvableError: The step does not need attention (a second
                click finds it already queued), has no error route, or has no late
                result.
        """
        # Authorized on an unlocked, scoped read, as `cancel` does, before any lock.
        run = await workflow_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        workflow = (
            await self._reachable(ctx, run.workflow_id, Perm.WORKFLOWS_VIEW)
            if run is not None
            else None
        )
        if (
            run is None
            or workflow is None
            or (ctx.api_key_id is not None and not run.public_origin)
        ):
            raise WorkflowRunNotFoundError(run_id=run_id)
        if not await self._may_resolve(ctx, run, workflow):
            raise AuthorizationError(
                message="Only the person who started this run, or an editor of its "
                "workflow, may resolve its steps",
                details={"run_id": run.id},
            )
        step = await workflow_run_repo.get_node_run_by_id(self.db, node_run_id)
        if step is None or step.workflow_run_id != run.id:
            raise WorkflowStepNotFoundError(node_run_id=node_run_id)

        # The order every settle takes: the organization locks, the run, then the step.
        await hold_subject(self.db, LockScope.WORKFLOW_FILE_BYTES, ctx.organization_id)
        await hold_subject(self.db, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, ctx.organization_id)
        run = await workflow_run_repo.get_run_for_update(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if run is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        if WorkflowRunStatus(run.status).is_terminal:
            raise WorkflowRunAlreadyTerminalError(run_id=run.id, status=run.status)
        # Read again under the lock: a second click finds the step already queued.
        node_run = await workflow_run_repo.get_node_run_by_id_for_update(self.db, node_run_id)
        if node_run is None or node_run.status != NodeRunStatus.NEEDS_ATTENTION.value:
            raise WorkflowStepNotResolvableError(
                run_id=run.id, node_run_id=node_run_id, reason="not_needing_attention"
            )

        latest = await workflow_run_repo.get_latest_attempt(self.db, node_run_id=node_run.id)
        await dispatcher.resolve_needs_attention(
            self.db,
            run=run,
            node_run=node_run,
            latest=latest,
            choice=body.choice,
            now=datetime.now(UTC),
        )
        run = await refresh_run_status(self.db, run=run)
        # Last, after every row lock: the audit chain's own lock is taken after them.
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=run.organization_id,
            action="workflow_run.step_resolved",
            target_type="workflow_run",
            target_id=str(run.id),
            details={
                "node_run_id": str(node_run.id),
                "node_instance_id": str(node_run.node_instance_id),
                "attempt_no": latest.attempt_no if latest else 0,
                "choice": body.choice,
            },
        )
        return _read(run, can_cancel=True)

    async def get(self, ctx: AuthContext, run_id: UUID) -> WorkflowRunRead:
        run, workflow = await self._load_with_workflow(ctx, run_id, Perm.WORKFLOWS_VIEW)
        return _read(run, can_cancel=await self._may_resolve(ctx, run, workflow))

    async def list(
        self,
        ctx: AuthContext,
        *,
        workflow_id: UUID | None = None,
        filters: WorkflowRunFilters | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> WorkflowRunList:
        """Runs in this caller's organization, optionally narrowed to one workflow
        and by `filters`, newest first.

        If `workflow_id` is given, it is checked the same way `get` checks a
        single run's - a 404 rather than an empty page for a workflow the
        caller cannot reach, so this cannot be used to probe which workflow
        ids exist. Otherwise, narrowed to the workflows this caller may see at
        all - their own, organization-visible ones and those shared with them,
        exactly what `GET /workflows` lists - so a role scoped to what it can
        see does not see every other workflow's run history just because it
        asked for the unfiltered list.
        """
        visible_to_user_id: UUID | None = None
        shared: list[UUID] | None = None
        if workflow_id is not None:
            await self._authorize(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        else:
            shared = await visible_resource_ids(
                self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
            )
            if shared is not None:
                visible_to_user_id = ctx.subject_id
        items, total = await workflow_run_repo.list_runs(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow_id,
            visible_to_user_id=visible_to_user_id,
            shared_workflow_ids=shared,
            filters=filters,
            public_only=ctx.api_key_id is not None,
            skip=skip,
            limit=limit,
        )
        return WorkflowRunList(items=[_read(item) for item in items], total=total)

    async def retry(self, ctx: AuthContext, run_id: UUID) -> WorkflowRunRead:
        """Run again what `run_id` ran - the same version or draft snapshot, the same
        input - with each step that succeeded there handing on the output it had.

        Only the failed step and what it did not reach run, so a step with a side
        effect is never repeated. A loop runs again, its items resolved from what
        they handed on, and a deciding step decides again on the same data.

        Raises:
            WorkflowRunNotFoundError: No such run, or this caller may not see it.
            WorkflowRunNotRetryableError: The run did not fail, was not
                cancelled and did not run out of budget.
            AuthorizationError: The caller may see the run but not run its
                workflow - or, for a test run, not edit it.
            WorkflowArchivedError: The workflow is archived.
            WorkflowNotRunnableError: The version the run ran no longer resolves.
            WorkflowAdmissionQuotaError: As `start`.
        """
        await hold_subject(self.db, LockScope.WORKFLOW_FILE_BYTES, ctx.organization_id)
        original = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        if original.status not in _RETRYABLE:
            raise WorkflowRunNotRetryableError(run_id=original.id, status=original.status)
        mode = WorkflowRunMode(original.mode)
        workflow = await self._reachable(ctx, original.workflow_id, Perm.WORKFLOWS_RUN)
        if workflow is None or (
            mode is WorkflowRunMode.TEST
            and not await resolve_access(
                self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
            )
        ):
            raise AuthorizationError(message="You may not retry this run")
        if workflow.status == WorkflowStatus.ARCHIVED.value:
            raise WorkflowArchivedError(
                workflow_id=workflow.id, message="This workflow is archived and cannot be run"
            )
        try:
            graph = await dispatcher.resolve_graph(self.db, original)
        except WorkflowGraphUnresolvableError as exc:
            raise WorkflowNotRunnableError(workflow_id=workflow.id) from exc
        run, _entry = await self._admit(
            ctx,
            workflow,
            graph=graph,
            workflow_version_id=original.workflow_version_id,
            draft_snapshot=original.draft_graph_snapshot,
            budget_limit=original.budget_limit,
            mode=mode,
            triggered_by=WorkflowRunTrigger(original.triggered_by),
            payload=original.input,
            deadline_seconds=None,
            reply_conversation_id=None,
            retry_of_run_id=original.id,
            # A retry is a root of its own, so it keeps the run's flag, not
            # its chain's: a member retrying a public child from the console
            # still runs it with no person.
            public_origin=original.public_origin,
            impersonated=original.impersonated,
            source_artifact_id=original.source_artifact_id,
            source_version_number=original.source_version_number,
        )
        return _read(run)

    async def graph(self, ctx: AuthContext, run_id: UUID) -> WorkflowRunGraph:
        """The graph this run executes, loop scopes derived, as a run view draws it.

        Raises:
            WorkflowRunNotFoundError: No such run, or this caller may not see it.
            WorkflowGraphUnresolvableError: The version no longer resolves.
        """
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        graph = await dispatcher.resolve_graph(self.db, run)
        return WorkflowRunGraph(graph=graph.model_dump(mode="json"))

    async def node_runs(
        self, ctx: AuthContext, run_id: UUID, *, skip: int = 0, limit: int = 200
    ) -> WorkflowNodeRunList:
        """Every step of a run, loop iterations included, with its tries, cost and error."""
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        rows, total = await workflow_run_repo.list_node_runs_page(
            self.db,
            workflow_run_id=run.id,
            organization_id=ctx.organization_id,
            skip=skip,
            limit=limit,
        )
        attempts = await workflow_run_repo.list_attempts_of(
            self.db, node_run_ids=[row.id for row in rows]
        )
        by_run: dict[UUID, list[NodeAttempt]] = {}
        for attempt in attempts:
            by_run.setdefault(attempt.node_run_id, []).append(attempt)
        return WorkflowNodeRunList(
            items=[node_run_read(row, by_run.get(row.id, [])) for row in rows], total=total
        )

    async def workflow_logs(
        self,
        ctx: AuthContext,
        workflow_id: UUID,
        *,
        filters: LogFilters,
        skip: int = 0,
        limit: int = 50,
    ) -> WorkflowLogEntryList:
        """A workflow's log, newest first, for a caller who may view the workflow. An
        organization key reads only the lines of runs it may see: the runs list's rule.

        Raises:
            NotFoundError: No such workflow, or this caller may not see it - the
                answer its runs list gives.
        """
        await self._authorize(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        rows, total = await workflow_log_repo.list_for_workflow(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow_id,
            filters=filters,
            public_only=ctx.api_key_id is not None,
            skip=skip,
            limit=limit,
        )
        return WorkflowLogEntryList(
            items=[WorkflowLogEntryRead.model_validate(row) for row in rows], total=total
        )

    async def workflow_log_summary(
        self,
        ctx: AuthContext,
        workflow_id: UUID,
        *,
        filters: LogFilters,
        days: int,
        tz: str = "UTC",
    ) -> WorkflowLogSummary:
        """A workflow's log counted per day of time zone `tz` (an IANA name) and outcome over
        the last `days` days, today included, for a caller who may view the workflow.
        `filters` narrows it as it narrows the listing; its time window is left to `days`.

        Raises:
            NotFoundError: No such workflow, or this caller may not see it.
        """
        await self._authorize(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        zone = ZoneInfo(tz)
        today = datetime.now(zone).date()
        first_day = today - timedelta(days=days - 1)
        rows = await workflow_log_repo.count_by_day(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow_id,
            filters=filters,
            since=datetime.combine(first_day, time.min, tzinfo=zone),
            # Local midnight ending today: a row dated ahead of the clock is outside the window.
            until=datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone),
            tz=tz,
            public_only=ctx.api_key_id is not None,
        )
        by_day = {
            first_day + timedelta(days=offset): WorkflowLogDay(
                day=first_day + timedelta(days=offset)
            )
            for offset in range(days)
        }
        for row in rows:
            by_day[row.day].counts[row.outcome] = row.lines
        return WorkflowLogSummary(
            days=days, total=sum(row.lines for row in rows), by_day=list(by_day.values())
        )

    async def recent_logs(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 20
    ) -> WorkflowRecentLogs:
        """The newest real-run lines across every workflow this caller may view - exactly
        what `GET /workflows` lists - and how many lines each outcome left in the last 24
        hours. An organization key reads only the lines of public-origin runs."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
        )
        visible_to_user_id = ctx.subject_id if shared is not None else None
        rows = await workflow_log_repo.list_recent(
            self.db,
            organization_id=ctx.organization_id,
            visible_to_user_id=visible_to_user_id,
            shared_workflow_ids=shared,
            public_only=ctx.api_key_id is not None,
            skip=skip,
            limit=limit,
        )
        counts = await workflow_log_repo.count_recent_by_outcome(
            self.db,
            organization_id=ctx.organization_id,
            visible_to_user_id=visible_to_user_id,
            shared_workflow_ids=shared,
            since=datetime.now(UTC) - timedelta(hours=24),
            public_only=ctx.api_key_id is not None,
        )
        return WorkflowRecentLogs(
            items=[
                WorkflowRecentLogEntry(
                    **WorkflowLogEntryRead.model_validate(entry).model_dump(), workflow_name=name
                )
                for entry, name in rows
            ],
            counts=counts,
        )

    async def run_logs(
        self, ctx: AuthContext, run_id: UUID, *, skip: int = 0, limit: int = 200
    ) -> WorkflowLogEntryList:
        """The lines a run's steps wrote, oldest first, for a caller who may view the run."""
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        rows, total = await workflow_log_repo.list_for_run(
            self.db, organization_id=ctx.organization_id, run_id=run.id, skip=skip, limit=limit
        )
        return WorkflowLogEntryList(
            items=[WorkflowLogEntryRead.model_validate(row) for row in rows], total=total
        )

    async def run_files(self, ctx: AuthContext, run_id: UUID) -> WorkflowFileList:
        """Every file this run made, for a caller who may view the run."""
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        rows = await workflow_file_repo.list_for_run(
            self.db, workflow_run_id=run.id, organization_id=ctx.organization_id
        )
        return WorkflowFileList(items=[WorkflowFileRead.model_validate(row) for row in rows])

    async def run_file(self, ctx: AuthContext, run_id: UUID, file_id: UUID) -> WorkflowFile:
        """A file this run made or was started with, for a caller who may view the run.

        Raises:
            WorkflowRunNotFoundError: The run is missing or out of reach.
            NotFoundError: The run has no such file - a file of another run, of
                another organization, or none at all, answered alike.
        """
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        row = await workflow_file_repo.get_for_run(
            self.db, file_id, organization_id=ctx.organization_id, workflow_run_id=run.id
        )
        if row is None:
            raise NotFoundError(message="File not found", details={"file_id": str(file_id)})
        return row

    async def events_since(
        self, ctx: AuthContext, run_id: UUID, *, after: str | None, limit: int = 100
    ) -> WorkflowEventList:
        """Every event after `after` (a cursor from a previous call, or `None`
        for the whole history), oldest first - backfill and live tailing
        through the same call.
        """
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        after_seq = events.decode_cursor(after) if after is not None else None
        rows = await workflow_run_repo.list_events_since(
            self.db,
            workflow_run_id=run.id,
            organization_id=ctx.organization_id,
            after_seq=after_seq,
            limit=limit,
        )
        next_cursor = events.encode_cursor(rows[-1].seq) if rows else after
        return WorkflowEventList(
            items=[WorkflowEventRead.model_validate(row) for row in rows], next_cursor=next_cursor
        )

    async def _reachable(self, ctx: AuthContext, workflow_id: UUID, perm: Perm) -> Workflow | None:
        """The workflow, if this caller may exercise `perm` on it; else `None`.

        A run's visibility mirrors its workflow's - there is no separate
        grant on a run - so authorizing a run action means resolving access
        to the workflow it belongs to, the same as `WorkflowRegistryService._load`.
        """
        workflow = await workflow_repo.get(
            self.db, workflow_id, organization_id=ctx.organization_id
        )
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, perm, resource_type=WORKFLOW
        ):
            return None
        return workflow

    async def _authorize(self, ctx: AuthContext, workflow_id: UUID, perm: Perm) -> Workflow:
        """`_reachable`, for a workflow id the caller supplied themselves."""
        workflow = await self._reachable(ctx, workflow_id, perm)
        if workflow is None:
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        return workflow

    async def _load(self, ctx: AuthContext, run_id: UUID, perm: Perm) -> WorkflowRun:
        """The run, if this caller may exercise `perm` on its workflow.

        A missing run and a run whose workflow the caller may not reach get
        the same `WorkflowRunNotFoundError`, naming only the id they asked
        for: telling them apart would confirm the run exists, and naming its
        workflow would hand out the id of a workflow they cannot see.
        """
        run, _workflow = await self._load_with_workflow(ctx, run_id, perm)
        return run

    async def _load_with_workflow(
        self, ctx: AuthContext, run_id: UUID, perm: Perm
    ) -> tuple[WorkflowRun, Workflow]:
        """`_load`, with the workflow it reached."""
        run = await workflow_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        workflow = (
            await self._reachable(ctx, run.workflow_id, perm)
            if run is not None and (ctx.api_key_id is None or run.public_origin)
            else None
        )
        if run is None or workflow is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        return run, workflow

    async def _may_cancel(self, ctx: AuthContext, run: WorkflowRun, workflow: Workflow) -> bool:
        if await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        ):
            return True
        return run.execution_principal_user_id == ctx.user_id and await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        )

    async def _may_resolve(self, ctx: AuthContext, run: WorkflowRun, workflow: Workflow) -> bool:
        """Who may cancel, and who may decide a step's fate: as `_may_cancel`, and for a
        test run only an editor."""
        if not await self._may_cancel(ctx, run, workflow):
            return False
        return WorkflowRunMode(run.mode) is not WorkflowRunMode.TEST or await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        )

    async def _resolve_start_graph(
        self, ctx: AuthContext, workflow: Workflow, *, mode: WorkflowRunMode
    ) -> tuple[WorkflowGraph, UUID | None, dict[str, Any] | None, Decimal | None]:
        if mode is WorkflowRunMode.REAL:
            if workflow.current_version_id is None:
                raise WorkflowNotRunnableError(workflow_id=workflow.id)
            version = await workflow_repo.get_version(
                self.db, workflow.current_version_id, organization_id=workflow.organization_id
            )
            if version is None:
                raise WorkflowNotRunnableError(workflow_id=workflow.id)
            # A published version was already checked by `validate_graph` at
            # publish time and is frozen - re-validating it here would only
            # repeat work `WorkflowRegistryService.publish` already did.
            return (
                WorkflowGraph.model_validate(version.graph),
                version.id,
                None,
                version.budget_limit,
            )

        try:
            graph = WorkflowGraph.model_validate(workflow.draft_graph)
        except PydanticValidationError as exc:
            raise WorkflowNotRunnableError(workflow_id=workflow.id) from exc
        # Unlike a published version, a draft is never required to have
        # passed `validate_graph` - autosave writes it after every edit, not
        # only valid ones. Run the same publish-time check here, so an invalid
        # draft is refused at the start with the same field-scoped
        # `GraphValidationError` `publish` itself raises - naming what the
        # author has to fix - instead of a run being admitted only to fail at
        # its first dispatch.
        graph = await validate_graph(self.db, ctx, graph)
        return graph, None, graph.model_dump(mode="json"), None

    async def _record_resource_refs(self, run: WorkflowRun, graph: WorkflowGraph) -> None:
        """Record file and table bindings after admission rechecks file access."""
        for _field, ref in graph_file_refs(graph):
            await workflow_run_repo.create_resource_ref(
                self.db,
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                kind=ResourceRefKind.FILE.value,
                ref=ref.model_dump(mode="json"),
            )
        for binding in graph.bindings:
            if isinstance(binding.source, TableIORef):
                await workflow_run_repo.create_resource_ref(
                    self.db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    kind=ResourceRefKind.TABLE.value,
                    ref=binding.source.model_dump(mode="json"),
                )


__all__ = ["Causation", "WorkflowExecutionService", "node_run_read"]


def node_run_read(row: NodeRun, attempts: list[NodeAttempt]) -> WorkflowNodeRunRead:
    """One node run as the API shows it: its latest failure, and what its tries cost."""
    # An attempt with no retry guarantee is the dispatcher's own record - a loop
    # item's element, a loop's collected results - not a try at the step; nor is
    # one that parked, which the wake after it carries on as the same try.
    tries = [
        attempt
        for attempt in attempts
        if attempt.retry_guarantee is not None and (attempt.result or {}).get("status") != "waiting"
    ]
    failed = [attempt for attempt in tries if attempt.status == NodeAttemptStatus.FAILED.value]
    latest_error = failed[-1].result.get("error") if failed and failed[-1].result else None
    completed = [
        attempt.result
        for attempt in attempts
        if attempt.status == NodeAttemptStatus.COMPLETED.value and attempt.result is not None
    ]
    output = completed[-1].get("output") if completed else None
    # A late result is on offer only while the step still waits for a person; once it was
    # used, the dispatcher's own completed record follows the try it came from.
    late = (
        tries[-1].late_result
        if tries and row.status == NodeRunStatus.NEEDS_ATTENTION.value
        else None
    )
    late_output = late.get("output") if late is not None else None
    last = tries[-1] if tries else None
    last_status = NodeAttemptStatus(last.status) if last is not None else None
    if last is not None and any(
        attempt.retry_guarantee is None
        and attempt.attempt_no > last.attempt_no
        and attempt.status == NodeAttemptStatus.COMPLETED.value
        for attempt in attempts
    ):
        last_status = NodeAttemptStatus.COMPLETED
    return WorkflowNodeRunRead(
        id=row.id,
        node_instance_id=row.node_instance_id,
        scope_path=row.scope_path,
        status=NodeRunStatus(row.status),
        waiting_reason=row.waiting_reason,
        attempts=len(tries),
        cost=float(sum((attempt.cost for attempt in attempts), Decimal(0))),
        error=latest_error,
        output=output if isinstance(output, dict) else None,
        last_attempt_status=last_status,
        late_output=late_output if isinstance(late_output, dict) else None,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )
