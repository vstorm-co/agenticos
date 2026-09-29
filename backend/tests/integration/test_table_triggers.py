"""A table's triggers against a real Postgres (#1785).

What only the database can show: that every way a record is added leaves the
event a trigger reads, that an event admits at most once per trigger however
often it is consumed, that the activation boundary holds, and that a chain of
runs writing into each other's tables stops at the trigger it already passed.
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
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
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
from app.schemas.virtual_table_trigger import TableTriggerCreate, TableTriggerUpdate
from app.services.virtual_tables.exceptions import SchemaDependencyError
from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.triggers import (
    MAX_DEPTH,
    MAX_RUNS_PER_ROOT,
    TableTriggerConsumer,
    TableTriggerService,
)
from app.services.workflow_execution.exceptions import (
    WorkflowNotRunnableError,
    WorkflowRunInputTooLargeError,
)
from app.workflows.contracts.io import Binding, LiteralValue, TableIORef
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


def _echo_graph() -> WorkflowGraph:
    entry = _node("debug.echo", {"message": "hi"})
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


def _writes_into(table: TableRead) -> WorkflowGraph:
    """A graph whose one real step adds a record to `table`."""
    entry = _node("core.input")
    create = _node(
        "table.record.create",
        {
            "table": TableIORef(table_id=table.id, schema_version=table.schema_version).model_dump(
                mode="json"
            )
        },
    )
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

    async def workflow(
        self, graph: WorkflowGraph | None = None, *, published: bool = True
    ) -> Workflow:
        async with self.factory() as db:
            workflow = Workflow(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                owner_user_id=self.owner.id,
                slug=f"wf-{uuid.uuid4().hex[:8]}",
                name="Follow up",
                status=WorkflowStatus.PUBLISHED.value,
                visibility=Visibility.ORG.value,
                draft_graph=(graph or _echo_graph()).model_dump(mode="json"),
            )
            db.add(workflow)
            await db.flush()
            if published:
                await self.publish(db, workflow, graph or _echo_graph(), number=1)
            await db.commit()
        return workflow

    @staticmethod
    async def publish(
        db: AsyncSession, workflow: Workflow, graph: WorkflowGraph, *, number: int
    ) -> WorkflowVersion:
        version = WorkflowVersion(
            id=uuid.uuid4(),
            workflow_id=workflow.id,
            organization_id=workflow.organization_id,
            version=number,
            graph=graph.model_dump(mode="json"),
        )
        db.add(version)
        await db.flush()
        await db.execute(
            update(Workflow).where(Workflow.id == workflow.id).values(current_version_id=version.id)
        )
        return version

    async def trigger(
        self,
        workflow: Workflow,
        *,
        table: TableRead | None = None,
        ctx: AuthContext | None = None,
        **fields: Any,
    ) -> uuid.UUID:
        async with self.factory() as db:
            made = await TableTriggerService(db).create(
                ctx or self.ctx,
                (table or self.leads).id,
                TableTriggerCreate(workflow_id=workflow.id, **fields),
            )
            await db.commit()
        return made.id

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


async def test_an_added_record_starts_the_live_version_with_its_mapped_values(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(
        workflow,
        input_mapping={
            "email": str(world.column("Email")),
            "by": "@author",
            "record_id": "@record_id",
        },
    )

    await world.add({"Email": "ada@example.com", "Score": 90})
    pairs = await world.consume()

    (admission,) = await world.admissions(trigger_id)
    assert (admission.status, admission.reason) == ("queued", None)
    assert pairs == [(admission.workflow_run_id, pairs[0][1])]
    run = await world.run(pairs[0][0])
    assert run.triggered_by == WorkflowRunTrigger.TABLE_CREATED.value
    (record_id,) = await _record_ids(world)
    assert run.input == {
        "email": "ada@example.com",
        "by": str(world.owner.id),
        "record_id": str(record_id),
    }
    assert run.execution_principal_user_id == world.owner.id
    assert run.visited_trigger_ids == [str(trigger_id)]
    assert (run.depth, run.root_run_id, run.causation_run_id) == (0, run.id, None)


async def test_an_event_admits_once_however_often_it_is_consumed(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
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
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
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
    workflow = await world.workflow()
    trigger_id = await world.trigger(
        workflow,
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
    await world.add({"Email": "early@x"})
    trigger_id = await world.trigger(workflow)
    async with world.factory() as db:
        await TableTriggerService(db).update(
            world.ctx, world.leads.id, trigger_id, TableTriggerUpdate(is_active=False)
        )
        await db.commit()
    await world.add({"Email": "while-off@x"})
    await world.consume()
    async with world.factory() as db:
        back_on = await TableTriggerService(db).update(
            world.ctx, world.leads.id, trigger_id, TableTriggerUpdate(is_active=True)
        )
        await db.commit()
    await world.add({"Email": "after@x"})
    await world.consume()

    # The record added before it existed was consumed with no trigger on the
    # table; the one added while it was off, with it switched off.
    assert _statuses(await world.admissions(trigger_id)) == [("queued", None)]
    assert back_on.is_active and back_on.revision == 1


async def test_a_pre_activation_event_still_pending_is_filtered(world: _World):
    workflow = await world.workflow()
    await world.add({"Email": "early@x"})
    trigger_id = await world.trigger(workflow)

    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("filtered", "pre_activation")]


@pytest.mark.security
async def test_a_principal_who_lost_access_fails_the_admission(world: _World):
    workflow = await world.workflow()
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
        workflow,
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
async def test_a_trigger_runs_as_whoever_last_changed_it_and_a_deactivated_one_fails(
    world: _World,
):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
    async with world.factory() as db:
        await db.execute(update(User).where(User.id == world.owner.id).values(is_active=False))
        await db.commit()

    await world.add({"Email": "a@x"})
    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("failed", "permission_denied")]


async def test_a_loop_through_two_tables_stops_at_the_trigger_it_already_passed(world: _World):
    contacts = await world.table("Contacts")
    into_contacts, into_leads = _writes_into(contacts), _writes_into(world.leads)
    first = await world.workflow(into_contacts)
    second = await world.workflow(into_leads)
    a = await world.trigger(first)
    b = await world.trigger(second, table=contacts)

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
    graph = _writes_into(contacts)
    first = await world.workflow(graph)
    trigger_id = await world.trigger(await world.workflow(), table=contacts)
    await world.trigger(first)
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
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
    await world.add({"Email": "a@x"})
    async with world.factory() as db:
        await db.execute(delete(VirtualTableRecordHistory))
        await db.commit()

    await world.consume()

    assert _statuses(await world.admissions(trigger_id)) == [("failed", "unavailable")]


async def test_an_input_the_run_refuses_is_blocked_as_a_quota(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow, input_mapping={"email": str(world.column("Email"))})
    await world.add({"Email": "a@x"})

    with patch(
        "app.services.workflow_execution.facade._checked_input",
        side_effect=WorkflowRunInputTooLargeError(limit=1, size=2),
    ):
        assert await world.consume() == []

    assert _statuses(await world.admissions(trigger_id)) == [("blocked", "quota")]
    async with world.factory() as db:
        assert (await db.execute(select(WorkflowRun))).first() is None


async def test_setting_one_up_is_refused_for_what_the_caller_cannot_reach(world: _World):
    workflow = await world.workflow()
    draft = await world.workflow(published=False)
    email = world.column("Email")
    async with world.factory() as db:
        service = TableTriggerService(db)
        with pytest.raises(WorkflowNotRunnableError):
            await service.create(
                world.ctx, world.leads.id, TableTriggerCreate(workflow_id=draft.id)
            )
        with pytest.raises(NotFoundError):
            await service.create(
                world.ctx, world.leads.id, TableTriggerCreate(workflow_id=uuid.uuid4())
            )
        with pytest.raises(BadRequestError, match="column this table does not have"):
            await service.create(
                world.ctx,
                world.leads.id,
                TableTriggerCreate(
                    workflow_id=workflow.id,
                    filters=[RecordFilter(column_id=uuid.uuid4(), op="eq", value="x")],
                ),
            )
        with pytest.raises(BadRequestError):
            await service.create(
                world.ctx,
                world.leads.id,
                TableTriggerCreate(
                    workflow_id=workflow.id,
                    filters=[RecordFilter(column_id=world.column("Score"), op="gt", value="high")],
                ),
            )
        with pytest.raises(BadRequestError, match="1 to 64"):
            await service.create(
                world.ctx,
                world.leads.id,
                TableTriggerCreate(workflow_id=workflow.id, input_mapping={" ": str(email)}),
            )
        with pytest.raises(BadRequestError, match="'x' takes its value"):
            await service.create(
                world.ctx,
                world.leads.id,
                TableTriggerCreate(workflow_id=workflow.id, input_mapping={"x": "nope"}),
            )
        with pytest.raises(NotFoundError, match="Trigger not found"):
            await service.update(world.ctx, world.leads.id, uuid.uuid4(), TableTriggerUpdate())


@pytest.mark.security
async def test_a_member_who_may_edit_the_table_but_not_run_the_workflow_is_refused(
    world: _World,
):
    async with world.factory() as db:
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=world.org.id,
            owner_user_id=world.owner.id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Archived",
            status=WorkflowStatus.ARCHIVED.value,
            visibility=Visibility.ORG.value,
            draft_graph=_echo_graph().model_dump(mode="json"),
        )
        db.add(workflow)
        await db.flush()
        await _World.publish(db, workflow, _echo_graph(), number=1)
        await db.commit()
        with pytest.raises(AuthorizationError, match="runs as you"):
            await TableTriggerService(db).create(
                world.ctx, world.leads.id, TableTriggerCreate(workflow_id=workflow.id)
            )


async def test_a_change_keeps_a_revision_and_moves_to_the_live_version_only_when_asked(
    world: _World,
):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow, name="Hot")
    async with world.factory() as db:
        live = await _World.publish(db, workflow, _echo_graph(), number=2)
        await db.commit()
    async with world.factory() as db:
        service = TableTriggerService(db)
        renamed = await service.update(
            world.ctx, world.leads.id, trigger_id, TableTriggerUpdate(name=None)
        )
        assert (renamed.name, renamed.revision, renamed.version_number) == (None, 1, 1)
        moved = await service.update(
            world.ctx,
            world.leads.id,
            trigger_id,
            TableTriggerUpdate(
                pin_current_version=True,
                filters=[RecordFilter(column_id=world.column("VIP"), op="eq", value=True)],
                input_mapping={"who": "@author"},
            ),
        )
        await db.commit()
    assert (moved.workflow_version_id, moved.version_number, moved.revision) == (live.id, 2, 2)
    async with world.factory() as db:
        revisions = (
            await db.execute(
                select(VirtualTableTriggerRevision.revision)
                .where(VirtualTableTriggerRevision.trigger_id == trigger_id)
                .order_by(VirtualTableTriggerRevision.revision)
            )
        ).scalars()
        assert list(revisions) == [1, 2]
        listed = await TableTriggerService(db).list_for_table(world.ctx, world.leads.id)
        assert [item.id for item in listed.items] == [trigger_id]


async def test_pinning_the_live_version_of_a_workflow_since_unpublished_is_refused(
    world: _World,
):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
    async with world.factory() as db:
        await db.execute(
            update(Workflow).where(Workflow.id == workflow.id).values(current_version_id=None)
        )
        await db.commit()
    async with world.factory() as db:
        with pytest.raises(WorkflowNotRunnableError):
            await TableTriggerService(db).update(
                world.ctx, world.leads.id, trigger_id, TableTriggerUpdate(pin_current_version=True)
            )


def _keeping(table: TableRead, *labels: str) -> list[ColumnInput]:
    """The schema change that archives every column but these."""
    return [
        ColumnInput(id=item.id, label=item.label, type=item.type)
        for item in table.columns
        if item.label in labels
    ]


async def test_archiving_a_column_a_trigger_uses_is_refused(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow, input_mapping={"score": str(world.column("Score"))})
    async with world.factory() as db:
        await TableTriggerService(db).update(
            world.ctx, world.leads.id, trigger_id, TableTriggerUpdate(is_active=False)
        )
        await db.commit()

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


async def test_the_routes_set_one_up_list_what_it_decided_and_remove_it(
    world: _World, http: AsyncClient
):
    workflow = await world.workflow()
    base = f"{settings.API_V1_STR}/tables/{world.leads.id}"

    created = await http.post(f"{base}/triggers", json={"workflow_id": str(workflow.id)})
    assert created.status_code == 201, created.text
    trigger_id = created.json()["id"]
    record = await http.post(
        f"{base}/records", json={"values": {str(world.column("Email")): "api@x"}}
    )
    assert record.status_code == 201, record.text
    await world.consume()

    listed = await http.get(f"{base}/triggers")
    assert [item["id"] for item in listed.json()["items"]] == [trigger_id]
    patched = await http.patch(f"{base}/triggers/{trigger_id}", json={"name": "API"})
    assert patched.json()["name"] == "API"
    history = await http.get(f"{base}/triggers/{trigger_id}/admissions")
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["status"] == "queued"
    assert "api@x" not in history.text

    removed = await http.delete(f"{base}/triggers/{trigger_id}")
    assert removed.status_code == 204
    async with world.factory() as db:
        assert (await db.execute(select(VirtualTableTrigger))).first() is None


@pytest.mark.security
async def test_a_trigger_whose_member_is_gone_admits_nothing(world: _World):
    workflow = await world.workflow()
    trigger_id = await world.trigger(workflow)
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


async def test_archiving_the_whole_table_is_not_held_up_by_its_triggers(world: _World):
    workflow = await world.workflow()
    await world.trigger(workflow, input_mapping={"email": str(world.column("Email"))})

    async with world.factory() as db:
        archived = await VirtualTableService(db).archive_table(world.ctx, world.leads.id)
        await db.commit()

    assert archived.archived_at is not None
