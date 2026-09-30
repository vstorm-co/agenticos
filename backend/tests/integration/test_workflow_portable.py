"""A workflow exported as a file and imported from one, against a real Postgres (#1953)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowDraftUpdate,
    WorkflowSettings,
    WorkflowUpdate,
)
from app.schemas.workflow_portable import WorkflowExport
from app.services.workflow_portable import WorkflowPortableService
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio


def _node(definition_id: str, config: dict | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _graph(secret_id: str) -> WorkflowGraph:
    trigger = _node("trigger.manual")
    call = _node(
        "http.request",
        {"url": "https://api.example.com", "auth": {"kind": "bearer", "secret_id": secret_id}},
    )
    edge = Edge(
        id=uuid.uuid4(),
        source_node_id=trigger.id,
        source_port="out",
        target_node_id=call.id,
        target_port="in",
    )
    return WorkflowGraph(entry_node_id=trigger.id, nodes=(trigger, call), edges=(edge,))


async def _ctx(db: AsyncSession, role: str = "owner") -> AuthContext:
    user, org = await seed_member(db, role=role)
    return AuthContext(user_id=user.id, organization_id=org.id, role=role)


async def _workflow(db: AsyncSession, ctx: AuthContext, graph: WorkflowGraph) -> uuid.UUID:
    registry = WorkflowRegistryService(db)
    created = await registry.create(ctx, WorkflowCreate(name="Lead intake", description="Leads"))
    await registry.update(ctx, created.id, WorkflowUpdate(tags=["sales"]))
    await registry.update_settings(
        ctx, created.id, WorkflowSettings(timezone="Europe/Warsaw", run_retention_days=30)
    )
    detail = await registry.get(ctx, created.id)
    await registry.update_draft(
        ctx,
        created.id,
        WorkflowDraftUpdate(
            graph=graph.model_dump(mode="json"), expected_revision=detail.draft_revision
        ),
    )
    return created.id


class TestExporting:
    @pytest.mark.security
    async def test_a_file_carries_no_secret_id_and_lists_what_it_left_out(self, db):
        ctx = await _ctx(db)
        secret = str(uuid.uuid4())
        graph = _graph(secret)
        workflow_id = await _workflow(db, ctx, graph)

        exported = await WorkflowPortableService(db).export(ctx, workflow_id)

        assert secret not in exported.model_dump_json()
        assert (exported.name, exported.description, exported.tags) == (
            "Lead intake",
            "Leads",
            ["sales"],
        )
        assert exported.settings.timezone == "Europe/Warsaw"
        assert exported.settings.error_workflow_id is None
        (left_out,) = exported.unresolved
        assert (left_out.node_id, left_out.field, left_out.kind) == (
            graph.nodes[1].id,
            "auth.secret_id",
            "secret",
        )

    async def test_a_workflow_with_no_steps_exports_no_graph(self, db):
        ctx = await _ctx(db)
        created = await WorkflowRegistryService(db).create(ctx, WorkflowCreate(name="Empty"))
        exported = await WorkflowPortableService(db).export(ctx, created.id)
        assert exported.graph is None and exported.unresolved == []

    @pytest.mark.security
    async def test_another_organization_cannot_export_it(self, db):
        ctx = await _ctx(db)
        workflow_id = await _workflow(db, ctx, _graph(str(uuid.uuid4())))
        with pytest.raises(NotFoundError):
            await WorkflowPortableService(db).export(await _ctx(db), workflow_id)


class TestImporting:
    async def test_an_export_imports_as_a_draft_naming_every_pin_to_choose(self, db):
        ctx = await _ctx(db)
        exported = await WorkflowPortableService(db).export(
            ctx, await _workflow(db, ctx, _graph(str(uuid.uuid4())))
        )
        elsewhere = await _ctx(db)

        imported = await WorkflowPortableService(db).import_(elsewhere, exported)

        assert imported.workflow.status == "draft"
        assert imported.workflow.name.startswith("Lead intake")
        assert imported.workflow.tags == ["sales"]
        assert [item.field for item in imported.unresolved] == ["auth.secret_id"]
        detail = await WorkflowRegistryService(db).get(elsewhere, imported.workflow.id)
        assert detail.settings.timezone == "Europe/Warsaw"
        assert detail.draft_graph is not None
        assert detail.draft_graph.nodes[1].config["auth"] == {"kind": "bearer"}

    @pytest.mark.security
    async def test_ids_a_hand_made_file_names_are_taken_out_too(self, db):
        ctx = await _ctx(db)
        secret = str(uuid.uuid4())
        file = WorkflowExport(name="Hand made", graph=_graph(secret).model_dump(mode="json"))

        imported = await WorkflowPortableService(db).import_(ctx, file)

        detail = await WorkflowRegistryService(db).get(ctx, imported.workflow.id)
        assert secret not in detail.model_dump_json()
        assert [item.kind for item in imported.unresolved] == ["secret"]

    async def test_a_file_with_no_graph_imports_an_empty_draft(self, db):
        ctx = await _ctx(db)
        imported = await WorkflowPortableService(db).import_(ctx, WorkflowExport(name="Blank"))
        detail = await WorkflowRegistryService(db).get(ctx, imported.workflow.id)
        assert detail.draft_graph is None and imported.unresolved == []

    @pytest.mark.parametrize(
        "graph",
        [
            {"nodes": "not a list"},
            _graph(str(uuid.uuid4()))
            .model_copy(update={"nodes": (_node("future.step"),)})
            .model_dump(mode="json"),
        ],
        ids=["malformed", "unknown-step"],
    )
    async def test_a_graph_it_cannot_take_is_refused_and_nothing_is_made(self, db, graph):
        ctx = await _ctx(db)
        with pytest.raises(GraphValidationError):
            await WorkflowPortableService(db).import_(ctx, WorkflowExport(name="Bad", graph=graph))
        listed = await WorkflowRegistryService(db).list(ctx)
        assert listed.total == 0

    @pytest.mark.security
    async def test_a_member_who_may_not_create_workflows_cannot_import(self, db):
        ctx = await _ctx(db, role="viewer")
        with pytest.raises(AuthorizationError):
            await WorkflowPortableService(db).import_(ctx, WorkflowExport(name="Nope"))
