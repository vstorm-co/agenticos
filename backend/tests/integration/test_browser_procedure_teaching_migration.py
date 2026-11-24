"""Native schema parity, interrupted indexes, and preserved procedure-teaching evidence."""

import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingPolicy
from app.db.models.skill_proposal import SkillProposal
from tests.integration.test_personal_coding_accounts import organization, person

pytestmark = [pytest.mark.anyio, pytest.mark.security]
_ROOT = Path(__file__).parents[2]
_PATH = _ROOT / "alembic/versions/0344_browser_procedure_teaching.py"
_SPEC = importlib.util.spec_from_file_location("browser_procedure_teaching_migration", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)


@pytest.fixture
async def engine(scratch_engine):
    """These tests downgrade and re-upgrade the schema, so they run on a database of their own.

    The worker's shared database is what every other test on that worker builds on;
    one left downgraded by a failed or cancelled migration test broke them (#238).
    """
    return scratch_engine


def migrate(connection, direction):
    context = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with context.begin_transaction(), Operations.context(context):
        getattr(_MIGRATION, direction)()


async def step(connection, direction):
    await connection.commit()
    await connection.run_sync(lambda sync: migrate(sync, direction))


def schema(connection):
    inspector = inspect(connection)
    tables = {
        table: {
            "columns": sorted(
                (item["name"], str(item["type"]), item["nullable"], item["default"])
                for item in inspector.get_columns(table)
            ),
            "primary_key": inspector.get_pk_constraint(table),
            "unique": sorted(
                inspector.get_unique_constraints(table), key=lambda item: item["name"]
            ),
            "foreign_keys": sorted(
                inspector.get_foreign_keys(table), key=lambda item: item["name"]
            ),
            "checks": sorted(inspector.get_check_constraints(table), key=lambda item: item["name"]),
            "indexes": sorted(inspector.get_indexes(table), key=lambda item: item["name"]),
        }
        for table in (*_MIGRATION._TABLES, "skill_proposals", "skill_versions")
    }
    return tables


async def seed(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        user = await person(db)
        org = await organization(db, user)
        proposal = SkillProposal(
            organization_id=org.id,
            name="legacy-procedure",
            description="Existing proposal",
            content="Keep this exact legacy body.",
            resources={},
            source="workspace",
        )
        db.add(proposal)
        await db.commit()
        return org.id, proposal.id


async def test_procedure_teaching_follows_the_published_t3_teaching_chain():
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    pairs = {
        "0345_credential_continuations": "0344_browser_procedure_teaching",
        "0344_browser_procedure_teaching": "0343_workflow_media_operations",
        "0343_workflow_media_operations": "0342_browser_credential_plans",
        "0342_browser_credential_plans": "0341_room_task_handoffs",
        "0341_room_task_handoffs": "0340_browser_teaching_review",
        "0340_browser_teaching_review": "0339_browser_teaching_capture",
        "0339_browser_teaching_capture": "0338_message_reply_excerpt",
    }
    for revision, parent in pairs.items():
        assert scripts.get_revision(revision).down_revision == parent
    assert scripts.get_revision("0331_merge_core_accounts").down_revision == "0330_role_navigation"
    assert scripts.get_revision("0333_room_threads").down_revision == "0332_merge_t3_pools_v1761"
    assert scripts.get_revision("0332_merge_t3_pools_v1761").down_revision == (
        "0331_merge_t3_rooms_and_v1761",
        "0326_provider_account_pools",
    )
    assert scripts.get_revision("0336_merge_core_v1761").down_revision == "0331_merge_core_accounts"
    assert scripts.get_heads() == ["0349_personal_work_context"]


async def test_upgrade_downgrade_preserves_existing_proposals_and_matches_every_model_column(
    engine,
):
    _, proposal = await seed(engine)
    query = text("SELECT to_jsonb(p) - 'browser_procedure' FROM skill_proposals p WHERE id = :id")
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        before = await connection.scalar(query, {"id": proposal})
        await step(connection, "downgrade")
        try:
            assert not await connection.run_sync(
                lambda sync: inspect(sync).has_table("browser_procedure_teaching_sessions")
            )
            assert await connection.run_sync(
                lambda sync: inspect(sync).has_table("browser_teaching_sessions")
            )
            assert await connection.scalar(query, {"id": proposal}) == before
        finally:
            await step(connection, "upgrade")
        assert await connection.scalar(query, {"id": proposal}) == before
        assert await connection.run_sync(schema) == expected


async def test_retry_keeps_exact_metadata_columns_and_standalone_indexes(engine):
    await seed(engine)
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(
            text("ALTER TABLE skill_proposals ADD COLUMN browser_procedure jsonb")
        )
        await connection.execute(
            text("ALTER TABLE skill_versions ADD COLUMN browser_procedure jsonb")
        )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_skill_proposals_tenant ON skill_proposals (id, organization_id)"
            )
        )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_skill_proposal_browser_source ON skill_proposals "
                "(organization_id, (browser_procedure->>'source_session_id')) WHERE browser_procedure IS NOT NULL"
            )
        )
        oids = await connection.execute(
            text(
                "SELECT 'uq_skill_proposals_tenant'::regclass::oid, 'uq_skill_proposal_browser_source'::regclass::oid"
            )
        )
        before = tuple(oids.one())
        await step(connection, "upgrade")
        oids = await connection.execute(
            text(
                "SELECT 'uq_skill_proposals_tenant'::regclass::oid, 'uq_skill_proposal_browser_source'::regclass::oid"
            )
        )
        assert tuple(oids.one()) == before


@pytest.mark.parametrize("kind", ["table", "nonunique", "wrong_expression", "wrong_predicate"])
async def test_conflicting_index_shapes_are_refused_without_replacing_them(engine, kind):
    await seed(engine)
    ddl = {
        "table": "CREATE TABLE uq_skill_proposal_browser_source (id uuid)",
        "nonunique": "CREATE INDEX uq_skill_proposal_browser_source ON skill_proposals (organization_id)",
        "wrong_expression": "CREATE UNIQUE INDEX uq_skill_proposal_browser_source ON skill_proposals (organization_id, (browser_procedure->>'wrong')) WHERE browser_procedure IS NOT NULL",
        "wrong_predicate": "CREATE UNIQUE INDEX uq_skill_proposal_browser_source ON skill_proposals (organization_id, (browser_procedure->>'source_session_id'))",
    }
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(
            text("ALTER TABLE skill_proposals ADD COLUMN browser_procedure jsonb")
        )
        await connection.execute(text(ddl[kind]))
        await connection.commit()
        before = await connection.scalar(
            text("SELECT 'uq_skill_proposal_browser_source'::regclass::oid")
        )
        try:
            with pytest.raises(RuntimeError, match="expected standalone teaching index"):
                await step(connection, "upgrade")
            assert (
                await connection.scalar(
                    text("SELECT 'uq_skill_proposal_browser_source'::regclass::oid")
                )
                == before
            )
            assert not await connection.run_sync(
                lambda sync: inspect(sync).has_table("browser_procedure_teaching_sessions")
            )
            assert await connection.run_sync(
                lambda sync: inspect(sync).has_table("browser_teaching_sessions")
            )
        finally:
            await connection.rollback()
            await connection.execute(
                text(
                    "DROP TABLE uq_skill_proposal_browser_source"
                    if kind == "table"
                    else "DROP INDEX uq_skill_proposal_browser_source"
                )
            )
            await step(connection, "upgrade")


async def test_unexpected_existing_metadata_column_is_preserved_and_refused(engine):
    _, proposal = await seed(engine)
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(
            text("ALTER TABLE skill_proposals ADD COLUMN browser_procedure text")
        )
        await connection.execute(
            text("UPDATE skill_proposals SET browser_procedure = 'existing data' WHERE id = :id"),
            {"id": proposal},
        )
        await connection.commit()
        try:
            with pytest.raises(RuntimeError, match="unexpected shape"):
                await step(connection, "upgrade")
            assert (
                await connection.scalar(
                    text("SELECT browser_procedure FROM skill_proposals WHERE id = :id"),
                    {"id": proposal},
                )
                == "existing data"
            )
        finally:
            await connection.rollback()
            await connection.execute(
                text("ALTER TABLE skill_proposals DROP COLUMN browser_procedure")
            )
            await step(connection, "upgrade")


async def wait_until_building(connection, pid, task):
    """Return once PostgreSQL reports the index build; surface the build's own failure first.

    The build parks behind the writer's open transaction, so it cannot finish before
    the test releases that writer. Waiting on the build task itself, rather than on a
    deadline, means a slow runner delays this loop instead of failing it.
    """
    while not task.done():
        if await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index WHERE pid = :pid)"),
            {"pid": pid},
        ):
            return
        await asyncio.sleep(0.05)
    await task
    pytest.fail("The source-index build finished before the writer released it")


@pytest.mark.parametrize("cancelled", [False, True])
async def test_active_source_index_build_is_preserved_and_exact_failed_build_is_recoverable(
    engine, cancelled
):
    _, proposal = await seed(engine)
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(
            text("ALTER TABLE skill_proposals ADD COLUMN browser_procedure jsonb")
        )
        await connection.commit()
        started, pid = asyncio.Event(), []
        async with engine.connect() as writer:
            await writer.execute(
                text("UPDATE skill_proposals SET content = content WHERE id = :id"),
                {"id": proposal},
            )

            async def build():
                async with engine.connect() as raw:
                    builder = await raw.execution_options(isolation_level="AUTOCOMMIT")
                    pid.append(await builder.scalar(text("SELECT pg_backend_pid()")))
                    started.set()
                    await builder.execute(
                        text(
                            "CREATE UNIQUE INDEX CONCURRENTLY uq_skill_proposal_browser_source ON skill_proposals "
                            "(organization_id, (browser_procedure->>'source_session_id')) WHERE browser_procedure IS NOT NULL"
                        )
                    )

            task = asyncio.create_task(build())
            try:
                await started.wait()
                await wait_until_building(connection, pid[0], task)
                with pytest.raises(RuntimeError, match="being built"):
                    await step(connection, "upgrade")
                if cancelled:
                    # The server cancels the parked build, which leaves the same invalid
                    # index a statement timeout does, without waiting out a clock.
                    assert await connection.scalar(
                        text("SELECT pg_cancel_backend(:pid)"), {"pid": pid[0]}
                    )
                    with pytest.raises(DBAPIError):
                        await task
                    assert await connection.scalar(
                        text(
                            "SELECT NOT indisvalid FROM pg_index WHERE indexrelid = 'uq_skill_proposal_browser_source'::regclass"
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
                "SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid = 'uq_skill_proposal_browser_source'::regclass"
            )
        )


@pytest.mark.parametrize("evidence", ["policy", "proposal"])
async def test_retained_consent_or_procedure_metadata_refuses_destructive_downgrade(
    engine, evidence
):
    org, proposal = await seed(engine)
    async with AsyncSession(engine) as db:
        if evidence == "policy":
            db.add(
                BrowserProcedureTeachingPolicy(
                    organization_id=org, enabled=False, generation=uuid4()
                )
            )
        else:
            await db.execute(
                text(
                    'UPDATE skill_proposals SET browser_procedure = \'{"source_session_id":"preserved"}\'::jsonb WHERE id = :id'
                ),
                {"id": proposal},
            )
        await db.flush()
        connection = await db.connection()
        before = await connection.run_sync(schema)
        with pytest.raises(RuntimeError, match="retains teaching decisions"):
            await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
        assert await connection.run_sync(schema) == before
