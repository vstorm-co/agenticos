"""Native sources join watches and routine policies without widening authority."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.services import routine_sources, watches
from app.services.integrations import IntegrationService
from app.services.mcp_connection import McpConnectionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def source(ctx, **changes):
    return McpConnection(
        **(
            {
                "id": uuid4(),
                "scope": "user",
                "user_id": ctx.user_id,
                "purpose": "account",
                "catalog_key": "odoo",
                "auth_type": "odoo",
                "is_enabled": True,
                "account_source_organization_id": ctx.organization_id,
                "name": "ERP",
                "label": "ERP",
                "url": "https://erp.example.com",
                "authorization_generation": uuid4(),
                "granted_scopes": ["odoo:read"],
            }
            | changes
        )
    )


async def test_watch_connection_choices_keep_accounts_in_the_active_organization(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    native = source(ctx)
    mcp = source(ctx, purpose="mcp", catalog_key="github")
    disabled = source(ctx, is_enabled=False)
    monkeypatch.setattr(
        watches.mcp_connection_repo, "list_for_user", AsyncMock(return_value=([mcp, disabled], 2))
    )
    monkeypatch.setattr(
        McpConnectionService,
        "list_accounts",
        AsyncMock(
            side_effect=lambda *args, **kwargs: [native] if kwargs["provider"] == "odoo" else []
        ),
    )
    result = await watches.WatchService(AsyncMock()).connections(ctx)
    assert [item.id for item in result] == [mcp.id, native.id]
    assert result[0].products == []
    assert set(result[1].products) == {
        "odoo_contacts",
        "odoo_crm",
        "odoo_sales",
        "odoo_accounting",
        "odoo_inventory",
        "odoo_projects",
    }
    monkeypatch.setattr(watches.mcp_connection_repo, "get_by_id", AsyncMock(return_value=native))
    assert (
        await watches.WatchService(AsyncMock())._own_connection(
            ctx.user_id, native.id, ctx.organization_id
        )
        is native
    )
    with pytest.raises(BadRequestError):
        await watches.WatchService(AsyncMock())._own_connection(ctx.user_id, native.id, uuid4())


@pytest.mark.parametrize("available,client_bound", [(False, False), (True, False), (True, True)])
async def test_routine_review_records_native_account_and_client_generations(
    monkeypatch, available, client_bound
):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    native = source(ctx)
    spec = AgentSpec(name="Monitor", capabilities=[CapabilityBindingSpec(id="odoo_contacts")])
    trigger = AgentTrigger(
        id=uuid4(),
        agent_id=uuid4(),
        organization_id=ctx.organization_id,
        created_by_user_id=ctx.user_id,
        trigger_type="event",
        event_source="odoo",
        event_config={"product_id": "odoo_contacts"},
        pinned_version_id=None,
        environment_id=None,
        project_id=None,
        connection_id=native.id,
        runs_as_creator=True,
    )
    service = routine_sources.RoutineSourceService(AsyncMock())
    service.agents.get_runnable_spec = AsyncMock(return_value=(MagicMock(), spec, uuid4()))
    lookup = AsyncMock(
        return_value=native,
        side_effect=None if available else AuthorizationError(message="not shared"),
    )
    monkeypatch.setattr(IntegrationService, "binding_account", lookup)
    monkeypatch.setattr(
        routine_sources.mcp_connection_repo, "get_by_id", AsyncMock(return_value=native)
    )
    secret_id, generation = uuid4(), uuid4()
    monkeypatch.setattr(
        "app.services.mcp_connection.account_client_identity",
        lambda row: (ctx.organization_id, secret_id, generation) if client_bound else None,
    )
    snapshot = await service.snapshot(ctx, trigger)
    assert snapshot.policy.mirage_accounts[native.id] == native.authorization_generation
    assert snapshot.policy.input_connection_id == native.id
    assert (secret_id in snapshot.policy.secret_sources) is client_bound
    assert bool(snapshot.unavailable) is not available


@pytest.mark.parametrize("enabled,available", [(True, True), (True, False), (False, True)])
async def test_native_portal_choices_are_filtered_by_binding_authority(
    monkeypatch, enabled, available
):
    from datetime import UTC, datetime

    from app.services import agent_trigger as trigger_module

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    row = SimpleNamespace(
        id=uuid4(),
        purpose="account",
        name="ERP",
        label="ERP",
        catalog_key="odoo",
        account_email="company",
        granted_scopes=["odoo:read"],
        scope="user",
        account_authorized=True,
        authorization_expired=False,
        created_at=datetime.now(UTC),
        is_enabled=enabled,
        auth_type="odoo",
        last_status="ok",
    )
    service = trigger_module.AgentTriggerService(AsyncMock())
    service.connections.get_org_portal_grant = AsyncMock(return_value=None)
    service.connections.list_accounts = AsyncMock(
        side_effect=lambda *args, **kwargs: (
            [row] if kwargs["provider"] == "odoo" and not kwargs["for_organization"] else []
        )
    )
    service.connections.get_polled_connection = AsyncMock(
        return_value=row,
        side_effect=None if available else AuthorizationError(message="not shared"),
    )
    monkeypatch.setattr(
        trigger_module.organization_secret_repo,
        "list_org_visible_by_kind",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        trigger_module.mcp_connection_repo,
        "get_org_scoped_by_catalog_key",
        AsyncMock(return_value=None),
    )
    result = await service.list_portals(ctx)
    portal = next(item for item in result if item.key == "odoo_contacts")
    assert [item.id for item in portal.connection_choices] == (
        [row.id] if enabled and available else []
    )
    assert portal.connection_id == (row.id if enabled and available else None)


@pytest.mark.parametrize("available,enabled", [(False, True), (True, True), (False, False)])
async def test_agent_publication_checks_org_account_binding_access(monkeypatch, available, enabled):
    from app.services.agent_registry import AgentRegistryService

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    check = AsyncMock(
        return_value=object(),
        side_effect=None if available else AuthorizationError(message="not shared"),
    )
    monkeypatch.setattr(IntegrationService, "binding_account", check)
    binding = CapabilityBindingSpec(
        id="odoo_contacts",
        enabled=enabled,
        config={"account": "organization", "connection_id": str(uuid4())},
    )
    result = await AgentRegistryService(AsyncMock())._binding_problems(ctx, binding)
    assert bool(result.messages) is (enabled and not available)
    assert check.await_count == int(enabled)
