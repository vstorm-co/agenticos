"""Preparing a reviewed workflow commits its table and graph together."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import WorkflowRunMode
from app.schemas.virtual_table import ColumnInput, RecordCreate, TableCreate
from app.schemas.workflow import WorkflowPreparationCreate
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.exceptions import InvalidRecordError
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.contracts.io import Binding, LiteralValue, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


def _graph(placeholder: UUID) -> WorkflowGraph:
    start = NodeInstance(
        id=uuid4(),
        definition_id="trigger.schedule",
        definition_version=1,
        config={"input": {"source": "fixture"}},
        layout=NodePosition(x=0, y=0),
    )
    save = NodeInstance(
        id=uuid4(),
        definition_id="table.record.upsert",
        definition_version=1,
        config={
            "table": TableIORef(table_id=placeholder, schema_version=1).model_dump(mode="json")
        },
        layout=NodePosition(x=300, y=0),
    )
    return WorkflowGraph(
        entry_node_id=start.id,
        nodes=(start, save),
        edges=(
            Edge(
                id=uuid4(),
                source_node_id=start.id,
                source_port="out",
                target_node_id=save.id,
                target_port="in",
            ),
        ),
        bindings=(
            Binding(
                target_node_id=save.id,
                target_field="external_id",
                source=LiteralValue(value="contact-1"),
            ),
            Binding(
                target_node_id=save.id,
                target_field="values",
                source=LiteralValue(value={"Contact ID": "contact-1"}),
            ),
        ),
    )


async def test_atomic_preparation_preserves_required_fields_and_binds_the_new_table(
    db: AsyncSession,
):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org, "owner")
    placeholder = uuid4()
    prepared = await WorkflowRegistryService(db).prepare(
        ctx,
        WorkflowPreparationCreate(
            name="Contacts",
            graph=_graph(placeholder),
            table_placeholder_id=placeholder,
            table=TableCreate(
                name="Contacts",
                columns=[ColumnInput(label="Contact ID", type="text", nullable=False)],
            ),
        ),
    )
    assert prepared.table is not None
    assert prepared.table.visibility == "private"
    assert prepared.table.columns[0].nullable is False
    assert prepared.workflow.draft_graph.nodes[1].config["table"]["table_id"] == str(
        prepared.table.id
    )
    with pytest.raises(InvalidRecordError):
        await VirtualTableService(db).create_record(ctx, prepared.table.id, RecordCreate(values={}))
    check = await WorkflowRegistryService(db).check_draft(ctx, prepared.workflow.id)
    assert check.graph_valid and check.requires_live_test
    assert not check.integration_verified and not check.execution_performed
    run = await WorkflowExecutionService(db).start(
        ctx, prepared.workflow.id, mode=WorkflowRunMode.TEST, run_input={"test": True}
    )
    from app.repositories import workflow_run as run_repo

    stored = await run_repo.get_run(db, run.id, organization_id=org.id)
    assert stored.input["input"] == {"source": "fixture", "test": True}
    assert "fired_at" in stored.input


async def test_invalid_graph_rolls_back_both_new_resources(db: AsyncSession):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org, "owner")
    placeholder = uuid4()
    graph = _graph(placeholder)
    bad = graph.nodes[1].model_copy(update={"definition_id": "unknown.action"})
    graph = graph.model_copy(update={"nodes": (graph.nodes[0], bad)})
    with pytest.raises(GraphValidationError):
        await WorkflowRegistryService(db).prepare(
            ctx,
            WorkflowPreparationCreate(
                name="Broken",
                graph=graph,
                table_placeholder_id=placeholder,
                table=TableCreate(
                    name="Broken", columns=[ColumnInput(label="Contact ID", type="text")]
                ),
            ),
        )
    for model in [Workflow, VirtualTable]:
        count = await db.scalar(
            select(func.count()).select_from(model).where(model.organization_id == org.id)
        )
        assert count == 0


@pytest.mark.security
async def test_structural_check_is_read_only_and_tenant_scoped(db: AsyncSession):
    from app.core.exceptions import NotFoundError
    from app.db.models.workflow_run import WorkflowRun

    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org, "owner")
    start = _graph(uuid4()).nodes[0]
    prepared = await WorkflowRegistryService(db).prepare(
        ctx,
        WorkflowPreparationCreate(
            name="Skeleton", graph=WorkflowGraph(entry_node_id=start.id, nodes=(start,))
        ),
    )
    assert prepared.table is None
    checked = await WorkflowRegistryService(db).check_draft(ctx, prepared.workflow.id)
    assert checked.graph_valid and not checked.requires_live_test
    assert (
        await db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_id == prepared.workflow.id)
        )
        == 0
    )
    outsider = await make_user(db)
    foreign = await make_org(db, owner=outsider)
    with pytest.raises(NotFoundError):
        await WorkflowRegistryService(db).check_draft(
            ctx_for(outsider, foreign, "owner"), prepared.workflow.id
        )


@pytest.mark.parametrize("source", ["config", "binding"])
async def test_new_table_does_not_accept_invented_column_ids(db: AsyncSession, source: str):
    from app.core.exceptions import BadRequestError

    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org, "owner")
    placeholder = uuid4()
    graph = _graph(placeholder)
    ref = TableIORef(table_id=placeholder, schema_version=1, column_ids=(uuid4(),))
    if source == "config":
        node = graph.nodes[1].model_copy(update={"config": {"table": ref.model_dump(mode="json")}})
        graph = graph.model_copy(update={"nodes": (graph.nodes[0], node)})
    else:
        binding = graph.bindings[1].model_copy(update={"source": ref})
        graph = graph.model_copy(update={"bindings": (graph.bindings[0], binding)})
    with pytest.raises(BadRequestError, match="all columns"):
        await WorkflowRegistryService(db).prepare(
            ctx,
            WorkflowPreparationCreate(
                name="Invalid columns",
                graph=graph,
                table_placeholder_id=placeholder,
                table=TableCreate(
                    name="Invalid columns", columns=[ColumnInput(label="Contact ID", type="text")]
                ),
            ),
        )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(VirtualTable)
            .where(VirtualTable.organization_id == org.id)
        )
        == 0
    )


async def test_prepare_requires_edit_authority_before_creating_resources(db: AsyncSession):
    from app.core.exceptions import AuthorizationError

    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org, "viewer")
    with pytest.raises(AuthorizationError):
        await WorkflowRegistryService(db).prepare(
            ctx, WorkflowPreparationCreate(name="Denied", graph=_graph(uuid4()))
        )
    assert (
        await db.scalar(
            select(func.count()).select_from(Workflow).where(Workflow.organization_id == org.id)
        )
        == 0
    )
