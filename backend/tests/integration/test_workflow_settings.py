"""A workflow's settings: its timezone, a default deadline, an error workflow, retention."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_exposure import WorkflowExposure
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import DispatchOutbox, NodeRun, WorkflowRun, WorkflowRunMode
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowPublish, WorkflowSettings
from app.services.agent_trigger import _cron_next
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import WorkflowAdmissionQuotaError
from app.services.workflow_registry import WorkflowRegistryService, WorkflowSettingsInvalidError
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    queued_dispatches,
    seed_member,
    seed_run,
)

pytestmark = pytest.mark.anyio

CRON = {"schedule_kind": "cron", "cron_expression": "0 9 * * *"}
HOURLY = {"schedule_kind": "interval", "interval_seconds": 3600}


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


class TestTheRunsTimezone:
    async def test_a_run_keeps_the_workflows_timezone_as_it_stood_at_the_start(self, db, owner):
        workflow = await _workflow(db, owner)
        await _publish(db, owner, workflow, _graph("trigger.manual"))
        registry = WorkflowRegistryService(db)
        await registry.update_settings(
            owner, workflow.id, WorkflowSettings(timezone="Europe/Warsaw")
        )
        service = WorkflowExecutionService(db)

        before = await service.start(owner, workflow.id)
        await registry.update_settings(owner, workflow.id, WorkflowSettings(timezone="Asia/Tokyo"))
        after = await service.start(owner, workflow.id)

        stored = {run.id: run.timezone for run in (await db.execute(select(WorkflowRun))).scalars()}
        assert (stored[before.id], stored[after.id]) == ("Europe/Warsaw", "Asia/Tokyo")


async def _failing_setup(engine: AsyncEngine, *, triggered_by: str = "api") -> tuple[Any, Workflow]:
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
        engine,
        WorkflowGraph(entry_node_id=entry.id, nodes=(entry,)),
        member=(principal, org),
        triggered_by=triggered_by,
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
        # Queued with the failure's own settle, like any admission.
        assert outbox.submitted_at is not None
        (job,) = await queued_dispatches(
            async_sessionmaker(engine, expire_on_commit=False), workflow_run_id=started.id
        )
        assert job.payload["node_run_id"] == str(outbox.node_run_id)

    @pytest.mark.security
    async def test_a_failure_run_under_a_public_root_is_public(self, engine: AsyncEngine):
        """The error workflow's run answers for the failed run's chain: an
        outsider started that, so nobody is behind this one either (D18a(5))."""
        seeded, handler = await _failing_setup(engine, triggered_by="webhook")

        await drive(seeded)

        [started] = await _runs_of(engine, handler.id)
        assert (started.triggered_by, started.root_run_id) == ("workflow_failed", seeded.run.id)
        assert started.public_origin is True

    @pytest.mark.security
    async def test_a_failure_run_under_a_door_root_stored_before_the_flag_is_public(
        self, engine: AsyncEngine
    ):
        """A webhook run admitted by code older than the column reads false, and
        its error workflow's run still fails closed on its trigger."""
        seeded, handler = await _failing_setup(engine, triggered_by="webhook")
        async with seeded.factory() as db:
            await workflow_run_repo.update_run(
                db, run=seeded.run, update_data={"public_origin": False}
            )
            await db.commit()

        await drive(seeded)

        [started] = await _runs_of(engine, handler.id)
        assert started.public_origin is True

    async def test_a_failure_run_under_a_member_root_is_not_public(self, engine: AsyncEngine):
        seeded, handler = await _failing_setup(engine)

        await drive(seeded)

        [started] = await _runs_of(engine, handler.id)
        assert started.public_origin is False

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


async def test_retention_keeps_a_finished_called_run_until_its_caller_ends(
    engine: AsyncEngine,
) -> None:
    root = await seed_run(engine, _graph("core.input"))
    child = await seed_run(engine, _graph("core.input"), member=(root.principal, root.org))
    now = datetime.now(UTC)
    async with root.factory() as db:
        parent_node = (
            await db.execute(select(NodeRun).where(NodeRun.workflow_run_id == root.run.id))
        ).scalar_one()
        workflow = await db.get(Workflow, child.run.workflow_id)
        assert workflow is not None
        workflow.settings = {"run_retention_days": 1}
        await workflow_run_repo.update_run(
            db,
            run=child.run,
            update_data={
                "status": "succeeded",
                "ended_at": now - timedelta(days=3),
                "root_run_id": root.run.id,
                "parent_node_run_id": parent_node.id,
            },
        )
        await db.commit()
    async with root.factory() as db:
        assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == []
        await workflow_run_repo.update_run(
            db, run=root.run, update_data={"status": "succeeded", "ended_at": now}
        )
        await db.commit()
    async with root.factory() as db:
        removed = await workflow_run_repo.take_expired_runs(db, now=now, limit=10)
        assert removed == [(child.run.id, [])]


async def test_retention_keeps_the_source_until_its_retry_ends(engine: AsyncEngine) -> None:
    source = await seed_run(engine, _graph("core.input"))
    retry = await seed_run(engine, _graph("core.input"), member=(source.principal, source.org))
    now = datetime.now(UTC)
    async with source.factory() as db:
        workflow = await db.get(Workflow, source.run.workflow_id)
        assert workflow is not None
        workflow.settings = {"run_retention_days": 1}
        await workflow_run_repo.update_run(
            db,
            run=source.run,
            update_data={"status": "failed", "ended_at": now - timedelta(days=3)},
        )
        await workflow_run_repo.update_run(
            db, run=retry.run, update_data={"retry_of_run_id": source.run.id}
        )
        await db.commit()
    async with source.factory() as db:
        assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == []
        await workflow_run_repo.update_run(
            db, run=retry.run, update_data={"status": "succeeded", "ended_at": now}
        )
        await db.commit()
    async with source.factory() as db:
        assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == [
            (source.run.id, [])
        ]


async def test_retention_keeps_file_producers_while_another_run_imports_their_outputs(
    engine: AsyncEngine,
) -> None:
    source = await seed_run(engine, _graph("core.input"))
    importer = await seed_run(engine, _graph("core.input"), member=(source.principal, source.org))
    now = datetime.now(UTC)
    async with source.factory() as db:
        workflow = await db.get(Workflow, source.run.workflow_id)
        assert workflow is not None
        workflow.settings = {"run_retention_days": 1}
        await workflow_run_repo.update_run(
            db,
            run=source.run,
            update_data={"status": "failed", "ended_at": now - timedelta(days=3)},
        )
        await workflow_run_repo.update_run(
            db, run=importer.run, update_data={"status": "succeeded", "ended_at": now}
        )
        file_id = uuid.uuid4()
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=source.org.id,
                workflow_run_id=source.run.id,
                storage_path="retained/import",
                content_type="text/plain",
                byte_size=1,
            )
        )
        await db.flush()
        ref = await workflow_run_repo.create_resource_ref(
            db,
            organization_id=source.org.id,
            workflow_run_id=importer.run.id,
            kind="file",
            ref={"file_id": str(file_id)},
        )
        assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == []
        await db.delete(ref)
        await db.flush()
        assert await workflow_run_repo.take_expired_runs(db, now=now, limit=10) == [
            (source.run.id, ["retained/import"])
        ]


async def test_a_workflows_own_later_run_keeps_its_files_only_when_asked_to_count(
    engine: AsyncEngine,
) -> None:
    from app.repositories import workflow_file as workflow_file_repo

    source = await seed_run(engine, _graph("core.input"))
    importer = await seed_run(engine, _graph("core.input"), member=(source.principal, source.org))
    async with source.factory() as db:
        await workflow_run_repo.update_run(
            db, run=importer.run, update_data={"workflow_id": source.run.workflow_id}
        )
        file_id = uuid.uuid4()
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=source.org.id,
                workflow_run_id=source.run.id,
                storage_path="retained/own",
                content_type="text/plain",
                byte_size=1,
            )
        )
        await db.flush()
        await workflow_run_repo.create_resource_ref(
            db,
            organization_id=source.org.id,
            workflow_run_id=importer.run.id,
            kind="file",
            ref={"file_id": str(file_id)},
        )
        scope = {"organization_id": source.org.id, "workflow_id": source.run.workflow_id}

        assert await workflow_file_repo.files_are_referenced(db, **scope) is False
        assert (
            await workflow_file_repo.files_are_referenced(db, **scope, include_same_workflow=True)
            is True
        )


@pytest.mark.security
async def test_error_workflow_retains_the_configuring_app_admins_current_authority(engine):
    from sqlalchemy import update

    from app.db.models.organization import OrganizationMember
    from app.db.models.user import User

    seeded, target = await _failing_setup(engine)
    async with seeded.factory() as db:
        await db.execute(
            update(User).where(User.id == seeded.principal.id).values(is_app_admin=True)
        )
        await db.execute(
            update(OrganizationMember)
            .where(
                OrganizationMember.organization_id == seeded.org.id,
                OrganizationMember.user_id == seeded.principal.id,
            )
            .values(role="viewer")
        )
        await db.commit()
    await drive(seeded)
    assert len(await _runs_of(engine, target.id)) == 1


async def test_version_pages_are_bounded_and_do_not_load_frozen_graphs(db):
    from sqlalchemy.exc import InvalidRequestError

    from app.db.models.workflow import WorkflowVersion
    from app.repositories import workflow as workflow_repo

    user, org = await seed_member(db)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    workflow = await _workflow(db, ctx)
    graph = _graph("trigger.manual").model_dump(mode="json")
    for number in range(1, 54):
        db.add(
            WorkflowVersion(
                id=uuid.uuid4(),
                workflow_id=workflow.id,
                organization_id=org.id,
                version=number,
                graph=graph,
            )
        )
    await db.flush()
    workflow_id = workflow.id
    db.expunge_all()
    lean = await workflow_repo.list_versions(
        db, workflow_id=workflow_id, organization_id=org.id, limit=2
    )
    assert [version.version for version in lean] == [53, 52, 51]
    assert all("graph" not in version.__dict__ for version in lean)
    with pytest.raises(InvalidRequestError, match="raiseload"):
        _ = lean[0].graph
    registry = WorkflowRegistryService(db)
    first = await registry.list_versions(ctx, workflow_id)
    assert len(first.items) == 50 and first.next_before == 4
    db.add(
        WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            organization_id=org.id,
            version=54,
            graph=graph,
        )
    )
    await db.flush()
    last = await registry.list_versions(ctx, workflow_id, before=first.next_before)
    assert [version.version for version in last.items] == [3, 2, 1]
    assert last.next_before is None


@pytest.mark.security
async def test_api_keys_cannot_capture_the_issuers_authority_as_an_error_workflow(db, owner):
    source = await _workflow(db, owner)
    handler = await _workflow(db, owner, "Error handler")
    await _publish(db, owner, handler, _graph("trigger.workflow_failed"))
    key_ctx = replace(
        owner,
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset({Perm.WORKFLOWS_VIEW, Perm.WORKFLOWS_EDIT, Perm.WORKFLOWS_RUN}),
    )
    with pytest.raises(AuthorizationError, match="member session"):
        await WorkflowRegistryService(db).update_settings(
            key_ctx, source.id, WorkflowSettings(error_workflow_id=handler.id)
        )
    assert not source.settings.get("error_workflow_run_as")


@pytest.mark.security
async def test_retention_rechecks_imports_committed_after_its_candidate_query(engine, monkeypatch):
    import asyncio

    from app.db.locks import LockScope
    from app.workflows.contracts.io import Binding, FileRef

    source = await seed_run(engine, _graph("core.input"))
    now = datetime.now(UTC)
    file_id = uuid.uuid4()
    async with source.factory() as db:
        workflow = await db.get(Workflow, source.run.workflow_id)
        assert workflow is not None
        workflow.settings = {"run_retention_days": 1}
        await workflow_run_repo.update_run(
            db,
            run=source.run,
            update_data={"status": "succeeded", "ended_at": now - timedelta(days=3)},
        )
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=source.org.id,
                workflow_run_id=source.run.id,
                storage_path="race/file",
                content_type="text/plain",
                byte_size=1,
            )
        )
        await db.commit()
    node = NodeInstance(
        id=uuid.uuid4(),
        definition_id="file.read",
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    graph = WorkflowGraph(
        entry_node_id=node.id,
        nodes=(node,),
        bindings=(
            Binding(
                target_node_id=node.id,
                target_field="file",
                source=FileRef(file_id=file_id, content_type="text/plain", byte_size=1),
            ),
        ),
    )
    consumer = await seed_run(engine, graph, member=(source.principal, source.org))
    selected, proceed = asyncio.Event(), asyncio.Event()
    original_lock = workflow_run_repo.hold_subject
    async with source.factory() as sweep_db:

        async def interleave(db, scope, organization_id):
            if db is sweep_db and scope == LockScope.WORKFLOW_FILE_BYTES:
                selected.set()
                await proceed.wait()
            await original_lock(db, scope, organization_id)

        monkeypatch.setattr(workflow_run_repo, "hold_subject", interleave)

        async def sweep():
            taken = await workflow_run_repo.take_expired_runs(sweep_db, now=now, limit=10)
            await sweep_db.commit()
            return taken

        async with asyncio.timeout(10):
            async with asyncio.TaskGroup() as tasks:
                task = tasks.create_task(sweep())
                await selected.wait()
                async with consumer.factory() as db:
                    await WorkflowExecutionService(db).start(
                        consumer.ctx, consumer.run.workflow_id, mode=WorkflowRunMode.TEST
                    )
                    await db.commit()
                proceed.set()
        assert task.result() == []
    async with source.factory() as db:
        assert await db.get(WorkflowFile, file_id) is not None
