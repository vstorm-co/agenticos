"""Historical policy SQL, disabled rollout state and non-destructive orphan refusal."""

import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import table_rls
from tests.integration.virtual_table_support import make_org, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _migration():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0328_tables_tenant_rls.py"
    spec = importlib.util.spec_from_file_location("tables_rls_historical_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(connection, module, operation):
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, operation)()


async def _installed_column(connection):
    return await connection.scalar(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'resource_grants' "
            "AND column_name = 'table_subject_user_id'"
        )
    )


async def test_historical_sql_installs_exact_policies_without_enabling_them(engine):
    module = _migration()
    async with engine.begin() as connection:
        await connection.run_sync(_apply, module, "downgrade")
        assert not await _installed_column(connection)
        await connection.run_sync(_apply, module, "upgrade")
        assert await _installed_column(connection) == 1
    async with async_sessionmaker(engine)() as db:
        assert not (await table_rls.table_rls_state(db)).active
        await table_rls.require_table_policy_inventory(db)
        assert module._POLICIES == table_rls.TENANT_POLICIES


async def test_sync_migration_fingerprints_are_accepted_by_the_async_runtime(engine):
    module = _migration()

    def install_with_sync_driver() -> None:
        synchronous = create_engine(engine.url.set(drivername="postgresql+psycopg2"))
        try:
            with synchronous.begin() as connection:
                _apply(connection, module, "downgrade")
                _apply(connection, module, "upgrade")
        finally:
            synchronous.dispose()

    # Production Alembic and runtime use different drivers. Internal PostgreSQL
    # types must not give them different policy representations or fingerprints.
    await asyncio.to_thread(install_with_sync_driver)
    async with async_sessionmaker(engine)() as db:
        await table_rls.require_table_policy_inventory(db)


async def test_orphan_tables_grants_abort_before_schema_mutation_and_other_namespaces_survive(
    engine,
):
    module = _migration()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner = await make_user(db)
        outsider = await make_user(db)
        organization = await make_org(db, owner=owner)
        await db.commit()
    orphan_id, unrelated_id = uuid4(), uuid4()
    async with engine.begin() as connection:
        await connection.run_sync(_apply, module, "downgrade")
        for grant_id, resource_type in ((orphan_id, "table_record"), (unrelated_id, "workflow")):
            await connection.execute(
                text(
                    "INSERT INTO resource_grants "
                    "(id, organization_id, subject_user_id, resource_type, resource_id, level) "
                    "VALUES (:id, :org, :person, :type, :resource, 'read')"
                ),
                {
                    "id": grant_id,
                    "org": organization.id,
                    "person": outsider.id,
                    "type": resource_type,
                    "resource": uuid4(),
                },
            )
        with pytest.raises(RuntimeError, match="orphan_user_grants=1"):
            await connection.run_sync(_apply, module, "upgrade")
        assert not await _installed_column(connection)
        assert await connection.scalar(text("SELECT count(*) FROM resource_grants")) == 2
        # An explicit repair performed by this test's owner; the migration never
        # removes or silently ignores the invalid share.
        await connection.execute(
            text("DELETE FROM resource_grants WHERE id = :id"), {"id": orphan_id}
        )
        await connection.run_sync(_apply, module, "upgrade")
        assert (
            await connection.scalar(
                text("SELECT id FROM resource_grants WHERE id = :id"), {"id": unrelated_id}
            )
            == unrelated_id
        )


async def test_migration_refuses_active_enforcement_and_unknown_policy_ownership(engine):
    module = _migration()
    async with engine.begin() as connection:
        await connection.run_sync(_apply, module, "downgrade")
        await connection.run_sync(_apply, module, "upgrade")
        await connection.execute(text("ALTER TABLE virtual_tables ENABLE ROW LEVEL SECURITY"))
        with pytest.raises(RuntimeError, match="Tables RLS is active"):
            await connection.run_sync(_apply, module, "downgrade")
        assert await _installed_column(connection) == 1
        await connection.execute(text("ALTER TABLE virtual_tables DISABLE ROW LEVEL SECURITY"))
        await connection.run_sync(_apply, module, "downgrade")
        await connection.execute(
            text("CREATE POLICY unrelated_policy ON virtual_tables USING (true)")
        )
        with pytest.raises(RuntimeError, match="Unexpected Tables policies"):
            await connection.run_sync(_apply, module, "upgrade")
        assert not await _installed_column(connection)
        await connection.execute(text("DROP POLICY unrelated_policy ON virtual_tables"))
        await connection.run_sync(_apply, module, "upgrade")
