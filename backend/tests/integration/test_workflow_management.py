"""Looking after a workflow from the console: its name and tags, its switch, archiving, deleting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_exposure import WorkflowExposure
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode, WorkflowRunStatus
from app.repositories import resource_grant_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowPublish, WorkflowUpdate
from app.schemas.workflow_run import WorkflowStepTest
from app.services.access import WORKFLOW
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import WorkflowArchivedError
from app.services.workflow_registry import WorkflowInUseError, WorkflowRegistryService
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio

HOURLY = {"schedule_kind": "interval", "interval_seconds": 3600}


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
        yield


def _graph(definition_id: str, config: dict | None = None) -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


@pytest.fixture
async def tenant(db):
    owner, org = await seed_member(db)
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Echo",
        status=WorkflowStatus.DRAFT.value,
        visibility=Visibility.ORG.value,
    )
    db.add(workflow)
    await db.flush()
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    return ctx, workflow


async def _publish(db, ctx, workflow, graph):
    workflow.draft_graph = graph.model_dump(mode="json")
    await db.flush()
    return await WorkflowRegistryService(db).publish(
        ctx, workflow.id, WorkflowPublish(expected_revision=workflow.draft_revision)
    )


async def _unfinished_run(db, ctx, workflow) -> None:
    graph = _graph("core.input")
    run = await workflow_run_repo.create_run(
        db,
        organization_id=ctx.organization_id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        draft_graph_snapshot=graph.model_dump(mode="json"),
        mode=WorkflowRunMode.TEST.value,
        triggered_by="api",
        execution_principal_user_id=ctx.subject_id,
        budget_limit=None,
        node_count=1,
        deadline_at=None,
        root_run_id=None,
        causation_run_id=None,
        visited_trigger_ids=[],
        depth=0,
        started_at=datetime.now(UTC),
        run_input=None,
    )
    await workflow_run_repo.update_run(
        db, run=run, update_data={"status": WorkflowRunStatus.WAITING_APPROVAL.value}
    )


async def test_an_organization_with_no_workflows_lists_none(db):
    owner, org = await seed_member(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")

    assert (await WorkflowRegistryService(db).list(ctx)).items == []


class TestNamingAndTags:
    async def test_a_rename_keeps_the_handle_and_tags_are_kept_once_each(self, db, tenant):
        ctx, workflow = tenant
        service = WorkflowRegistryService(db)

        updated = await service.update(
            ctx,
            workflow.id,
            WorkflowUpdate(
                name="Lead intake", description="From the form", tags=["Sales", "sales", "nightly"]
            ),
        )

        assert (updated.name, updated.slug, updated.description) == (
            "Lead intake",
            workflow.slug,
            "From the form",
        )
        assert updated.tags == ["sales", "nightly"]
        listed = await service.list(ctx)
        assert listed.items[0].tags == ["sales", "nightly"]

    async def test_an_update_with_nothing_set_changes_nothing(self, db, tenant):
        ctx, workflow = tenant
        revision = workflow.updated_at

        same = await WorkflowRegistryService(db).update(ctx, workflow.id, WorkflowUpdate())

        assert same.name == "Echo" and workflow.updated_at == revision

    async def test_an_archived_workflow_is_not_renamed(self, db, tenant):
        ctx, workflow = tenant
        await WorkflowRegistryService(db).archive(ctx, workflow.id)

        with pytest.raises(WorkflowArchivedError):
            await WorkflowRegistryService(db).update(ctx, workflow.id, WorkflowUpdate(name="New"))


class TestTheSwitch:
    async def test_a_schedule_is_paused_and_resumed_and_the_list_says_which(self, db, tenant):
        ctx, workflow = tenant
        await _publish(db, ctx, workflow, _graph("trigger.schedule", HOURLY))
        service = WorkflowRegistryService(db)
        assert (await service.get(ctx, workflow.id)).trigger_active is True

        paused = await service.set_active(ctx, workflow.id, False)
        assert paused.trigger_active is False
        assert (await service.list(ctx)).items[0].trigger_active is False

        resumed = await service.set_active(ctx, workflow.id, True)
        assert resumed.trigger_active is True

    async def test_a_workflow_started_by_hand_has_nothing_to_switch(self, db, tenant):
        ctx, workflow = tenant
        await _publish(db, ctx, workflow, _graph("trigger.manual"))
        service = WorkflowRegistryService(db)

        assert (await service.get(ctx, workflow.id)).trigger_active is None
        with pytest.raises(BadRequestError):
            await service.set_active(ctx, workflow.id, True)

    @pytest.mark.security
    async def test_an_editor_who_may_not_run_it_cannot_switch_it(self, db, tenant):
        ctx, workflow = tenant
        await _publish(db, ctx, workflow, _graph("trigger.schedule", HOURLY))

        with (
            patch(
                "app.services.workflow_registry.resolve_access",
                new=AsyncMock(side_effect=[True, False]),
            ),
            pytest.raises(AuthorizationError),
        ):
            await WorkflowRegistryService(db).set_active(ctx, workflow.id, True)

    @pytest.mark.security
    async def test_another_organization_cannot_switch_it(self, db, tenant):
        _ctx, workflow = tenant
        stranger, org = await seed_member(db)
        other = AuthContext(user_id=stranger.id, organization_id=org.id, role="owner")

        with pytest.raises(NotFoundError):
            await WorkflowRegistryService(db).set_active(other, workflow.id, False)


class TestArchiving:
    async def test_archiving_pauses_the_trigger_and_restoring_leaves_it_paused(self, db, tenant):
        ctx, workflow = tenant
        published = await _publish(db, ctx, workflow, _graph("trigger.schedule", HOURLY))
        service = WorkflowRegistryService(db)

        archived = await service.archive(ctx, workflow.id)
        again = await service.archive(ctx, workflow.id)

        assert (archived.status, archived.trigger_active, archived.can_edit) == (
            "archived",
            False,
            False,
        )
        assert again.status == "archived"
        with pytest.raises(WorkflowArchivedError):
            await service.set_active(ctx, workflow.id, True)
        restored = await service.unarchive(ctx, workflow.id)
        assert (restored.status, restored.trigger_active) == ("published", False)
        exposure = await db.get(WorkflowExposure, published.exposure.id)
        assert exposure is not None and exposure.is_active is False

    async def test_a_draft_comes_back_a_draft_and_only_an_archived_one_comes_back(self, db, tenant):
        ctx, workflow = tenant
        service = WorkflowRegistryService(db)
        with pytest.raises(BadRequestError):
            await service.unarchive(ctx, workflow.id)

        await service.archive(ctx, workflow.id)
        assert (await service.unarchive(ctx, workflow.id)).status == "draft"


class TestDeleting:
    async def test_deleting_removes_the_workflow_and_its_shares(self, db, tenant):
        ctx, workflow = tenant
        await _publish(db, ctx, workflow, _graph("trigger.schedule", HOURLY))
        colleague, _org = await seed_member(db)
        await resource_grant_repo.upsert(
            db,
            organization_id=ctx.organization_id,
            subject_user_id=colleague.id,
            resource_type=WORKFLOW.key,
            resource_id=workflow.id,
            level=GrantLevel.EDIT,
        )

        await WorkflowRegistryService(db).delete(ctx, workflow.id)

        assert await db.get(Workflow, workflow.id) is None
        grants = await db.scalars(
            select(ResourceGrant).where(ResourceGrant.resource_id == workflow.id)
        )
        assert grants.all() == []

    async def test_a_workflow_with_a_run_still_going_is_not_deleted(self, db, tenant):
        ctx, workflow = tenant
        await _unfinished_run(db, ctx, workflow)

        with pytest.raises(WorkflowInUseError) as refused:
            await WorkflowRegistryService(db).delete(ctx, workflow.id)

        assert refused.value.details["unfinished_runs"] == 1
        assert await db.get(Workflow, workflow.id) is not None

    async def test_a_workflow_other_runs_descend_from_is_not_deleted(self, db, tenant):
        ctx, workflow = tenant

        with (
            patch(
                "app.services.workflow_registry.workflow_repo.delete",
                new=AsyncMock(side_effect=IntegrityError("DELETE", {}, Exception("fk"))),
            ),
            pytest.raises(WorkflowInUseError),
        ):
            await WorkflowRegistryService(db).delete(ctx, workflow.id)


def _pinned_line() -> tuple[WorkflowGraph, NodeInstance, NodeInstance]:
    """input -> map (with data pinned) -> output."""
    entry, step, out = (
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=definition_id,
            definition_version=1,
            config=config,
            layout=NodePosition(x=0, y=0),
            pinned_output=pinned,
        )
        for definition_id, config, pinned in (
            ("core.input", {}, None),
            (
                "data.map",
                {"mappings": [{"target_field": "a", "source_path": "'b'", "coerce_to": "string"}]},
                {"values": {"a": "pinned"}},
            ),
            ("core.output", {}, None),
        )
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, step, out),
        edges=tuple(
            Edge(
                id=uuid.uuid4(),
                source_node_id=source.id,
                source_port="out",
                target_node_id=target.id,
                target_port="in",
            )
            for source, target in ((entry, step), (step, out))
        ),
        bindings=(
            Binding(
                target_node_id=step.id,
                target_field="source",
                source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload",)),
            ),
            Binding(
                target_node_id=out.id,
                target_field="text",
                source=NodeOutputRef(node_id=step.id, port="out", field_path=("values", "a")),
            ),
        ),
    )
    return graph, entry, step


class TestPinnedDataAndAStepTest:
    async def test_publishing_leaves_the_pins_on_the_draft_and_out_of_the_version(self, db, tenant):
        ctx, workflow = tenant
        graph, _entry, step = _pinned_line()

        await _publish(db, ctx, workflow, graph)

        version = await db.get(WorkflowVersion, workflow.current_version_id)
        assert version is not None
        assert all(node["pinned_output"] is None for node in version.graph["nodes"])
        pinned = WorkflowGraph.model_validate(workflow.draft_graph).node_by_id[step.id]
        assert pinned.pinned_output == {"values": {"a": "pinned"}}

    async def test_a_step_test_runs_the_step_and_what_leads_to_it(self, db, tenant):
        ctx, workflow = tenant
        graph, entry, step = _pinned_line()
        workflow.draft_graph = graph.model_dump(mode="json")
        await db.flush()

        started = await WorkflowExecutionService(db).start(
            ctx,
            workflow.id,
            mode=WorkflowRunMode.TEST,
            step=WorkflowStepTest(node_id=step.id, outputs={entry.id: {"payload": {}}}),
        )

        run = await db.get(WorkflowRun, started.id)
        assert run is not None and run.node_count == 2
        snapshot = WorkflowGraph.model_validate(run.draft_graph_snapshot)
        assert [node.id for node in snapshot.nodes] == [entry.id, step.id]
        assert snapshot.node_by_id[entry.id].pinned_output == {"payload": {}}
        assert snapshot.node_by_id[step.id].pinned_output is None
