"""The deployed policy family, using actual non-owner PostgreSQL login connections."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request
from pydantic import SecretStr
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.db import table_rls
from app.db.base import Base
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTable, VirtualTableOutbox, VirtualTableRecord
from app.db.models.virtual_table_trigger import TableTriggerAdmission, VirtualTableTrigger
from app.db.table_tenant import TableTenantContextError, UnsafeTableDatabaseRoleError
from app.schemas.virtual_table import RecordCreate
from app.services.account_maintenance import account_maintenance
from app.services.directory.sync import DirectorySyncService
from app.services.virtual_tables import VirtualTableService
from app.services.virtual_tables.triggers import TableTriggerConsumer
from app.worker.tasks import workflow_tasks
from tests.integration.table_rls_support import RlsWorld, make_rls_world
from tests.integration.virtual_table_support import cid, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
async def rls_world(engine: AsyncEngine, monkeypatch, request) -> AsyncIterator[RlsWorld]:
    async with make_rls_world(
        engine, monkeypatch, activate=getattr(request, "param", True)
    ) as world:
        yield world


async def test_no_context_is_closed_and_the_complete_family_is_tenant_scoped(rls_world):
    world = rls_world
    first, second = world.tenants
    async with world.runtime() as db:
        assert await table_rls.verify_table_runtime(db)
        for name in table_rls.TABLE_OBJECTS:
            # Intentionally omit organization predicates: the database is the backstop.
            count = await db.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
            assert count == (2 if name == "resource_grants" else 0), name
        await table_rls.bind_table_access(db, first.ctx)
        expected_counts = {
            "virtual_tables": 2,
            "virtual_table_records": 2,
            "virtual_table_record_history": 2,
            "virtual_table_receipts": 1,
            "virtual_table_outbox": 2,
            "virtual_table_media": 1,
            "table_views": 1,
            "virtual_table_triggers": 1,
            "table_trigger_admissions": 1,
            "virtual_table_relations": 1,
            "virtual_table_record_links": 1,
            "virtual_table_link_evidence": 1,
            "virtual_table_schema_versions": 2,
            "virtual_table_trigger_revisions": 1,
            "resource_grants": 4,
        }
        assert set(expected_counts) == set(table_rls.TABLE_OBJECTS)
        for name in table_rls.TABLE_OBJECTS:
            table = Base.metadata.tables[name]
            assert (
                await db.scalar(select(func.count()).select_from(table)) == expected_counts[name]
            ), name
            if name == "virtual_table_schema_versions":
                assert set(await db.scalars(select(table.c.table_id))) == {
                    first.source.id,
                    first.target.id,
                }
            elif name == "virtual_table_trigger_revisions":
                assert set(await db.scalars(select(table.c.trigger_id))) == {first.trigger_id}
            elif name == "resource_grants":
                assert set(
                    await db.scalars(
                        select(table.c.resource_id).where(
                            table.c.resource_type.in_(["table", "table_record"])
                        )
                    )
                ) == {first.source.id, first.source_record}
            else:
                assert set(await db.scalars(select(table.c.organization_id))) == {
                    first.organization.id
                }, name
        assert set(await db.scalars(select(VirtualTable.id))) == {first.source.id, first.target.id}
        assert set(await db.scalars(select(VirtualTableRecord.id))) == {
            first.source_record,
            first.target_record,
        }
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ResourceGrant)
                .where(
                    ResourceGrant.organization_id == second.organization.id,
                    ResourceGrant.resource_type.in_(["table", "table_record"]),
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ResourceGrant)
                .where(ResourceGrant.resource_type == "workflow")
            )
            == 2
        )
        with pytest.raises(TableTenantContextError, match="Cannot switch"):
            await table_rls.bind_table_access(db, second.ctx)
        await db.commit()
        assert list(await db.scalars(select(VirtualTable.id))) == []
        await table_rls.bind_table_access(db, second.ctx)
        assert set(await db.scalars(select(VirtualTable.id))) == {
            second.source.id,
            second.target.id,
        }


async def test_cross_tenant_writes_and_mismatched_legacy_parents_are_rejected(rls_world):
    world = rls_world
    first, second = world.tenants
    async with world.runtime() as db:
        await table_rls.bind_table_access(db, first.ctx)
        for statement in (
            update(VirtualTableRecord)
            .where(VirtualTableRecord.id == first.source_record)
            .values(organization_id=second.organization.id, table_id=second.source.id),
            update(VirtualTableTrigger)
            .where(VirtualTableTrigger.id == first.trigger_id)
            .values(table_id=second.source.id),
            update(TableTriggerAdmission)
            .where(TableTriggerAdmission.trigger_id == first.trigger_id)
            .values(trigger_id=second.trigger_id),
        ):
            with pytest.raises(DBAPIError, match="row-level security"):
                async with db.begin_nested():
                    await db.execute(statement)
        for model in (
            VirtualTableRecord(
                organization_id=second.organization.id,
                table_id=second.target.id,
                schema_version=1,
                values={},
                revision=1,
            ),
            ResourceGrant(
                organization_id=second.organization.id,
                subject_user_id=second.owner.id,
                resource_type="table_record",
                resource_id=second.source_record,
                level="read",
            ),
        ):
            with pytest.raises(DBAPIError, match="row-level security"):
                async with db.begin_nested():
                    db.add(model)
                    await db.flush()
        result = await db.execute(
            delete(VirtualTableRecord).where(
                VirtualTableRecord.organization_id == second.organization.id
            )
        )
        assert result.rowcount == 0


async def test_actual_request_context_and_idempotent_service_bind_before_savepoints(rls_world):
    world = rls_world
    first, second = world.tenants
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-organization-id", str(second.organization.id).encode())],
        }
    )
    async with world.runtime() as db:
        ctx = await deps.get_auth_context(request, first.owner, first.organization, db)
        assert ctx.organization_id == first.organization.id
        service = VirtualTableService(db)
        body = RecordCreate(values={cid(first.target, "Name"): "new"})
        created = await service.create_record(ctx, first.target.id, body, operation_key="request")
        replay = await service.create_record(ctx, first.target.id, body, operation_key="request")
        assert replay.replayed and replay.record.id == created.record.id
        with pytest.raises(NotFoundError):
            await service.describe_table(ctx, second.source.id)
        await db.commit()
    async with world.runtime() as db:
        # Direct service calls, including tools and worker-owned sessions, have
        # no HTTP dependency to bind for them.
        created = await VirtualTableService(db).create_record(
            first.ctx, first.target.id, body, operation_key="direct-service"
        )
        assert not created.replayed
        assert await db.scalar(text("SELECT current_setting('t3os.organization_id', true)")) == str(
            first.organization.id
        )
        await db.rollback()
    async with world.runtime() as db:
        with pytest.raises(NotFoundError):
            await deps.get_path_org_context(second.organization.id, request, first.owner, db)
        assert list(await db.scalars(select(VirtualTable.id))) == []


async def test_trigger_consumer_and_worker_fanout_do_not_claim_another_tenant(
    rls_world, monkeypatch
):
    world = rls_world
    first, second = world.tenants
    async with world.runtime() as db:
        assert await TableTriggerConsumer(db).consume(first.ctx) == []
        await db.commit()
    async with world.maintenance() as db:
        pending = set(
            await db.scalars(
                select(VirtualTableOutbox.organization_id).where(
                    VirtualTableOutbox.dispatched_at.is_(None)
                )
            )
        )
        assert pending == {second.organization.id}

    @asynccontextmanager
    async def worker_context():
        async with world.runtime() as db:
            try:
                yield db
                await db.commit()
            finally:
                await db.rollback()

    monkeypatch.setattr(workflow_tasks, "get_worker_db_context", worker_context)
    assert await workflow_tasks.consume_table_triggers() == 0
    async with world.maintenance() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(VirtualTableOutbox)
                .where(VirtualTableOutbox.dispatched_at.is_(None))
            )
            == 0
        )


@pytest.mark.parametrize("damage", ["missing", "expression", "roles", "unknown"])
async def test_policy_drift_is_refused_and_only_owned_definitions_can_be_recreated(
    rls_world, damage
):
    world = rls_world
    name = "virtual_table_records"
    guard = table_rls.GUARD_POLICY
    statements = {
        "missing": f'DROP POLICY "{guard}" ON {name}',
        "expression": f'ALTER POLICY "{guard}" ON {name} USING (true)',
        "roles": f'ALTER POLICY "{guard}" ON {name} TO "{world.runtime_role}"',
        "unknown": f"CREATE POLICY foreign_policy ON {name} USING (true) WITH CHECK (true)",
    }
    async with world.migration() as db:
        await db.execute(text(statements[damage]))
        await db.commit()
    try:
        async with world.runtime() as db:
            with pytest.raises(table_rls.TableRlsConfigurationError, match="policy"):
                await table_rls.verify_table_runtime(db)
        if damage == "unknown":
            # An extra permissive policy cannot OR around the restrictive guard.
            async with world.runtime() as db:
                assert list(await db.scalars(select(VirtualTableRecord.id))) == []
            with pytest.raises(table_rls.TableRlsConfigurationError, match="inventory"):
                await world.activate()
        else:
            async with (
                world.migration() as migration,
                world.runtime() as runtime,
                world.maintenance() as maintenance,
            ):
                with pytest.raises(table_rls.TableRlsConfigurationError, match="policy"):
                    await table_rls.preflight_table_rls(migration, runtime, maintenance)
            await world.activate()
            async with world.runtime() as db:
                assert await table_rls.verify_table_runtime(db)
                assert list(await db.scalars(select(VirtualTableRecord.id))) == []
    finally:
        if damage == "unknown":
            async with world.migration() as db:
                await db.execute(text(f"DROP POLICY foreign_policy ON {name}"))
                await db.commit()


async def test_policy_fingerprints_do_not_depend_on_role_search_path(rls_world):
    world = rls_world
    async with world.migration() as db:
        await db.execute(
            text(f'ALTER ROLE "{world.runtime_role}" SET search_path = pg_catalog, public')
        )
        await db.execute(
            text(f'ALTER ROLE "{world.maintenance_role}" SET search_path = public, pg_catalog')
        )
        await db.commit()
    async with (
        world.migration() as migration,
        world.runtime() as runtime,
        world.maintenance() as maintenance,
    ):
        await table_rls.preflight_table_rls(migration, runtime, maintenance)
        assert await table_rls.verify_table_runtime(runtime)


@pytest.mark.parametrize(
    "privilege", ["truncate", "maintenance", "owner", "missing_dml", "group_login"]
)
async def test_effective_role_privileges_are_checked(rls_world, privilege):
    world = rls_world
    statements = {
        "truncate": f'GRANT TRUNCATE ON virtual_tables TO "{world.runtime_role}"',
        "maintenance": f'GRANT "{world.group}" TO "{world.runtime_role}"',
        "owner": f'ALTER TABLE virtual_tables OWNER TO "{world.runtime_role}"',
        "missing_dml": f'REVOKE DELETE ON virtual_tables FROM "{world.runtime_role}"',
        "group_login": f'ALTER ROLE "{world.group}" LOGIN',
    }
    async with world.migration() as db:
        if privilege == "owner":
            await db.execute(text(f'GRANT CREATE ON SCHEMA public TO "{world.runtime_role}"'))
        await db.execute(text(statements[privilege]))
        await db.commit()
    try:
        factory = world.maintenance if privilege == "group_login" else world.runtime
        async with factory() as db:
            with pytest.raises(UnsafeTableDatabaseRoleError, match="Unsafe Tables"):
                await table_rls.require_table_connection_role(
                    db, maintenance=privilege == "group_login"
                )
    finally:
        if privilege == "owner":
            async with world.migration() as db:
                owner = await db.scalar(text("SELECT current_user"))
                await db.execute(text(f'ALTER TABLE virtual_tables OWNER TO "{owner}"'))
                await db.commit()


async def test_set_role_does_not_hide_a_privileged_login_identity(rls_world):
    world = rls_world
    async with world.migration() as db:
        await db.execute(text(f'SET LOCAL ROLE "{world.runtime_role}"'))
        assert await db.scalar(text("SELECT current_user")) == world.runtime_role
        with pytest.raises(UnsafeTableDatabaseRoleError, match="Unsafe Tables"):
            await table_rls.require_table_connection_role(db)


@pytest.mark.parametrize("privilege", ["bypass", "owner"])
async def test_noinherit_indirect_membership_cannot_hide_assumable_privileges(rls_world, privilege):
    world = rls_world
    intermediate = f"tables_intermediate_{uuid4().hex}"
    privileged = f"tables_privileged_{uuid4().hex}"
    async with world.migration() as db:
        await db.execute(text(f'CREATE ROLE "{intermediate}" NOLOGIN NOINHERIT'))
        mode = "BYPASSRLS" if privilege == "bypass" else "NOBYPASSRLS"
        await db.execute(text(f'CREATE ROLE "{privileged}" NOLOGIN {mode}'))
        await db.execute(text(f'ALTER ROLE "{world.runtime_role}" NOINHERIT'))
        await db.execute(text(f'GRANT "{privileged}" TO "{intermediate}"'))
        await db.execute(text(f'GRANT "{intermediate}" TO "{world.runtime_role}"'))
        if privilege == "owner":
            await db.execute(text(f'GRANT CREATE ON SCHEMA public TO "{privileged}"'))
            await db.execute(text(f'ALTER TABLE virtual_tables OWNER TO "{privileged}"'))
        await db.commit()
    try:
        async with world.runtime() as db:
            assert not await db.scalar(
                text("SELECT pg_has_role(current_user, :role, 'USAGE')"), {"role": privileged}
            )
            with pytest.raises(UnsafeTableDatabaseRoleError, match="Unsafe Tables"):
                await table_rls.require_table_connection_role(db)
    finally:
        async with world.migration() as db:
            if privilege == "owner":
                owner = await db.scalar(text("SELECT current_user"))
                await db.execute(text(f'ALTER TABLE virtual_tables OWNER TO "{owner}"'))
            for role in (intermediate, privileged):
                await db.execute(text(f'DROP OWNED BY "{role}"'))
                await db.execute(text(f'DROP ROLE "{role}"'))
            await db.commit()


async def test_database_identity_challenge_is_nonblocking_and_transaction_scoped(
    rls_world, monkeypatch
):
    world = rls_world
    key = uuid4().int % (2**63)
    monkeypatch.setattr("secrets.randbits", lambda _bits: key)
    wrong_engine = create_async_engine(
        world.runtime_engine.url.set(database="postgres"),
        poolclass=NullPool,
        connect_args={"timeout": 10, "command_timeout": 30},
    )
    try:
        async with world.runtime() as runtime, async_sessionmaker(wrong_engine)() as wrong:
            with pytest.raises(table_rls.TableRlsConfigurationError, match="same database"):
                await table_rls.same_table_database(runtime, wrong)
        async with world.runtime() as holder, world.runtime() as other:
            assert await holder.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
            with pytest.raises(table_rls.TableRlsConfigurationError, match="busy"):
                await table_rls.same_table_database(other, holder)
        async with world.runtime() as db:
            assert await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
    finally:
        await wrong_engine.dispose()


@pytest.mark.parametrize("selected_role", ["runtime", "nonowner"])
async def test_preflight_requires_a_distinct_migration_owner(rls_world, selected_role):
    world = rls_world
    role = world.runtime_role if selected_role == "runtime" else world.group
    async with (
        world.migration() as migration,
        world.runtime() as runtime,
        world.maintenance() as maintenance,
    ):
        await migration.execute(text(f'SET LOCAL ROLE "{role}"'))
        with pytest.raises(table_rls.TableRlsConfigurationError, match=r"distinct|must own"):
            await table_rls.preflight_table_rls(migration, runtime, maintenance)


async def test_partial_activation_is_refused_on_a_fresh_request(rls_world):
    world = rls_world
    async with world.migration() as db:
        await db.execute(text("ALTER TABLE virtual_table_records DISABLE ROW LEVEL SECURITY"))
        await db.commit()
    async with world.runtime() as db:
        with pytest.raises(table_rls.TableRlsConfigurationError, match="partially"):
            await table_rls.bind_table_access(db, world.tenants[0].ctx)


@pytest.mark.parametrize("rls_world", [False], indirect=True)
async def test_inactive_context_is_not_cached_across_operator_activation(rls_world):
    world = rls_world
    first, second = world.tenants
    async with world.runtime() as db:
        assert not await table_rls.verify_table_runtime(db)
        await table_rls.bind_table_access(db, first.ctx)
        await table_rls.bind_table_access(db, second.ctx)
        await db.rollback()
        await world.activate()
        await table_rls.bind_table_access(db, first.ctx)
        with pytest.raises(TableTenantContextError, match="Cannot switch"):
            await table_rls.bind_table_access(db, second.ctx)


@pytest.mark.parametrize("rls_world", [False], indirect=True)
@pytest.mark.parametrize("parent", ["trigger", "admission"])
async def test_legacy_parent_corruption_refuses_activation_without_hiding_rows(rls_world, parent):
    world = rls_world
    first, second = world.tenants
    async with world.migration() as db:
        statement = (
            update(VirtualTableTrigger)
            .where(VirtualTableTrigger.id == first.trigger_id)
            .values(table_id=second.source.id)
            if parent == "trigger"
            else update(TableTriggerAdmission)
            .where(TableTriggerAdmission.trigger_id == first.trigger_id)
            .values(trigger_id=second.trigger_id)
        )
        await db.execute(statement)
        await db.commit()
    with pytest.raises(table_rls.TableRlsConfigurationError, match="legacy parent mismatch"):
        await world.activate()
    async with world.runtime() as db:
        assert not (await table_rls.table_rls_state(db)).active
        assert len(list(await db.scalars(select(VirtualTable.id)))) == 4


async def test_directory_membership_cleanup_is_atomic_across_tenants_with_rls(
    rls_world, monkeypatch
):
    world = rls_world
    from app.services.channels.discord_roles import DiscordMembershipGrant, DiscordRoleSync

    monkeypatch.setattr(
        DiscordRoleSync,
        "membership_grant",
        AsyncMock(return_value=DiscordMembershipGrant(None, frozenset())),
    )
    async with world.maintenance() as db:
        user = await make_user(db)
        for tenant in world.tenants:
            db.add(
                OrganizationMember(
                    organization_id=tenant.organization.id,
                    user_id=user.id,
                    role="viewer",
                    source="directory",
                )
            )
        await db.flush()
        for tenant in world.tenants:
            db.add(
                ResourceGrant(
                    organization_id=tenant.organization.id,
                    subject_user_id=user.id,
                    resource_type="table_record",
                    resource_id=tenant.source_record,
                    level="read",
                )
            )
        await db.commit()
        user_id = user.id
    async with world.runtime() as db:
        assert list(await db.scalars(select(VirtualTable.id))) == []
        await DirectorySyncService(db).apply(user_id, [], provider="ldap")
        assert (
            await db.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.user_id == user_id)
            )
            == 0
        )
        await db.rollback()
    async with world.maintenance() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ResourceGrant)
                .where(ResourceGrant.subject_user_id == user_id)
            )
            == 2
        )
    async with world.runtime() as db:
        await DirectorySyncService(db).apply(user_id, [], provider="ldap")
        await db.commit()
    async with world.maintenance() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ResourceGrant)
                .where(ResourceGrant.subject_user_id == user_id)
            )
            == 0
        )
        # Other resource types do not acquire the Tables membership constraint.
        db.add(
            ResourceGrant(
                organization_id=world.tenants[0].organization.id,
                subject_user_id=user_id,
                resource_type="workflow",
                resource_id=uuid4(),
                level="read",
            )
        )
        await db.flush()
        with pytest.raises(DBAPIError, match="fk_resource_grants_table_member"):
            async with db.begin_nested():
                db.add(
                    ResourceGrant(
                        organization_id=world.tenants[0].organization.id,
                        subject_user_id=user_id,
                        resource_type="table",
                        resource_id=world.tenants[0].source.id,
                        level="read",
                    )
                )
                await db.flush()


async def test_maintenance_selection_requires_configuration_and_refreshes_authority(
    rls_world, monkeypatch
):
    world = rls_world
    actor = world.tenants[0].owner
    monkeypatch.setattr(settings, "POSTGRES_MAINTENANCE_URL", None)
    async with world.runtime() as db:
        with pytest.raises(table_rls.TableRlsConfigurationError, match="POSTGRES_MAINTENANCE_URL"):
            async with account_maintenance(db, actor, require_admin=False):
                pytest.fail("missing credentials must not fall through")
    monkeypatch.setattr(
        settings,
        "POSTGRES_MAINTENANCE_URL",
        SecretStr(world.maintenance_engine.url.render_as_string(hide_password=False)),
    )
    async with world.runtime() as db:
        async with account_maintenance(db, actor, require_admin=False) as selected:
            assert selected is not db
            assert len(list(await selected.scalars(select(VirtualTable.id)))) == 4
        with pytest.raises(AuthorizationError):
            async with account_maintenance(db, actor, require_admin=True):
                pytest.fail("non-admin may not open an admin maintenance action")
    async with world.migration() as db:
        await db.execute(update(User).where(User.id == actor.id).values(is_active=False))
        await db.commit()
    async with world.runtime() as db:
        with pytest.raises(AuthenticationError):
            async with account_maintenance(db, actor, require_admin=False):
                pytest.fail("a stale authenticated actor must be checked again")


async def test_global_account_export_delete_and_rollback_share_one_maintenance_transaction(
    rls_world, monkeypatch
):
    from app.api.routes.v1 import admin_users
    from app.core.permissions import AuthContext
    from app.db.models.audit_log import AppAdminAuditLog
    from app.db.models.notification import Notification
    from app.schemas.task import TaskCreate
    from app.schemas.virtual_table import TableCreate
    from app.services.notifications import NotificationService
    from app.services.personal_data import PersonalDataService
    from app.services.tasks import TaskService
    from app.services.user import UserService

    world = rls_world
    monkeypatch.setattr(
        settings,
        "POSTGRES_MAINTENANCE_URL",
        SecretStr(world.maintenance_engine.url.render_as_string(hide_password=False)),
    )
    async with world.maintenance() as db:
        actor = await make_user(db)
        actor.is_app_admin = True
        target = await make_user(db)
        for tenant in world.tenants:
            await db.execute(
                update(Organization)
                .where(Organization.id == tenant.organization.id)
                .values(created_by_user_id=target.id)
            )
            db.add(
                OrganizationMember(
                    organization_id=tenant.organization.id,
                    user_id=target.id,
                    role="owner",
                )
            )
        await db.commit()
    private_records = []
    retained_tables = []
    for tenant in world.tenants:
        ctx = AuthContext(user_id=target.id, organization_id=tenant.organization.id, role="owner")
        async with world.runtime() as db:
            task = await TaskService(db).create(ctx, TaskCreate(title="Personal reminder"))
            table = await VirtualTableService(db).create_table(
                ctx, TableCreate(name="Retained team data")
            )
            private_records.append(task.id)
            retained_tables.append((table.id, tenant.organization.id, tenant.owner.id))
            await db.commit()
    async with world.runtime() as db:
        exported = await admin_users.export_user_data(
            target.id,
            PersonalDataService(db),
            actor,
            reason="RLS integration export",
        )
        assert {row.id for row in exported.private_task_records} == set(private_records)
        assert len(exported.private_task_boards) == 2
    async with world.maintenance() as db:
        before_notifications = await db.scalar(select(func.count()).select_from(Notification))

    original = NotificationService.security_event

    async def fail_after_notification(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        raise RuntimeError("test notification rollback")

    monkeypatch.setattr(NotificationService, "security_event", fail_after_notification)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 12345)})
    async with world.runtime() as db:
        with pytest.raises(RuntimeError, match="test notification rollback"):
            await admin_users.delete_user(
                target.id,
                request,
                actor,
                db,
                UserService(db),
                reason="RLS integration removal",
            )
    async with world.maintenance() as db:
        assert await db.get(User, target.id) is not None
        assert set(
            await db.scalars(
                select(VirtualTableRecord.id).where(VirtualTableRecord.id.in_(private_records))
            )
        ) == set(private_records)
        for table_id, organization_id, _ in retained_tables:
            retained = await db.get(VirtualTable, table_id)
            assert retained is not None
            assert retained.owner_user_id == target.id
            assert retained.organization_id == organization_id
            assert (
                await db.scalar(
                    select(Organization.created_by_user_id).where(
                        Organization.id == organization_id
                    )
                )
                == target.id
            )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.action == "admin.user.delete")
            )
            == 0
        )
        assert (
            await db.scalar(select(func.count()).select_from(Notification)) == before_notifications
        )

    monkeypatch.setattr(NotificationService, "security_event", original)
    async with world.runtime() as db:
        await admin_users.delete_user(
            target.id,
            request,
            actor,
            db,
            UserService(db),
            reason="RLS integration removal",
        )
    async with world.maintenance() as db:
        assert await db.get(User, target.id) is None
        assert not list(
            await db.scalars(
                select(VirtualTableRecord.id).where(VirtualTableRecord.id.in_(private_records))
            )
        )
        for table_id, organization_id, heir in retained_tables:
            retained = await db.get(VirtualTable, table_id)
            assert retained is not None
            # Tables remain in the organization with a cleared user owner;
            # the shared organization's creator is handed to its other Owner.
            assert retained.owner_user_id is None
            assert retained.organization_id == organization_id
            assert (
                await db.scalar(
                    select(Organization.created_by_user_id).where(
                        Organization.id == organization_id
                    )
                )
                == heir
            )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.action == "admin.user.delete")
            )
            == 1
        )


async def test_retention_uses_a_new_tenant_transaction_for_each_organization(rls_world):
    from datetime import UTC, datetime

    from app.db.models.virtual_table import VirtualTableRecordHistory
    from app.services.retention import RetentionService

    world = rls_world
    async with world.maintenance() as db:
        await db.execute(
            update(VirtualTableRecordHistory).values(created_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
        await db.commit()
    async with world.runtime() as db:
        with pytest.raises(UnsafeTableDatabaseRoleError):
            await RetentionService(db).sweep()
        await db.rollback()
        await RetentionService(db).sweep(commit_each=True)
    async with world.maintenance() as db:
        assert await db.scalar(select(func.count()).select_from(VirtualTableRecordHistory)) == 0
        await RetentionService(db).sweep()


async def test_maintenance_login_cannot_mask_its_privilege_by_selecting_runtime_role(rls_world):
    world = rls_world
    async with world.migration() as db:
        await db.execute(text(f'GRANT "{world.runtime_role}" TO "{world.maintenance_role}"'))
        await db.commit()
    async with world.maintenance() as db:
        await db.execute(text(f'SET LOCAL ROLE "{world.runtime_role}"'))
        with pytest.raises(UnsafeTableDatabaseRoleError):
            await table_rls.require_table_connection_role(db)


async def test_workflow_table_node_uses_its_persisted_principal_in_a_fresh_runtime_transaction(
    rls_world, monkeypatch
):
    from app.services.workflow_execution import context
    from app.workflows.contracts.results import Completed
    from app.workflows.nodes import _tables

    world = rls_world
    first = world.tenants[0]

    @asynccontextmanager
    async def worker_context():
        async with world.runtime() as db:
            yield db
            await db.commit()

    monkeypatch.setattr(_tables, "get_worker_db_context", worker_context)
    dispatch = context.DispatchContext(
        organization_id=first.organization.id,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=first.ctx,
        resumed_agent_run_id=None,
        idempotency_key="tenant-node-attempt",
    )
    writes = []

    async def create(service, auth):
        assert auth is dispatch.auth
        assert await service.db.scalar(
            text("SELECT current_setting('t3os.organization_id', true)")
        ) == str(first.organization.id)
        result = await service.create_record(
            auth,
            first.target.id,
            RecordCreate(values={cid(first.target, "Name"): "workflow"}),
            operation_key=_tables.operation_key(),
        )
        writes.append(result)
        return Completed[_tables.TableRecordOutput](
            output=_tables.record_output(first.target, result.record, created=result.created)
        )

    with context.dispatching_as(dispatch):
        first_result = await _tables.with_service(create)
        replay = await _tables.with_service(create)
    assert isinstance(first_result, Completed)
    assert isinstance(replay, Completed)
    assert len(writes) == 2
    assert not writes[0].replayed
    assert writes[1].replayed
    assert replay.output.record_id == first_result.output.record_id
