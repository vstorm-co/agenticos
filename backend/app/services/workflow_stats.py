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
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.db.models.workflow_run import WorkflowRunStatus
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_approval as workflow_approval_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import StoredWorkflowSettings
from app.schemas.workflow_stats import (
    ApprovalOutcomes,
    EditRatioBucket,
    WorkflowApprovalDay,
    WorkflowApprovalsSummary,
    WorkflowApprovalsSummaryRow,
    WorkflowApprovalStats,
    WorkflowApprovalStep,
    WorkflowsSummary,
    WorkflowStats,
    WorkflowStatsDay,
    WorkflowStatsStep,
    WorkflowSummaryRow,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.services.workflow_execution.limits import month_start
from app.workflows.graph.model import NodeInstance, WorkflowGraph

_ENDED = frozenset(status.value for status in WorkflowRunStatus if status.is_terminal)


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
        nodes = {node.id: node for node in (await self._graph(workflow)).nodes}
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
            steps=await self._steps(nodes, scope),
            approvals=await self._approvals(nodes, workflow.id, first_day, days, scope),
        )

    async def summary(self, ctx: AuthContext, *, first: date, last: date) -> WorkflowsSummary:
        """The real runs of every workflow this caller may see, admitted on the UTC days
        from `first` to `last`, and how many of their runs wait for a person now."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
        )
        rows = await workflow_run_repo.runs_by_workflow(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=shared or [],
            since=datetime.combine(first, datetime.min.time(), tzinfo=UTC),
            until=datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        )
        per: dict[UUID, WorkflowSummaryRow] = {}
        succeeded = 0
        for row in rows:
            entry = per.setdefault(
                row.workflow_id,
                WorkflowSummaryRow(id=row.workflow_id, name=row.name, runs=0, failed=0, cost_usd=0),
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
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                see_all=shared is None,
                shared_ids=shared or [],
            ),
            workflows=busiest[:5],
        )

    async def approvals_summary(
        self, ctx: AuthContext, *, first: date, last: date
    ) -> WorkflowApprovalsSummary:
        """The approval outcomes of every workflow this caller may see, for requests
        asked on the UTC days from `first` to `last`; the five with the most requests
        are named. Counts and times only: no request text is read."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
        )
        scope: dict[str, Any] = {
            "organization_id": ctx.organization_id,
            "since": datetime.combine(first, datetime.min.time(), tzinfo=UTC),
            "until": datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
            # A caller whose role reaches every workflow is not narrowed.
            "visible_to_user_id": None if shared is None else ctx.subject_id,
            "shared_ids": shared,
        }
        (total,) = await workflow_approval_repo.outcome_figures(self.db, **scope, level="total")
        rows = await workflow_approval_repo.outcome_figures(self.db, **scope, level="workflow")
        busiest = sorted(rows, key=lambda row: (-row.requests, cast(str, row.name)))
        return WorkflowApprovalsSummary(
            **_outcomes(total).model_dump(),
            workflows=[
                WorkflowApprovalsSummaryRow(
                    **_outcomes(row).model_dump(),
                    # The workflow level always sets both: it joins on the workflow.
                    id=cast(UUID, row.workflow_id),
                    name=cast(str, row.name),
                )
                for row in busiest[:5]
            ],
        )

    async def _steps(
        self, nodes: dict[UUID, NodeInstance], scope: dict[str, Any]
    ) -> list[WorkflowStatsStep]:
        """Each step's figures, named as the live version - or the draft - names it."""
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

    async def _approvals(
        self,
        nodes: dict[UUID, NodeInstance],
        workflow_id: UUID,
        first_day: date,
        days: int,
        scope: dict[str, Any],
    ) -> WorkflowApprovalStats:
        """The workflow's approval outcomes in all, per step and per day."""
        (total,) = await workflow_approval_repo.outcome_figures(
            self.db, **scope, until=None, level="total"
        )
        steps = []
        for row in await workflow_approval_repo.outcome_figures(
            self.db, **scope, until=None, level="step"
        ):
            # A step's key is never null at this level: the join is on node_runs.
            node_instance_id = cast(UUID, row.node_instance_id)
            node = nodes.get(node_instance_id)
            steps.append(
                WorkflowApprovalStep(
                    **_outcomes(row).model_dump(),
                    node_instance_id=node_instance_id,
                    label=None if node is None else node.label,
                    definition_id=None if node is None else node.definition_id,
                )
            )
        steps.sort(key=lambda step: (-step.requests, str(step.node_instance_id)))
        return WorkflowApprovalStats(
            **_outcomes(total).model_dump(),
            by_day=_approval_days(
                first_day,
                days,
                await workflow_approval_repo.outcome_days(
                    self.db,
                    organization_id=scope["organization_id"],
                    workflow_id=workflow_id,
                    since=scope["since"],
                ),
            ),
            steps=steps,
        )

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
        # The window is read off this host's clock and the rows are stamped by the
        # database's, so a row just past the window is clock skew, not an error.
        if (day := by_day.get(row.day)) is None:
            continue
        runs = int(row.runs)
        if row.status == WorkflowRunStatus.SUCCEEDED.value:
            day.succeeded += runs
        elif row.status == WorkflowRunStatus.FAILED.value:
            day.failed += runs
        else:
            day.other += runs
        day.cost_usd += float(row.cost)
    return list(by_day.values())


def _rate(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def _outcomes(row: workflow_approval_repo.OutcomeFigures) -> ApprovalOutcomes:
    """The figures of one aggregate row, with the rates computed from its counts."""
    decided = row.approved_unchanged + row.approved_edited + row.rejected
    return ApprovalOutcomes(
        requests=row.requests,
        pending=row.pending,
        approved_unchanged=row.approved_unchanged,
        approved_edited=row.approved_edited,
        rejected=row.rejected,
        expired=row.expired,
        cancelled=row.cancelled,
        acceptance_rate=_rate(row.approved_unchanged + row.approved_edited, decided),
        unchanged_rate=_rate(row.approved_unchanged, decided),
        decide_p50_seconds=None if row.decide_p50 is None else float(row.decide_p50),
        decide_p95_seconds=None if row.decide_p95 is None else float(row.decide_p95),
        edit_ratio_median=None if row.edit_ratio_median is None else float(row.edit_ratio_median),
        edit_ratios=[
            EditRatioBucket(upto=upto, count=count)
            for upto, count in zip(
                (0.0, 0.1, 0.25, 0.5, 1.0),
                (row.b0, row.b10, row.b25, row.b50, row.b100),
                strict=True,
            )
        ],
    )


def _approval_days(
    first_day: date, days: int, rows: list[workflow_approval_repo.OutcomeDay]
) -> list[WorkflowApprovalDay]:
    """One entry for every day of the window, an empty one for a day nothing was asked."""
    by_day = {
        first_day + timedelta(days=offset): WorkflowApprovalDay(
            day=first_day + timedelta(days=offset)
        )
        for offset in range(days)
    }
    for row in rows:
        if (day := by_day.get(row.day)) is None:
            continue
        if row.status == WorkflowApprovalStatus.APPROVED.value:
            if row.edited:
                day.approved_edited += row.count
            else:
                day.approved_unchanged += row.count
        elif row.status == WorkflowApprovalStatus.REJECTED.value:
            day.rejected += row.count
        elif row.status == WorkflowApprovalStatus.EXPIRED.value:
            day.expired += row.count
    return list(by_day.values())
