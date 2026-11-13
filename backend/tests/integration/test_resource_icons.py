"""Presentation edits persist without revising executable resource definitions."""

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.schemas.virtual_table import TableCreate, TableUpdate
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate
from app.services.virtual_tables import VirtualTableService
from app.services.workflow_registry import WorkflowRegistryService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


async def test_table_icon_changes_preserve_the_schema(db: AsyncSession) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = VirtualTableService(db)
    table = await service.create_table(ctx, TableCreate(name="Report", icon="chart"))
    assert table.icon == "chart"
    changed = await service.update_table(ctx, table.id, TableUpdate(icon="calendar"))
    assert changed.icon == "calendar"
    assert changed.schema_version == table.schema_version
    renamed = await service.update_table(ctx, table.id, TableUpdate(name="Calendar"))
    assert renamed.icon == "calendar"
    reset = await service.update_table(ctx, table.id, TableUpdate(icon=None))
    assert reset.icon is None
    assert reset.schema_version == table.schema_version


async def test_workflow_icon_changes_preserve_the_graph_revision(db: AsyncSession) -> None:
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    ctx = ctx_for(owner, org)
    service = WorkflowRegistryService(db)
    workflow = await service.create(ctx, WorkflowCreate(name="Report", icon="chart"))
    assert workflow.icon == "chart"
    before = await service.get(ctx, workflow.id)
    changed = await service.update(ctx, workflow.id, WorkflowUpdate(icon="calendar"))
    assert changed.icon == "calendar"
    assert changed.draft_revision == workflow.draft_revision
    assert changed.draft_graph == before.draft_graph
    renamed = await service.update(ctx, workflow.id, WorkflowUpdate(name="Calendar"))
    assert renamed.icon == "calendar"
    reset = await service.update(ctx, workflow.id, WorkflowUpdate(icon=None))
    assert reset.icon is None
    assert reset.draft_revision == workflow.draft_revision


def _roundtrip(session: Session) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0321_resource_icons.py"
    spec = importlib.util.spec_from_file_location("resource_icon_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = session.connection()
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        for table in ("virtual_tables", "workflows"):
            assert "icon" not in {
                column["name"] for column in inspect(connection).get_columns(table)
            }
        migration.upgrade()
        for table in ("virtual_tables", "workflows"):
            column = next(c for c in inspect(connection).get_columns(table) if c["name"] == "icon")
            assert column["nullable"] is True
            assert column["type"].length == 32


async def test_resource_icon_migration_roundtrip(db: AsyncSession) -> None:
    await db.run_sync(_roundtrip)
