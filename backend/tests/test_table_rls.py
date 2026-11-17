"""Configuration refusal paths complement the real PostgreSQL enforcement tests."""

from contextlib import asynccontextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

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


async def test_policy_installation_never_stamps_or_drops_an_unowned_policy(monkeypatch):
    async def policies(_db, names):
        return [
            {
                "tablename": names[0],
                "policyname": policy,
                "qual": "stored-expression-tree",
                "check": "stored-expression-tree",
                "permissive": policy == table_rls.ACCESS_POLICY,
                "cmd": "*",
                "roles": [0],
                "server_version": "160006",
            }
            for policy in (table_rls.GUARD_POLICY, table_rls.ACCESS_POLICY)
        ] + [{"policyname": "operator_owned_policy"}]

    monkeypatch.setattr(table_rls, "_policies", policies)
    db = AsyncMock()
    await table_rls.install_table_policies(db)
    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    comments = [statement for statement in statements if statement.startswith("COMMENT ON POLICY")]
    assert len(comments) == 2 * len(table_rls.TABLE_OBJECTS)
    assert all("t3os.tables.rls.v1.pg16:" in statement for statement in comments)
    assert not any("operator_owned_policy" in statement for statement in statements)


async def test_admin_revoked_between_connections_cannot_enter_maintenance_work(monkeypatch):
    from app.core.exceptions import AuthorizationError
    from app.services import account_maintenance as boundary

    runtime, selected = AsyncMock(), AsyncMock()

    @asynccontextmanager
    async def maintenance(db):
        assert db is runtime
        yield selected

    actor = SimpleNamespace(id=uuid4(), is_active=True, is_app_admin=True)
    current = SimpleNamespace(id=actor.id, is_active=True, is_app_admin=False)
    reread = AsyncMock(return_value=current)
    monkeypatch.setattr(boundary, "get_table_maintenance_context", maintenance)
    monkeypatch.setattr(boundary.user_repo, "get_by_id", reread)
    privileged_work = AsyncMock()
    with pytest.raises(AuthorizationError, match="administrator required"):
        async with account_maintenance(runtime, actor, require_admin=True) as db:
            await privileged_work(db)
    reread.assert_awaited_once_with(selected, actor.id)
    privileged_work.assert_not_awaited()


@pytest.mark.parametrize("resource_key", ["table", "table_record"])
async def test_sharing_refuses_partial_rls_before_reading_grants_or_member_names(
    monkeypatch, resource_key
):
    from app.core.permissions import AuthContext, OrgRoleName, Perm
    from app.services import sharing
    from app.services.access import ResourceType

    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(relname="virtual_tables", relrowsecurity=True, relforcerowsecurity=True)
    ]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        get_transaction=lambda: None,
        no_autoflush=nullcontext(),
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.MEMBER)
    resource = SimpleNamespace(id=uuid4(), organization_id=ctx.organization_id)
    listed, emails, groups = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(sharing.resource_grant_repo, "list_for_resource", listed)
    monkeypatch.setattr(sharing.member_repo, "get_emails_for_users", emails)
    monkeypatch.setattr(sharing.group_repo, "get_names", groups)
    with pytest.raises(table_rls.TableRlsConfigurationError, match="partially"):
        await sharing.SharingService(db).get_sharing(
            ctx,
            resource,
            resource_type=ResourceType(resource_key, Perm.TABLES_VIEW, Perm.TABLES_EDIT),
        )
    db.execute.assert_awaited_once()
    assert db.execute.await_args.args[1] == {"objects": list(table_rls.TABLE_OBJECTS)}
    listed.assert_not_awaited()
    emails.assert_not_awaited()
    groups.assert_not_awaited()
