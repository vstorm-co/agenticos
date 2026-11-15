"""MCP use grants select tools without handing over connection administration."""

from contextlib import asynccontextmanager
from dataclasses import replace
from time import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from app.agents.mcp_oauth import OAuthError
from app.agents.spec import OrgMcpServerRef
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.mcp_connection import McpConnection
from app.db.models.resource_grant import GrantLevel, Visibility
from app.repositories import mcp_connection_repo, resource_grant_repo
from app.schemas.mcp_connection import OrgMcpConnectionUpdate
from app.services import mcp_connection as connection_module
from app.services.access import MCP_CONNECTION, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_connection import McpConnectionService
from app.services.sharing import SharingService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes.mcp_call import _handler as workflow_mcp

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def caller() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.BUILDER)


@pytest.fixture
def connection(caller: AuthContext) -> McpConnection:
    return McpConnection(
        id=uuid4(),
        organization_id=caller.organization_id,
        scope="org",
        purpose="mcp",
        created_by_user_id=uuid4(),
        visibility=Visibility.PRIVATE.value,
        name="ledger",
        label=None,
        url="https://ledger.example/mcp",
        is_enabled=True,
        allowed_tools=["find"],
        last_tools=[{"name": "find", "description": "Find a record", "read_only": True}],
    )


@pytest.fixture
def use_grant(monkeypatch, connection: McpConnection):
    grant = AsyncMock(return_value=GrantLevel.USE)
    monkeypatch.setattr(resource_grant_repo, "get_level", grant)
    monkeypatch.setattr(
        mcp_connection_repo, "get_org_scoped_by_id", AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(
        mcp_connection_repo,
        "get_org_scoped_by_ids",
        AsyncMock(return_value={connection.id: connection}),
    )
    return grant


async def test_use_grant_still_binds_but_cannot_change_sharing(caller, connection, use_grant):
    db = AsyncMock()
    assert await McpConnectionService(db).get_org_connection(caller, connection.id) is connection
    assert (
        await AgentRegistryService(db)._mcp_problems(
            caller, [OrgMcpServerRef(connection_id=connection.id)], taken={}
        )
        == []
    )
    with pytest.raises(AuthorizationError):
        await SharingService(db).share(
            caller,
            connection,
            resource_type=MCP_CONNECTION,
            subject_user_id=uuid4(),
            level=GrantLevel.EDIT,
        )


async def test_use_grant_cannot_reauthorize_an_existing_connection(
    caller, connection, use_grant, monkeypatch
):
    monkeypatch.setattr(
        mcp_connection_repo, "get_org_scoped_by_name", AsyncMock(return_value=connection)
    )
    service = McpConnectionService(AsyncMock())
    start = AsyncMock()
    monkeypatch.setattr(service, "_oauth_start", start)
    with pytest.raises(NotFoundError):
        await service.oauth_start_for_org(caller, name=connection.name, url=connection.url)
    start.assert_not_awaited()


@pytest.mark.parametrize("current_grant", [GrantLevel.USE, None])
async def test_oauth_completion_rechecks_management_before_exchanging_credentials(
    caller, connection, use_grant, monkeypatch, current_grant
):
    connection.auth_type = "oauth"
    connection.oauth_pending_payload = "staged"
    use_grant.return_value = current_grant
    monkeypatch.setattr(
        mcp_connection_repo, "get_by_oauth_state", AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(
        connection_module,
        "_decode_payload",
        lambda *_args: SimpleNamespace(started_at=time(), initiator_id=caller.user_id),
    )
    monkeypatch.setattr(connection_module, "decider_context", AsyncMock(return_value=caller))
    service = McpConnectionService(AsyncMock())
    secret = AsyncMock()
    monkeypatch.setattr(service, "_refresh_client_secret", secret)
    with pytest.raises(OAuthError, match="connection access changed"):
        await service.oauth_callback(state="staged-state", code="provider-code")
    secret.assert_not_awaited()


@pytest.mark.parametrize("operation", ["update", "delete", "probe", "calls"])
async def test_use_grant_never_authorizes_administration(
    caller, connection, use_grant, monkeypatch, operation
):
    service = McpConnectionService(AsyncMock())
    update = AsyncMock()
    delete = AsyncMock()
    probe = AsyncMock()
    monkeypatch.setattr(mcp_connection_repo, "update", update)
    monkeypatch.setattr(mcp_connection_repo, "delete", delete)
    monkeypatch.setattr(service, "_probe", probe)
    with pytest.raises(NotFoundError):
        if operation == "update":
            await service.update_for_org(
                caller, connection_id=connection.id, data=OrgMcpConnectionUpdate(label="changed")
            )
        elif operation == "delete":
            await service.delete_for_org(caller, connection_id=connection.id)
        elif operation == "probe":
            await service.test_for_org(caller, connection_id=connection.id)
        else:
            await service.recent_calls(caller, connection_id=connection.id)
    update.assert_not_awaited()
    delete.assert_not_awaited()
    probe.assert_not_awaited()


@pytest.mark.parametrize("authority", ["owner-role", "connection-owner", "edit-grant", "org-scope"])
async def test_existing_owners_scopes_and_edit_grants_keep_administration(
    caller, connection, use_grant, monkeypatch, authority
):
    if authority == "owner-role":
        caller = replace(caller, role=OrgRoleName.OWNER)
    elif authority == "connection-owner":
        connection.created_by_user_id = caller.user_id
    elif authority == "edit-grant":
        use_grant.return_value = GrantLevel.EDIT
    else:
        connection.visibility = Visibility.ORG.value
    service = McpConnectionService(AsyncMock())
    probe = AsyncMock(return_value=(connection, [], None))
    monkeypatch.setattr(service, "_probe", probe)
    assert await service.test_for_org(caller, connection_id=connection.id) == (connection, [], None)
    probe.assert_awaited_once_with(connection)


async def test_use_and_management_lists_apply_different_grant_levels(
    caller, connection, use_grant, monkeypatch
):
    monkeypatch.setattr(
        mcp_connection_repo, "list_org_scoped", AsyncMock(return_value=([connection], 1))
    )

    async def shared_ids(_db, *, minimum_level, **_kwargs):
        return [connection.id] if minimum_level == GrantLevel.USE else []

    monkeypatch.setattr(resource_grant_repo, "list_shared_ids", shared_ids)
    service = McpConnectionService(AsyncMock())
    assert await service.list_usable(caller) == [connection]
    assert await service.list_for_org(caller) == ([], 0)


@pytest.mark.parametrize(
    "key_scopes", [None, frozenset({Perm.MCP_USE}), frozenset({Perm.MCP_MANAGE})]
)
async def test_organization_api_keys_list_org_connections_without_a_user(
    caller, connection, monkeypatch, key_scopes
):
    caller = replace(
        caller,
        user_id=None,
        role=OrgRoleName.OWNER,
        api_key_id=uuid4(),
        key_scopes=key_scopes,
    )
    connection.visibility = Visibility.ORG.value
    private = McpConnection(
        id=uuid4(),
        organization_id=caller.organization_id,
        visibility=Visibility.PRIVATE.value,
        created_by_user_id=None,
    )
    monkeypatch.setattr(
        mcp_connection_repo,
        "list_org_scoped",
        AsyncMock(return_value=([connection, private], 2)),
    )
    lookup = AsyncMock(return_value=connection)
    monkeypatch.setattr(mcp_connection_repo, "get_org_scoped_by_id", lookup)
    grant = AsyncMock(return_value=GrantLevel.EDIT)
    monkeypatch.setattr(resource_grant_repo, "get_level", grant)
    service = McpConnectionService(AsyncMock())

    assert await service.list_usable(caller) == [connection]
    assert await service.get_org_connection(caller, connection.id) is connection
    lookup.return_value = private
    with pytest.raises(NotFoundError):
        await service.get_org_connection(caller, private.id)
    grant.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["other-tenant-owner", "no-subject"])
async def test_no_scope_or_grant_crosses_tenant_or_subject_boundaries(
    caller, connection, use_grant, invalid
):
    connection.created_by_user_id = caller.user_id
    if invalid == "other-tenant-owner":
        connection.organization_id = uuid4()
    else:
        caller = replace(caller, user_id=None)
    for permission in (Perm.MCP_USE, Perm.MCP_MANAGE):
        assert not await resolve_access(
            AsyncMock(), caller, connection, permission, resource_type=MCP_CONNECTION
        )
    use_grant.assert_not_awaited()
    with pytest.raises(NotFoundError):
        await McpConnectionService(AsyncMock()).test_for_org(caller, connection_id=connection.id)


async def test_a_use_only_key_cannot_spend_its_owners_management_authority(
    caller, connection, use_grant
):
    caller = replace(caller, role=OrgRoleName.OWNER, key_scopes=frozenset({Perm.MCP_USE}))
    assert caller.has(Perm.MCP_USE)
    assert not caller.has(Perm.MCP_MANAGE)
    assert not caller.key_allows(Perm.MCP_MANAGE)
    use_grant.return_value = GrantLevel.EDIT
    service = McpConnectionService(AsyncMock())
    assert await service.get_org_connection(caller, connection.id) is connection
    with pytest.raises(NotFoundError):
        await service.test_for_org(caller, connection_id=connection.id)


async def test_a_preexisting_management_key_keeps_selecting_its_use_grant(
    caller, connection, use_grant
):
    caller = replace(caller, key_scopes=frozenset({Perm.MCP_MANAGE}))
    assert caller.key_allows(Perm.MCP_USE)
    assert (
        await McpConnectionService(AsyncMock()).get_org_connection(caller, connection.id)
        is connection
    )
    assert (
        await AgentRegistryService(AsyncMock())._mcp_problems(
            caller, [OrgMcpServerRef(connection_id=connection.id)], taken={}
        )
        == []
    )


async def test_an_unrelated_key_scope_cannot_borrow_a_private_use_grant(
    caller, connection, use_grant
):
    caller = replace(caller, key_scopes=frozenset({Perm.AGENTS_EDIT}))
    with pytest.raises(NotFoundError):
        await McpConnectionService(AsyncMock()).get_org_connection(caller, connection.id)
    use_grant.assert_not_awaited()


async def test_organization_visibility_does_not_authorize_a_member_to_administer(
    caller, connection, use_grant
):
    caller = replace(caller, role=OrgRoleName.MEMBER)
    connection.visibility = Visibility.ORG.value
    use_grant.return_value = None
    service = McpConnectionService(AsyncMock())
    assert await service.get_org_connection(caller, connection.id) is connection
    with pytest.raises(NotFoundError):
        await service.test_for_org(caller, connection_id=connection.id)


async def test_workflow_calls_with_use_and_refuses_revocation_before_reading_credentials(
    caller, connection, use_grant, monkeypatch
):
    caller = replace(caller, role=OrgRoleName.MEMBER)
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    calls = AsyncMock(
        return_value=CallToolResult(content=[TextContent(type="text", text="record")])
    )

    class Client:
        async def list_tools(self):
            return ListToolsResult(tools=[Tool(name="find", input_schema={"type": "object"})])

        async def call_tool(self, name, arguments):
            return await calls(name, arguments)

    @asynccontextmanager
    async def remote_session(_url, _headers):
        yield Client()

    headers = AsyncMock(return_value={})
    monkeypatch.setattr(workflow_mcp, "get_worker_db_context", session)
    monkeypatch.setattr(workflow_mcp, "mcp_session", remote_session)
    monkeypatch.setattr(workflow_mcp, "resolve_auth_headers", headers)
    monkeypatch.setattr(
        workflow_mcp.approval_repo, "get_for_node_run_for_update", AsyncMock(return_value=None)
    )
    dispatch = context.DispatchContext(
        organization_id=caller.organization_id,
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=caller,
        resumed_agent_run_id=None,
        workflow_id=uuid4(),
    )
    config = workflow_mcp.McpCallConfig(connection_id=connection.id, tool="find", approval="none")
    with context.dispatching_as(dispatch):
        result = await workflow_mcp.handle(config, None)
    assert isinstance(result, Completed)
    calls.assert_awaited_once_with("find", {})
    headers.assert_awaited_once_with(connection)

    use_grant.return_value = None
    headers.reset_mock()
    calls.reset_mock()
    with context.dispatching_as(dispatch):
        refused = await workflow_mcp.handle(config, None)
    assert isinstance(refused, Failed)
    assert refused.error.code == "MCP_SERVER_UNAVAILABLE"
    headers.assert_not_awaited()
    calls.assert_not_awaited()
