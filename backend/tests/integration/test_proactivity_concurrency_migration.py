"""Legacy queued watches and nightly jobs acquire the same member budget lane."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.anyio


async def test_backfill_groups_one_members_work_and_refuses_active_unkeyed_jobs(
    db: AsyncSession,
) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0285_member_proactivity.py"
    spec = importlib.util.spec_from_file_location("member_concurrency", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    await db.execute(
        text(
            "CREATE TEMP TABLE background_jobs (kind text, status text, organization_id uuid, payload jsonb, concurrency_key text) ON COMMIT DROP"
        )
    )
    await db.execute(
        text(
            "CREATE TEMP TABLE watches (id uuid, organization_id uuid, user_id uuid) ON COMMIT DROP"
        )
    )
    org, user, watch = uuid4(), uuid4(), uuid4()
    await db.execute(
        text("INSERT INTO watches VALUES (:id, :org, :user)"),
        {"id": watch, "org": org, "user": user},
    )
    await db.execute(
        text(
            "INSERT INTO background_jobs VALUES ('think-for-person', 'running', :org, jsonb_build_object('user_id', CAST(:user AS text)), NULL), ('look-through-watch', 'queued', :org, jsonb_build_object('watch_id', CAST(:watch AS text)), NULL)"
        ),
        {"org": org, "user": str(user), "watch": str(watch)},
    )

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    connection = await db.connection()
    with pytest.raises(RuntimeError, match="Drain proactive workers"):
        await connection.run_sync(upgrade)
    await db.execute(text("UPDATE background_jobs SET status = 'queued'"))
    await connection.run_sync(upgrade)
    keys = list(await db.scalars(text("SELECT concurrency_key FROM background_jobs")))
    assert keys == [f"proactivity:{org}:{user}"] * 2

    def downgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

    await connection.run_sync(downgrade)
    cleared = list(await db.scalars(text("SELECT concurrency_key FROM background_jobs")))
    assert cleared == [None, None]
    await connection.run_sync(upgrade)
    restored = list(await db.scalars(text("SELECT concurrency_key FROM background_jobs")))
    assert restored == keys
