"""`WorkflowExecutionService` - start, cancel, read and tail a workflow run.

The public facade routes call. Mirrors `WorkflowRegistryService`'s own split:
authorization and lifecycle checks happen here, against the *workflow* (a
run has no owner/visibility of its own - it inherits its workflow's), before
anything about the run itself is touched.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
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
from app.repositories import workflow_approval as workflow_approval_repo
from app.repositories import workflow_file as workflow_file_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import (
    WorkflowEventList,
    WorkflowEventRead,
    WorkflowFileList,
    WorkflowFileRead,
    WorkflowNodeRunList,
    WorkflowNodeRunRead,
    WorkflowRunGraph,
    WorkflowRunList,
    WorkflowRunRead,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.services.workflow_execution import admission, delivery, dispatcher, events
from app.services.workflow_execution.exceptions import (
    WorkflowArchivedError,
    WorkflowNotRunnableError,
    WorkflowRunAlreadyTerminalError,
    WorkflowRunInputInvalidError,
    WorkflowRunInputTooLargeError,
    WorkflowRunNotFoundError,
    WorkflowTriggerMismatchError,
)
from app.workflows.contracts.io import FileRef, TableIORef
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.core_input._handler import ManualTriggerConfig, input_problems
from app.workflows.triggers import CHAT, MANUAL

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Causation:
    """Where a run sits in a chain of runs one started another through.

    A table trigger's run is caused by the run whose step wrote the record, or by
    nothing when a person did. `visited_trigger_ids` is every trigger the chain
    has passed through, this one included, which is what lets a trigger that
    would start itself again - directly or round a loop - be refused.
    """

    root_run_id: UUID | None
    causation_run_id: UUID | None
    visited_trigger_ids: list[str]
    depth: int


def _checked_input(run_input: dict[str, Any] | None) -> dict[str, Any]:
    """`run_input` as a run stores it, refused when it is over the size limit.

    Raises:
        WorkflowRunInputTooLargeError: Over `WORKFLOW_RUN_MAX_INPUT_BYTES` as
            compact JSON.
    """
    payload = run_input or {}
    size = len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    if size > settings.WORKFLOW_RUN_MAX_INPUT_BYTES:
        raise WorkflowRunInputTooLargeError(limit=settings.WORKFLOW_RUN_MAX_INPUT_BYTES, size=size)
    return payload


def _check_declared_input(graph: WorkflowGraph, payload: dict[str, Any]) -> None:
    """Refuse `payload` when the graph's "Manual or API" entry declares fields it does not fit.

    Raises:
        WorkflowRunInputInvalidError: A declared field is missing or of the
            wrong type, or the payload has one that is not declared.
    """
    entry = graph.node_by_id[graph.entry_node_id]
    if entry.definition_id != MANUAL:
        return
    # The graph passed `validate_graph` - at publish, or just now for a draft -
    # so its config fits.
    problems = input_problems(ManualTriggerConfig.model_validate(entry.config), payload)
    if problems:
        raise WorkflowRunInputInvalidError(problems=problems)


def _read(run: WorkflowRun) -> WorkflowRunRead:
    return WorkflowRunRead(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_version_id=run.workflow_version_id,
        mode=run.mode,
        status=run.status,
        triggered_by=run.triggered_by,
        budget_limit=float(run.budget_limit) if run.budget_limit is not None else None,
        spent_cost=float(run.spent_cost),
        cost_is_partial=run.cost_is_partial,
        deadline_at=run.deadline_at,
        paused_reason=run.paused_reason,
        error=run.error,
        output=run.output,
        root_run_id=run.root_run_id,
        causation_run_id=run.causation_run_id,
        depth=run.depth,
        started_at=run.started_at,
        ended_at=run.ended_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


# The triggers each door a member stands at starts in `real` mode. A version
# whose entry is no trigger starts by hand, as `core.input` does. The unattended
# doors - webhook, schedule, table - run only the version that switched them on.
_DOOR_TRIGGERS: dict[WorkflowRunTrigger, frozenset[str | None]] = {
    WorkflowRunTrigger.API: frozenset({None, MANUAL}),
    WorkflowRunTrigger.WEBSOCKET: frozenset({None, MANUAL}),
    WorkflowRunTrigger.CHAT: frozenset({CHAT}),
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
    ) -> WorkflowRunRead:
        """Admit a new run of `workflow_id`'s current published version (or,
        in `test` mode, a snapshot of its current draft).

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

        Raises:
            NotFoundError: The workflow does not exist, or this caller may
                not reach it.
            AuthorizationError: The caller lacks `workflows:run`.
            WorkflowArchivedError: The workflow is archived - `ARCHIVED`
                keeps a workflow's history and its past runs but refuses new
                ones, in both `real` and `test` mode.
            WorkflowNotRunnableError: `real` mode with no published version,
                or `test` mode with no valid, structurally sound draft graph.
            WorkflowTriggerMismatchError: `real` mode through a door the live
                version's trigger is not - the API or a WebSocket for a workflow
                that starts from anything but "Manual or API", the chat for one
                that does not start from a chat message.
            WorkflowRunInputTooLargeError: `run_input` is over
                `WORKFLOW_RUN_MAX_INPUT_BYTES`.
            WorkflowRunInputInvalidError: The version being run starts from
                "Manual or API" with declared fields, and `run_input` does not
                fit them.
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
        if (
            mode is WorkflowRunMode.REAL
            and workflow.current_version_id is not None
            and workflow.live_trigger not in _DOOR_TRIGGERS[triggered_by]
        ):
            raise WorkflowTriggerMismatchError(
                workflow_id=workflow.id, trigger=workflow.live_trigger, door=triggered_by.value
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
        _check_declared_input(graph, payload)
        run, entry_node_run_id = await self._admit(
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
        )
        self._trigger_dispatch(workflow_run_id=run.id, node_run_id=entry_node_run_id)
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
    ) -> tuple[WorkflowRun, UUID]:
        """Admit a run of one pinned version as `ctx` - a webhook's, a schedule's or
        a table trigger's fire. `causation` places it in a chain of runs.

        The exposure layer has already decided `ctx` may run `workflow` and that
        it is not archived; this is the rest of `start`, on the version the
        exposure pinned rather than the workflow's current one. Returns the run
        and its entry node run, whose first dispatch the caller submits once its
        own transaction commits - a request through `trigger_dispatch`, the
        schedule heartbeat after its claim commits.

        Raises:
            WorkflowRunInputTooLargeError: `run_input` is over
                `WORKFLOW_RUN_MAX_INPUT_BYTES`.
            WorkflowAdmissionQuotaError: The organization's or the principal's
                outstanding node work would pass its ceiling.
        """
        return await self._admit(
            ctx,
            workflow,
            graph=WorkflowGraph.model_validate(version.graph),
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
    ) -> tuple[WorkflowRun, UUID]:
        """One admitted run: its row, its references, its entry node and first outbox row.

        Every surface ends here, so a run started from the console, the API, a
        webhook, a schedule or the chat is the same row with the same
        governance - the admission quota, the pinned principal, the frozen input.
        """
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
        deadline_at = (
            now + timedelta(seconds=deadline_seconds) if deadline_seconds is not None else None
        )
        run = await workflow_run_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            workflow_version_id=workflow_version_id,
            draft_graph_snapshot=draft_snapshot,
            mode=mode.value,
            triggered_by=triggered_by.value,
            execution_principal_user_id=ctx.subject_id,
            budget_limit=budget_limit,
            node_count=len(graph.nodes),
            deadline_at=deadline_at,
            root_run_id=causation.root_run_id if causation else None,
            causation_run_id=causation.causation_run_id if causation else None,
            visited_trigger_ids=causation.visited_trigger_ids if causation else [],
            depth=causation.depth if causation else 0,
            started_at=now,
            run_input=payload,
            reply_conversation_id=reply_conversation_id,
        )
        await self._record_resource_refs(run, graph)
        entry_node_run = await workflow_run_repo.create_node_run(
            self.db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_instance_id=graph.entry_node_id,
            scope_path=[],
        )
        # Stamped submitted: the caller submits it once its transaction commits,
        # so the poll leaves it alone unless that submission is lost.
        await workflow_run_repo.create_outbox(
            self.db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=entry_node_run.id,
            submitted=True,
        )
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

        Cancels every `pending` or `claimed` `DispatchOutbox` row. What the
        design also calls for - cancelling a live linked `agent_runs` row
        through its existing path - has no existing path today: this codebase
        has no agent-run cancellation mechanism to call. Inventing one is a
        different subsystem's scope, not #1788's; a `NodeRun` still
        `waiting`/`approval` when its workflow is cancelled is left exactly as
        it was, and whichever issue adds agent-run cancellation should close
        this gap in the same change.

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
        if run is None or workflow is None:
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

        await workflow_run_repo.cancel_live_outbox_for_run(self.db, workflow_run_id=run.id)
        # A `human.approval` request left pending would sit in the queue asking
        # for a decision that can no longer decide anything.
        await workflow_approval_repo.cancel_pending_for_run(self.db, run.id)
        # A loop mid-iteration has no outbox row of its own to cancel - its row
        # is `running` until its last iteration ends - so it is ended here, with
        # every other row nothing will now settle.
        ended_at = datetime.now(UTC)
        for live in await workflow_run_repo.list_live_node_runs(self.db, workflow_run_id=run.id):
            await workflow_run_repo.update_node_run(
                self.db,
                node_run=live,
                update_data={
                    "status": NodeRunStatus.CANCELLED.value,
                    "ended_at": ended_at,
                    "waiting_reason": None,
                    "waiting_agent_run_id": None,
                },
            )
            await events.append(
                self.db, run=run, kind=events.EventKind.NODE_CANCELLED, node_run_id=live.id
            )
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
        return _read(run)

    async def get(self, ctx: AuthContext, run_id: UUID) -> WorkflowRunRead:
        run = await self._load(ctx, run_id, Perm.WORKFLOWS_VIEW)
        return _read(run)

    async def list(
        self, ctx: AuthContext, *, workflow_id: UUID | None = None, skip: int = 0, limit: int = 50
    ) -> WorkflowRunList:
        """Runs in this caller's organization, optionally narrowed to one workflow.

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
            skip=skip,
            limit=limit,
        )
        return WorkflowRunList(items=[_read(item) for item in items], total=total)

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
            items=[_node_run_read(row, by_run.get(row.id, [])) for row in rows], total=total
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
        run = await workflow_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None or await self._reachable(ctx, run.workflow_id, perm) is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        return run

    async def _may_cancel(self, ctx: AuthContext, run: WorkflowRun, workflow: Workflow) -> bool:
        if await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        ):
            return True
        return run.execution_principal_user_id == ctx.user_id and await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
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
        """`FileRef`/`TableIORef` bindings, resolved once at run start.

        Thin and unopinionated, like the reference types themselves
        (`app.workflows.contracts.io`): this records what the graph named, not
        whether it still resolves against real storage - #1791's job once it
        exists.
        """
        for binding in graph.bindings:
            if isinstance(binding.source, FileRef):
                await workflow_run_repo.create_resource_ref(
                    self.db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    kind=ResourceRefKind.FILE.value,
                    ref=binding.source.model_dump(mode="json"),
                )
            elif isinstance(binding.source, TableIORef):
                await workflow_run_repo.create_resource_ref(
                    self.db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    kind=ResourceRefKind.TABLE.value,
                    ref=binding.source.model_dump(mode="json"),
                )

    def _trigger_dispatch(self, *, workflow_run_id: UUID, node_run_id: UUID) -> None:
        """The low-latency direct trigger. Losing this is not a bug -
        `workflow-dispatch-poll` resubmits the row once its submission is a
        lease old - so this is best-effort, never awaited.
        """
        from app.worker.tasks.workflow_tasks import trigger_dispatch

        trigger_dispatch(self.db, workflow_run_id=workflow_run_id, node_run_id=node_run_id)


__all__ = ["Causation", "WorkflowExecutionService"]


def _node_run_read(row: NodeRun, attempts: list[NodeAttempt]) -> WorkflowNodeRunRead:
    """One node run as the API shows it: its latest failure, and what its tries cost."""
    # An attempt with no retry guarantee is the dispatcher's own record - a loop
    # item's element, a loop's collected results - not a try at the step.
    tries = [attempt for attempt in attempts if attempt.retry_guarantee is not None]
    failed = [attempt for attempt in tries if attempt.status == NodeAttemptStatus.FAILED.value]
    latest_error = failed[-1].result.get("error") if failed and failed[-1].result else None
    return WorkflowNodeRunRead(
        id=row.id,
        node_instance_id=row.node_instance_id,
        scope_path=row.scope_path,
        status=NodeRunStatus(row.status),
        waiting_reason=row.waiting_reason,
        attempts=len(tries),
        cost=float(sum((attempt.cost for attempt in attempts), Decimal(0))),
        error=latest_error,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )
