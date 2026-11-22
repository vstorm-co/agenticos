"""Revision 0342 preserves published history, legacy bytes and used credential evidence."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db.base import Base
from app.schemas.browser_credential import BrowserCredentialPolicyWrite
from app.services.browser_credentials import BrowserCredentialPolicyService
from tests.integration.test_browser_credential_plans import BrowserFixture
from tests.integration.test_browser_credential_plans import browser as browser

pytestmark = [pytest.mark.anyio, pytest.mark.security]
_ROOT = Path(__file__).parents[2]


def load_revision(stem: str) -> ModuleType:
    path = _ROOT / "alembic" / "versions" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"credential_fixture_{stem}", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


_MIGRATION = load_revision("0342_browser_credential_plans")
_DESCENDANTS = (
    load_revision("0343_workflow_media_operations"),
    load_revision("0344_browser_procedure_teaching"),
    load_revision("0345_credential_continuations"),
)
assert tuple(migration.down_revision for migration in _DESCENDANTS[:2]) == (
    _MIGRATION.revision,
    _DESCENDANTS[0].revision,
)
assert _DESCENDANTS[2].down_revision == "0344_browser_procedure_teaching"
_TABLES = (
    "browser_credential_policies",
    "browser_credential_agent_grants",
    "browser_credential_member_grants",
    "browser_credential_plans",
)


def migrate(connection, direction, migration=_MIGRATION):
    ctx = MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    with ctx.begin_transaction(), Operations.context(ctx):
        getattr(migration, direction)()


async def step(connection, direction):
    # The create_all fixture includes later consumers of 0342's tenant keys.
    # Exercise their real downgrade/upgrade in dependency order; a direct 0342
    # downgrade is retained below only for its own used-evidence refusal test.
    migrations = (
        (*reversed(_DESCENDANTS), _MIGRATION)
        if direction == "downgrade"
        else (_MIGRATION, *_DESCENDANTS)
    )
    # Concurrent tenant-key construction must begin outside the introspection
    # transaction, so Alembic owns the transaction it commits for autocommit_block.
    for migration in migrations:
        await connection.commit()
        await connection.run_sync(
            lambda sync, revision=migration: migrate(sync, direction, revision)
        )


def schema(connection):
    inspector = inspect(connection)
    result = {}
    for table in _TABLES:
        result[table] = {
            "columns": sorted(
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table)
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
    result["parent_keys"] = {
        table: [item for item in inspector.get_unique_constraints(table) if item["name"] == name]
        for table, name in _MIGRATION._KEYS
    }
    return result


async def test_chain_rebases_browser_credential_plans_after_the_current_t3_head():
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert (
        scripts.get_revision("0341_room_task_handoffs").down_revision
        == "0340_browser_teaching_review"
    )
    assert (
        scripts.get_revision("0342_browser_credential_plans").down_revision
        == "0341_room_task_handoffs"
    )
    assert (
        scripts.get_revision("0343_workflow_media_operations").down_revision
        == "0342_browser_credential_plans"
    )
    assert (
        scripts.get_revision("0344_browser_procedure_teaching").down_revision
        == "0343_workflow_media_operations"
    )
    assert (
        scripts.get_revision("0345_credential_continuations").down_revision
        == "0344_browser_procedure_teaching"
    )
    assert scripts.get_heads() == ["0347_network_connections"]
    assert scripts.get_revision("0333_room_threads").down_revision == "0332_merge_t3_pools_v1761"
    assert scripts.get_revision("0332_merge_t3_pools_v1761").down_revision == (
        "0331_merge_t3_rooms_and_v1761",
        "0326_provider_account_pools",
    )
    assert (
        scripts.get_revision("0326_provider_account_pools").down_revision
        == "0325_merge_t3_rooms_v173"
    )


async def test_native_concurrent_upgrade_preserves_legacy_rows_and_matches_models(
    engine, browser: BrowserFixture
):
    b = browser
    await b.db.commit()
    query = text("SELECT to_jsonb(s) FROM organization_secrets s WHERE id = :id")
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        before = await connection.scalar(query, {"id": b.secret.id})
        await step(connection, "downgrade")
        try:
            assert await connection.scalar(query, {"id": b.secret.id}) == before
            assert not await connection.run_sync(
                lambda sync: inspect(sync).has_table("browser_credential_plans")
            )
        finally:
            await step(connection, "upgrade")
        assert await connection.scalar(query, {"id": b.secret.id}) == before
        assert await connection.run_sync(schema) == expected


async def test_retry_reuses_only_an_exact_valid_standalone_tenant_index(
    engine, browser: BrowserFixture
):
    await browser.db.commit()
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(
            text("CREATE UNIQUE INDEX uq_agents_org_id ON agents (organization_id, id)")
        )
        before = await connection.scalar(text("SELECT 'uq_agents_org_id'::regclass::oid"))
        await step(connection, "upgrade")
        assert await connection.scalar(text("SELECT 'uq_agents_org_id'::regclass::oid")) == before
        keys = await connection.run_sync(
            lambda sync: inspect(sync).get_unique_constraints("agents")
        )
        assert any(
            item["name"] == "uq_agents_org_id" and item["column_names"] == ["organization_id", "id"]
            for item in keys
        )


async def test_an_unexpected_existing_object_is_refused_without_dropping_or_rebuilding_it(
    engine, browser: BrowserFixture
):
    await browser.db.commit()
    async with engine.connect() as connection:
        await step(connection, "downgrade")
        await connection.execute(text("CREATE INDEX uq_agents_org_id ON agents (id)"))
        await connection.commit()
        before = await connection.scalar(
            text("SELECT pg_get_indexdef('uq_agents_org_id'::regclass)")
        )
        try:
            with pytest.raises(RuntimeError, match="expected standalone tenant key"):
                await step(connection, "upgrade")
            assert (
                await connection.scalar(
                    text("SELECT pg_get_indexdef('uq_agents_org_id'::regclass)")
                )
                == before
            )
        finally:
            await connection.rollback()
            await connection.execute(text("DROP INDEX uq_agents_org_id"))
            await step(connection, "upgrade")


@pytest.mark.parametrize("evidence", ["policy", "requested", "filled", "unknown"])
async def test_used_policy_or_plan_blocks_destructive_rollback(browser: BrowserFixture, evidence):
    b = browser
    if evidence == "policy":
        await BrowserCredentialPolicyService(b.db).update(
            b.ctx,
            b.secret.id,
            BrowserCredentialPolicyWrite(
                generation=b.secret.authorization_generation,
                mode="shared",
                agent_ids=(b.agent.id,),
                member_ids=(b.owner.id,),
            ),
        )
    elif evidence == "requested":
        await b.service.request(b.ctx, b.run.id, b.request())
    else:
        claim = await b.claimed()
        await b.service.finish(b.identity, claim, filled=evidence == "filled")
    connection = await b.db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="policy or plan evidence"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade"))
    assert await connection.run_sync(schema) == before
