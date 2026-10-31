"""The entry migration reverses cleanly and refuses incompatible published history."""

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = pytest.mark.anyio


def _roundtrip(session: Session) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0242_workflow_entry_triggers.py"
    spec = importlib.util.spec_from_file_location("workflow_entry_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = session.connection()
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        inspector = inspect(connection)
        assert "entry_node_id" not in {
            column["name"] for column in inspector.get_columns("workflow_runs")
        }
        migration.upgrade()
        inspector = inspect(connection)
        assert "entry_node_id" in {
            column["name"] for column in inspector.get_columns("workflow_runs")
        }
        assert any(
            constraint["column_names"] == ["workflow_id", "adapter"]
            for constraint in inspector.get_unique_constraints("workflow_exposures")
        )


async def test_workflow_entry_migration_roundtrip(db: AsyncSession) -> None:
    await db.run_sync(_roundtrip)
