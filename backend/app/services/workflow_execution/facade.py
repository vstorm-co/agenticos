"""`WorkflowExecutionService` - start, cancel, read and tail a workflow run.

The public facade routes call. Mirrors `WorkflowRegistryService`'s own split:
authorization and lifecycle checks happen here, against the *workflow* (a
run has no owner/visibility of its own - it inherits its workflow's), before
anything about the run itself is touched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode, WorkflowRunStatus
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import (
    WorkflowEventList,
    WorkflowEventRead,
    WorkflowRunList,
    WorkflowRunRead,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.services.workflow_execution import events
from app.services.workflow_execution.exceptions import (
    WorkflowNotRunnableError,
    WorkflowRunAlreadyTerminalError,
    WorkflowRunNotFoundError,
)
from app.workflows.contracts.io import FileRef, TableIORef
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.validate import validate_graph

logger = logging.getLogger(__name__)


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
        root_run_id=run.root_run_id,
        causation_run_id=run.causation_run_id,
        depth=run.depth,
        started_at=run.started_at,
        ended_at=run.ended_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


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
        triggered_by: str = "api",
    ) -> WorkflowRunRead:
        """Admit a new run of `workflow_id`'s current published version (or,
        in `test` mode, a snapshot of its current draft).

        Raises:
            NotFoundError: The workflow does not exist, or this caller may
                not reach it.
            AuthorizationError: The caller lacks `workflows:run`.
            WorkflowNotRunnableError: `real` mode with no published version,
                or `test` mode with no valid, structurally sound draft graph.
        """
        workflow = await self._authorize(ctx, workflow_id, Perm.WORKFLOWS_RUN)
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

        now = datetime.now(UTC)
        run = await workflow_run_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            workflow_version_id=workflow_version_id,
            draft_graph_snapshot=draft_snapshot,
            mode=mode.value,
            triggered_by=triggered_by,
            execution_principal_user_id=ctx.subject_id,
            budget_limit=budget_limit,
            deadline_at=None,
            root_run_id=None,
            causation_run_id=None,
            visited_trigger_ids=[],
            depth=0,
            started_at=now,
        )
        await self._record_resource_refs(run, graph)
        entry_node_run = await workflow_run_repo.create_node_run(
            self.db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_instance_id=graph.entry_node_id,
            scope_path=[],
        )
        await workflow_run_repo.create_outbox(
            self.db,
            organization_id=run.organization_id,
            workflow_run_id=run.id,
            node_run_id=entry_node_run.id,
            available_at=now,
        )
        run = await workflow_run_repo.update_run(
            self.db, run=run, update_data={"status": WorkflowRunStatus.RUNNING.value}
        )
        await events.append(self.db, run=run, kind=events.EventKind.RUN_STARTED)
        self._trigger_dispatch(workflow_run_id=run.id, node_run_id=entry_node_run.id)
        return _read(run)

    async def cancel(self, ctx: AuthContext, run_id: UUID) -> WorkflowRunRead:
        """Stop a run: no further node ever dispatches for it.

        Cancels every non-`done` `DispatchOutbox` row. What the design also
        calls for - cancelling a live linked `agent_runs` row through its
        existing path - has no existing path today: this codebase has no
        agent-run cancellation mechanism to call (grepped across
        `AgentRunnerService`, `agent_run_repo` and the run routes). Inventing
        one is a different subsystem's scope, not #1788's; a `NodeRun` still
        `waiting`/`approval` when its workflow is cancelled is left exactly
        as it was; whichever issue adds agent-run cancellation should close
        this gap in the same change.

        Raises:
            NotFoundError: No such run, or this caller may not reach its workflow.
            AuthorizationError: The caller lacks `workflows:run`.
            WorkflowRunAlreadyTerminalError: The run already ended.
        """
        run = await workflow_run_repo.get_run_by_id_for_update(self.db, run_id)
        if run is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        await self._authorize(ctx, run.workflow_id, Perm.WORKFLOWS_RUN)
        if WorkflowRunStatus(run.status).is_terminal:
            raise WorkflowRunAlreadyTerminalError(run_id=run.id, status=run.status)

        await workflow_run_repo.cancel_live_outbox_for_run(self.db, workflow_run_id=run.id)
        run = await workflow_run_repo.update_run(
            self.db,
            run=run,
            update_data={
                "status": WorkflowRunStatus.CANCELLED.value,
                "ended_at": datetime.now(UTC),
                "paused_reason": None,
            },
        )
        await events.append(self.db, run=run, kind=events.EventKind.RUN_CANCELLED)
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
        ids exist. Otherwise, narrowed to the workflows this caller may see
        at all - `visible_resource_ids` - so a role scoped to its own
        workflows does not see every other workflow's run history just
        because it asked for the unfiltered list.
        """
        visible_workflow_ids: list[UUID] | None = None
        if workflow_id is not None:
            await self._authorize(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        else:
            visible_workflow_ids = await visible_resource_ids(
                self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
            )
        items, total = await workflow_run_repo.list_runs(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow_id,
            visible_workflow_ids=visible_workflow_ids,
            skip=skip,
            limit=limit,
        )
        return WorkflowRunList(items=[_read(item) for item in items], total=total)

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

    async def _authorize(self, ctx: AuthContext, workflow_id: UUID, perm: Perm) -> Workflow:
        """The workflow, if this caller may exercise `perm` on it.

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
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        return workflow

    async def _load(self, ctx: AuthContext, run_id: UUID, perm: Perm) -> WorkflowRun:
        run = await workflow_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None:
            raise WorkflowRunNotFoundError(run_id=run_id)
        await self._authorize(ctx, run.workflow_id, perm)
        return run

    async def _resolve_start_graph(
        self, ctx: AuthContext, workflow: Workflow, *, mode: WorkflowRunMode
    ) -> tuple[WorkflowGraph, UUID | None, dict[str, Any] | None, Any]:
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
        # only valid ones. Dispatching a structurally invalid graph (an
        # unregistered node, a cycle, an unbound required input) would not
        # fail cleanly: `begin_attempt` would raise from inside a Prefect
        # flow with nothing catching it, and `workflow-reconcile` would keep
        # re-triggering the same crash forever. Run the same publish-time
        # check here instead, so an invalid draft is refused - with the same
        # field-scoped `GraphValidationError` `publish` itself raises, left
        # to propagate rather than collapsed into a vaguer refusal - before a
        # run row, and an unkillable dispatch loop, ever exists.
        graph = await validate_graph(self.db, ctx, graph)
        return graph, None, graph.model_dump(mode="json"), None

    async def _record_resource_refs(self, run: WorkflowRun, graph: WorkflowGraph) -> None:
        """`FileRef`/`TableIORef` bindings, resolved once at run start.

        Thin and unopinionated, matching the contract itself
        (56-shared-contracts.md, decision 1/2): this records what the graph
        named, not whether it still resolves against real storage - #1791's
        job once it exists.
        """
        for binding in graph.bindings:
            if isinstance(binding.source, FileRef):
                await workflow_run_repo.create_resource_ref(
                    self.db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    kind="file",
                    ref=binding.source.model_dump(mode="json"),
                )
            elif isinstance(binding.source, TableIORef):
                await workflow_run_repo.create_resource_ref(
                    self.db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    kind="table",
                    ref=binding.source.model_dump(mode="json"),
                )

    def _trigger_dispatch(self, *, workflow_run_id: UUID, node_run_id: UUID) -> None:
        """The low-latency direct trigger. Losing this is not a bug -
        `workflow-dispatch-poll` and `workflow-reconcile` both find the same
        row on their own schedule - so this is best-effort, never awaited.
        """
        from app.core.background import spawn_after_commit
        from app.worker.tasks.workflow_tasks import workflow_dispatch_node_flow

        spawn_after_commit(
            self.db,
            workflow_dispatch_node_flow(
                workflow_run_id=str(workflow_run_id), node_run_id=str(node_run_id)
            ),
            name="workflow-dispatch-node",
        )


__all__ = ["WorkflowExecutionService"]
