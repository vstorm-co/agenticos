"""A workflow node's dispatch is a job queued with its outbox row, against a real Postgres.

`dispatch_outbox` is where a run's position lives; `workflow-dispatch-node` is the
job that wakes a worker for one row. These tests pin the contract between the two:
they commit or roll back together, a row due later has a job that is not claimable
before then, the poll is only the backstop, an early wake queues a due-now job, and
a run goes from admission to its end through the real claim and the production
handlers.
"""

import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.background_job import BackgroundJob
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import background_job as job_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import WorkflowExecutionService, dispatch_queue
from app.worker.tasks import workflow_tasks
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import (
    SeededRun,
    queued_dispatches,
    run_jobs,
    run_next_job,
    seed_member,
    seed_run,
)

pytestmark = pytest.mark.anyio


def _echoes(length: int) -> WorkflowGraph:
    nodes = tuple(
        NodeInstance(
            id=uuid.uuid4(),
            definition_id="debug.echo",
            definition_version=1,
            config={"message": "hi"},
            layout=NodePosition(x=index * 100, y=0),
        )
        for index in range(length)
    )
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        for source, target in pairwise(nodes)
    )
    return WorkflowGraph(entry_node_id=nodes[0].id, nodes=nodes, edges=edges)


async def _published(
    factory: async_sessionmaker[AsyncSession], graph: WorkflowGraph
) -> tuple[Workflow, User, Organization]:
    async with factory() as db:
        owner, org = await seed_member(db)
        body = graph.model_dump(mode="json")
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            owner_user_id=owner.id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Echoes",
            status=WorkflowStatus.PUBLISHED.value,
            visibility=Visibility.PRIVATE.value,
            draft_graph=body,
        )
        db.add(workflow)
        await db.flush()
        version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            organization_id=org.id,
            version=1,
            graph=body,
        )
        db.add(version)
        await db.flush()
        workflow.current_version_id = version.id
        await db.commit()
    return workflow, owner, org


def _ctx(owner: User, org: Organization):
    from app.core.permissions import AuthContext

    return AuthContext(user_id=owner.id, organization_id=org.id, role="owner")


async def _all_jobs(factory: async_sessionmaker[AsyncSession]) -> list[BackgroundJob]:
    async with factory() as db:
        return list(
            (await db.execute(select(BackgroundJob).order_by(BackgroundJob.created_at)))
            .scalars()
            .all()
        )


async def _outbox(seeded: SeededRun) -> DispatchOutbox:
    async with seeded.factory() as db:
        return (
            await db.execute(
                select(DispatchOutbox).where(DispatchOutbox.workflow_run_id == seeded.run.id)
            )
        ).scalar_one()


class TestAdmission:
    async def test_a_rolled_back_admission_queues_no_job(self, engine: AsyncEngine):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        workflow, owner, org = await _published(factory, _echoes(1))

        async with factory() as db:
            await WorkflowExecutionService(db).start(_ctx(owner, org), workflow.id)
            await db.rollback()

        assert await _all_jobs(factory) == []
        async with factory() as db:
            assert (await db.execute(select(DispatchOutbox))).scalars().all() == []

    async def test_a_committed_admission_queues_one_job_for_its_entry_node(
        self, engine: AsyncEngine
    ):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        workflow, owner, org = await _published(factory, _echoes(1))

        async with factory() as db:
            started = await WorkflowExecutionService(db).start(_ctx(owner, org), workflow.id)
            await db.commit()

        (job,) = await queued_dispatches(factory)
        assert job.organization_id == org.id
        assert job.payload["workflow_run_id"] == str(started.id)
        assert job.pool == "workflow" and job.max_attempts == 1
        # Someone started it through the API and may be waiting.
        assert job.priority == 0
        async with factory() as db:
            (row,) = (await db.execute(select(DispatchOutbox))).scalars().all()
        assert job.payload["node_run_id"] == str(row.node_run_id)
        assert row.status == DispatchOutboxStatus.PENDING.value


class TestTimersAndBackoff:
    async def test_a_row_due_later_has_a_job_that_cannot_be_claimed_before_then(
        self, engine: AsyncEngine
    ):
        seeded = await seed_run(engine, _echoes(1))
        due = datetime.now(UTC) + timedelta(hours=1)
        async with seeded.factory() as db:
            run = await workflow_run_repo.get_run_by_id_for_update(db, seeded.run.id)
            assert run is not None
            node_run = await workflow_run_repo.create_node_run(
                db,
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                node_instance_id=uuid.uuid4(),
                scope_path=[],
            )
            row = await dispatch_queue.queue_dispatch(
                db, run=run, node_run_id=node_run.id, available_at=due
            )
            await db.commit()

        (job,) = [
            job
            for job in await queued_dispatches(seeded.factory)
            if job.payload["node_run_id"] == str(node_run.id)
        ]
        assert abs(job.run_after - due) < timedelta(seconds=1)
        assert abs(row.available_at - due) < timedelta(seconds=1)
        # The row's own marker is the hour it is due, not the moment it was written.
        assert row.submitted_at is not None and row.submitted_at >= row.available_at
        async with seeded.factory() as db:
            claimed = await job_repo.claim(
                db, pool="workflow", worker_id="w", lease=timedelta(minutes=1)
            )
        assert claimed is None


class TestThePollBackstop:
    async def test_it_queues_one_job_per_node_however_often_it_looks(self, engine: AsyncEngine):
        seeded = await seed_run(engine, _echoes(1))  # a row with no job: its job was lost
        await _age_the_marker(seeded)

        assert await workflow_tasks.poll_due_dispatches() == 1
        assert len(await queued_dispatches(seeded.factory)) == 1

        # A pool that is backed up leaves the job queued; the next looks add none.
        await _age_the_marker(seeded)
        assert await workflow_tasks.poll_due_dispatches() == 1
        assert len(await queued_dispatches(seeded.factory)) == 1

    async def test_a_job_that_was_cancelled_is_queued_again(self, engine: AsyncEngine):
        seeded = await seed_run(engine, _echoes(1))
        await _age_the_marker(seeded)
        await workflow_tasks.poll_due_dispatches()
        (job,) = await queued_dispatches(seeded.factory)
        async with seeded.factory() as db:
            assert await job_repo.cancel_queued(db, job.id)
            await db.commit()
        await _age_the_marker(seeded)

        await workflow_tasks.poll_due_dispatches()

        statuses = sorted(job.status for job in await queued_dispatches(seeded.factory))
        assert statuses == ["cancelled", "queued"]

    async def test_a_row_whose_job_is_still_inside_its_lease_is_left_alone(
        self, engine: AsyncEngine
    ):
        seeded = await seed_run(engine, _echoes(1))
        async with seeded.factory() as db:
            await db.execute(
                sql_update(DispatchOutbox)
                .where(DispatchOutbox.workflow_run_id == seeded.run.id)
                .values(submitted_at=datetime.now(UTC))
            )
            await db.commit()

        assert await workflow_tasks.poll_due_dispatches() == 0
        assert await queued_dispatches(seeded.factory) == []


async def _age_the_marker(seeded: SeededRun) -> None:
    async with seeded.factory() as db:
        await db.execute(
            sql_update(DispatchOutbox)
            .where(DispatchOutbox.workflow_run_id == seeded.run.id)
            .values(submitted_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await db.commit()


class TestBringForward:
    async def test_an_early_wake_runs_the_node_now_and_the_delayed_job_finds_it_done(
        self, engine: AsyncEngine
    ):
        seeded = await seed_run(engine, _echoes(1))
        entry = await _outbox(seeded)
        due = datetime.now(UTC) + timedelta(hours=1)
        async with seeded.factory() as db:
            # The node was parked on a timer: row and job both wait for the hour.
            await db.execute(
                sql_update(DispatchOutbox)
                .where(DispatchOutbox.id == entry.id)
                .values(available_at=due, submitted_at=due)
            )
            run = await workflow_run_repo.get_run_by_id_for_update(db, seeded.run.id)
            assert run is not None
            await dispatch_queue.queue_dispatch_job(db, entry)
            delayed = (
                await db.execute(
                    select(BackgroundJob).where(BackgroundJob.kind == "workflow-dispatch-node")
                )
            ).scalar_one()
            delayed.run_after = due
            await db.commit()

        async with seeded.factory() as db:
            run = await workflow_run_repo.get_run_by_id_for_update(db, seeded.run.id)
            assert run is not None
            await dispatch_queue.wake_now(db, run=run, node_run_id=entry.node_run_id)
            await db.commit()

        # The due-now job runs the node; the delayed one is not claimable yet.
        assert await run_next_job(seeded.factory)
        assert not await run_next_job(seeded.factory)
        run_row = await _run(seeded)
        assert run_row.status == WorkflowRunStatus.SUCCEEDED.value

        # The hour passes: the shadowed job finds nothing left to claim.
        async with seeded.factory() as db:
            await db.execute(
                sql_update(BackgroundJob)
                .where(BackgroundJob.id == delayed.id)
                .values(run_after=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()
        assert await run_next_job(seeded.factory)
        async with seeded.factory() as db:
            job = await job_repo.get(db, delayed.id)
        assert job is not None and job.status == "succeeded"
        assert job.result == {"status": "nothing_to_claim"}


async def _run(seeded: SeededRun) -> WorkflowRun:
    async with seeded.factory() as db:
        return (
            await db.execute(select(WorkflowRun).where(WorkflowRun.id == seeded.run.id))
        ).scalar_one()


class TestAFullRunThroughTheQueue:
    async def test_a_two_node_run_goes_from_admission_to_its_end_through_the_real_claim(
        self, engine: AsyncEngine
    ):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        workflow, owner, org = await _published(factory, _echoes(2))
        async with factory() as db:
            started = await WorkflowExecutionService(db).start(_ctx(owner, org), workflow.id)
            await db.commit()

        ran = await run_jobs(factory)

        # One job for the entry node, one its settle queued for the successor.
        assert ran == 2
        async with factory() as db:
            run = (
                await db.execute(select(WorkflowRun).where(WorkflowRun.id == started.id))
            ).scalar_one()
        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        jobs = await _all_jobs(factory)
        assert [job.status for job in jobs] == ["succeeded", "succeeded"]
        assert [job.result for job in jobs] == [{"status": "settled"}] * 2
