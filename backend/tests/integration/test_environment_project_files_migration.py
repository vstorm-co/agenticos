"""Environment mount ownership is separate, constrained and safely reversible."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.base import Base

pytestmark = pytest.mark.anyio


async def test_environment_project_mount_migration_round_trips_without_model_drift(
    db: AsyncSession,
):
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/0383_environment_project_files.py"
    )
    spec = importlib.util.spec_from_file_location("environment_project_files_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0382_merge_live_environments"

    def cycle(session: Session):
        connection = session.connection()
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
            columns = {
                item["name"]: item
                for item in inspect(connection).get_columns("project_filesystem_leases")
            }
            assert "environment_id" not in columns
            assert columns["run_id"]["nullable"] is False
            migration.upgrade()
            columns = {
                item["name"]: item
                for item in inspect(connection).get_columns("project_filesystem_leases")
            }
            assert columns["run_id"]["nullable"] is True
            assert "environment_id" in columns
            checks = inspect(connection).get_check_constraints("project_filesystem_leases")
            assert any(item["name"] == "ck_project_filesystem_lease_owner" for item in checks)

            def included(obj, _name, kind, _reflected, _compare_to):
                return (
                    obj.name == "project_filesystem_leases"
                    if kind == "table"
                    else obj.table.name == "project_filesystem_leases"
                )

            assert (
                compare_metadata(
                    MigrationContext.configure(connection, opts={"include_object": included}),
                    Base.metadata,
                )
                == []
            )

            # Even an orphaned resource journal must remain decodable by the
            # cleanup worker; a rollback cannot discard its new sealed schema.
            orphan_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO conversation_environments "
                    "(id,vault_organization_id,kind,execution_target,session_lifetime,idle_seconds,"
                    "state,fingerprint,revision,provisioning_attempt,expires_at,resource_ciphertext,resource_key_version) "
                    "VALUES (:id,:org,'desktop','agent','conversation',900,'expired',:fp,1,0,now(),:handle,1)"
                ),
                {
                    "id": orphan_id,
                    "org": uuid4(),
                    "fp": "a" * 64,
                    "handle": "sealed-new-desktop-handle",
                },
            )
            with pytest.raises(RuntimeError, match="drain their cleanup jobs"):
                migration.downgrade()
            connection.execute(
                text(
                    "UPDATE conversation_environments SET resource_ciphertext=NULL,resource_key_version=NULL WHERE id=:id"
                ),
                {"id": orphan_id},
            )
            migration.downgrade()
            migration.upgrade()

    await db.run_sync(cycle)


async def test_database_requires_exactly_one_lease_owner(db, monkeypatch):
    from sqlalchemy import select, update
    from sqlalchemy.exc import IntegrityError

    from app.db.models.project_filesystem import ProjectFilesystemLease
    from tests.integration.test_agent_attention import _run
    from tests.integration.test_conversation_environment_project_filesystem import admit, prepared

    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    run = await _run(db, case.agent, conversation_id=case.conversation.id, user_id=case.user.id)
    for values in ({"run_id": run.id}, {"environment_id": None}):
        with pytest.raises(IntegrityError, match="ck_project_filesystem_lease_owner"):
            async with db.begin_nested():
                await db.execute(
                    update(ProjectFilesystemLease)
                    .where(ProjectFilesystemLease.id == lease.id)
                    .values(**values)
                )
    row = await db.scalar(
        select(ProjectFilesystemLease).where(ProjectFilesystemLease.id == lease.id)
    )
    assert row is not None
    assert row.environment_id == case.row.id
    assert row.run_id is None
