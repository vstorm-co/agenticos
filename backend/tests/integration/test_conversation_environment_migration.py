"""The new ownership journal round-trips and cannot be downgraded while live."""

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


async def test_environment_journal_migration_matches_models_and_guards_destructive_downgrade(
    db: AsyncSession,
):
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/0376_conversation_environments.py"
    )
    spec = importlib.util.spec_from_file_location("conversation_environments_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0375_merge_service_connections"
    tables = {"conversation_environments", "conversation_environment_drivers"}

    # A later migration owns a foreign key into this journal. Reverse that
    # dependency before exercising this older revision in isolation.
    owner_path = path.with_name("0383_environment_project_files.py")
    owner_spec = importlib.util.spec_from_file_location(
        "environment_project_files_owner", owner_path
    )
    assert owner_spec is not None and owner_spec.loader is not None
    owner = importlib.util.module_from_spec(owner_spec)
    owner_spec.loader.exec_module(owner)

    layout_spec = importlib.util.spec_from_file_location(
        "environment_layout_driver", path.with_name("0384_environment_layout_driver.py")
    )
    assert layout_spec is not None and layout_spec.loader is not None
    layout = importlib.util.module_from_spec(layout_spec)
    layout_spec.loader.exec_module(layout)

    def cycle(session: Session):
        connection = session.connection()
        context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
        with Operations.context(context):
            layout.downgrade()
            owner.downgrade()
            migration.downgrade()
            assert not tables.intersection(inspect(connection).get_table_names())
            migration.upgrade()
            assert tables.issubset(inspect(connection).get_table_names())

            def included(obj, _name, kind, _reflected, _compare_to):
                if kind == "table":
                    return obj.name in tables
                return obj.table.name in tables

            diff = compare_metadata(
                MigrationContext.configure(connection, opts={"include_object": included}),
                Base.metadata,
            )
            assert diff == []
            identity, org_scope = uuid4(), uuid4()
            connection.execute(
                text(
                    "INSERT INTO conversation_environments (id,vault_organization_id,kind,execution_target,session_lifetime,idle_seconds,state,fingerprint,revision,provisioning_attempt,expires_at) VALUES (:id,:org,'browser','agent','conversation',900,'starting',:fingerprint,1,0,now()+interval '15 minutes')"
                ),
                {"id": identity, "org": org_scope, "fingerprint": "a" * 64},
            )
            with pytest.raises(RuntimeError, match="drain their cleanup jobs"):
                migration.downgrade()
            connection.execute(
                text(
                    "UPDATE conversation_environments SET state='expired',resource_ciphertext='sealed-handle',resource_key_version=1 WHERE id=:id"
                ),
                {"id": identity},
            )
            with pytest.raises(RuntimeError, match="drain their cleanup jobs"):
                migration.downgrade()
            connection.execute(
                text(
                    "UPDATE conversation_environments SET resource_ciphertext=NULL,resource_key_version=NULL WHERE id=:id"
                ),
                {"id": identity},
            )
            migration.downgrade()
            assert not tables.intersection(inspect(connection).get_table_names())
            migration.upgrade()
            owner.upgrade()
            layout.upgrade()

    await db.run_sync(cycle)
