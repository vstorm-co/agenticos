"""A table's triggers against a real Postgres (#1785).

A trigger is a workflow's "New table record" node, switched on by publishing.
What only the database can show: that every way a record is added leaves the
event a trigger reads, that an event admits at most once per trigger however
often it is consumed, that the activation boundary holds across publishes and
pauses, and that a chain of runs writing into each other's tables stops at the
trigger it already passed.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import pairwise
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.virtual_tables import VirtualTables
from app.agents.capabilities.virtual_tables._access import TableOperation
from app.agents.deps import AgentDeps
from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.virtual_table import (
    VirtualTableOutbox,
    VirtualTableRecord,
    VirtualTableRecordHistory,
)
from app.db.models.virtual_table_trigger import (
    TableTriggerAdmission,
    VirtualTableTrigger,
    VirtualTableTriggerRevision,
)
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStatus, WorkflowRunTrigger
from app.main import app
from app.schemas.virtual_table import (
    ColumnInput,
    RecordCreate,
    RecordFilter,
    RecordUpsert,
    SchemaUpdate,
    TableCreate,
    TableRead,
)
from app.schemas.virtual_table_trigger import TableTriggerUpdate
from app.schemas.workflow import WorkflowPublish
from app.services.virtual_tables.exceptions import SchemaDependencyError
from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.triggers import (
    MAX_DEPTH,
    MAX_RUNS_PER_ROOT,
    TableTriggerConsumer,
    TableTriggerService,
)
from app.services.workflow_execution.exceptions import WorkflowRunInputTooLargeError
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.contracts.io import Binding, LiteralValue, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, drive, seed_member

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()) as submitted:
        yield submitted


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _ref(table: TableRead) -> dict[str, Any]:
    return TableIORef(table_id=table.id, schema_version=table.schema_version).model_dump(
        mode="json"
    )


def _on_new_record(
    table: TableRead, *, filters: list[RecordFilter] | None = None, into: TableRead | None = None
) -> WorkflowGraph:
    """A workflow a new record in `table` starts - that adds a record to `into`, if given."""
    entry = _node(
        "trigger.table_record",
        {
            "table": _ref(table),
            "filters": [item.model_dump(mode="json") for item in filters or []],
        },
    )
    if into is None:
        return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))
    create = _node("table.record.create", {"table": _ref(into)})
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, create),
        edges=tuple(
            Edge(
                id=uuid.uuid4(),
                source_node_id=a.id,
                source_port="out",
                target_node_id=b.id,
                target_port="in",
            )
            for a, b in pairwise((entry, create))
        ),
        bindings=(
            Binding(
                target_node_id=create.id,
                target_field="values",
                source=LiteralValue(value={"Email": "loop@example.com", "Score": 1}),
            ),
        ),
    )


def _by_hand() -> WorkflowGraph:
    entry = _node("core.input")
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


@dataclass
class _World:
    factory: async_sessionmaker[AsyncSession]
    owner: User
    org: Organization
    leads: TableRead

    @property
    def ctx(self) -> AuthContext:
        return AuthContext(user_id=self.owner.id, organization_id=self.org.id, role="owner")

    def column(self, label: str, table: TableRead | None = None) -> uuid.UUID:
        return next(item.id for item in (table or self.leads).columns if item.label == label)

    async def table(self, name: str) -> TableRead:
        return await _table(self.factory, self.ctx, name)

    async def workflow(self) -> Workflow:
        async with self.factory() as db:
            workflow = Workflow(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                owner_user_id=self.owner.id,
                slug=f"wf-{uuid.uuid4().hex[:8]}",
                name="Follow up",
                status=WorkflowStatus.DRAFT.value,
                visibility=Visibility.ORG.value,
            )
            db.add(workflow)
            await db.commit()
        return workflow

    async def publish(
        self, workflow: Workflow, graph: WorkflowGraph, *, ctx: AuthContext | None = None
    ) -> WorkflowVersion:
        """Make `graph` the draft and publish it, as a member does in the editor."""
        async with self.factory() as db:
            current = await db.get(Workflow, workflow.id)
            assert current is not None
            current.draft_graph = graph.model_dump(mode="json")
            await db.flush()
            published = await WorkflowRegistryService(db).publish(
                ctx or self.ctx,
                workflow.id,
                WorkflowPublish(expected_revision=current.draft_revision),
            )
            await db.commit()
            version = await db.get(WorkflowVersion, published.id)
        assert version is not None
        return version

    async def trigger(
        self,
        workflow: Workflow | None = None,
        *,
        table: TableRead | None = None,
        ctx: AuthContext | None = None,
        filters: list[RecordFilter] | None = None,
        into: TableRead | None = None,
    ) -> uuid.UUID:
        """Publish `workflow` - a new one when not given - to start from a new record
        in `table`, and return the trigger that publish switched on."""
        workflow = workflow or await self.workflow()
        graph = _on_new_record(table or self.leads, filters=filters, into=into)
        await self.publish(workflow, graph, ctx=ctx)
        async with self.factory() as db:
            return (
                await db.execute(
                    select(VirtualTableTrigger.id).where(
                        VirtualTableTrigger.workflow_id == workflow.id
                    )
                )
            ).scalar_one()

    async def trigger_of(self, workflow: Workflow) -> VirtualTableTrigger:
        async with self.factory() as db:
            return (
                await db.execute(
                    select(VirtualTableTrigger).where(
                        VirtualTableTrigger.workflow_id == workflow.id
                    )
                )
            ).scalar_one()

    async def pause(self, trigger_id: uuid.UUID, *, active: bool = False) -> None:
        async with self.factory() as db:
            await TableTriggerService(db).set_active(
                self.ctx, self.leads.id, trigger_id, TableTriggerUpdate(is_active=active)
            )
            await db.commit()

    async def add(self, values: dict[str, Any], table: TableRead | None = None) -> None:
        target = table or self.leads
        async with self.factory() as db:
            await VirtualTableService(db).create_record(
                self.ctx,
                target.id,
                RecordCreate(
                    values={
                        str(self.column(label, target)): value for label, value in values.items()
                    }
                ),
            )
            await db.commit()

    async def consume(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        async with self.factory() as db:
            pairs = await TableTriggerConsumer(db).consume()
            await db.commit()
        return pairs

    async def admissions(self, trigger_id: uuid.UUID) -> list[TableTriggerAdmission]:
        async with self.factory() as db:
            rows = await db.execute(
                select(TableTriggerAdmission)
                .where(TableTriggerAdmission.trigger_id == trigger_id)
                .order_by(TableTriggerAdmission.created_at)
            )
            return list(rows.scalars())

    async def run(self, run_id: uuid.UUID) -> WorkflowRun:
        async with self.factory() as db:
            return (
                await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
            ).scalar_one()

    async def drive(self, run_id: uuid.UUID, graph: WorkflowGraph) -> WorkflowRun:
        seeded = SeededRun(
            run=await self.run(run_id),
            graph=graph,
            principal=self.owner,
            org=self.org,
            factory=self.factory,
        )
        return await drive(seeded)


async def _table(
    factory: async_sessionmaker[AsyncSession], ctx: AuthContext, name: str
) -> TableRead:
    async with factory() as db:
        made = await VirtualTableService(db).create_table(
            ctx,
            TableCreate(
                name=name,
                columns=[
                    ColumnInput(label="Email", type="text"),
                    ColumnInput(label="Score", type="integer"),
                    ColumnInput(label="VIP", type="boolean"),
                ],
            ),
        )
        await db.commit()
    return made


@pytest.fixture
async def world(engine: AsyncEngine) -> _World:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner, org = await seed_member(db)
        await db.commit()
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    return _World(factory=factory, owner=owner, org=org, leads=await _table(factory, ctx, "Leads"))


async def _record_ids(world: _World) -> list[uuid.UUID]:
    async with world.factory() as db:
        return list((await db.execute(select(VirtualTableRecord.id))).scalars())


def _statuses(rows: list[TableTriggerAdmission]) -> list[tuple[str, str | None]]:
    return [(row.status, row.reason) for row in rows]


async def test_an_added_record_starts_the_live_version_with_the_record(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)

    await world.add({"Email": "ada@example.com", "Score": 90})
    pairs = await world.consume()

    (admission,) = await world.admissions(trigger_id)
    assert (admission.status, admission.reason) == ("queued", None)
    assert pairs == [(admission.workflow_run_id, pairs[0][1])]
    run = await world.run(pairs[0][0])
    assert run.triggered_by == WorkflowRunTrigger.TABLE_CREATED.value
    (record_id,) = await _record_ids(world)
    email, score = str(world.column("Email")), str(world.column("Score"))
    assert run.input == {
        "table_id": str(world.leads.id),
        "record_id": str(record_id),
        "values": {email: "ada@example.com", score: 90},
        "fields": {"Email": "ada@example.com", "Score": 90},
        "author_id": str(world.owner.id),
    }
    assert run.execution_principal_user_id == world.owner.id
    assert run.visited_trigger_ids == [str(trigger_id)]
    assert (run.depth, run.root_run_id, run.causation_run_id) == (0, run.id, None)
    # The trigger node hands the graph what the run was started with.
    ended = await world.drive(run.id, _on_new_record(world.leads))
    assert ended.status == WorkflowRunStatus.SUCCEEDED.value


async def test_an_event_admits_once_however_often_it_is_consumed(world: _World):
    trigger_id = await world.trigger()
    await world.add({"Email": "a@x"})

    first = await world.consume()
    async with world.factory() as db:
        # A consumer that died after deciding but before stamping the event.
        await db.execute(update(VirtualTableOutbox).values(dispatched_at=None))
        await db.commit()
    second = await world.consume()

    assert len(first) == 1 and second == []
    assert len(await world.admissions(trigger_id)) == 1


async def test_every_way_a_record_is_added_starts_it_and_an_upsert_update_does_not(
    world: _World, engine: AsyncEngine
):
    trigger_id = await world.trigger()
    email = str(world.column("Email"))

    # The console and the HTTP API: one service method behind both.
    await world.add({"Email": "console@x"})
    async with world.factory() as db:
        service = VirtualTableService(db)
        await service.upsert_record(
            world.ctx, world.leads.id, "ext-1", RecordUpsert(values={email: "upsert@x"})
        )
        await db.commit()
    async with world.factory() as db:
        service = VirtualTableService(db)
        await service.upsert_record(
            world.ctx,
            world.leads.id,
            "ext-1",
            RecordUpsert(values={email: "changed@x"}, expected_revision=1),
        )
        await db.commit()
    # An agent's table tool.
    capability: VirtualTables[AgentDeps] = VirtualTables(
        grants={world.leads.id: frozenset({TableOperation.READ, TableOperation.CREATE})},
        allow_create=False,
    )
    tool = capability.get_toolset().tools["create_record"].function
    run_ctx = RunContext(
        deps=AgentDeps(
            organization_id=world.org.id, user_id=str(world.owner.id), run_id=uuid.uuid4()
        ),
        model=TestModel(),
        usage=RunUsage(),
        retry=0,
        max_retries=1,
        tool_call_id="call-1",
    )
    with patch(
        "app.agents.capabilities.virtual_tables._toolset.get_db_context",
        side_effect=lambda: world.factory.begin(),
    ):
        answer = await tool(run_ctx, table_id=world.leads.id, values={"Email": "agent@x"})
    assert "agent@x" in answer

    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("queued", None)] * 3


async def test_filters_hold_on_the_record_as_it_was_created(world: _World):
    trigger_id = await world.trigger(
        filters=[
            RecordFilter(column_id=world.column("Score"), op="gt", value=80),
            RecordFilter(column_id=world.column("VIP"), op="eq", value=True),
            RecordFilter(column_id=world.column("Email"), op="is_null", value=False),
        ],
    )

    await world.add({"Email": "a@x", "Score": 90, "VIP": True})
    await world.add({"Email": "b@x", "Score": 70, "VIP": True})
    await world.add({"Score": 99, "VIP": True})
    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [
        ("queued", None),
        ("filtered", "filter_mismatch"),
        ("filtered", "filter_mismatch"),
    ]


async def test_a_record_added_before_it_was_on_never_starts_it(world: _World):
    workflow = await world.workflow()
    graph = _on_new_record(world.leads)
    await world.add({"Email": "early@x"})
    await world.publish(workflow, graph)
    trigger_id = (await world.trigger_of(workflow)).id
    await world.pause(trigger_id)
    await world.add({"Email": "while-off@x"})
    await world.consume()
    await world.pause(trigger_id, active=True)
    await world.add({"Email": "after@x"})
    await world.consume()
    await world.pause(trigger_id)
    await world.add({"Email": "paused-again@x"})
    # Publishing switches a paused trigger back on - from now, not from the pause.
    await world.publish(workflow, graph)
    assert (await world.trigger_of(workflow)).id == trigger_id
    await world.consume()

    # The record added before it existed was consumed with no trigger on the
    # table, the first one added while it was off with it switched off, and the
    # second after the publish switched it back on - as added before that.
    assert _statuses(await world.admissions(trigger_id)) == [
        ("queued", None),
        ("filtered", "pre_activation"),
    ]


async def test_a_pre_activation_event_still_pending_is_filtered(world: _World):
    await world.add({"Email": "early@x"})
    trigger_id = await world.trigger()

    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("filtered", "pre_activation")]


@pytest.mark.security
async def test_a_principal_who_lost_access_fails_the_admission(world: _World):
    async with world.factory() as db:
        member = User(
            id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.com", hashed_password="x", is_active=True
        )
        db.add(member)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=world.org.id, user_id=member.id, role="admin"
            )
        )
        await db.commit()
    trigger_id = await world.trigger(
        ctx=AuthContext(user_id=member.id, organization_id=world.org.id, role="admin"),
    )
    async with world.factory() as db:
        await db.execute(
            update(OrganizationMember)
            .where(OrganizationMember.user_id == member.id)
            .values(role="viewer")
        )
        await db.commit()

    await world.add({"Email": "a@x"})
    assert await world.consume() == []

    assert _statuses(await world.admissions(trigger_id)) == [("failed", "permission_denied")]


@pytest.mark.security
async def test_a_trigger_whose_publisher_was_deactivated_fails(world: _World):
    trigger_id = await world.trigger()
    async with world.factory() as db:
        await db.execute(update(User).where(User.id == world.owner.id).values(is_active=False))
        await db.commit()

    await world.add({"Email": "a@x"})
    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("failed", "permission_denied")]


async def test_a_loop_through_two_tables_stops_at_the_trigger_it_already_passed(world: _World):
    contacts = await world.table("Contacts")
    into_contacts = _on_new_record(world.leads, into=contacts)
    into_leads = _on_new_record(contacts, into=world.leads)
    first, second = await world.workflow(), await world.workflow()
    await world.publish(first, into_contacts)
    await world.publish(second, into_leads)
    a = (await world.trigger_of(first)).id
    b = (await world.trigger_of(second)).id

    await world.add({"Email": "start@x"})
    ((r1, _entry),) = await world.consume()
    assert (await world.drive(r1, into_contacts)).status == WorkflowRunStatus.SUCCEEDED.value
    ((r2, _entry),) = await world.consume()
    assert (await world.drive(r2, into_leads)).status == WorkflowRunStatus.SUCCEEDED.value
    assert await world.consume() == []

    run = await world.run(r2)
    assert (run.root_run_id, run.causation_run_id, run.depth) == (r1, r1, 1)
    assert run.visited_trigger_ids == [str(a), str(b)]
    assert _statuses(await world.admissions(a)) == [("queued", None), ("blocked", "cycle")]
    assert _statuses(await world.admissions(b)) == [("queued", None)]


async def test_a_chain_too_deep_or_too_long_is_blocked(world: _World):
    contacts = await world.table("Contacts")
    graph = _on_new_record(world.leads, into=contacts)
    await world.publish(await world.workflow(), graph)
    trigger_id = await world.trigger(table=contacts)
    await world.add({"Email": "start@x"})
    ((root, _entry),) = await world.consume()

    async with world.factory() as db:
        await db.execute(update(WorkflowRun).where(WorkflowRun.id == root).values(depth=MAX_DEPTH))
        await db.commit()
    await world.drive(root, graph)
    await world.consume()
    assert _statuses(await world.admissions(trigger_id)) == [("blocked", "depth_limit")]

    async with world.factory() as db:
        await db.execute(update(WorkflowRun).where(WorkflowRun.id == root).values(depth=0))
        await db.execute(delete(TableTriggerAdmission))
        await db.execute(update(VirtualTableOutbox).values(dispatched_at=None))
        with patch("app.services.virtual_tables.triggers.MAX_RUNS_PER_ROOT", 1):
            assert MAX_RUNS_PER_ROOT > 1
            await TableTriggerConsumer(db).consume()
        await db.commit()
    # The chain's root is its one run so far, the quota of this patched one.
    assert ("blocked", "quota") in _statuses(await world.admissions(trigger_id))


async def test_a_record_whose_creation_is_gone_fails_as_unavailable(world: _World):
    trigger_id = await world.trigger()
    await world.add({"Email": "a@x"})
    async with world.factory() as db:
        await db.execute(delete(VirtualTableRecordHistory))
        await db.commit()

    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("failed", "unavailable")]


async def test_an_input_the_run_refuses_is_blocked_as_a_quota(world: _World):
    trigger_id = await world.trigger()
    await world.add({"Email": "a@x"})

    with patch(
        "app.services.workflow_execution.facade._checked_input",
        side_effect=WorkflowRunInputTooLargeError(limit=1, size=2),
    ):
        assert await world.consume() == []

    assert _statuses(await world.admissions(trigger_id)) == [("blocked", "quota")]
    async with world.factory() as db:
        assert (await db.execute(select(WorkflowRun))).first() is None


async def test_a_publish_is_refused_for_a_table_or_filter_that_does_not_fit(world: _World):
    workflow = await world.workflow()
    missing = TableRead.model_validate({**world.leads.model_dump(), "id": uuid.uuid4()})
    refusals = {
        "table": _on_new_record(missing),
        "filters.0.column_id": _on_new_record(
            world.leads, filters=[RecordFilter(column_id=uuid.uuid4(), op="eq", value="x")]
        ),
        "filters.0": _on_new_record(
            world.leads,
            filters=[RecordFilter(column_id=world.column("VIP"), op="contains", value="x")],
        ),
    }
    for field, graph in refusals.items():
        with pytest.raises(GraphValidationError) as refused:
            await world.publish(workflow, graph)
        entry = str(graph.entry_node_id)
        assert any(
            problem["field"] == f"nodes.{entry}.config.{field}"
            for problem in refused.value.details["fields"]
        ), refused.value.details
    async with world.factory() as db:
        assert (await db.execute(select(VirtualTableTrigger))).first() is None
        with pytest.raises(NotFoundError, match="Trigger not found"):
            await TableTriggerService(db).set_active(
                world.ctx, world.leads.id, uuid.uuid4(), TableTriggerUpdate(is_active=True)
            )


@pytest.mark.security
async def test_a_publisher_who_may_not_run_the_workflow_cannot_make_it_run_as_them(
    world: _World,
):
    with (
        patch("app.services.workflow_triggers.resolve_access", new=AsyncMock(return_value=False)),
        pytest.raises(AuthorizationError, match="runs as you"),
    ):
        await world.trigger()
    async with world.factory() as db:
        assert (await db.execute(select(VirtualTableTrigger))).first() is None


async def test_a_new_version_takes_it_over_as_a_new_revision(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
    node_id = (await world.trigger_of(workflow)).node_instance_id
    graph = _on_new_record(
        world.leads, filters=[RecordFilter(column_id=world.column("VIP"), op="eq", value=True)]
    )
    same_node = WorkflowGraph(
        entry_node_id=node_id,
        nodes=(NodeInstance(**{**graph.nodes[0].model_dump(), "id": node_id}),),
    )
    live = await world.publish(workflow, same_node)

    async with world.factory() as db:
        listed = await TableTriggerService(db).list_for_table(world.ctx, world.leads.id)
        revisions = (
            await db.execute(
                select(VirtualTableTriggerRevision.revision)
                .where(VirtualTableTriggerRevision.trigger_id == trigger_id)
                .order_by(VirtualTableTriggerRevision.revision)
            )
        ).scalars()
        assert list(revisions) == [1, 2]
    (moved,) = listed.items
    assert (moved.id, moved.workflow_version_id, moved.version_number) == (trigger_id, live.id, 2)
    assert (moved.revision, moved.node_instance_id) == (2, node_id)
    assert [item.column_id for item in moved.filters] == [world.column("VIP")]


async def test_another_node_or_table_replaces_it_and_starting_another_way_removes_it(
    world: _World,
):
    workflow = await world.workflow()
    first = await world.trigger(workflow)
    second = await world.trigger(workflow)
    assert second != first
    contacts = await world.table("Contacts")
    third = await world.trigger(workflow, table=contacts)
    async with world.factory() as db:
        remaining = (await db.execute(select(VirtualTableTrigger))).scalars().all()
    assert [(item.id, item.table_id) for item in remaining] == [(third, contacts.id)]

    await world.publish(workflow, _by_hand())
    async with world.factory() as db:
        assert (await db.execute(select(VirtualTableTrigger))).first() is None
        stored = await db.get(Workflow, workflow.id)
    assert stored is not None and stored.live_trigger == "core.input"


def _keeping(table: TableRead, *labels: str) -> list[ColumnInput]:
    """The schema change that archives every column but these."""
    return [
        ColumnInput(id=item.id, label=item.label, type=item.type)
        for item in table.columns
        if item.label in labels
    ]


async def test_archiving_a_column_a_trigger_filters_on_is_refused(world: _World):
    trigger_id = await world.trigger(
        filters=[RecordFilter(column_id=world.column("Score"), op="gt", value=1)]
    )
    await world.pause(trigger_id)

    async with world.factory() as db:
        with pytest.raises(SchemaDependencyError) as refused:
            await VirtualTableService(db).update_schema(
                world.ctx,
                world.leads.id,
                SchemaUpdate(
                    expected_version=world.leads.schema_version,
                    columns=_keeping(world.leads, "Email", "VIP"),
                ),
            )
    assert str(trigger_id) in json.dumps(refused.value.details, default=str)

    async with world.factory() as db:
        updated = await VirtualTableService(db).update_schema(
            world.ctx,
            world.leads.id,
            SchemaUpdate(
                expected_version=world.leads.schema_version,
                columns=_keeping(world.leads, "Email", "Score"),
            ),
        )
        await db.commit()
    assert updated.schema_version == world.leads.schema_version + 1


@pytest.fixture
async def http(world: _World, mock_redis: MagicMock) -> AsyncIterator[AsyncClient]:
    async def session() -> AsyncGenerator[AsyncSession, None]:
        async with world.factory() as opened:
            try:
                yield opened
                await opened.commit()
            except BaseException:
                await opened.rollback()
                raise

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_auth_context] = lambda: world.ctx
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    async with open_client() as client:
        yield client
    app.dependency_overrides.clear()


async def test_the_routes_list_it_pause_it_and_say_what_it_decided(
    world: _World, http: AsyncClient
):
    trigger_id = str(await world.trigger())
    base = f"{settings.API_V1_STR}/tables/{world.leads.id}"
    record = await http.post(
        f"{base}/records", json={"values": {str(world.column("Email")): "api@x"}}
    )
    assert record.status_code == 201, record.text
    await world.consume()

    listed = await http.get(f"{base}/triggers")
    assert [item["id"] for item in listed.json()["items"]] == [trigger_id]
    assert listed.json()["items"][0]["workflow_name"] == "Follow up"
    paused = await http.patch(f"{base}/triggers/{trigger_id}", json={"is_active": False})
    assert paused.json()["is_active"] is False
    history = await http.get(f"{base}/triggers/{trigger_id}/admissions")
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["status"] == "queued"
    assert "api@x" not in history.text
    # Made and removed by publishing its workflow, not here.
    assert (await http.post(f"{base}/triggers", json={})).status_code == 405
    assert (await http.delete(f"{base}/triggers/{trigger_id}")).status_code == 405


@pytest.mark.security
async def test_a_trigger_whose_member_is_gone_admits_nothing(world: _World):
    trigger_id = await world.trigger()
    async with world.factory() as db:
        # What deleting the member's account leaves: `SET NULL`, and the history.
        await db.execute(
            update(VirtualTableTrigger)
            .where(VirtualTableTrigger.id == trigger_id)
            .values(execution_principal_user_id=None)
        )
        await db.commit()

    await world.add({"Email": "a@x"})
    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("failed", "permission_denied")]


async def test_archiving_the_table_a_workflow_starts_from_names_that_workflow(world: _World):
    workflow = await world.workflow()
    await world.trigger(workflow)

    async with world.factory() as db:
        with pytest.raises(SchemaDependencyError) as refused:
            await VirtualTableService(db).archive_table(world.ctx, world.leads.id)

    assert str(workflow.id) in json.dumps(refused.value.details, default=str)


async def test_a_trigger_switched_off_after_the_list_was_read_starts_nothing(world: _World):
    """The consumer lists a table's triggers once per event; one switched off in
    between is re-read under its lock and judged off, not by the stale copy."""
    trigger_id = await world.trigger()
    async with world.factory() as db:
        stale = await db.get(VirtualTableTrigger, trigger_id)
    await world.add({"Email": "a@x"})
    await world.pause(trigger_id)

    with patch(
        "app.services.virtual_tables.triggers.trigger_repo.list_for_table",
        new=AsyncMock(return_value=[stale]),
    ):
        assert await world.consume() == []

    assert await world.admissions(trigger_id) == []
    async with world.factory() as db:
        assert (await db.execute(select(WorkflowRun))).first() is None
