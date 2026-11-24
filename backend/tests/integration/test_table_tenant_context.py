"""Real PostgreSQL RLS, WITH CHECK, savepoints and pooled transaction reuse."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.table_tenant import (
    ORGANIZATION_POLICY,
    TableTenantContextError,
    UnsafeTableDatabaseRoleError,
    bind_table_tenant,
    require_non_bypass_table_role,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass(frozen=True)
class Probe:
    role: str
    first_org: UUID
    second_org: UUID

    def context(self, organization_id: UUID) -> AuthContext:
        return AuthContext(user_id=uuid4(), organization_id=organization_id, role="viewer")


@pytest.fixture
async def tenant_probe(engine: AsyncEngine) -> AsyncGenerator[Probe]:
    probe = Probe(f"table_rls_test_{uuid4().hex}", uuid4(), uuid4())
    async with engine.begin() as connection:
        await connection.execute(
            text(f'CREATE ROLE "{probe.role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
        )
        await connection.execute(
            text(
                "CREATE TABLE table_tenant_probe "
                "(id uuid PRIMARY KEY, organization_id uuid NOT NULL, label text NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO table_tenant_probe VALUES "
                "(:first_id, :first_org, 'first'), (:second_id, :second_org, 'second')"
            ),
            {
                "first_id": uuid4(),
                "second_id": uuid4(),
                "first_org": probe.first_org,
                "second_org": probe.second_org,
            },
        )
        await connection.execute(text("ALTER TABLE table_tenant_probe ENABLE ROW LEVEL SECURITY"))
        await connection.execute(text("ALTER TABLE table_tenant_probe FORCE ROW LEVEL SECURITY"))
        await connection.execute(
            text(
                "CREATE POLICY table_tenant_scope ON table_tenant_probe "
                f"USING ({ORGANIZATION_POLICY}) WITH CHECK ({ORGANIZATION_POLICY})"
            )
        )
        await connection.execute(
            text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON table_tenant_probe TO "{probe.role}"')
        )
    try:
        yield probe
    finally:
        # Only this test's table and generated role; no existing role is altered.
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS table_tenant_probe"))
            await connection.execute(text(f'DROP ROLE IF EXISTS "{probe.role}"'))


async def _runtime(db: AsyncSession, probe: Probe) -> None:
    await db.execute(text(f'SET LOCAL ROLE "{probe.role}"'))
    await require_non_bypass_table_role(db)


async def _labels(db: AsyncSession) -> list[str]:
    # Deliberately no organization WHERE clause: PostgreSQL must enforce it.
    return list(await db.scalars(text("SELECT label FROM table_tenant_probe ORDER BY label")))


async def test_binding_can_start_a_transaction_without_committing_it(
    engine: AsyncEngine, tenant_probe: Probe
):
    probe = tenant_probe
    async with async_sessionmaker(engine)() as db:
        assert not db.in_transaction()
        await bind_table_tenant(db, probe.context(probe.first_org))
        assert db.in_transaction()
        await _runtime(db, probe)
        assert await _labels(db) == ["first"]
        await db.rollback()
        await _runtime(db, probe)
        assert await _labels(db) == []


async def test_rls_denies_missing_context_and_cross_tenant_reads_and_writes(
    engine: AsyncEngine, tenant_probe: Probe
):
    probe = tenant_probe
    async with async_sessionmaker(engine)() as db:
        await _runtime(db, probe)
        assert await _labels(db) == []
        with pytest.raises(DBAPIError, match="row-level security"):
            async with db.begin_nested():
                await db.execute(
                    text("INSERT INTO table_tenant_probe VALUES (:id, :org, 'missing')"),
                    {"id": uuid4(), "org": probe.first_org},
                )
        await bind_table_tenant(db, probe.context(probe.first_org))
        assert await _labels(db) == ["first"]
        for statement, parameters in (
            (
                "INSERT INTO table_tenant_probe VALUES (:id, :org, 'foreign')",
                {"id": uuid4(), "org": probe.second_org},
            ),
            (
                "UPDATE table_tenant_probe SET organization_id = :org",
                {"org": probe.second_org},
            ),
        ):
            with pytest.raises(DBAPIError, match="row-level security"):
                async with db.begin_nested():
                    await db.execute(text(statement), parameters)
        result = await db.execute(
            text("DELETE FROM table_tenant_probe WHERE organization_id = :org"),
            {"org": probe.second_org},
        )
        assert result.rowcount == 0
        with pytest.raises(TableTenantContextError, match="Cannot switch"):
            await bind_table_tenant(db, probe.context(probe.second_org))
        assert await _labels(db) == ["first"]


async def test_commit_and_rollback_clear_context_on_a_reused_session_and_connection(
    engine: AsyncEngine, tenant_probe: Probe
):
    probe = tenant_probe
    async with async_sessionmaker(engine)() as db:
        await _runtime(db, probe)
        backend = await db.scalar(text("SELECT pg_backend_pid()"))
        await bind_table_tenant(db, probe.context(probe.first_org))
        assert await _labels(db) == ["first"]
        await db.commit()

        await _runtime(db, probe)
        assert await db.scalar(text("SELECT pg_backend_pid()")) == backend
        assert await _labels(db) == []
        await bind_table_tenant(db, probe.context(probe.second_org))
        assert await _labels(db) == ["second"]
        await db.rollback()

        await _runtime(db, probe)
        assert await db.scalar(text("SELECT pg_backend_pid()")) == backend
        assert await _labels(db) == []


async def test_a_savepoint_cannot_erase_or_switch_the_outer_tenant(
    engine: AsyncEngine, tenant_probe: Probe
):
    probe = tenant_probe
    async with async_sessionmaker(engine)() as db:
        await _runtime(db, probe)
        async with db.begin_nested():
            with pytest.raises(TableTenantContextError, match="before opening a savepoint"):
                await bind_table_tenant(db, probe.context(probe.first_org))
        await bind_table_tenant(db, probe.context(probe.first_org))
        with pytest.raises(RuntimeError, match="test rollback"):
            async with db.begin_nested():
                await bind_table_tenant(db, probe.context(probe.first_org))
                with pytest.raises(TableTenantContextError, match="Cannot switch"):
                    await bind_table_tenant(db, probe.context(probe.second_org))
                raise RuntimeError("test rollback")
        assert await _labels(db) == ["first"]


async def test_force_rls_also_applies_to_a_non_bypass_table_owner(
    engine: AsyncEngine, tenant_probe: Probe
):
    probe = tenant_probe
    async with engine.begin() as connection:
        await connection.execute(text(f'GRANT CREATE ON SCHEMA public TO "{probe.role}"'))
        await connection.execute(text(f'ALTER TABLE table_tenant_probe OWNER TO "{probe.role}"'))
        await connection.execute(text(f'REVOKE CREATE ON SCHEMA public FROM "{probe.role}"'))
    async with async_sessionmaker(engine)() as db:
        await _runtime(db, probe)
        assert await _labels(db) == []
        await bind_table_tenant(db, probe.context(probe.first_org))
        assert await _labels(db) == ["first"]


async def test_privileged_migration_credentials_are_refused_as_runtime_credentials(
    engine: AsyncEngine,
):
    async with async_sessionmaker(engine)() as db:
        privileged = await db.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        if not privileged:
            pytest.skip("The disposable migration connection is already unprivileged")
        with pytest.raises(UnsafeTableDatabaseRoleError, match="SUPERUSER or BYPASSRLS"):
            await require_non_bypass_table_role(db)
