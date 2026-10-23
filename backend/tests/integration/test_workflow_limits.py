"""A workflow's own limits - runs at once, one run's spend, a month's - and its figures."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_exposure import WorkflowExposure
from app.db.models.workflow_run import NodeAttempt, NodeRun, WorkflowRun, WorkflowRunMode
from app.schemas.workflow import WorkflowPublish, WorkflowSettings
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowBudgetReachedError,
)
from app.services.workflow_exposure import WorkflowExposureService
from app.services.workflow_registry import WorkflowRegistryService
from app.services.workflow_stats import WorkflowStatsService
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
        yield


def _graph(definition_id: str = "trigger.manual", config: dict[str, Any] | None = None):
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


@pytest.fixture
async def owner(db: AsyncSession) -> AuthContext:
    principal, org = await seed_member(db)
    return AuthContext(user_id=principal.id, organization_id=org.id, role="owner")


async def _published(
    db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph | None = None, **limits: Any
) -> Workflow:
    """A workflow published with `graph`, run with `limits`."""
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.subject_id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Limited",
        status=WorkflowStatus.DRAFT.value,
        visibility=Visibility.ORG.value,
    )
    db.add(workflow)
    await db.flush()
    registry = WorkflowRegistryService(db)
    await registry.update_settings(ctx, workflow.id, WorkflowSettings(**limits))
    workflow.draft_graph = (graph or _graph()).model_dump(mode="json")
    await db.flush()
    await registry.publish(
        ctx, workflow.id, WorkflowPublish(expected_revision=workflow.draft_revision)
    )
    return workflow


async def _start(db: AsyncSession, ctx: AuthContext, workflow: Workflow, mode=WorkflowRunMode.REAL):
    return await WorkflowExecutionService(db).start(ctx, workflow.id, mode=mode, run_input={})


class TestRunsAtOnce:
    async def test_a_real_start_past_the_limit_is_refused_until_one_ends(self, db, owner):
        workflow = await _published(db, owner, max_concurrent_runs=1)
        first = await _start(db, owner, workflow)

        with pytest.raises(WorkflowAdmissionQuotaError) as refused:
            await _start(db, owner, workflow)
        assert refused.value.details["scope"] == "workflow"
        assert "as many runs under way as its settings allow" in refused.value.message

        await db.execute(
            update(WorkflowRun).where(WorkflowRun.id == first.id).values(status="succeeded")
        )
        assert (await _start(db, owner, workflow)).id != first.id

    async def test_a_test_run_is_neither_counted_nor_held_back(self, db, owner):
        workflow = await _published(db, owner, max_concurrent_runs=1)
        await _start(db, owner, workflow, WorkflowRunMode.TEST)
        await _start(db, owner, workflow, WorkflowRunMode.TEST)
        await _start(db, owner, workflow)


class TestWhatARunMaySpend:
    @pytest.mark.security
    async def test_a_run_gets_the_tighter_of_the_setting_and_the_versions_budget(self, db, owner):
        workflow = await _published(db, owner, run_budget_usd=0.5)
        assert (await _start(db, owner, workflow)).budget_limit == 0.5

        await db.execute(
            update(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow.id)
            .values(budget_limit=Decimal("0.2"))
        )
        assert (await _start(db, owner, workflow)).budget_limit == 0.2

    @pytest.mark.security
    async def test_with_no_setting_the_version_budget_holds(self, db, owner):
        workflow = await _published(db, owner)
        assert (await _start(db, owner, workflow)).budget_limit is None


@pytest.mark.security
class TestTheMonthlyBudget:
    async def test_a_spent_month_starts_nothing_test_runs_included(self, db, owner):
        workflow = await _published(db, owner, monthly_budget_usd=1.0)
        run = await _start(db, owner, workflow, WorkflowRunMode.TEST)
        await db.execute(
            update(WorkflowRun).where(WorkflowRun.id == run.id).values(spent_cost=Decimal("1"))
        )

        for mode in (WorkflowRunMode.REAL, WorkflowRunMode.TEST):
            with pytest.raises(WorkflowBudgetReachedError) as refused:
                await _start(db, owner, workflow, mode)
        assert refused.value.status_code == 402
        assert refused.value.details == {"budget_usd": "1.0", "spent_usd": "1.000000"}

    async def test_last_months_spend_is_not_this_months(self, db, owner):
        workflow = await _published(db, owner, monthly_budget_usd=1.0)
        run = await _start(db, owner, workflow)
        last_month = datetime.now(UTC).replace(day=1) - timedelta(days=1)
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run.id)
            .values(spent_cost=Decimal("5"), created_at=last_month)
        )

        assert (await _start(db, owner, workflow)).id != run.id

    async def test_a_schedule_skips_its_tick_once_the_month_is_spent(self, db, owner):
        workflow = await _published(
            db,
            owner,
            _graph("trigger.schedule", {"schedule_kind": "interval", "interval_seconds": 3600}),
            monthly_budget_usd=1.0,
        )
        spent = await _start(db, owner, workflow, WorkflowRunMode.TEST)
        await db.execute(
            update(WorkflowRun).where(WorkflowRun.id == spent.id).values(spent_cost=Decimal("2"))
        )
        exposure = await WorkflowExposureService(db).get_for_workflow(owner, workflow.id)
        assert exposure is not None
        row = await db.get(WorkflowExposure, exposure.id)
        assert row is not None
        row.next_fire_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.flush()

        assert await WorkflowExposureService(db).fire_due(now=datetime.now(UTC)) == []


async def _two_step(db: AsyncSession, ctx: AuthContext) -> tuple[Workflow, WorkflowGraph]:
    start = NodeInstance(
        id=uuid.uuid4(),
        definition_id="trigger.manual",
        definition_version=1,
        label="Start",
        layout=NodePosition(x=0, y=0),
    )
    answer = NodeInstance(
        id=uuid.uuid4(),
        definition_id="core.output",
        definition_version=1,
        layout=NodePosition(x=1, y=0),
    )
    graph = WorkflowGraph(
        entry_node_id=start.id,
        nodes=(start, answer),
        edges=(
            Edge(
                id=uuid.uuid4(),
                source_node_id=start.id,
                source_port="out",
                target_node_id=answer.id,
                target_port="in",
            ),
        ),
    )
    return await _published(db, ctx, graph, monthly_budget_usd=10.0), graph


async def _ran(
    db: AsyncSession,
    ctx: AuthContext,
    workflow: Workflow,
    *,
    status: str,
    seconds: float,
    cost: str,
    mode=WorkflowRunMode.REAL,
    created_at: datetime | None = None,
) -> WorkflowRun:
    """A run that ended `status` after `seconds`, its entry step having spent `cost`."""
    started = await _start(db, ctx, workflow, mode)
    run = await db.get(WorkflowRun, started.id)
    assert run is not None
    began = datetime.now(UTC) - timedelta(minutes=5)
    run.status = status
    run.started_at = began
    run.ended_at = began + timedelta(seconds=seconds)
    run.spent_cost = Decimal(cost)
    if created_at is not None:
        run.created_at = created_at
    (entry,) = (
        await db.execute(select(NodeRun).where(NodeRun.workflow_run_id == run.id))
    ).scalars()
    entry.status = "failed" if status == "failed" else "succeeded"
    entry.started_at = began
    entry.ended_at = began + timedelta(seconds=seconds)
    db.add(
        NodeAttempt(
            organization_id=run.organization_id,
            node_run_id=entry.id,
            attempt_no=1,
            idempotency_key=f"k-{uuid.uuid4()}",
            status="completed",
            cost=Decimal(cost),
            started_at=began,
        )
    )
    await db.flush()
    return run


class TestTheFigures:
    async def test_real_runs_over_the_window_by_status_day_and_step(self, db, owner):
        workflow, graph = await _two_step(db, owner)
        await _ran(db, owner, workflow, status="succeeded", seconds=2, cost="0.01")
        await _ran(db, owner, workflow, status="succeeded", seconds=4, cost="0.02")
        await _ran(db, owner, workflow, status="failed", seconds=10, cost="0.03")
        await _ran(db, owner, workflow, status="cancelled", seconds=1, cost="0")
        await _ran(
            db, owner, workflow, status="succeeded", seconds=1, cost="1", mode=WorkflowRunMode.TEST
        )
        await _ran(
            db,
            owner,
            workflow,
            status="succeeded",
            seconds=1,
            cost="5",
            created_at=datetime.now(UTC) - timedelta(days=40),
        )

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        assert (stats.runs, stats.succeeded, stats.failed, stats.ended) == (4, 2, 1, 4)
        assert stats.success_rate == pytest.approx(0.5)
        assert stats.duration_p50_seconds == pytest.approx(3.0)
        assert stats.duration_p95_seconds == pytest.approx(9.1)
        assert stats.cost_usd == pytest.approx(0.06) and stats.cost_is_partial is False
        assert stats.monthly_budget_usd == 10.0
        assert len(stats.by_day) == 30
        today = stats.by_day[-1]
        assert (today.succeeded, today.failed, today.other) == (2, 1, 1)
        assert today.cost_usd == pytest.approx(0.06)
        assert sum(day.succeeded + day.failed + day.other for day in stats.by_day[:-1]) == 0
        (step,) = stats.steps
        assert (step.node_instance_id, step.label, step.definition_id) == (
            graph.entry_node_id,
            "Start",
            "trigger.manual",
        )
        assert (step.runs, step.failed) == (4, 1)
        assert step.cost_usd == pytest.approx(0.06)
        assert step.avg_seconds == pytest.approx(4.25)

    async def test_the_months_spend_counts_test_runs_and_a_quiet_window_reads_empty(
        self, db, owner
    ):
        workflow, _graph_ = await _two_step(db, owner)
        await _ran(
            db, owner, workflow, status="succeeded", seconds=1, cost="1", mode=WorkflowRunMode.TEST
        )

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=7)

        assert stats.month_cost_usd == pytest.approx(1.0)
        assert (stats.runs, stats.success_rate, stats.duration_p50_seconds) == (0, None, None)
        assert stats.steps == [] and len(stats.by_day) == 7

    async def test_a_step_no_longer_in_the_workflow_is_named_by_nothing(self, db, owner):
        workflow, _graph_ = await _two_step(db, owner)
        run = await _ran(db, owner, workflow, status="succeeded", seconds=1, cost="0")
        db.add(
            NodeRun(
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                node_instance_id=uuid.uuid4(),
                scope_path="",
                status="succeeded",
            )
        )
        workflow.current_version_id = None
        workflow.draft_graph = {}
        await db.flush()

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=1)

        assert {(step.label, step.definition_id) for step in stats.steps} == {(None, None)}

    async def test_a_workflow_never_published_names_its_steps_by_the_draft(self, db, owner):
        workflow, graph = await _two_step(db, owner)
        await _ran(db, owner, workflow, status="succeeded", seconds=1, cost="0")
        workflow.current_version_id = None
        workflow.draft_graph = graph.model_dump(mode="json")
        await db.flush()

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=1)

        assert {(step.label, step.definition_id) for step in stats.steps} == {
            ("Start", "trigger.manual")
        }

    @pytest.mark.security
    async def test_another_organization_reads_no_figures(self, db, owner):
        workflow, _graph_ = await _two_step(db, owner)
        stranger, elsewhere = await seed_member(db)
        with pytest.raises(NotFoundError):
            await WorkflowStatsService(db).stats(
                AuthContext(user_id=stranger.id, organization_id=elsewhere.id, role="owner"),
                workflow.id,
                days=7,
            )


class TestTheSummary:
    async def test_real_runs_of_the_window_by_workflow_busiest_first(self, db, owner):
        quiet, _graph_ = await _two_step(db, owner)
        busy, _graph_ = await _two_step(db, owner)
        busy.name = "Busy"
        await _ran(db, owner, busy, status="succeeded", seconds=1, cost="0.10")
        await _ran(db, owner, busy, status="failed", seconds=1, cost="0.20")
        await _ran(db, owner, quiet, status="succeeded", seconds=1, cost="0.30")
        await _ran(db, owner, quiet, status="needs_attention", seconds=1, cost="0")
        await _ran(
            db, owner, quiet, status="succeeded", seconds=1, cost="9", mode=WorkflowRunMode.TEST
        )
        await _ran(
            db,
            owner,
            quiet,
            status="succeeded",
            seconds=1,
            cost="9",
            created_at=datetime.now(UTC) - timedelta(days=40),
        )
        today = datetime.now(UTC).date()

        summary = await WorkflowStatsService(db).summary(
            owner, first=today - timedelta(days=6), last=today
        )

        assert (summary.runs, summary.succeeded, summary.failed) == (4, 2, 1)
        assert summary.cost_usd == pytest.approx(0.6)
        assert summary.needs_you == 1
        assert [(row.name, row.runs, row.failed) for row in summary.workflows] == [
            ("Busy", 2, 1),
            ("Limited", 2, 0),
        ]

    async def test_with_no_workflow_in_sight_everything_reads_nothing(self, db, owner):
        today = datetime.now(UTC).date()

        summary = await WorkflowStatsService(db).summary(owner, first=today, last=today)

        assert (summary.runs, summary.needs_you, summary.workflows) == (0, 0, [])

    @pytest.mark.security
    async def test_another_organizations_runs_are_not_counted(self, db, owner):
        workflow, _graph_ = await _two_step(db, owner)
        await _ran(db, owner, workflow, status="succeeded", seconds=1, cost="1")
        stranger, elsewhere = await seed_member(db)
        today = datetime.now(UTC).date()

        summary = await WorkflowStatsService(db).summary(
            AuthContext(user_id=stranger.id, organization_id=elsewhere.id, role="owner"),
            first=today,
            last=today,
        )

        assert (summary.runs, summary.workflows) == (0, [])
