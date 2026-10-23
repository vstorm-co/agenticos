"""`WorkflowStatsService` - what a workflow's real runs did over a window.

The runs page's figures: how many ran and how they ended, how long they took,
what they cost - by day and by step - and this month's spend against the
workflow's monthly budget. Test runs are left out of every figure but the month's
spend, because the budget counts them: a draft tried twenty times is not twenty
runs of the workflow, but it is twenty runs somebody paid for.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow, WorkflowVersion
from app.db.models.workflow_run import WorkflowRunStatus
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import StoredWorkflowSettings
from app.schemas.workflow_stats import (
    WorkflowsSummary,
    WorkflowStats,
    WorkflowStatsDay,
    WorkflowStatsStep,
    WorkflowSummaryRow,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.services.workflow_execution.limits import month_start
from app.workflows.graph.model import WorkflowGraph

_ENDED = frozenset(status.value for status in WorkflowRunStatus if status.is_terminal)

_SUMMARY_WORKFLOWS = 500
"""The most workflows the dashboard's summary reads: an organization's whole set, in practice."""


class WorkflowStatsService:
    """Read a workflow's run figures for whoever may view it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def stats(self, ctx: AuthContext, workflow_id: UUID, *, days: int) -> WorkflowStats:
        """The workflow's real runs over the last `days` UTC days, today included.

        Raises:
            NotFoundError: The workflow does not exist, or this caller may not view it.
        """
        workflow = await workflow_repo.get(
            self.db, workflow_id, organization_id=ctx.organization_id
        )
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        now = datetime.now(UTC)
        first_day = now.date() - timedelta(days=days - 1)
        since = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
        scope = {"organization_id": ctx.organization_id, "workflow_id": workflow.id, "since": since}

        figures = await workflow_run_repo.run_figures(self.db, **scope)
        counts: dict[str, tuple[int, Decimal, bool]] = figures["counts"]
        runs = sum(count for count, _cost, _partial in counts.values())
        succeeded = counts.get(WorkflowRunStatus.SUCCEEDED.value, (0, Decimal(0), False))[0]
        failed = counts.get(WorkflowRunStatus.FAILED.value, (0, Decimal(0), False))[0]
        ended = sum(count for status, (count, _c, _p) in counts.items() if status in _ENDED)
        settings = StoredWorkflowSettings.model_validate(workflow.settings)
        month_spent = await workflow_run_repo.spent_since(
            self.db,
            organization_id=ctx.organization_id,
            workflow_id=workflow.id,
            since=month_start(now),
        )
        return WorkflowStats(
            days=days,
            since=since,
            runs=runs,
            succeeded=succeeded,
            failed=failed,
            ended=ended,
            success_rate=None if ended == 0 else succeeded / ended,
            duration_p50_seconds=figures["p50"],
            duration_p95_seconds=figures["p95"],
            cost_usd=float(sum((cost for _n, cost, _p in counts.values()), Decimal(0))),
            cost_is_partial=any(partial for _n, _c, partial in counts.values()),
            month_cost_usd=float(month_spent),
            monthly_budget_usd=settings.monthly_budget_usd,
            by_day=_days(first_day, days, await workflow_run_repo.runs_by_day(self.db, **scope)),
            steps=await self._steps(workflow, scope),
        )

    async def summary(self, ctx: AuthContext, *, first: date, last: date) -> WorkflowsSummary:
        """The real runs of every workflow this caller may see, admitted on the UTC days
        from `first` to `last`, and how many of their runs wait for a person now."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
        )
        workflows, _total = await workflow_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=shared or [],
            skip=0,
            limit=_SUMMARY_WORKFLOWS,
        )
        names = {workflow.id: workflow.name for workflow in workflows}
        ids = list(names)
        rows = await workflow_run_repo.runs_by_workflow(
            self.db,
            organization_id=ctx.organization_id,
            workflow_ids=ids,
            since=datetime.combine(first, datetime.min.time(), tzinfo=UTC),
            until=datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        )
        per: dict[UUID, WorkflowSummaryRow] = {}
        succeeded = 0
        for row in rows:
            entry = per.setdefault(
                row.workflow_id,
                WorkflowSummaryRow(
                    id=row.workflow_id, name=names[row.workflow_id], runs=0, failed=0, cost_usd=0
                ),
            )
            entry.runs += int(row.runs)
            entry.cost_usd += float(row.cost)
            if row.status == WorkflowRunStatus.FAILED.value:
                entry.failed += int(row.runs)
            elif row.status == WorkflowRunStatus.SUCCEEDED.value:
                succeeded += int(row.runs)
        busiest = sorted(per.values(), key=lambda entry: (-entry.runs, entry.name))
        return WorkflowsSummary(
            runs=sum(entry.runs for entry in per.values()),
            succeeded=succeeded,
            failed=sum(entry.failed for entry in per.values()),
            cost_usd=sum(entry.cost_usd for entry in per.values()),
            needs_you=await workflow_run_repo.count_waiting_on_people(
                self.db, organization_id=ctx.organization_id, workflow_ids=ids
            ),
            workflows=busiest[:5],
        )

    async def _steps(self, workflow: Workflow, scope: dict[str, Any]) -> list[WorkflowStatsStep]:
        """Each step's figures, named as the live version - or the draft - names it."""
        nodes = {node.id: node for node in (await self._graph(workflow)).nodes}
        steps = []
        for row in await workflow_run_repo.step_figures(self.db, **scope):
            node = nodes.get(row.node_instance_id)
            steps.append(
                WorkflowStatsStep(
                    node_instance_id=row.node_instance_id,
                    label=None if node is None else node.label,
                    definition_id=None if node is None else node.definition_id,
                    runs=int(row.runs),
                    failed=int(row.failed),
                    cost_usd=float(row.cost),
                    avg_seconds=None if row.avg_seconds is None else float(row.avg_seconds),
                )
            )
        return steps

    async def _graph(self, workflow: Workflow) -> WorkflowGraph:
        """The graph the steps are named by: the live version's, else the draft's."""
        if workflow.current_version_id is not None:
            # The workflow's own current version: the foreign key keeps it.
            version = cast(
                WorkflowVersion,
                await workflow_repo.get_version(
                    self.db, workflow.current_version_id, organization_id=workflow.organization_id
                ),
            )
            return WorkflowGraph.model_validate(version.graph)
        if workflow.draft_graph:
            return WorkflowGraph.model_validate(workflow.draft_graph)
        return WorkflowGraph.model_construct(nodes=())


def _days(first_day: date, days: int, rows: list[Any]) -> list[WorkflowStatsDay]:
    """One entry for every day of the window, an empty one for a day nothing ran."""
    by_day = {
        first_day + timedelta(days=offset): WorkflowStatsDay(day=first_day + timedelta(days=offset))
        for offset in range(days)
    }
    for row in rows:
        day = by_day[row.day]
        runs = int(row.runs)
        if row.status == WorkflowRunStatus.SUCCEEDED.value:
            day.succeeded += runs
        elif row.status == WorkflowRunStatus.FAILED.value:
            day.failed += runs
        else:
            day.other += runs
        day.cost_usd += float(row.cost)
    return list(by_day.values())
