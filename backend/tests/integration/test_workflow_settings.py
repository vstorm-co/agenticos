"""A workflow's settings: its timezone, a default deadline, an error workflow, retention."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_exposure import WorkflowExposure
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import DispatchOutbox, WorkflowRun, WorkflowRunMode
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowPublish, WorkflowSettings
from app.services.agent_trigger import _cron_next
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import WorkflowAdmissionQuotaError
from app.services.workflow_registry import WorkflowRegistryService, WorkflowSettingsInvalidError
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio

CRON = {"schedule_kind": "cron", "cron_expression": "0 9 * * *"}
HOURLY = {"schedule_kind": "interval", "interval_seconds": 3600}


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
        yield


def _graph(definition_id: str, config: dict[str, Any] | None = None) -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


async def _workflow(db: AsyncSession, ctx: AuthContext, name: str = "Echo") -> Workflow:
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.subject_id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name=name,
        status=WorkflowStatus.DRAFT.value,
        visibility=Visibility.ORG.value,
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def _publish(db: AsyncSession, ctx: AuthContext, workflow: Workflow, graph: WorkflowGraph):
    workflow.draft_graph = graph.model_dump(mode="json")
    await db.flush()
    return await WorkflowRegistryService(db).publish(
        ctx, workflow.id, WorkflowPublish(expected_revision=workflow.draft_revision)
    )


@pytest.fixture
async def owner(db: AsyncSession) -> AuthContext:
    principal, org = await seed_member(db)
    return AuthContext(user_id=principal.id, organization_id=org.id, role="owner")


class TestSavingSettings:
    async def test_the_settings_are_kept_on_the_workflow_and_read_back(self, db, owner):
        workflow = await _workflow(db, owner)
        settings = WorkflowSettings(
            timezone="Europe/Warsaw",
            default_deadline_seconds=600,
            run_retention_days=30,
            keep_succeeded_runs=False,
        )

        detail = await WorkflowRegistryService(db).update_settings(owner, workflow.id, settings)

        assert detail.settings.timezone == "Europe/Warsaw"
        assert (detail.settings.default_deadline_seconds, detail.settings.run_retention_days) == (
            600,
            30,
        )
        assert detail.settings.keep_succeeded_runs is False
        assert (
            await WorkflowRegistryService(db).get(owner, workflow.id)
        ).settings == detail.settings

    def test_a_timezone_that_does_not_exist_is_refused(self):
        with pytest.raises(ValueError, match="is not a timezone"):
            WorkflowSettings(timezone="Mars/Olympus")

    async def test_an_error_workflow_must_be_another_one_the_caller_can_run_starting_from_a_failure(
        self, db, owner
    ):
        workflow = await _workflow(db, owner)
        manual = await _workflow(db, owner, "Manual")
        await _publish(db, owner, manual, _graph("trigger.manual"))
        service = WorkflowRegistryService(db)

        for target, reason in (
            (workflow.id, "own error workflow"),
            (uuid.uuid4(), "No workflow you can run"),
            (manual.id, "On failure of a workflow"),
        ):
            with pytest.raises(WorkflowSettingsInvalidError, match=reason) as refused:
                await service.update_settings(
                    owner, workflow.id, WorkflowSettings(error_workflow_id=target)
                )
            assert refused.value.details["field"] == "error_workflow_id"

    async def test_an_error_workflow_runs_as_whoever_chose_it(self, db, owner):
        workflow = await _workflow(db, owner)
        handler = await _workflow(db, owner, "On failure")
        await _publish(db, owner, handler, _graph("trigger.workflow_failed"))
        service = WorkflowRegistryService(db)

        chosen = await service.update_settings(
            owner, workflow.id, WorkflowSettings(error_workflow_id=handler.id)
        )
        assert chosen.settings.error_workflow_run_as == owner.subject_id

        colleague, _org = await seed_member(db)
        other = AuthContext(
            user_id=colleague.id, organization_id=owner.organization_id, role="owner"
        )
        kept = await service.update_settings(
            other, workflow.id, WorkflowSettings(error_workflow_id=handler.id, timezone="UTC")
        )
        assert kept.settings.error_workflow_run_as == owner.subject_id
        cleared = await service.update_settings(other, workflow.id, WorkflowSettings())
        assert cleared.settings.error_workflow_run_as is None


class TestTheTimezone:
    def test_a_cron_expression_is_read_in_the_timezone(self):
        now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert _cron_next("0 9 * * *", now=now) == datetime(2026, 1, 16, 9, 0, tzinfo=UTC)
        assert _cron_next("0 9 * * *", now=now, timezone="Europe/Warsaw") == datetime(
            2026, 1, 16, 8, 0, tzinfo=UTC
        )

    async def test_a_published_schedule_keeps_the_workflows_timezone_and_moves_with_it(
        self, db, owner
    ):
        workflow = await _workflow(db, owner)
        service = WorkflowRegistryService(db)
        await service.update_settings(owner, workflow.id, WorkflowSettings(timezone="Asia/Tokyo"))
        published = await _publish(db, owner, workflow, _graph("trigger.schedule", CRON))
        exposure = await db.get(WorkflowExposure, published.exposure.id)
        assert exposure is not None and exposure.timezone == "Asia/Tokyo"
        assert exposure.next_fire_at is not None and exposure.next_fire_at.hour == 0

        await service.update_settings(
            owner, workflow.id, WorkflowSettings(timezone="Europe/Warsaw")
        )
        await db.refresh(exposure)
        assert exposure.timezone == "Europe/Warsaw"
        assert exposure.next_fire_at.hour in (7, 8)

    async def test_an_interval_or_a_paused_schedule_keeps_its_count(self, db, owner):
        workflow = await _workflow(db, owner)
        service = WorkflowRegistryService(db)
        published = await _publish(db, owner, workflow, _graph("trigger.schedule", HOURLY))
        exposure = await db.get(WorkflowExposure, published.exposure.id)
        assert exposure is not None
        tick = exposure.next_fire_at

        await service.update_settings(owner, workflow.id, WorkflowSettings(timezone="Asia/Tokyo"))
        await db.refresh(exposure)
        assert (exposure.timezone, exposure.next_fire_at) == ("Asia/Tokyo", tick)
        # Unchanged, nothing to move.
        await service.update_settings(owner, workflow.id, WorkflowSettings(timezone="Asia/Tokyo"))

    async def test_a_workflow_with_no_schedule_has_nothing_to_move(self, db, owner):
        workflow = await _workflow(db, owner)
        await _publish(db, owner, workflow, _graph("trigger.manual"))

        detail = await WorkflowRegistryService(db).update_settings(
            owner, workflow.id, WorkflowSettings(timezone="Asia/Tokyo")
        )

        assert detail.settings.timezone == "Asia/Tokyo"


class TestTheDefaultDeadline:
    async def test_a_run_nobody_gave_a_deadline_gets_the_workflows(self, db, owner):
        workflow = await _workflow(db, owner)
        await _publish(db, owner, workflow, _graph("trigger.manual"))
        await WorkflowRegistryService(db).update_settings(
            owner, workflow.id, WorkflowSettings(default_deadline_seconds=600)
        )
        service = WorkflowExecutionService(db)

        defaulted = await service.start(owner, workflow.id)
        named = await service.start(owner, workflow.id, deadline_seconds=60)

        assert defaulted.deadline_at is not None and named.deadline_at is not None
        assert defaulted.deadline_at - named.deadline_at > timedelta(minutes=8)


async def _failing_setup(engine: AsyncEngine) -> tuple[Any, Workflow]:
    """A real run that fails, of a workflow whose error workflow is published."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        principal, org = await seed_member(db)
        ctx = AuthContext(user_id=principal.id, organization_id=org.id, role="owner")
        handler = await _workflow(db, ctx, "On failure")
        await _publish(db, ctx, handler, _graph("trigger.workflow_failed"))
        await db.commit()
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="error.raise",
        definition_version=1,
        config={"code": "BAD_LEAD", "message": "The lead has no email"},
        layout=NodePosition(x=0, y=0),
        label="Check the lead",
    )
    seeded = await seed_run(
        engine, WorkflowGraph(entry_node_id=entry.id, nodes=(entry,)), member=(principal, org)
    )
    async with factory() as db:
        await WorkflowRegistryService(db).update_settings(
            ctx, seeded.run.workflow_id, WorkflowSettings(error_workflow_id=handler.id)
        )
        await workflow_run_repo.update_run(
            db, run=seeded.run, update_data={"mode": WorkflowRunMode.REAL.value}
        )
        await db.commit()
    return seeded, handler


async def _runs_of(engine: AsyncEngine, workflow_id: uuid.UUID) -> list[WorkflowRun]:
    async with async_sessionmaker(engine)() as db:
        rows = await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id))
        return list(rows.scalars().all())


class TestTheErrorWorkflow:
    async def test_a_failed_run_starts_it_once_with_what_failed(self, engine: AsyncEngine):
        seeded, handler = await _failing_setup(engine)

        await drive(seeded)

        [started] = await _runs_of(engine, handler.id)
        assert started.triggered_by == "workflow_failed"
        assert started.causation_run_id == seeded.run.id
        assert started.input["run_id"] == str(seeded.run.id)
        assert started.input["step_name"] == "Check the lead"
        assert started.input["error"] == {"code": "BAD_LEAD", "message": "The lead has no email"}
        async with async_sessionmaker(engine)() as db:
            outbox = (
                await db.execute(
                    select(DispatchOutbox).where(DispatchOutbox.workflow_run_id == started.id)
                )
            ).scalar_one()
        # Left to the poll: the settle that failed the run cannot submit it.
        assert outbox.submitted_at is None

    async def test_a_test_run_or_an_error_workflows_own_run_starts_nothing(
        self, engine: AsyncEngine
    ):
        seeded, handler = await _failing_setup(engine)
        async with seeded.factory() as db:
            await workflow_run_repo.update_run(
                db, run=seeded.run, update_data={"triggered_by": "workflow_failed"}
            )
            await db.commit()
        await drive(seeded)
        assert await _runs_of(engine, handler.id) == []

        again, other = await _failing_setup(engine)
        async with again.factory() as db:
            await workflow_run_repo.update_run(
                db, run=again.run, update_data={"mode": WorkflowRunMode.TEST.value}
            )
            await db.commit()
        await drive(again)
        assert await _runs_of(engine, other.id) == []

    async def test_nothing_starts_when_the_error_workflow_can_no_longer_be_run(
        self, engine: AsyncEngine, caplog
    ):
        seeded, handler = await _failing_setup(engine)
        async with seeded.factory() as db:
            row = await db.get(Workflow, handler.id)
            assert row is not None
            row.status = WorkflowStatus.ARCHIVED.value
            await db.commit()

        await drive(seeded)

        assert await _runs_of(engine, handler.id) == []
        assert "workflow_error_workflow_not_started" in caplog.text

    async def test_a_member_gone_or_a_quota_reached_starts_nothing(
        self, engine: AsyncEngine, caplog
    ):
        seeded, handler = await _failing_setup(engine)
        with patch(
            "app.services.workflow_execution.failure.member_repo.get_active",
            new=AsyncMock(return_value=None),
        ):
            await drive(seeded)
        assert await _runs_of(engine, handler.id) == []

        again, other = await _failing_setup(engine)
        with patch(
            "app.services.workflow_execution.facade.admission.enforce_admission_quota",
            new=AsyncMock(
                side_effect=WorkflowAdmissionQuotaError(
                    scope="organization", limit=1, outstanding=1, requested=1
                )
            ),
        ):
            await drive(again)
        assert await _runs_of(engine, other.id) == []
        assert "workflow_error_workflow_refused" in caplog.text

    async def test_a_workflow_with_no_error_workflow_starts_none(self, engine: AsyncEngine):
        entry = NodeInstance(
            id=uuid.uuid4(),
            definition_id="error.raise",
            definition_version=1,
            config={"code": "BAD", "message": "No"},
            layout=NodePosition(x=0, y=0),
        )
        seeded = await seed_run(engine, WorkflowGraph(entry_node_id=entry.id, nodes=(entry,)))
        async with seeded.factory() as db:
            await workflow_run_repo.update_run(
                db, run=seeded.run, update_data={"mode": WorkflowRunMode.REAL.value}
            )
            await db.commit()

        run = await drive(seeded)

        assert run.status == "failed"


class TestKeepingRuns:
    async def test_runs_past_the_retention_go_with_their_files_and_a_chains_root_stays(
        self, engine: AsyncEngine
    ):
        graph = _graph("core.input")
        old = await seed_run(engine, graph)
        recent = await seed_run(engine, graph, member=(old.principal, old.org))
        now = datetime.now(UTC)
        async with old.factory() as db:
            workflow = await db.get(Workflow, old.run.workflow_id)
            assert workflow is not None
            workflow.settings = {"run_retention_days": 7}
            other = await db.get(Workflow, recent.run.workflow_id)
            assert other is not None
            other.settings = {"keep_succeeded_runs": False}
            for run, status, ended in (
                (old.run, "failed", now - timedelta(days=8)),
                (recent.run, "succeeded", now - timedelta(days=2)),
            ):
                await workflow_run_repo.update_run(
                    db, run=run, update_data={"status": status, "ended_at": ended}
                )
            db.add(
                WorkflowFile(
                    id=uuid.uuid4(),
                    organization_id=old.org.id,
                    workflow_run_id=old.run.id,
                    storage_path="workflow-files/x/y/z",
                    content_type="text/plain",
                    byte_size=1,
                )
            )
            await db.commit()

        async with old.factory() as db:
            taken = dict(await workflow_run_repo.take_expired_runs(db, now=now, limit=10))
            await db.commit()

        assert taken == {old.run.id: ["workflow-files/x/y/z"], recent.run.id: []}
        async with old.factory() as db:
            assert await db.get(WorkflowRun, old.run.id) is None
            assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == []

    async def test_a_run_a_chain_starts_from_is_kept_until_the_chain_has_gone(
        self, engine: AsyncEngine
    ):
        root = await seed_run(engine, _graph("core.input"))
        now = datetime.now(UTC)
        async with root.factory() as db:
            workflow = await db.get(Workflow, root.run.workflow_id)
            assert workflow is not None
            workflow.settings = {"run_retention_days": 1}
            await workflow_run_repo.update_run(
                db,
                run=root.run,
                update_data={"status": "failed", "ended_at": now - timedelta(days=3)},
            )
            await workflow_run_repo.create_run(
                db,
                organization_id=root.org.id,
                workflow_id=root.run.workflow_id,
                workflow_version_id=None,
                draft_graph_snapshot=root.graph.model_dump(mode="json"),
                mode="test",
                triggered_by="api",
                execution_principal_user_id=root.principal.id,
                budget_limit=None,
                node_count=1,
                deadline_at=None,
                root_run_id=root.run.id,
                causation_run_id=root.run.id,
                visited_trigger_ids=[],
                depth=1,
                started_at=now,
            )
            await db.commit()

        async with root.factory() as db:
            assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == []


class TestStartingAnErrorWorkflowDirectly:
    """`start_error_workflow` called as the run's end calls it, each way out of it."""

    async def test_it_admits_the_error_workflow_or_leaves_it(self, engine: AsyncEngine):
        from app.services.workflow_execution.failure import start_error_workflow
        from app.workflows.contracts.results import WorkflowError

        seeded, handler = await _failing_setup(engine)
        error = WorkflowError(code="BAD_LEAD", message="No email")
        step_id = seeded.graph.entry_node_id
        async with seeded.factory() as db:
            run = await db.get(WorkflowRun, seeded.run.id)
            assert run is not None
            await start_error_workflow(db, run=run, step_id=step_id, error=error)
            with patch(
                "app.services.workflow_execution.facade.admission.enforce_admission_quota",
                new=AsyncMock(
                    side_effect=WorkflowAdmissionQuotaError(
                        scope="organization", limit=1, outstanding=1, requested=1
                    )
                ),
            ):
                await start_error_workflow(db, run=run, step_id=step_id, error=error)
            await db.commit()
        assert len(await _runs_of(engine, handler.id)) == 1

        async with seeded.factory() as db:
            run = await db.get(WorkflowRun, seeded.run.id)
            workflow = await db.get(Workflow, seeded.run.workflow_id)
            assert run is not None and workflow is not None
            workflow.settings = {}
            await db.flush()
            await start_error_workflow(db, run=run, step_id=step_id, error=error)
            with patch(
                "app.services.workflow_execution.failure.workflow_repo.get",
                new=AsyncMock(return_value=None),
            ):
                await start_error_workflow(db, run=run, step_id=step_id, error=error)
        assert len(await _runs_of(engine, handler.id)) == 1


class TestTheFailureTrigger:
    async def test_the_error_workflow_hands_on_what_failed(self, engine: AsyncEngine):
        seeded, handler = await _failing_setup(engine)
        await drive(seeded)
        [started] = await _runs_of(engine, handler.id)
        async with seeded.factory() as db:
            row = await db.get(WorkflowRun, started.id)
        assert row is not None
        graph = WorkflowGraph.model_validate(
            await _version_graph(engine, started.workflow_version_id)
        )
        error_run = SeededRun(
            run=row,
            graph=graph,
            principal=seeded.principal,
            org=seeded.org,
            factory=seeded.factory,
        )

        finished = await drive(error_run)

        assert finished.status == "succeeded"

    async def test_a_test_run_with_no_failure_to_hand_on_says_so(self, engine: AsyncEngine):
        seeded = await seed_run(engine, _graph("trigger.workflow_failed"), run_input={})

        run = await drive(seeded)

        assert run.status == "failed"
        assert run.error["code"] == "TRIGGER_INPUT_INVALID"


async def _version_graph(engine: AsyncEngine, version_id: uuid.UUID | None) -> dict[str, Any]:
    from app.db.models.workflow import WorkflowVersion

    async with async_sessionmaker(engine)() as db:
        version = await db.get(WorkflowVersion, version_id)
        assert version is not None
        return version.graph
