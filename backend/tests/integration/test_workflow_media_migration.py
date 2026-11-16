"""Real lineage indexes, immutable predecessor history and preservation on rollback."""

import asyncio
import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.db.base import Base
from app.repositories import workflow_media_operation as media_repo
from tests.integration.workflow_media_support import seed_media

pytestmark = [pytest.mark.anyio, pytest.mark.security]
_ROOT = Path(__file__).parents[2]
_PATH = _ROOT / "alembic/versions/0334_workflow_media_operations.py"
_SPEC = importlib.util.spec_from_file_location("workflow_media_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


def migrate(connection, direction):
    ctx = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with ctx.begin_transaction(), Operations.context(ctx):
        getattr(_MIGRATION, direction)()


async def step(connection, direction):
    await connection.commit()
    await connection.run_sync(lambda sync: migrate(sync, direction))


def schema(connection):
    inspector = inspect(connection)
    table = "workflow_media_operations"
    return {
        "columns": sorted(
            (item["name"], str(item["type"]), item["nullable"], item["default"])
            for item in inspector.get_columns(table)
        ),
        "primary_key": inspector.get_pk_constraint(table),
        "unique": sorted(inspector.get_unique_constraints(table), key=lambda item: item["name"]),
        "foreign_keys": sorted(inspector.get_foreign_keys(table), key=lambda item: item["name"]),
        "checks": sorted(inspector.get_check_constraints(table), key=lambda item: item["name"]),
        "indexes": sorted(inspector.get_indexes(table), key=lambda item: item["name"]),
        "parent_keys": {
            parent: [
                item for item in inspector.get_unique_constraints(parent) if item["name"] == name
            ]
            for parent, name, _columns in _MIGRATION._KEYS
        },
    }


async def test_media_has_the_real_browser_predecessor_and_preserves_published_accounts():
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert (
        scripts.get_revision("0334_workflow_media_operations").down_revision
        == "0333_browser_credential_plans"
    )
    assert (
        scripts.get_revision("0333_browser_credential_plans").down_revision
        == "0332_room_task_handoffs"
    )
    assert (
        scripts.get_revision("0332_room_task_handoffs").down_revision == "0331_merge_core_accounts"
    )
    assert scripts.get_revision("0331_merge_core_accounts").down_revision == "0330_role_navigation"
    assert scripts.get_revision("0333_room_threads").down_revision == "0332_merge_t3_pools_v1761"
    assert scripts.get_revision("0332_merge_t3_pools_v1761").down_revision == (
        "0331_merge_t3_rooms_and_v1761",
        "0326_provider_account_pools",
    )
    assert (
        scripts.get_revision("0326_provider_account_pools").down_revision
        == "0325_merge_t3_rooms_v173"
    )


async def test_concurrent_upgrade_preserves_the_run_and_matches_the_model_schema(engine):
    rows = await seed_media(engine)
    query = text("SELECT to_jsonb(r) FROM workflow_runs r WHERE id = :id")
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        before = await connection.scalar(query, {"id": rows.seeded.run.id})
        await step(connection, "downgrade")
        try:
            assert not await connection.run_sync(
                lambda sync: inspect(sync).has_table("workflow_media_operations")
            )
            assert await connection.scalar(query, {"id": rows.seeded.run.id}) == before
        finally:
            await step(connection, "upgrade")
        assert await connection.scalar(query, {"id": rows.seeded.run.id}) == before
        assert await connection.run_sync(schema) == expected


async def test_retry_reuses_the_exact_standalone_lineage_index(engine):
    await seed_media(engine)
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_workflow_runs_org_id ON workflow_runs (organization_id, id)"
            )
        )
        before = await connection.scalar(text("SELECT 'uq_workflow_runs_org_id'::regclass::oid"))
        await step(connection, "upgrade")
        assert (
            await connection.scalar(text("SELECT 'uq_workflow_runs_org_id'::regclass::oid"))
            == before
        )


@pytest.mark.parametrize("kind", ["table", "nonunique", "descending"])
async def test_conflicting_objects_are_preserved_and_refused_before_any_schema_change(engine, kind):
    await seed_media(engine)
    ddl = {
        "table": "CREATE TABLE uq_workflow_runs_org_id (id uuid)",
        "nonunique": "CREATE INDEX uq_workflow_runs_org_id ON workflow_runs (id)",
        "descending": "CREATE UNIQUE INDEX uq_workflow_runs_org_id ON workflow_runs (organization_id DESC, id)",
    }
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(text(ddl[kind]))
        await connection.commit()
        before = await connection.scalar(text("SELECT 'uq_workflow_runs_org_id'::regclass::oid"))
        try:
            with pytest.raises(RuntimeError, match="expected standalone lineage key"):
                await step(connection, "upgrade")
            assert (
                await connection.scalar(text("SELECT 'uq_workflow_runs_org_id'::regclass::oid"))
                == before
            )
            assert not await connection.run_sync(
                lambda sync: inspect(sync).has_table("workflow_media_operations")
            )
        finally:
            await connection.rollback()
            await connection.execute(
                text(
                    "DROP TABLE uq_workflow_runs_org_id"
                    if kind == "table"
                    else "DROP INDEX uq_workflow_runs_org_id"
                )
            )
            await step(connection, "upgrade")


@pytest.mark.parametrize("times_out", [False, True])
async def test_active_build_is_left_alone_and_an_exact_failed_build_can_be_retried(
    engine, times_out
):
    rows = await seed_media(engine)
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        builder_started = asyncio.Event()
        pid = []
        async with engine.connect() as writer:
            await writer.execute(
                text("UPDATE workflow_runs SET status = status WHERE id = :id"),
                {"id": rows.seeded.run.id},
            )

            async def build():
                async with engine.connect() as raw:
                    builder = await raw.execution_options(isolation_level="AUTOCOMMIT")
                    await builder.execute(
                        text(
                            "SET statement_timeout = '1500ms'"
                            if times_out
                            else "SET statement_timeout = '10000ms'"
                        )
                    )
                    pid.append(await builder.scalar(text("SELECT pg_backend_pid()")))
                    builder_started.set()
                    await builder.execute(
                        text(
                            "CREATE UNIQUE INDEX CONCURRENTLY uq_workflow_runs_org_id ON workflow_runs (organization_id, id)"
                        )
                    )

            task = asyncio.create_task(build())
            try:
                await builder_started.wait()
                async with asyncio.timeout(5):
                    # The PostgreSQL process exposes progress through its view,
                    # independently of this task's command-submission event.
                    for _ in range(250):
                        if await connection.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index WHERE pid = :pid)"
                            ),
                            {"pid": pid[0]},
                        ):
                            break
                        await asyncio.sleep(0.02)
                    else:
                        pytest.fail("The owned index build did not enter its progress view")
                with pytest.raises(RuntimeError, match="being built"):
                    await step(connection, "upgrade")
                if times_out:
                    with pytest.raises(DBAPIError):
                        await task
                    assert await connection.scalar(
                        text(
                            "SELECT NOT indisvalid FROM pg_index WHERE indexrelid = 'uq_workflow_runs_org_id'::regclass"
                        )
                    )
            finally:
                await writer.rollback()
                if not task.done():
                    await task
                await connection.rollback()
                await step(connection, "upgrade")
        assert await connection.scalar(
            text(
                "SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid = 'uq_workflow_runs_org_id'::regclass"
            )
        )


@pytest.mark.parametrize("phase", ["prepared", "unknown", "failed"])
async def test_any_media_evidence_refuses_destructive_downgrade(engine, phase):
    rows = await seed_media(engine)
    async with rows.seeded.factory() as db:
        operation = await media_repo.create(db, rows.admission())
        await media_repo.change(
            db, operation.id, organization_id=rows.seeded.org.id, values={"phase": phase}
        )
        connection = await db.connection()
        before = await connection.run_sync(schema)
        with pytest.raises(RuntimeError, match="retains media receipts and holds"):
            await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
        assert await connection.run_sync(schema) == before
