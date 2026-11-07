"""Organization credentials follow the binding author's current resource access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.services.integrations import authority

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_binding_requires_resource_access_and_accepts_an_explicit_grant(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    row = McpConnection(id=uuid4(), organization_id=ctx.organization_id, scope="org")
    access = AsyncMock(return_value=False)
    monkeypatch.setattr(authority, "resolve_access", access)
    with pytest.raises(AuthorizationError, match="not available"):
        await authority.authorize(AsyncMock(), row, ctx)
    access.return_value = True
    await authority.authorize(AsyncMock(), row, ctx)
    assert access.await_args.args[1:3] == (ctx, row)


@pytest.mark.parametrize("kind", ["agent", "workflow"])
@pytest.mark.parametrize("published", [False, True])
async def test_runtime_resolves_the_frozen_versions_author_not_the_consumer(
    monkeypatch, kind, published
):
    consumer, author, org, run_id, version_id = (uuid4() for _ in range(5))
    run = SimpleNamespace(
        agent_version_id=version_id if published else None,
        user_id=author,
        workflow_version_id=version_id if published else None,
        execution_principal_user_id=author,
    )
    repository = authority.agent_run_repo if kind == "agent" else authority.workflow_run_repo
    versions = authority.agent_repo if kind == "agent" else authority.workflow_repo
    monkeypatch.setattr(repository, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(
        versions,
        "get_version",
        AsyncMock(return_value=SimpleNamespace(published_by_user_id=author)),
    )
    member = AsyncMock(
        return_value=AuthContext(user_id=author, organization_id=org, role="builder")
    )
    monkeypatch.setattr(authority, "decider_context", member)
    result = await authority.run_author(
        AsyncMock(),
        organization_id=org,
        person_id=consumer,
        agent_run_id=run_id if kind == "agent" else None,
        workflow_run_id=run_id if kind == "workflow" else None,
    )
    assert result.user_id == author and result.role == "builder"
    assert member.await_args.kwargs == {"organization_id": org, "user_id": author}


@pytest.mark.parametrize("kind", ["agent", "workflow"])
@pytest.mark.parametrize("missing", ["run", "version", "member"])
async def test_removed_run_version_or_membership_cannot_keep_a_shared_credential(
    monkeypatch, kind, missing
):
    org, run_id = uuid4(), uuid4()
    run = SimpleNamespace(agent_version_id=uuid4(), workflow_version_id=uuid4())
    repository = authority.agent_run_repo if kind == "agent" else authority.workflow_run_repo
    versions = authority.agent_repo if kind == "agent" else authority.workflow_repo
    monkeypatch.setattr(
        repository, "get_run", AsyncMock(return_value=None if missing == "run" else run)
    )
    monkeypatch.setattr(
        versions,
        "get_version",
        AsyncMock(
            return_value=None
            if missing == "version"
            else SimpleNamespace(published_by_user_id=uuid4())
        ),
    )
    monkeypatch.setattr(authority, "decider_context", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError):
        await authority.run_author(
            AsyncMock(),
            organization_id=org,
            person_id=uuid4(),
            agent_run_id=run_id if kind == "agent" else None,
            workflow_run_id=run_id if kind == "workflow" else None,
        )


async def test_a_direct_internal_call_still_requires_a_live_binding_author(monkeypatch):
    org, person = uuid4(), uuid4()
    member = AsyncMock(return_value=AuthContext(user_id=person, organization_id=org, role="owner"))
    monkeypatch.setattr(authority, "decider_context", member)
    result = await authority.run_author(
        AsyncMock(), organization_id=org, person_id=person, agent_run_id=None, workflow_run_id=None
    )
    assert result.user_id == person
    with pytest.raises(AuthorizationError):
        await authority.run_author(
            AsyncMock(),
            organization_id=org,
            person_id=None,
            agent_run_id=None,
            workflow_run_id=None,
        )


@pytest.mark.parametrize(
    "provider,product,scopes,method,channels,expected",
    [
        ("google", "unknown", [], "oauth", None, False),
        ("slack", "gmail", ["channels:history"], "bearer", None, False),
        (
            "google",
            "google_sheets",
            ["https://www.googleapis.com/auth/gmail.readonly"],
            "oauth",
            None,
            False,
        ),
        ("slack", "slack", ["channels:history"], "bearer", None, True),
        ("slack", "slack", ["groups:history"], "bearer", ("Cprivate",), True),
        ("slack", "slack", ["chat:write"], "bearer", None, False),
        ("microsoft", "teams", ["Chat.Read"], "oauth", (), True),
        ("microsoft", "teams", ["Chat.Read.All"], "application", (), True),
        ("microsoft", "teams", ["ChannelMessage.Read.All"], "oauth", None, True),
        ("microsoft", "teams", ["ChannelMessage.Read.All"], "oauth", ("channel/t/c",), True),
        ("microsoft", "teams", ["ChannelMessage.Read.All"], "oauth", ("chat",), False),
        ("microsoft", "teams", ["Chat.Read"], "oauth", ("channel/t/c",), False),
        (
            "microsoft",
            "teams",
            ["ChannelMessage.Read.All", "Chat.Read"],
            "oauth",
            ("channel/t/c", "chat"),
            True,
        ),
        ("microsoft", "outlook_mail", ["Mail.Read"], "application", None, True),
    ],
)
def test_a_trigger_feed_requires_the_products_actual_read_scope(
    provider, product, scopes, method, channels, expected
):
    from app.services.integrations import can_read_feed

    row = McpConnection(catalog_key=provider, auth_type=method, granted_scopes=scopes)
    assert can_read_feed(row, product, channels) is expected


async def test_odoo_shared_tools_use_authority_before_unsealing_the_key(monkeypatch):
    from app.core.odoo_credential import OdooCredential
    from app.services.integrations import AccountSelection, IntegrationService, odoo
    from app.services.mcp_connection import McpConnectionService

    org, person, identifier = uuid4(), uuid4(), uuid4()
    row = McpConnection(
        id=identifier,
        scope="org",
        organization_id=org,
        catalog_key="odoo",
        auth_type="odoo",
        granted_scopes=["odoo:read"],
    )
    service = IntegrationService(AsyncMock())
    monkeypatch.setattr(service, "account", AsyncMock(return_value=row))
    monkeypatch.setattr(
        authority,
        "run_author",
        AsyncMock(return_value=AuthContext(user_id=person, organization_id=org, role="builder")),
    )
    allowed = AsyncMock(return_value=False)
    monkeypatch.setattr(authority, "resolve_access", allowed)
    credential = OdooCredential(
        origin="https://erp.example.com", database="company", api_key="private-key"
    )
    # The unsealer is deliberately synchronous; no credential is opened on refusal.
    from unittest.mock import MagicMock

    opened = MagicMock(return_value=credential)
    monkeypatch.setattr(McpConnectionService, "integration_odoo_credential", opened)
    call = AsyncMock(return_value={"result": []})
    monkeypatch.setattr(odoo, "execute", call)
    args = {"organization_id": org, "person_id": person, "parameters": {}, "query": {}, "body": {}}
    selection = AccountSelection(account="organization", connection_id=identifier)
    with pytest.raises(AuthorizationError):
        await service.run("odoo_contacts", "search_contacts", selection, **args)
    opened.assert_not_called()
    allowed.return_value = True
    assert await service.run("odoo_contacts", "search_contacts", selection, **args) == {
        "result": []
    }
    call.assert_awaited_once()
    token = await service.source_token(
        organization_id=org, connection_id=identifier, provider="odoo"
    )
    assert token.credential == credential and token.connection_id == identifier


async def test_knowledge_sync_cannot_spend_unselected_default_application_roles(monkeypatch):
    from app.core.exceptions import BadRequestError
    from app.services.integrations import IntegrationService
    from app.services.mcp_connection import McpConnectionService
    from app.services.sync_source import SyncSourceService

    org, person, identifier = uuid4(), uuid4(), uuid4()
    row = McpConnection(
        id=identifier,
        scope="org",
        organization_id=org,
        catalog_key="microsoft",
        auth_type="application",
        granted_scopes=["Mail.Read"],
    )
    opened = AsyncMock()
    monkeypatch.setattr(McpConnectionService, "integration_access_token", opened)
    service = IntegrationService(AsyncMock())
    monkeypatch.setattr(service, "account", AsyncMock(return_value=row))
    with pytest.raises(AuthorizationError, match="knowledge product"):
        await service.source_token(
            organization_id=org, connection_id=identifier, provider="microsoft"
        )
    opened.assert_not_awaited()
    monkeypatch.setattr(IntegrationService, "binding_account", AsyncMock(return_value=row))
    ctx = AuthContext(user_id=person, organization_id=org, role="builder")
    with pytest.raises(BadRequestError, match="knowledge product"):
        await SyncSourceService(AsyncMock())._checked_account(
            {"connection_id": str(identifier)}, "sharepoint", None, ctx
        )
    row.granted_scopes = ["Files.Read.All"]
    await SyncSourceService(AsyncMock())._checked_account(
        {"connection_id": str(identifier)}, "sharepoint", None, ctx
    )


async def test_slack_knowledge_binding_checks_selected_histories_before_saving(monkeypatch):
    from app.core.exceptions import BadRequestError
    from app.services.integrations import IntegrationService
    from app.services.sync_source import SyncSourceService

    org, person, identifier = uuid4(), uuid4(), uuid4()
    row = McpConnection(
        id=identifier,
        scope="org",
        organization_id=org,
        catalog_key="slack",
        granted_scopes=["channels:history"],
    )
    monkeypatch.setattr(IntegrationService, "binding_account", AsyncMock(return_value=row))
    check = AsyncMock(side_effect=BadRequestError(message="selected history requires im:history"))
    monkeypatch.setattr(IntegrationService, "validate_feed_selection", check)
    ctx = AuthContext(user_id=person, organization_id=org, role="builder")
    with pytest.raises(BadRequestError, match="im:history"):
        await SyncSourceService(AsyncMock())._checked_account(
            {"connection_id": str(identifier), "channels": ["D1"]}, "slack", None, ctx
        )
    check.assert_awaited_once_with(row, ("D1",), organization_id=org)
