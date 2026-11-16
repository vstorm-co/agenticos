"""Configuration refusal paths complement the real PostgreSQL enforcement tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import table_rls
from app.services.account_maintenance import account_maintenance

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("enabled,forced", [(False, False), (True, False), (False, True)])
async def test_catalog_records_actual_enable_and_force_flags(enabled, forced):
    row = SimpleNamespace(
        relname="virtual_tables", relrowsecurity=enabled, relforcerowsecurity=forced
    )
    result = MagicMock()
    result.all.return_value = [row]
    # A non-Mock session-shaped object deliberately exercises the actual reader,
    # instead of the common mock-session preactivation catalog fixture.
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    state = await table_rls.table_rls_state(db)
    assert state.present == frozenset({"virtual_tables"})
    assert state.enabled == (state.present if enabled else frozenset())
    assert state.forced == (state.present if forced else frozenset())
    if enabled or forced:
        with pytest.raises(table_rls.TableRlsConfigurationError, match="partially"):
            _ = state.active
    else:
        assert not state.active


async def test_inventory_requires_every_migrated_object_before_any_policy_mutation(monkeypatch):
    missing = "virtual_table_record_links"
    state = table_rls.TableRlsState(
        frozenset(table_rls.TABLE_OBJECTS) - {missing}, frozenset(), frozenset()
    )
    monkeypatch.setattr(table_rls, "table_rls_state", AsyncMock(return_value=state))
    db = AsyncMock()
    with pytest.raises(table_rls.TableRlsConfigurationError, match=missing):
        await table_rls.require_table_policy_inventory(db)
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        {"permissive": True},
        {"cmd": "r"},
        {"roles": [42]},
        {"qual": None},
        {"check": None},
        {"stamp": "stale.pg15:value"},
    ],
)
async def test_inventory_refuses_invalid_guard_metadata(monkeypatch, change):
    state = table_rls.TableRlsState(frozenset(table_rls.TABLE_OBJECTS), frozenset(), frozenset())
    monkeypatch.setattr(table_rls, "table_rls_state", AsyncMock(return_value=state))
    rows = []
    for name in table_rls.TABLE_OBJECTS:
        for policy in (table_rls.GUARD_POLICY, table_rls.ACCESS_POLICY):
            row = {
                "tablename": name,
                "policyname": policy,
                "qual": "stored-expression-tree",
                "check": "stored-expression-tree",
                "permissive": policy == table_rls.ACCESS_POLICY,
                "cmd": "*",
                "roles": [0],
                "server_version": "160006",
                "using_expression": "true",
                "check_expression": "true",
            }
            row["stamp"] = table_rls.policy_fingerprint(row)
            rows.append(row)
    rows[0].update(change)
    monkeypatch.setattr(table_rls, "_policies", AsyncMock(return_value=rows))
    with pytest.raises(table_rls.TableRlsConfigurationError, match="definition changed"):
        await table_rls.require_table_policy_inventory(AsyncMock())


async def test_disabled_actor_is_refused_before_selecting_a_maintenance_connection(monkeypatch):
    from app.core.exceptions import AuthenticationError
    from app.services import account_maintenance as boundary

    opener = MagicMock()
    monkeypatch.setattr(boundary, "get_table_maintenance_context", opener)
    actor = SimpleNamespace(is_active=False, is_app_admin=True)
    with pytest.raises(AuthenticationError, match="disabled"):
        async with account_maintenance(AsyncMock(), actor, require_admin=True):
            pytest.fail("disabled actor must never reach the selected connection")
    opener.assert_not_called()
