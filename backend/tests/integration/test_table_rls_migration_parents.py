"""Frozen migration refuses legacy cross-tenant parents before changing schema or data."""

import pytest
from sqlalchemy import Text, cast, func, select, table, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import table_rls
from tests.integration.table_rls_support import make_rls_world
from tests.integration.test_table_rls_migration import _apply, _installed_column, _migration

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _snapshot(connection: AsyncConnection) -> dict[str, list[object]]:
    """Capture every protected row, including historical and unrelated grant data."""
    result: dict[str, list[object]] = {}
    for name in table_rls.TABLE_OBJECTS:
        # A whole-row value also works before the generated grant column exists.
        value = func.to_jsonb(table(name, schema="public").table_valued())
        rows = await connection.scalars(select(value).order_by(cast(value, Text)))
        result[name] = list(rows)
    return result


@pytest.mark.parametrize("parent", ["trigger-table", "admission-trigger", "admission-outbox"])
async def test_frozen_migration_refuses_cross_tenant_parents_without_mutation(
    engine, monkeypatch, parent
):
    module = _migration()
    async with make_rls_world(engine, monkeypatch, activate=False) as world:
        first, second = world.tenants
        async with engine.connect() as connection:
            original = await _snapshot(connection)
            await connection.run_sync(_apply, module, "downgrade")
            assert not await _installed_column(connection)
            if parent == "trigger-table":
                statement = (
                    "UPDATE virtual_table_triggers SET table_id = :other_table WHERE id = :trigger"
                )
            elif parent == "admission-trigger":
                statement = (
                    "UPDATE table_trigger_admissions SET trigger_id = :other_trigger "
                    "WHERE trigger_id = :trigger"
                )
            else:
                statement = (
                    "UPDATE table_trigger_admissions SET outbox_event_id = "
                    "(SELECT id FROM virtual_table_outbox WHERE record_id = :other_record) "
                    "WHERE trigger_id = :trigger"
                )
            await connection.execute(
                text(statement),
                {
                    "trigger": first.trigger_id,
                    "other_trigger": second.trigger_id,
                    "other_table": second.source.id,
                    "other_record": second.source_record,
                },
            )
            before = await _snapshot(connection)
            mismatch = (
                "triggers=1, admissions=0"
                if parent == "trigger-table"
                else "triggers=0, admissions=1"
            )
            with pytest.raises(RuntimeError, match=mismatch):
                await connection.run_sync(_apply, module, "upgrade")

            assert not await _installed_column(connection)
            assert await _snapshot(connection) == before
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_catalog.pg_policy AS policy "
                        "JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid "
                        "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' AND relation.relname = ANY(:objects)"
                    ),
                    {"objects": list(table_rls.TABLE_OBJECTS)},
                )
                == 0
            )

            # Even the deliberately corrupt fixture and its preparatory downgrade
            # roll back together; the migration must not commit an implicit repair.
            await connection.rollback()
            assert await _installed_column(connection) == 1
            assert await _snapshot(connection) == original
