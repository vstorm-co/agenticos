"""A workflow's approval outcomes: what its real runs' requests came to, over a window.

The figures are read through `WorkflowStatsService.stats` and the repository's
aggregates against a real Postgres, because the quantiles and the `FILTER`
counts only exist there.
"""

import statistics
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_approval import WorkflowApproval
from app.db.models.workflow_run import NodeRun, WorkflowRun, WorkflowRunMode
from app.repositories import workflow_approval as approval_repo
from app.services.workflow_stats import WorkflowStatsService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio

# Seconds the nine decided requests of the first step waited, in the order seeded.
GAPS = [60, 120, 180, 240, 300, 360, 420, 480, 540]


@pytest.fixture
async def owner(db: AsyncSession) -> AuthContext:
    principal, org = await seed_member(db)
    return AuthContext(user_id=principal.id, organization_id=org.id, role="owner")


def _step(label: str) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id="human.approval",
        definition_version=1,
        label=label,
        layout=NodePosition(x=0, y=0),
    )


async def _workflow(
    db: AsyncSession,
    ctx: AuthContext,
    steps: tuple[NodeInstance, ...] = (),
    *,
    name: str = "Replies",
    visibility: Visibility = Visibility.ORG,
    owner_user_id: uuid.UUID | None = None,
) -> Workflow:
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=owner_user_id or ctx.subject_id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name=name,
        status=WorkflowStatus.DRAFT.value,
        visibility=visibility.value,
        draft_graph=WorkflowGraph(
            entry_node_id=steps[0].id if steps else uuid.uuid4(), nodes=steps
        ).model_dump(mode="json")
        if steps
        else {},
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def _asked(
    db: AsyncSession,
    workflow: Workflow,
    step: NodeInstance,
    *,
    status: str,
    edited: bool = False,
    edit_ratio: float | None = None,
    editable: bool = False,
    waited: int | None = None,
    mode: WorkflowRunMode = WorkflowRunMode.REAL,
    created_at: datetime | None = None,
    organization_id: uuid.UUID | None = None,
) -> WorkflowApproval:
    """One request `step` made in a run of `workflow`, decided `waited` seconds later."""
    org_id = organization_id or workflow.organization_id
    asked = created_at or datetime.now(UTC)
    run_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        root_run_id=run_id,
        draft_graph_snapshot=workflow.draft_graph,
        organization_id=org_id,
        workflow_id=workflow.id,
        mode=mode.value,
        status="succeeded",
        triggered_by="api",
    )
    db.add(run)
    await db.flush()
    node_run = NodeRun(
        id=uuid.uuid4(),
        organization_id=org_id,
        workflow_run_id=run.id,
        node_instance_id=step.id,
        scope_path=[],
        status="succeeded",
    )
    db.add(node_run)
    await db.flush()
    row = WorkflowApproval(
        organization_id=org_id,
        workflow_id=workflow.id,
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        title="Send it?",
        status=status,
        editable=editable,
        edited=edited,
        edit_ratio=edit_ratio,
        decided_at=None if waited is None else asked + timedelta(seconds=waited),
    )
    row.created_at = asked
    db.add(row)
    await db.flush()
    return row


async def _the_first_step(db: AsyncSession, workflow: Workflow, step: NodeInstance) -> None:
    """Ten requests: 6 approved unchanged, 2 approved edited, 1 rejected, 1 expired."""
    outcomes: list[tuple[str, bool, float | None]] = [
        *[("approved", False, 0.0)] * 6,
        ("approved", True, 0.1),
        ("approved", True, 0.4),
        ("rejected", False, None),
        ("expired", False, None),
    ]
    # The expired request carries a decided_at too: it must not move the quantiles.
    waits: list[int | None] = [*GAPS, 9999]
    for (status, edited, ratio), waited in zip(outcomes, waits, strict=True):
        await _asked(
            db,
            workflow,
            step,
            status=status,
            edited=edited,
            edit_ratio=ratio,
            editable=True,
            waited=waited,
        )


@pytest.fixture
async def replies(db: AsyncSession, owner: AuthContext) -> tuple[Workflow, NodeInstance]:
    step = _step("Approve the reply")
    workflow = await _workflow(db, owner, (step,))
    await _the_first_step(db, workflow, step)
    return workflow, step


class TestTheFiguresOfAStep:
    async def test_the_counts_and_rates_of_a_step(self, db, owner, replies):
        workflow, step = replies

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        (found,) = stats.approvals.steps
        for figures in (stats.approvals, found):
            assert (
                figures.requests,
                figures.pending,
                figures.approved_unchanged,
                figures.approved_edited,
                figures.rejected,
                figures.expired,
                figures.cancelled,
            ) == (10, 0, 6, 2, 1, 1, 0)
            assert figures.acceptance_rate == pytest.approx(8 / 9)
            assert figures.unchanged_rate == pytest.approx(6 / 9)
        assert (found.node_instance_id, found.label, found.definition_id) == (
            step.id,
            "Approve the reply",
            "human.approval",
        )

    async def test_time_to_decide_quantiles_count_decided_requests_only(self, db, owner, replies):
        workflow, _step_ = replies
        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        cuts = statistics.quantiles(GAPS, n=100, method="inclusive")
        assert stats.approvals.decide_p50_seconds == pytest.approx(statistics.median(GAPS))
        assert stats.approvals.decide_p95_seconds == pytest.approx(cuts[94])
        assert stats.approvals.steps[0].decide_p50_seconds == pytest.approx(300.0)

    async def test_the_edit_ratio_distribution(self, db, owner, replies):
        workflow, _step_ = replies

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        assert stats.approvals.edit_ratio_median == pytest.approx(0.25)
        assert [(bucket.upto, bucket.count) for bucket in stats.approvals.edit_ratios] == [
            (0.0, 6),
            (0.1, 1),
            (0.25, 0),
            (0.5, 1),
            (1.0, 0),
        ]

    async def test_a_ratio_on_a_bucket_bound_falls_in_the_lower_bucket(self, db, owner):
        step = _step("Approve")
        workflow = await _workflow(db, owner, (step,))
        for ratio in (0.25, 0.5, 0.5001, 1.0):
            await _asked(
                db,
                workflow,
                step,
                status="approved",
                edited=True,
                edit_ratio=ratio,
                editable=True,
                waited=1,
            )

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=1)

        assert [bucket.count for bucket in stats.approvals.edit_ratios] == [0, 0, 1, 1, 2]

    async def test_each_step_reports_its_own(self, db, owner, replies):
        workflow, first = replies
        second = _step("Approve the refund")
        workflow.draft_graph = WorkflowGraph(
            entry_node_id=first.id, nodes=(first, second)
        ).model_dump(mode="json")
        for _ in range(2):
            await _asked(db, workflow, second, status="rejected", waited=30)
        await _asked(db, workflow, second, status="pending")

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        assert [(step.label, step.requests) for step in stats.approvals.steps] == [
            ("Approve the reply", 10),
            ("Approve the refund", 3),
        ]
        refund = stats.approvals.steps[1]
        assert (refund.rejected, refund.pending, refund.approved_unchanged) == (2, 1, 0)
        assert refund.acceptance_rate == 0.0 and refund.unchanged_rate == 0.0
        assert refund.decide_p50_seconds == pytest.approx(30.0)
        assert refund.edit_ratio_median is None
        assert stats.approvals.requests == 13

    async def test_a_request_decided_before_the_ratio_existed_is_not_counted_as_unchanged_edits(
        self, db, owner
    ):
        step = _step("Approve")
        workflow = await _workflow(db, owner, (step,))
        await _asked(db, workflow, step, status="approved", edited=True, waited=5)

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=1)

        assert (stats.approvals.approved_edited, stats.approvals.approved_unchanged) == (1, 0)
        assert stats.approvals.edit_ratio_median is None
        assert [bucket.count for bucket in stats.approvals.edit_ratios] == [0] * 5

    async def test_a_step_no_longer_in_the_workflow_is_named_by_nothing(self, db, owner):
        step = _step("Gone")
        workflow = await _workflow(db, owner)
        await _asked(db, workflow, step, status="cancelled")

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=1)

        (found,) = stats.approvals.steps
        assert (found.label, found.definition_id, found.cancelled) == (None, None, 1)


class TestWhatIsLeftOut:
    @pytest.mark.security
    async def test_test_runs_and_other_organizations_are_left_out(self, db, owner, replies):
        workflow, step = replies
        await _asked(db, workflow, step, status="approved", waited=1, mode=WorkflowRunMode.TEST)
        _, elsewhere = await seed_member(db)
        await _asked(db, workflow, step, status="approved", waited=1, organization_id=elsewhere.id)

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        assert stats.approvals.requests == 10
        assert stats.approvals.steps[0].requests == 10

    async def test_a_request_outside_the_window_is_left_out(self, db, owner, replies):
        workflow, step = replies
        await _asked(
            db,
            workflow,
            step,
            status="rejected",
            waited=1,
            created_at=datetime.now(UTC) - timedelta(days=40),
        )

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=30)

        assert (stats.approvals.requests, stats.approvals.rejected) == (10, 1)

    async def test_a_workflow_with_no_approvals_reports_zeros(self, db, owner):
        workflow = await _workflow(db, owner)

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=7)

        approvals = stats.approvals
        assert approvals.requests == 0 and approvals.steps == []
        assert (approvals.acceptance_rate, approvals.unchanged_rate) == (None, None)
        assert (approvals.decide_p50_seconds, approvals.decide_p95_seconds) == (None, None)
        assert approvals.edit_ratio_median is None
        assert [(bucket.upto, bucket.count) for bucket in approvals.edit_ratios] == [
            (0.0, 0),
            (0.1, 0),
            (0.25, 0),
            (0.5, 0),
            (1.0, 0),
        ]
        assert len(approvals.by_day) == 7
        assert all(
            (day.approved_unchanged, day.approved_edited, day.rejected, day.expired) == (0, 0, 0, 0)
            for day in approvals.by_day
        )

    @pytest.mark.security
    async def test_a_member_who_may_not_view_the_workflow_gets_not_found(self, db, owner):
        workflow = await _workflow(db, owner, visibility=Visibility.PRIVATE)
        colleague, _org = await seed_member(db)
        member = AuthContext(
            user_id=colleague.id, organization_id=owner.organization_id, role="viewer"
        )

        with pytest.raises(NotFoundError):
            await WorkflowStatsService(db).stats(member, workflow.id, days=7)


class TestTheDaySeries:
    async def test_the_day_series_counts_each_outcome(self, db, owner):
        step = _step("Approve")
        workflow = await _workflow(db, owner, (step,))
        today = datetime.now(UTC)
        yesterday = today - timedelta(days=1)
        for asked, status, edited in (
            (today, "approved", False),
            (today, "approved", False),
            (today, "approved", True),
            (today, "pending", False),
            (yesterday, "rejected", False),
            (yesterday, "expired", False),
            (yesterday, "cancelled", False),
        ):
            await _asked(
                db,
                workflow,
                step,
                status=status,
                edited=edited,
                waited=None if status in ("pending", "expired", "cancelled") else 1,
                created_at=asked,
            )

        stats = await WorkflowStatsService(db).stats(owner, workflow.id, days=3)

        by_day = {day.day: day for day in stats.approvals.by_day}
        assert list(by_day) == [(today - timedelta(days=offset)).date() for offset in (2, 1, 0)]
        quiet, before, now = stats.approvals.by_day
        assert (quiet.approved_unchanged, quiet.rejected, quiet.expired) == (0, 0, 0)
        assert (before.rejected, before.expired, before.approved_unchanged) == (1, 1, 0)
        assert (now.approved_unchanged, now.approved_edited, now.rejected) == (2, 1, 0)


class TestThePerWorkflowLevel:
    async def test_each_workflow_reports_its_own_and_only_the_visible_ones(self, db, owner):
        step = _step("Approve")
        busy = await _workflow(db, owner, (step,), name="Busy")
        quiet = await _workflow(db, owner, (step,), name="Quiet")
        other_member, _org = await seed_member(db)
        hidden = await _workflow(
            db,
            owner,
            (step,),
            name="Hidden",
            visibility=Visibility.PRIVATE,
        )
        for workflow, asks in ((busy, 3), (quiet, 1), (hidden, 2)):
            for _ in range(asks):
                await _asked(db, workflow, step, status="approved", waited=1)
        since = datetime.now(UTC) - timedelta(days=1)

        everything = await approval_repo.outcome_figures(
            db,
            organization_id=owner.organization_id,
            since=since,
            until=datetime.now(UTC) + timedelta(days=1),
            level="workflow",
        )
        seen = await approval_repo.outcome_figures(
            db,
            organization_id=owner.organization_id,
            since=since,
            until=None,
            level="workflow",
            visible_to_user_id=other_member.id,
        )
        shared = await approval_repo.outcome_figures(
            db,
            organization_id=owner.organization_id,
            since=since,
            until=None,
            level="workflow",
            visible_to_user_id=other_member.id,
            shared_ids=[hidden.id],
        )
        past = await approval_repo.outcome_figures(
            db,
            organization_id=owner.organization_id,
            since=since,
            until=since,
            level="workflow",
        )

        assert {(row.name, row.requests) for row in everything} == {
            ("Busy", 3),
            ("Quiet", 1),
            ("Hidden", 2),
        }
        assert {row.workflow_id for row in everything} == {busy.id, quiet.id, hidden.id}
        assert {(row.name, row.requests) for row in seen} == {("Busy", 3), ("Quiet", 1)}
        assert {row.name for row in shared} == {"Busy", "Quiet", "Hidden"}
        assert past == []


async def _colleague(db: AsyncSession, owner: AuthContext) -> AuthContext:
    """A plain member of the owner's organization, with no grant on anything."""
    colleague, _elsewhere = await seed_member(db)
    db.add(
        OrganizationMember(
            organization_id=owner.organization_id, user_id=colleague.id, role="member"
        )
    )
    await db.flush()
    return AuthContext(user_id=colleague.id, organization_id=owner.organization_id, role="member")


def _today() -> date:
    return datetime.now(UTC).date()


class TestTheOrganizationSummary:
    async def test_the_summary_adds_up_every_visible_workflow(self, db, owner):
        step = _step("Approve")
        first = await _workflow(db, owner, (step,), name="First")
        second = await _workflow(db, owner, (step,), name="Second")
        for workflow, status, edited, waited in (
            (first, "approved", False, 60),
            (first, "approved", True, 120),
            (first, "rejected", False, 180),
            (second, "approved", False, 240),
            (second, "pending", False, None),
            (second, "expired", False, None),
        ):
            await _asked(
                db,
                workflow,
                step,
                status=status,
                edited=edited,
                edit_ratio=0.3 if edited else None,
                editable=True,
                waited=waited,
            )

        summary = await WorkflowStatsService(db).approvals_summary(
            owner, first=_today(), last=_today()
        )

        assert (summary.requests, summary.pending, summary.expired) == (6, 1, 1)
        assert (summary.approved_unchanged, summary.approved_edited, summary.rejected) == (2, 1, 1)
        assert summary.acceptance_rate == pytest.approx(3 / 4)
        assert summary.unchanged_rate == pytest.approx(2 / 4)
        assert summary.decide_p50_seconds == pytest.approx(150)
        assert summary.edit_ratio_median == pytest.approx(0.3)
        assert [(bucket.upto, bucket.count) for bucket in summary.edit_ratios] == [
            (0.0, 0),
            (0.1, 0),
            (0.25, 0),
            (0.5, 1),
            (1.0, 0),
        ]
        rows = {row.name: row for row in summary.workflows}
        assert set(rows) == {"First", "Second"}
        assert rows["First"].id == first.id
        assert (rows["First"].requests, rows["First"].approved_edited, rows["First"].rejected) == (
            3,
            1,
            1,
        )
        assert (rows["Second"].requests, rows["Second"].pending, rows["Second"].expired) == (
            3,
            1,
            1,
        )

    @pytest.mark.security
    async def test_a_member_sees_only_the_workflows_they_may_view(self, db, owner):
        step = _step("Approve")
        visible = await _workflow(db, owner, (step,), name="A")
        private = await _workflow(db, owner, (step,), name="B", visibility=Visibility.PRIVATE)
        for workflow in (visible, private, private):
            await _asked(db, workflow, step, status="approved", waited=1)
        member = await _colleague(db, owner)

        summary = await WorkflowStatsService(db).approvals_summary(
            member, first=_today(), last=_today()
        )
        everything = await WorkflowStatsService(db).approvals_summary(
            owner, first=_today(), last=_today()
        )

        assert summary.requests == 1
        assert [(row.name, row.requests) for row in summary.workflows] == [("A", 1)]
        assert everything.requests == 3

    @pytest.mark.security
    async def test_another_organization_sees_nothing(self, db, owner):
        step = _step("Approve")
        workflow = await _workflow(db, owner, (step,))
        await _asked(db, workflow, step, status="approved", waited=1)
        stranger, elsewhere = await seed_member(db)

        summary = await WorkflowStatsService(db).approvals_summary(
            AuthContext(user_id=stranger.id, organization_id=elsewhere.id, role="owner"),
            first=_today(),
            last=_today(),
        )

        assert (summary.requests, summary.workflows) == (0, [])
        assert summary.acceptance_rate is None
        assert [bucket.count for bucket in summary.edit_ratios] == [0, 0, 0, 0, 0]

    async def test_the_five_busiest_come_first(self, db, owner):
        step = _step("Approve")
        for name, asks in (("G", 1), ("F", 2), ("E", 2), ("D", 4), ("C", 5), ("B", 6), ("A", 7)):
            workflow = await _workflow(db, owner, (step,), name=name)
            for _ in range(asks):
                await _asked(db, workflow, step, status="pending")

        summary = await WorkflowStatsService(db).approvals_summary(
            owner, first=_today(), last=_today()
        )

        assert [(row.name, row.requests) for row in summary.workflows] == [
            ("A", 7),
            ("B", 6),
            ("C", 5),
            ("D", 4),
            ("E", 2),
        ]
        assert summary.requests == 27

    async def test_the_window_is_whole_utc_days(self, db, owner):
        step = _step("Approve")
        workflow = await _workflow(db, owner, (step,))
        midnight = datetime.combine(_today(), datetime.min.time(), tzinfo=UTC)
        for asked in (
            midnight - timedelta(seconds=1),
            midnight,
            midnight + timedelta(days=1) - timedelta(seconds=1),
            midnight + timedelta(days=1),
        ):
            await _asked(db, workflow, step, status="pending", created_at=asked)

        summary = await WorkflowStatsService(db).approvals_summary(
            owner, first=_today(), last=_today()
        )

        assert summary.requests == 2
