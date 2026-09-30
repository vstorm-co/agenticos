"""The Virtual Tables workflow nodes, run end to end against Postgres (#1784).

Each graph is published through the real validator and driven through the real
dispatcher, writing through the same `VirtualTableService` the console and the
agent tools use - so what is proved is what a workflow does to a table: the
writes land, a retried step replays rather than repeats, conflicts and unknown
columns fail typed, and a table a live workflow uses cannot be archived out from
under it.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTableRecord, VirtualTableRecordHistory
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import NodeAttempt, NodeRun, WorkflowRunStatus
from app.schemas.virtual_table import (
    ColumnInput,
    RecordCreate,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.services.virtual_tables.exceptions import SchemaDependencyError
from app.services.virtual_tables.facade import VirtualTableService
from app.services.workflow_execution import context
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.table_record_create import TableRecordCreateConfig, TableRecordCreateInput
from app.workflows.nodes.table_record_create._handler import handle as create_handle
from app.workflows.nodes.table_record_delete import TableRecordDeleteConfig, TableRecordDeleteInput
from app.workflows.nodes.table_record_delete._handler import handle as delete_handle
from app.workflows.nodes.table_record_update import TableRecordUpdateConfig, TableRecordUpdateInput
from app.workflows.nodes.table_record_update._handler import handle as update_handle
from app.workflows.nodes.table_record_upsert import TableRecordUpsertConfig, TableRecordUpsertInput
from app.workflows.nodes.table_record_upsert._handler import handle as upsert_handle
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _chain(*nodes: NodeInstance) -> tuple[Edge, ...]:
    return tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=a.id,
            source_port="out",
            target_node_id=b.id,
            target_port="in",
        )
        for a, b in pairwise(nodes)
    )


def _ref(node: NodeInstance, *path: str) -> NodeOutputRef:
    return NodeOutputRef(node_id=node.id, port="out", field_path=path)


def _literal(target: NodeInstance, field: str, value: Any) -> Binding:
    return Binding(target_node_id=target.id, target_field=field, source=LiteralValue(value=value))


def _bind(target: NodeInstance, field: str, source: NodeOutputRef) -> Binding:
    return Binding(target_node_id=target.id, target_field=field, source=source)


async def _world(engine: AsyncEngine) -> tuple[tuple[User, Organization], TableRead]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        member = await seed_member(db)
        table = await VirtualTableService(db).create_table(
            AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner"),
            TableCreate(
                name="Leads",
                columns=[
                    ColumnInput(label="Email", type="text"),
                    ColumnInput(label="Score", type="integer"),
                ],
            ),
        )
        await db.commit()
    return member, table


def _pin(table: TableRead) -> dict[str, Any]:
    return {
        "table": TableIORef(table_id=table.id, schema_version=table.schema_version).model_dump(
            mode="json"
        )
    }


async def _run(
    engine: AsyncEngine,
    member: tuple[User, Organization],
    graph: WorkflowGraph,
    run_input: dict[str, Any] | None = None,
) -> SeededRun:
    seeded = await seed_run(engine, graph, run_input=run_input, member=member)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    return seeded


async def _records(engine: AsyncEngine) -> list[VirtualTableRecord]:
    async with async_sessionmaker(engine)() as db:
        return list((await db.execute(select(VirtualTableRecord))).scalars())


async def test_a_new_record_is_written_by_label_and_handed_on_by_id_and_label(engine: AsyncEngine):
    member, table = await _world(engine)
    entry, create, output = (
        _node("core.input"),
        _node("table.record.create", _pin(table)),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, create, output),
        edges=_chain(entry, create, output),
        bindings=(
            _bind(create, "values", _ref(entry, "payload", "lead")),
            _bind(create, "external_id", _ref(entry, "payload", "lead", "Email")),
            _bind(output, "structured", _ref(create)),
        ),
    )
    seeded = await _run(engine, member, graph, {"lead": {"Email": "ada@example.com", "Score": 87}})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    written = run.output["structured"]
    assert written["fields"] == {"Email": "ada@example.com", "Score": 87}
    assert written["external_id"] == "ada@example.com" and written["created"] is True
    (row,) = await _records(engine)
    assert row.values == written["values"]


async def test_a_retried_step_replays_its_write_rather_than_adding_a_second(engine: AsyncEngine):
    member, table = await _world(engine)
    ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")
    dispatch = context.DispatchContext(
        organization_id=member[1].id,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=ctx,
        resumed_agent_run_id=None,
        idempotency_key=f"{member[1].id}:run:node:[]",
    )
    config = TableRecordCreateConfig.model_validate(_pin(table))

    for attempt in (1, 2):
        with context.dispatching_as(replace(dispatch, attempt_no=attempt)):
            await create_handle(config, TableRecordCreateInput(values={"Email": "a@x"}))

    assert len(await _records(engine)) == 1


def _dispatch(member: tuple[User, Organization]) -> context.DispatchContext:
    ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")
    return context.DispatchContext(
        organization_id=member[1].id,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=ctx,
        resumed_agent_run_id=None,
        idempotency_key=f"{member[1].id}:run:node:[]",
    )


async def _history(engine: AsyncEngine, operation: str) -> int:
    async with async_sessionmaker(engine)() as db:
        rows = await db.execute(
            select(VirtualTableRecordHistory).where(
                VirtualTableRecordHistory.operation == operation
            )
        )
        return len(rows.scalars().all())


async def test_a_retried_update_after_its_write_committed_replays_it(engine: AsyncEngine):
    """The first attempt moved the record to revision 2 and its worker died before
    the result was saved. Its retry must replay that write, not send revision 2 as
    a new request under the same key and be refused as a different one."""
    member, table = await _world(engine)
    dispatch = _dispatch(member)
    with context.dispatching_as(dispatch):
        await create_handle(
            TableRecordCreateConfig.model_validate(_pin(table)),
            TableRecordCreateInput(values={"Email": "a@x"}),
        )
    (record,) = await _records(engine)
    config = TableRecordUpdateConfig.model_validate(_pin(table))
    change = TableRecordUpdateInput(record_id=record.id, values={"Score": 91})
    step = replace(dispatch, node_instance_id=uuid.uuid4(), idempotency_key="update-step")

    results = []
    for attempt in (1, 2):
        with context.dispatching_as(replace(step, attempt_no=attempt)):
            results.append(await update_handle(config, change))

    assert all(result.status == "completed" for result in results)
    (row,) = await _records(engine)
    assert row.revision == 2
    assert await _history(engine, "update") == 1


async def test_a_retried_upsert_that_updated_an_existing_record_replays_it(engine: AsyncEngine):
    member, table = await _world(engine)
    dispatch = _dispatch(member)
    config = TableRecordUpsertConfig.model_validate(_pin(table))
    with context.dispatching_as(replace(dispatch, idempotency_key="first-step")):
        await upsert_handle(
            config, TableRecordUpsertInput(external_id="ada", values={"Email": "a@x"})
        )
    step = replace(dispatch, idempotency_key="second-step")

    results = []
    for attempt in (1, 2):
        with context.dispatching_as(replace(step, attempt_no=attempt)):
            results.append(
                await upsert_handle(
                    config, TableRecordUpsertInput(external_id="ada", values={"Score": 7})
                )
            )

    assert all(result.status == "completed" for result in results)
    (row,) = await _records(engine)
    assert row.revision == 2
    assert await _history(engine, "update") == 1


async def test_a_retried_delete_after_its_delete_committed_succeeds_again(engine: AsyncEngine):
    """Reading the revision first would find no record on the retry and fail the step."""
    member, table = await _world(engine)
    dispatch = _dispatch(member)
    with context.dispatching_as(dispatch):
        await create_handle(
            TableRecordCreateConfig.model_validate(_pin(table)),
            TableRecordCreateInput(values={"Email": "a@x"}),
        )
    (record,) = await _records(engine)
    config = TableRecordDeleteConfig.model_validate(_pin(table))
    step = replace(dispatch, idempotency_key="delete-step")

    results = []
    for attempt in (1, 2):
        with context.dispatching_as(replace(step, attempt_no=attempt)):
            results.append(await delete_handle(config, TableRecordDeleteInput(record_id=record.id)))

    assert all(result.status == "completed" for result in results)
    assert await _records(engine) == []
    assert await _history(engine, "delete") == 1


async def test_an_upsert_creates_then_updates_the_same_record(engine: AsyncEngine):
    member, table = await _world(engine)

    def graph_for() -> WorkflowGraph:
        entry, upsert, output = (
            _node("core.input"),
            _node("table.record.upsert", _pin(table)),
            _node("core.output"),
        )
        return WorkflowGraph(
            entry_node_id=entry.id,
            nodes=(entry, upsert, output),
            edges=_chain(entry, upsert, output),
            bindings=(
                _bind(upsert, "external_id", _ref(entry, "payload", "email")),
                _bind(upsert, "values", _ref(entry, "payload", "values")),
                _bind(output, "structured", _ref(upsert)),
            ),
        )

    first = await drive(
        await _run(engine, member, graph_for(), {"email": "a@x", "values": {"Score": 1}})
    )
    second = await drive(
        await _run(engine, member, graph_for(), {"email": "a@x", "values": {"Score": 2}})
    )

    assert first.output is not None and first.output["structured"]["created"] is True
    assert second.output is not None and second.output["structured"]["created"] is False
    (row,) = await _records(engine)
    assert row.revision == 2


async def test_a_record_is_found_updated_and_listed(engine: AsyncEngine):
    member, table = await _world(engine)
    async with async_sessionmaker(engine)() as db:
        await VirtualTableService(db).create_record(
            AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner"),
            table.id,
            RecordCreate(external_id="a@x", values={str(table.columns[1].id): 10}),
        )
        await db.commit()
    entry = _node("core.input")
    find = _node("table.record.get", _pin(table))
    update = _node("table.record.update", _pin(table))
    query = _node("table.record.query", {**_pin(table), "limit": 5})
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, find, update, query, output),
        edges=_chain(entry, find, update, query, output),
        bindings=(
            _literal(find, "external_id", "a@x"),
            _bind(update, "record_id", _ref(find, "record", "record_id")),
            _literal(update, "values", {"Score": 11}),
            _bind(output, "structured", _ref(query)),
        ),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    (listed,) = run.output["structured"]["records"]
    assert listed["fields"]["Score"] == 11 and listed["revision"] == 2
    assert run.output["structured"]["has_more"] is False


async def test_a_record_that_is_not_there_is_an_answer_not_a_failure(engine: AsyncEngine):
    member, table = await _world(engine)
    entry, find, output = (
        _node("core.input"),
        _node("table.record.get", _pin(table)),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, find, output),
        edges=_chain(entry, find, output),
        bindings=(
            _literal(find, "external_id", "nobody@x"),
            _bind(output, "structured", _ref(find)),
        ),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.output is not None and run.output["structured"] == {"found": False, "record": None}


async def test_a_stale_revision_fails_without_a_blind_retry(engine: AsyncEngine):
    """The same stale revision would conflict on every retry, so it is the
    author's to route - to a fresh read - never the retry policy's."""
    member, table = await _world(engine)
    async with async_sessionmaker(engine)() as db:
        written = await VirtualTableService(db).create_record(
            AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner"),
            table.id,
            RecordCreate(values={}),
        )
        await db.commit()
    entry, update = _node("core.input"), _node("table.record.update", _pin(table))
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, update),
        edges=_chain(entry, update),
        bindings=(
            _literal(update, "record_id", str(written.record.id)),
            _literal(update, "expected_revision", 9),
            _literal(update, "values", {"Score": 1}),
        ),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "REVISION_CONFLICT"
    assert run.error["retryable"] is False


async def test_a_value_for_a_column_the_table_does_not_have_fails_typed(engine: AsyncEngine):
    member, table = await _world(engine)
    entry, create = _node("core.input"), _node("table.record.create", _pin(table))
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, create),
        edges=_chain(entry, create),
        bindings=(_literal(create, "values", {"Colour": "red"}),),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.error is not None and run.error["code"] == "UNKNOWN_COLUMN"
    assert await _records(engine) == []


async def test_a_record_is_deleted_at_its_current_revision(engine: AsyncEngine):
    member, table = await _world(engine)
    async with async_sessionmaker(engine)() as db:
        written = await VirtualTableService(db).create_record(
            AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner"),
            table.id,
            RecordCreate(values={}),
        )
        await db.commit()
    entry, remove = _node("core.input"), _node("table.record.delete", _pin(table))
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, remove),
        edges=_chain(entry, remove),
        bindings=(_literal(remove, "record_id", str(written.record.id)),),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert await _records(engine) == []


async def test_a_table_a_step_creates_is_written_to_by_the_next(engine: AsyncEngine):
    member, _table = await _world(engine)
    entry = _node("core.input")
    make = _node(
        "table.create",
        {"name": "Scores", "columns": [{"label": "Email", "type": "text"}]},
    )
    create = _node("table.record.create")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, make, create),
        edges=_chain(entry, make, create),
        bindings=(
            _bind(create, "table", _ref(make, "table")),
            _literal(create, "values", {"Email": "a@x"}),
        ),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    (row,) = await _records(engine)
    assert list(row.values.values()) == ["a@x"]


@pytest.mark.security
async def test_a_table_the_author_cannot_write_cannot_be_published(engine: AsyncEngine):
    member, table = await _world(engine)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        viewer = User(
            id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.com", hashed_password="x", is_active=True
        )
        db.add(viewer)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=member[1].id, user_id=viewer.id, role="viewer"
            )
        )
        await db.commit()
    entry, create = _node("core.input"), _node("table.record.create", _pin(table))
    make = _node("table.create", {"name": "X", "columns": [{"label": "A", "type": "text"}]})
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, create, make), edges=_chain(entry, create, make)
    )
    ctx = AuthContext(user_id=viewer.id, organization_id=member[1].id, role="viewer")

    with pytest.raises(GraphValidationError) as refused:
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, ctx, graph)

    fields = {problem["field"] for problem in refused.value.details["fields"]}
    assert f"nodes.{create.id}.config.table" in fields
    assert f"nodes.{make.id}.config.name" in fields


async def _published_workflow(
    engine: AsyncEngine, member: tuple[User, Organization], graph: WorkflowGraph
) -> Workflow:
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=member[1].id,
            owner_user_id=member[0].id,
            slug=f"wf-{uuid.uuid4().hex[:6]}",
            name="Scorer",
            status=WorkflowStatus.PUBLISHED.value,
            visibility=Visibility.PRIVATE.value,
            draft_graph=graph.model_dump(mode="json"),
        )
        db.add(workflow)
        await db.flush()
        version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            organization_id=member[1].id,
            version=1,
            graph=graph.model_dump(mode="json"),
        )
        db.add(version)
        await db.flush()
        workflow.current_version_id = version.id
        await db.commit()
    return workflow


async def test_a_table_a_live_workflow_writes_to_cannot_be_archived(engine: AsyncEngine):
    member, table = await _world(engine)
    entry, create = _node("core.input"), _node("table.record.create", _pin(table))
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, create), edges=_chain(entry, create)
    )
    workflow = await _published_workflow(engine, member, graph)
    ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")

    with pytest.raises(SchemaDependencyError) as blocked:
        async with async_sessionmaker(engine)() as db:
            await VirtualTableService(db).archive_table(ctx, table.id)
    assert blocked.value.details["dependents"] == [
        {"kind": "workflow", "id": workflow.id, "name": workflow.name}
    ]

    async with async_sessionmaker(engine)() as db:
        await db.execute(
            Workflow.__table__.update()
            .where(Workflow.id == workflow.id)
            .values(status=WorkflowStatus.ARCHIVED.value)
        )
        await db.commit()
    async with async_sessionmaker(engine)() as db:
        archived = await VirtualTableService(db).archive_table(ctx, table.id)
        await db.commit()
    assert archived.archived_at is not None


async def test_a_column_is_blocked_only_where_a_workflow_pins_it(engine: AsyncEngine):
    member, table = await _world(engine)
    email, score = table.columns
    pinned = TableIORef(table_id=table.id, column_ids=(score.id,), schema_version=1)
    entry, create = (
        _node("core.input"),
        _node("table.record.create", {"table": pinned.model_dump(mode="json")}),
    )
    await _published_workflow(
        engine,
        member,
        WorkflowGraph(entry_node_id=entry.id, nodes=(entry, create), edges=_chain(entry, create)),
    )
    ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")

    async with async_sessionmaker(engine)() as db:
        service = VirtualTableService(db)
        # Archiving the unpinned column goes through...
        await service.update_schema(
            ctx,
            table.id,
            SchemaUpdate(
                expected_version=1,
                columns=[ColumnInput(id=score.id, label="Score", type="integer")],
            ),
        )
        await db.commit()
    with pytest.raises(SchemaDependencyError):
        async with async_sessionmaker(engine)() as db:
            # ...and archiving the pinned one does not.
            await VirtualTableService(db).update_schema(
                ctx, table.id, SchemaUpdate(expected_version=2, columns=[])
            )
    assert email.label == "Email"


async def test_tables_are_listed_and_one_is_described_for_the_steps_after(engine: AsyncEngine):
    member, table = await _world(engine)
    entry = _node("core.input")
    listed = _node("table.list", {"limit": 10})
    described = _node("table.describe", _pin(table))
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, listed, described, output),
        edges=_chain(entry, listed, described, output),
        bindings=(
            _literal(listed, "search", "lea"),
            _bind(output, "structured", _ref(described)),
        ),
    )

    run = await drive(await _run(engine, member, graph))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    async with async_sessionmaker(engine)() as db:
        attempt = (
            await db.execute(
                select(NodeAttempt.result)
                .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
                .where(NodeRun.node_instance_id == listed.id)
            )
        ).scalar_one()
    found = attempt["output"]
    assert found["total"] == 1 and found["tables"][0]["name"] == "Leads"
    assert run.output is not None
    shape = run.output["structured"]
    assert (shape["name"], shape["schema_version"]) == ("Leads", table.schema_version)
    assert [(column["label"], column["type"]) for column in shape["columns"]] == [
        ("Email", "text"),
        ("Score", "integer"),
    ]


async def _branch_taken(engine: AsyncEngine, member, graph: WorkflowGraph) -> dict[str, str]:
    run = await drive(await _run(engine, member, graph))
    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    async with async_sessionmaker(engine)() as db:
        rows = (await db.execute(select(NodeRun))).scalars().all()
    return {str(row.node_instance_id): row.status for row in rows}


@pytest.mark.parametrize(("name", "port"), [("LEADS", "yes"), ("Lead", "no")])
async def test_a_table_is_found_by_its_whole_name_whatever_the_case(
    engine: AsyncEngine, name: str, port: str
):
    member, _table = await _world(engine)
    entry = _node("core.input")
    exists = _node("table.exists")
    yes, no = _node("core.output"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, exists, yes, no),
        edges=(
            *_chain(entry, exists),
            Edge(
                id=uuid.uuid4(),
                source_node_id=exists.id,
                source_port="yes",
                target_node_id=yes.id,
                target_port="in",
            ),
            Edge(
                id=uuid.uuid4(),
                source_node_id=exists.id,
                source_port="no",
                target_node_id=no.id,
                target_port="in",
            ),
        ),
        bindings=(_literal(exists, "name", name),),
    )

    statuses = await _branch_taken(engine, member, graph)

    taken, skipped = (yes, no) if port == "yes" else (no, yes)
    assert statuses[str(taken.id)] == "succeeded"
    assert statuses.get(str(skipped.id), "skipped") == "skipped"


@pytest.mark.parametrize(("score", "port"), [(10, "yes"), (99, "no")])
async def test_a_record_that_matches_every_filter_takes_the_yes_branch(
    engine: AsyncEngine, score: int, port: str
):
    member, table = await _world(engine)
    async with async_sessionmaker(engine)() as db:
        await VirtualTableService(db).create_record(
            AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner"),
            table.id,
            RecordCreate(values={str(table.columns[1].id): 10}),
        )
        await db.commit()
    entry = _node("core.input")
    exists = _node(
        "table.record.exists",
        {
            **_pin(table),
            "filters": [{"column_id": str(table.columns[1].id), "op": "eq", "value": score}],
        },
    )
    yes, no = _node("core.output"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, exists, yes, no),
        edges=(
            *_chain(entry, exists),
            Edge(
                id=uuid.uuid4(),
                source_node_id=exists.id,
                source_port="yes",
                target_node_id=yes.id,
                target_port="in",
            ),
            Edge(
                id=uuid.uuid4(),
                source_node_id=exists.id,
                source_port="no",
                target_node_id=no.id,
                target_port="in",
            ),
        ),
        bindings=(
            _bind(yes, "structured", NodeOutputRef(node_id=exists.id, port="yes", field_path=())),
        ),
    )

    statuses = await _branch_taken(engine, member, graph)

    taken = yes if port == "yes" else no
    assert statuses[str(taken.id)] == "succeeded"
