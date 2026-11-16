"""0338 preserves manual envelopes and refuses removal of protected-session evidence."""

import pytest
from sqlalchemy import inspect, text

from app.agents.browser_sign_ins import SignIn
from app.core.vault import VaultScope, seal
from app.repositories import browser_sign_in as sign_ins
from tests.integration.test_browser_credential_continuations import continuation as continuation
from tests.integration.test_browser_credential_migration import load_revision, migrate
from tests.integration.test_browser_credential_plans import browser as browser

pytestmark = [pytest.mark.anyio, pytest.mark.security]
_MIGRATION = load_revision("0338_credential_continuations")


def schema(connection):
    inspector = inspect(connection)
    return {
        table: {
            "columns": sorted(
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table)
            ),
            "primary": inspector.get_pk_constraint(table),
            "foreign": sorted(inspector.get_foreign_keys(table), key=lambda item: item["name"]),
            "unique": sorted(
                inspector.get_unique_constraints(table), key=lambda item: item["name"]
            ),
            "checks": sorted(inspector.get_check_constraints(table), key=lambda item: item["name"]),
            "indexes": sorted(inspector.get_indexes(table), key=lambda item: item["name"]),
        }
        for table in ("browser_sign_ins", "browser_credential_continuations")
    }


async def test_native_up_down_preserves_legacy_envelopes_and_exact_model_parity(engine, browser):
    b = browser
    legacy = SignIn(
        site="legacy.example.com",
        origin="https://legacy.example.com",
        cookies=[],
        local_storage={"synthetic": "private"},
    )
    sealed = seal(legacy.model_dump_json(), scope=VaultScope.user(b.owner.id))
    row = await sign_ins.save(
        b.db,
        organization_id=b.org.id,
        user_id=b.owner.id,
        site=legacy.site,
        sealed_state=sealed.ciphertext,
        key_version=sealed.key_version,
    )
    await b.db.commit()
    async with engine.connect() as connection:
        expected = await connection.run_sync(schema)
        query = text(
            "SELECT to_jsonb(s) - 'protection_kind' FROM browser_sign_ins s WHERE id = :id"
        )
        original = await connection.scalar(query, {"id": row.id})
        await connection.run_sync(lambda sync: migrate(sync, "downgrade", _MIGRATION))
        assert await connection.scalar(query, {"id": row.id}) == original
        assert not await connection.run_sync(
            lambda sync: inspect(sync).has_table("browser_credential_continuations")
        )
        await connection.run_sync(lambda sync: migrate(sync, "upgrade", _MIGRATION))
        assert await connection.scalar(query, {"id": row.id}) == original
        assert await connection.run_sync(schema) == expected
        assert (
            await connection.scalar(
                text("SELECT protection_kind FROM browser_sign_ins WHERE id=:id"), {"id": row.id}
            )
            == "manual"
        )
        await connection.commit()


@pytest.mark.parametrize("evidence", ["requested", "claimed", "unknown", "continued", "saved_only"])
async def test_used_continuation_or_saved_taint_refuses_downgrade_without_cascade(
    continuation, evidence
):
    f, b = continuation, continuation.browser
    if evidence == "requested":
        await f.request()
    else:
        claim = await f.claimed(keep=True)
        if evidence == "unknown":
            from app.core.browser_continuation import BrowserContinuationReason

            await f.service.refuse(
                b.identity, claim.id, BrowserContinuationReason.PROVIDER_UNAVAILABLE
            )
        elif evidence in ("continued", "saved_only"):
            await f.service.finish(b.ctx, b.identity, claim, f.state(claim))
            if evidence == "saved_only":
                await b.db.execute(
                    text("DELETE FROM browser_credential_continuations WHERE id=:id"),
                    {"id": claim.id},
                )
    connection = await b.db.connection()
    before = await connection.run_sync(schema)
    with pytest.raises(RuntimeError, match="protected continuation or saved-session evidence"):
        await connection.run_sync(lambda sync: migrate(sync, "downgrade", _MIGRATION))
    assert await connection.run_sync(schema) == before
