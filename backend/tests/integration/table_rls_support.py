"""Disposable roles and the real protected object family, never a production role."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.permissions import AuthContext
from app.db import table_rls
from app.db.models.organization import Organization
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTableMedia, VirtualTableOutbox
from app.db.models.virtual_table_relation import VirtualTableLinkEvidence
from app.db.models.virtual_table_trigger import (
    TableTriggerAdmission,
    VirtualTableTrigger,
    VirtualTableTriggerRevision,
)
from app.db.models.workflow import Workflow, WorkflowVersion
from app.schemas.virtual_table import RecordCreate, TableCreate, TableRead
from app.services.virtual_tables import VirtualTableService
from tests.integration.virtual_table_support import (
    bound_view,
    cid,
    column,
    ctx_for,
    make_org,
    make_user,
)


@dataclass(frozen=True)
class Tenant:
    organization: Organization
    owner: User
    source: TableRead
    target: TableRead
    source_record: UUID
    target_record: UUID
    trigger_id: UUID
    workflow_id: UUID
    version_id: UUID

    @property
    def ctx(self) -> AuthContext:
        return ctx_for(self.owner, self.organization)


@dataclass(frozen=True)
class RlsWorld:
    migration: async_sessionmaker[AsyncSession]
    runtime: async_sessionmaker[AsyncSession]
    maintenance: async_sessionmaker[AsyncSession]
    runtime_engine: AsyncEngine
    maintenance_engine: AsyncEngine
    runtime_role: str
    maintenance_role: str
    group: str
    tenants: tuple[Tenant, Tenant]

    async def activate(self) -> None:
        async with (
            self.migration() as migration,
            self.runtime() as runtime,
            self.maintenance() as maintenance,
        ):
            await table_rls.activate_table_rls(migration, runtime, maintenance)
            await migration.commit()


async def _tenant(db: AsyncSession, name: str) -> Tenant:
    owner = await make_user(db)
    organization = await make_org(db, owner=owner)
    ctx = ctx_for(owner, organization)
    service = VirtualTableService(db)
    target = await service.create_table(
        ctx, TableCreate(name=f"{name} customers", columns=[column("Name", "text")])
    )
    source = await service.create_table(
        ctx,
        TableCreate(
            name=f"{name} orders",
            columns=[
                column("Name", "text"),
                column("Customer", "link", link_table_id=target.id),
            ],
        ),
    )
    target_record = (
        await service.create_record(
            ctx, target.id, RecordCreate(values={cid(target, "Name"): name})
        )
    ).record.id
    source_record = (
        await service.create_record(
            ctx,
            source.id,
            RecordCreate(values={cid(source, "Customer"): [str(target_record)]}),
            operation_key="seed",
        )
    ).record.id
    await bound_view(db, ctx, source.id)
    db.add(
        VirtualTableMedia(
            organization_id=organization.id,
            table_id=source.id,
            mime_type="image/png",
            data=b"disposable-test-payload",
        )
    )
    db.add(
        VirtualTableLinkEvidence(
            organization_id=organization.id,
            source_table_id=source.id,
            source_record_id=source_record,
            column_id=UUID(cid(source, "Customer")),
            source_revision=1,
            position=0,
            reason="missing_target",
            value=str(uuid4()),
        )
    )
    for resource_type, resource_id in (
        ("table", source.id),
        ("table_record", source_record),
        ("workflow", uuid4()),
    ):
        db.add(
            ResourceGrant(
                organization_id=organization.id,
                subject_user_id=owner.id,
                resource_type=resource_type,
                resource_id=resource_id,
                level="read",
            )
        )
    workflow = Workflow(
        organization_id=organization.id,
        owner_user_id=owner.id,
        slug=f"rls-{uuid4().hex}",
        name="RLS trigger",
        status="draft",
    )
    db.add(workflow)
    await db.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id,
        organization_id=organization.id,
        version=1,
        graph={},
    )
    db.add(version)
    await db.flush()
    trigger = VirtualTableTrigger(
        organization_id=organization.id,
        table_id=source.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        node_instance_id=uuid4(),
        is_active=False,
        activated_at=datetime.now(UTC),
        execution_principal_user_id=owner.id,
    )
    db.add(trigger)
    await db.flush()
    db.add(
        VirtualTableTriggerRevision(
            trigger_id=trigger.id, revision=1, workflow_version_id=version.id, filters=[]
        )
    )
    event = await db.scalar(
        select(VirtualTableOutbox).where(VirtualTableOutbox.record_id == source_record)
    )
    assert event is not None
    db.add(
        TableTriggerAdmission(
            organization_id=organization.id,
            trigger_id=trigger.id,
            trigger_revision=1,
            outbox_event_id=event.id,
            status="filtered",
        )
    )
    await db.flush()
    return Tenant(
        organization,
        owner,
        source,
        target,
        source_record,
        target_record,
        trigger.id,
        workflow.id,
        version.id,
    )


@asynccontextmanager
async def make_rls_world(
    engine: AsyncEngine, monkeypatch, *, activate: bool = True
) -> AsyncIterator[RlsWorld]:
    """Use unique cluster roles so independent xdist databases cannot drop each other's role."""
    suffix = uuid4().hex
    group = f"tables_group_{suffix}"
    runtime_role = f"tables_runtime_{suffix}"
    maintenance_role = f"tables_maint_{suffix}"
    password = secrets.token_hex(24)
    monkeypatch.setattr(table_rls, "MAINTENANCE_ROLE", group)
    monkeypatch.setattr(
        table_rls,
        "MAINTENANCE_PREDICATE",
        f"COALESCE(pg_catalog.pg_has_role(current_user, pg_catalog.to_regrole('{group}'), 'MEMBER'), false)",
    )
    owned_roles = []
    connections = []
    try:
        async with engine.begin() as connection:
            for role, login in ((group, False), (runtime_role, True), (maintenance_role, True)):
                mode = f"LOGIN PASSWORD '{password}'" if login else "NOLOGIN"
                await connection.execute(
                    text(f'CREATE ROLE "{role}" {mode} NOSUPERUSER NOBYPASSRLS NOCREATEROLE')
                )
                owned_roles.append(role)
            await connection.execute(text(f'GRANT "{group}" TO "{maintenance_role}"'))
            for role in (runtime_role, maintenance_role):
                await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
                await connection.execute(
                    text(
                        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'
                    )
                )
                await connection.execute(
                    text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
                )
        for role in (runtime_role, maintenance_role):
            connections.append(
                create_async_engine(
                    engine.url.set(username=role, password=password),
                    poolclass=NullPool,
                    connect_args={"timeout": 10, "command_timeout": 30},
                )
            )
        runtime_engine, maintenance_engine = connections
        migration = async_sessionmaker(engine, expire_on_commit=False)
        async with migration() as db:
            tenants = (await _tenant(db, "First"), await _tenant(db, "Second"))
            await table_rls.install_table_policies(db)
            await db.commit()
        world = RlsWorld(
            migration,
            async_sessionmaker(runtime_engine, expire_on_commit=False),
            async_sessionmaker(maintenance_engine, expire_on_commit=False),
            runtime_engine,
            maintenance_engine,
            runtime_role,
            maintenance_role,
            group,
            tenants,
        )
        if activate:
            await world.activate()
        yield world
    finally:
        for connection in connections:
            await connection.dispose()
        async with engine.begin() as connection:
            for name in table_rls.TABLE_OBJECTS:
                await connection.execute(
                    text(f'ALTER TABLE public."{name}" DISABLE ROW LEVEL SECURITY')
                )
                await connection.execute(
                    text(f'ALTER TABLE public."{name}" NO FORCE ROW LEVEL SECURITY')
                )
                for policy in (table_rls.GUARD_POLICY, table_rls.ACCESS_POLICY):
                    await connection.execute(
                        text(f'DROP POLICY IF EXISTS "{policy}" ON public."{name}"')
                    )
            for role in reversed(owned_roles):
                await connection.execute(text(f'DROP OWNED BY "{role}"'))
                await connection.execute(text(f'DROP ROLE "{role}"'))
