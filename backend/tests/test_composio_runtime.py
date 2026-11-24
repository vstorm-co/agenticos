"""Managed apps keep personal ownership, explicit account pins, and tool ceilings."""

import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx2
import pydantic_ai.mcp  # noqa: F401 - load SDK transports before tests replace their boundary
import pytest
from pydantic import SecretStr
from pydantic_ai import RunContext, Tool
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from app.agents import mcp
from app.agents.mcp import McpSourceIdentity, tool_origin, tool_prefix
from app.agents.spec import AgentSpec, PersonalMcpServerRef, PlatformMcpServerRef
from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.db.models.mcp_connection import McpConnection
from app.schemas.mcp_connection import McpConnectionCreate
from app.services import agent_registry, mcp_connection
from app.services.app_connections import composio_user_id, runtime

pytestmark = pytest.mark.anyio

_READ = "GMAIL_FETCH_EMAILS"
_DETAIL = "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"
_THREAD = "GMAIL_FETCH_MESSAGE_BY_THREAD_ID"
_WRITE = "GMAIL_SEND_EMAIL"
_ROUTER = "COMPOSIO_MULTI_EXECUTE_TOOL"
_DYNAMIC_TOOLS = ["GOOGLESHEETS_GET_SPREADSHEET", "GOOGLESHEETS_FIND_SPREADSHEET"]
_ORIGIN = "https://backend.composio.dev"


@pytest.fixture(autouse=True)
def configured_apps(monkeypatch):
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", SecretStr("runtime-provider-key"))
    monkeypatch.setattr(
        settings, "COMPOSIO_AUTH_CONFIGS", {"gmail": "ac_gmail", "slack": "ac_slack"}
    )
    monkeypatch.setattr(settings, "COMPOSIO_USER_NAMESPACE", "runtime-tests")


@pytest.fixture
def provider(monkeypatch):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.verify_account = AsyncMock(
        return_value=SimpleNamespace(
            status="ACTIVE", is_disabled=False, auth_config=SimpleNamespace(is_disabled=False)
        )
    )
    client.create_session = AsyncMock(return_value=f"{_ORIGIN}/tool_router/trs_runtime/mcp")
    client.mcp_headers.return_value = {"x-api-key": "runtime-provider-key"}
    monkeypatch.setattr(runtime, "ComposioClient", MagicMock(return_value=client))
    return client


def _connection(**overrides) -> McpConnection:
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "organization_id": None,
        "scope": "user",
        "purpose": "mcp",
        "name": "composio-gmail",
        "catalog_key": "composio-gmail",
        "url": "https://backend.composio.dev/connected_accounts/ca_primary",
        "auth_type": "composio",
        "auth_token": None,
        "oauth_payload": None,
        "allowed_tools": None,
        "is_enabled": True,
        "is_default": False,
        "include_instructions": True,
        "account_email": "reader@example.test",
        "label": "Work",
        "authorization_generation": uuid4(),
        "composio_account_id": "ca_primary",
        "composio_auth_config_id": "ac_gmail",
        "composio_status": "ACTIVE",
    }
    values.update(overrides)
    return McpConnection(**values)


async def _spec(connection, *, name="composio-gmail", allowed_tools=None, approval="writes"):
    return await runtime.managed_connection_spec(
        connection, name=name, allowed_tools=allowed_tools, approval=approval
    )


def _dynamic_connection(**overrides) -> McpConnection:
    values = {
        "name": "google_sheets-account",
        "catalog_key": "composio-google_sheets",
        "url": f"{_ORIGIN}/api/v3.1/toolkits/google_sheets",
        "allowed_tools": list(_DYNAMIC_TOOLS),
        "composio_auth_config_id": "ac_google_sheets",
    }
    values.update(overrides)
    return _connection(**values)


async def test_a_session_pins_the_member_account_config_and_reviewed_actions(provider):
    connection = _connection()
    spec = await _spec(connection, approval="none")

    assert spec is not None
    expected_account = {
        "user_id": composio_user_id(connection.user_id),
        "toolkit": "gmail",
        "account_id": "ca_primary",
        "auth_config_id": "ac_gmail",
    }
    assert provider.verify_account.await_args.kwargs == expected_account
    assert provider.create_session.await_args.kwargs == {
        **expected_account,
        "tools": [_READ, _DETAIL, _THREAD],
    }
    assert spec.allowed_tools == [_READ, _DETAIL, _THREAD]
    assert spec.approval == "writes"
    assert spec.account == "Work · reader@example.test"
    assert spec.managed_app_name == "Gmail"
    assert spec.source_connection_id == connection.id
    assert spec.authorization_generation == connection.authorization_generation
    assert spec.source_url == connection.url
    assert spec.url != spec.source_url
    assert spec.credential_origin == _ORIGIN
    assert spec.include_instructions is False
    assert "runtime-provider-key" not in repr(spec)


@pytest.mark.security
async def test_dynamic_session_freezes_direct_tools_and_requires_approval_for_every_call(
    monkeypatch, provider
):
    monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIGS", {})
    connection = _dynamic_connection()

    spec = await _spec(
        connection,
        name="composio-google_sheets",
        allowed_tools=[_DYNAMIC_TOOLS[1], "TOOL_NOT_GRANTED"],
        approval="none",
    )

    assert spec is not None
    pinned = {
        "user_id": composio_user_id(connection.user_id),
        "toolkit": "google_sheets",
        "account_id": connection.composio_account_id,
        "auth_config_id": "ac_google_sheets",
    }
    assert provider.verify_account.await_args.kwargs == pinned
    assert provider.create_session.await_args.kwargs == {
        **pinned,
        "tools": [_DYNAMIC_TOOLS[1]],
    }
    assert spec.allowed_tools == [_DYNAMIC_TOOLS[1]]
    assert spec.approval == "all"
    assert spec.source_connection_id == connection.id
    assert spec.authorization_generation == connection.authorization_generation
    assert spec.source_url == connection.url


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_tools": None},
        {"allowed_tools": []},
        {"allowed_tools": ["COMPOSIO_MULTI_EXECUTE_TOOL"]},
        {"allowed_tools": ["not a tool name"]},
        {"allowed_tools": ["DUPLICATE", "DUPLICATE"]},
        {"allowed_tools": [f"TOOL_{index}" for index in range(1001)]},
        {"url": f"{_ORIGIN}/api/v3.1/toolkits/another_toolkit"},
    ],
)
async def test_dynamic_connection_needs_its_frozen_safe_action_list_and_stable_source_url(
    provider, changes
):
    assert (
        await _spec(_dynamic_connection(**changes), name="composio-google_sheets", approval="all")
        is None
    )
    provider.verify_account.assert_not_awaited()
    provider.create_session.assert_not_awaited()


async def test_dynamic_sender_accounts_stay_user_scoped_and_keep_source_identity(
    monkeypatch, provider
):
    first = _dynamic_connection()
    second = _dynamic_connection(user_id=uuid4(), composio_account_id="ca_second")
    accounts = {first.user_id: first, second.user_id: second}

    async def owned(_db, *, user_id, catalog_key):
        assert catalog_key == "composio-google_sheets"
        return [accounts[user_id]]

    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo, "list_user_scoped_by_catalog_key", owned
    )
    provider.create_session.side_effect = [
        f"{_ORIGIN}/tool_router/trs_first/mcp",
        f"{_ORIGIN}/tool_router/trs_second/mcp",
    ]
    ref = PersonalMcpServerRef(
        account="personal",
        catalog_key="composio-google_sheets",
        allowed_tools=[_DYNAMIC_TOOLS[1]],
        approval="all",
    )
    resolved = [
        await mcp_connection._own_specs(AsyncMock(), ref, user_id=account.user_id)
        for account in (first, second)
    ]

    assert all(isinstance(own, list) and len(own) == 1 for own in resolved)
    assert [own[0].spec.source_connection_id for own in resolved] == [first.id, second.id]
    assert [call.kwargs["user_id"] for call in provider.create_session.await_args_list] == [
        composio_user_id(first.user_id),
        composio_user_id(second.user_id),
    ]
    assert [call.kwargs["account_id"] for call in provider.create_session.await_args_list] == [
        first.composio_account_id,
        second.composio_account_id,
    ]
    assert all(own[0].spec.allowed_tools == [_DYNAMIC_TOOLS[1]] for own in resolved)


@pytest.mark.parametrize(
    "identity,label,display",
    [
        (None, None, "Gmail"),
        (None, "Work", "Work"),
        ("reader@example.test", None, "reader@example.test"),
        ("reader@example.test", "reader@example.test", "reader@example.test"),
    ],
)
async def test_account_display_does_not_invent_an_unavailable_identity(
    provider, identity, label, display
):
    spec = await _spec(_connection(account_email=identity, label=label))

    assert spec is not None
    assert spec.account == display


@pytest.mark.parametrize(
    ("account_tools", "binding_tools", "expected"),
    [
        (None, [_DETAIL, _WRITE, _ROUTER], [_DETAIL]),
        ([_READ, _DETAIL, _ROUTER], [_DETAIL, _THREAD, _ROUTER], [_DETAIL]),
        ([_READ], None, [_READ]),
        ([], None, []),
        (None, [], []),
        ([_ROUTER, _WRITE], None, []),
    ],
)
async def test_neither_binding_nor_account_can_widen_the_reviewed_action_ceiling(
    provider, account_tools, binding_tools, expected
):
    spec = await _spec(_connection(allowed_tools=account_tools), allowed_tools=binding_tools)

    if expected:
        assert spec is not None and spec.allowed_tools == expected
        assert provider.create_session.await_args.kwargs["tools"] == expected
    else:
        assert spec is None
        provider.verify_account.assert_not_awaited()
        provider.create_session.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_type": "bearer"},
        {"scope": "org"},
        {"organization_id": uuid4()},
        {"purpose": "account"},
        {"user_id": None},
        {"is_enabled": False},
        {"composio_status": "EXPIRED"},
        {"composio_account_id": None},
        {"composio_auth_config_id": None},
        {"catalog_key": "composio-unreviewed"},
    ],
)
async def test_ineligible_connection_metadata_never_opens_a_provider_session(provider, changes):
    assert await _spec(_connection(**changes)) is None
    provider.verify_account.assert_not_awaited()
    provider.create_session.assert_not_awaited()


@pytest.mark.parametrize("missing", ["key", "blank_key", "config", "blank_config"])
async def test_a_disabled_provider_configuration_cannot_open_a_managed_session(
    monkeypatch, provider, missing
):
    if missing in {"key", "blank_key"}:
        monkeypatch.setattr(
            settings, "COMPOSIO_API_KEY", None if missing == "key" else SecretStr("  ")
        )
    else:
        monkeypatch.setattr(
            settings, "COMPOSIO_AUTH_CONFIGS", {} if missing == "config" else {"gmail": "  "}
        )

    assert await _spec(_connection()) is None
    provider.verify_account.assert_not_awaited()
    provider.create_session.assert_not_awaited()


async def test_config_rotation_keeps_existing_accounts_pinned_to_their_original_config(
    monkeypatch, provider
):
    monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIGS", {"gmail": "ac_replacement"})

    spec = await _spec(_connection(composio_auth_config_id="ac_gmail"))

    assert spec is not None
    assert provider.verify_account.await_args.kwargs["auth_config_id"] == "ac_gmail"
    assert provider.create_session.await_args.kwargs["auth_config_id"] == "ac_gmail"


@pytest.mark.parametrize(
    "status,disabled,config_disabled",
    [("EXPIRED", False, False), ("ACTIVE", True, False), ("ACTIVE", False, True)],
)
async def test_provider_revocation_refuses_the_account_before_session_creation(
    provider, status, disabled, config_disabled
):
    provider.verify_account.return_value = SimpleNamespace(
        status=status,
        is_disabled=disabled,
        auth_config=SimpleNamespace(is_disabled=config_disabled),
    )

    assert await _spec(_connection()) is None
    provider.create_session.assert_not_awaited()


@pytest.mark.parametrize("failure", ["verify_account", "create_session"])
async def test_provider_failure_is_unavailable_and_does_not_expose_provider_details(
    provider, failure, caplog
):
    getattr(provider, failure).side_effect = ExternalServiceError(
        message="private provider detail runtime-provider-key"
    )

    assert await _spec(_connection()) is None
    assert "private provider detail" not in caplog.text
    assert "runtime-provider-key" not in caplog.text


async def test_each_sender_resolves_and_pins_their_own_account(monkeypatch, provider):
    first, second = _connection(), _connection(composio_account_id="ca_second")
    accounts = {first.user_id: first, second.user_id: second}

    async def owned(_db, *, user_id, catalog_key):
        assert catalog_key == "composio-gmail"
        return [accounts[user_id]]

    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo, "list_user_scoped_by_catalog_key", owned
    )
    provider.create_session.side_effect = [
        f"{_ORIGIN}/tool_router/trs_first/mcp",
        f"{_ORIGIN}/tool_router/trs_second/mcp",
    ]
    ref = PersonalMcpServerRef(account="personal", catalog_key="composio-gmail")
    resolved = [
        await mcp_connection._own_specs(AsyncMock(), ref, user_id=account.user_id)
        for account in (first, second)
    ]

    assert all(isinstance(own, list) and len(own) == 1 for own in resolved)
    assert resolved[0][0].spec.source_connection_id == first.id
    assert resolved[1][0].spec.source_connection_id == second.id
    assert resolved[0][0].spec.url != resolved[1][0].spec.url
    assert [call.kwargs["user_id"] for call in provider.create_session.await_args_list] == [
        composio_user_id(first.user_id),
        composio_user_id(second.user_id),
    ]
    assert [call.kwargs["account_id"] for call in provider.create_session.await_args_list] == [
        "ca_primary",
        "ca_second",
    ]


async def test_a_surface_without_a_person_cannot_resolve_personal_managed_apps(
    monkeypatch, provider
):
    lookup = AsyncMock(return_value=[_connection()])
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo, "list_user_scoped_by_catalog_key", lookup
    )
    ref = PersonalMcpServerRef(account="personal", catalog_key="composio-gmail")

    assert await mcp_connection._personal_specs(AsyncMock(), ref, sender_user_id=None) == (
        [],
        "nobody_to_speak_as",
    )
    lookup.assert_not_awaited()
    provider.verify_account.assert_not_awaited()


async def test_identical_account_names_still_map_each_selected_id_to_its_own_tool_prefix(
    monkeypatch, provider
):
    from app.services.agent_runner import _with_account_notes, _with_managed_app_notes

    first = _connection()
    second = _connection(user_id=first.user_id, composio_account_id="ca_second")
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[first, second]),
    )
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo, "get_org_scoped_by_ids", AsyncMock(return_value={})
    )

    async def probed(specs):
        return [(spec, FunctionToolset()) for spec in specs]

    monkeypatch.setattr(mcp_connection, "probe_toolsets", probed)
    ref = PersonalMcpServerRef(account="personal", catalog_key="composio-gmail")
    resolved = await mcp_connection.build_toolsets_for_agent(
        AsyncMock(), organization_id=uuid4(), refs=[ref], sender_user_id=first.user_id
    )

    assert len(resolved.accounts) == 2
    assert len({note.prefix for note in resolved.accounts}) == 2
    assert len(resolved.managed_apps) == 2
    assert {note.app for note in resolved.managed_apps} == {"Gmail"}
    spec_with_apps = _with_managed_app_notes(AgentSpec(name="Assistant"), resolved.managed_apps)
    instructions = _with_account_notes(AgentSpec(name="Assistant"), resolved.accounts).instructions
    assert "Gmail is connected for this person" in spec_with_apps.instructions
    assert all(f"`{note.prefix}_`" in spec_with_apps.instructions for note in resolved.managed_apps)
    for account in (first, second):
        note = next(note for note in resolved.accounts if str(account.id) in note.account)
        assert "Work · reader@example.test" in note.account
        assert f"`{note.prefix}_`" in instructions
        assert f"connection {account.id}" in instructions
        assert resolved.sources[account.id].tool_prefix == note.prefix
    assert {call.kwargs["account_id"] for call in provider.create_session.await_args_list} == {
        "ca_primary",
        "ca_second",
    }


@pytest.mark.parametrize("changed", ["endpoint", "generation"])
async def test_old_source_consent_cannot_reach_a_changed_managed_account(
    monkeypatch, provider, changed
):
    connection = _connection()
    identity = McpSourceIdentity(
        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
        authorization_generation=connection.authorization_generation,
        tool_prefix="composio_gmail",
    )
    if changed == "endpoint":
        connection.url += "/replaced"
    else:
        connection.authorization_generation = uuid4()
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[connection]),
    )
    ref = PersonalMcpServerRef(account="personal", catalog_key="composio-gmail")

    assert (
        await mcp_connection._own_specs(
            AsyncMock(), ref, user_id=connection.user_id, approved_sources={connection.id: identity}
        )
        == "not_connected"
    )
    provider.verify_account.assert_not_awaited()


async def test_resolved_source_consent_uses_the_stable_connection_not_a_temporary_session(
    monkeypatch, provider
):
    connection = _connection()
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[connection]),
    )
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo, "get_org_scoped_by_ids", AsyncMock(return_value={})
    )

    async def probed(specs):
        return [(spec, FunctionToolset()) for spec in specs]

    monkeypatch.setattr(mcp_connection, "probe_toolsets", probed)
    ref = PersonalMcpServerRef(account="personal", catalog_key="composio-gmail")
    resolved = await mcp_connection.build_toolsets_for_agent(
        AsyncMock(), organization_id=uuid4(), refs=[ref], sender_user_id=connection.user_id
    )

    assert len(resolved.toolsets) == 1
    assert resolved.unavailable == []
    assert resolved.sources == {
        connection.id: McpSourceIdentity(
            endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
            authorization_generation=connection.authorization_generation,
            tool_prefix="composio_gmail",
        )
    }


@pytest.mark.security
@pytest.mark.parametrize(
    "approval,read_hint,gated", [("none", True, False), ("none", False, True), ("all", True, True)]
)
async def test_actual_toolset_filters_router_tools_and_retains_approval_and_source_metadata(
    monkeypatch, provider, approval, read_hint, gated
):
    connection = _connection()
    spec = await _spec(connection, allowed_tools=[_READ, _ROUTER], approval=approval)
    assert spec is not None

    def result() -> str:
        return "read"

    inner = FunctionToolset(
        [
            Tool(result, name=_READ, metadata={"annotations": {"readOnlyHint": read_hint}}),
            Tool(result, name=_WRITE, metadata={"annotations": {"readOnlyHint": True}}),
            Tool(result, name=_ROUTER, metadata={"annotations": {"readOnlyHint": True}}),
        ]
    )
    monkeypatch.setattr(mcp, "MCPToolset", MagicMock(return_value=inner))
    monkeypatch.setattr(mcp, "_origin_bound_client", MagicMock(return_value=object()))
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())
    origins = []
    for session in ("first", "second"):
        tools = await mcp._make_toolset(
            replace(spec, url=f"{_ORIGIN}/tool_router/trs_{session}/mcp")
        ).get_tools(ctx)
        assert list(tools) == [f"{tool_prefix(spec.name)}_{_READ}"]
        tool = next(iter(tools.values())).tool_def
        assert tool.metadata[mcp.NEEDS_APPROVAL] is gated
        origins.append(tool_origin(tool))

    assert origins[0] == origins[1]
    assert origins[0].connection_id == connection.id
    assert origins[0].tool_id == _READ
    assert origins[0].identity.endpoint_hash == hashlib.sha256(connection.url.encode()).hexdigest()
    assert origins[0].identity.authorization_generation == connection.authorization_generation


@pytest.mark.security
async def test_dynamic_read_only_looking_actions_still_require_approval(monkeypatch, provider):
    spec = await _spec(_dynamic_connection(), name="composio-google_sheets", approval="none")
    assert spec is not None and spec.approval == "all"

    def result() -> str:
        return "read"

    inner = FunctionToolset(
        [Tool(result, name=_DYNAMIC_TOOLS[0], metadata={"annotations": {"readOnlyHint": True}})]
    )
    monkeypatch.setattr(mcp, "MCPToolset", MagicMock(return_value=inner))
    monkeypatch.setattr(mcp, "_origin_bound_client", MagicMock(return_value=object()))
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())

    tools = await mcp._make_toolset(spec).get_tools(ctx)

    assert list(tools) == [f"{tool_prefix(spec.name)}_{_DYNAMIC_TOOLS[0]}"]
    tool = next(iter(tools.values())).tool_def
    assert tool.metadata[mcp.NEEDS_APPROVAL] is True


async def test_managed_metadata_cannot_fall_through_to_generic_bearer_transport():
    assert await mcp_connection.resolve_auth_headers(_connection()) is None


@pytest.mark.parametrize("available", [True, False])
async def test_a_watch_uses_the_same_verified_account_and_reviewed_action_ceiling(
    monkeypatch, provider, available
):
    connection = _connection(allowed_tools=[_READ, _WRITE])
    if not available:
        provider.verify_account.return_value.status = "EXPIRED"
    generic_headers = AsyncMock(
        side_effect=AssertionError("managed accounts cannot use bearer auth")
    )
    monkeypatch.setattr(mcp_connection, "resolve_auth_headers", generic_headers)

    spec = await mcp_connection.watched_connection_spec(connection)

    generic_headers.assert_not_awaited()
    assert provider.verify_account.await_args.kwargs["account_id"] == "ca_primary"
    assert provider.verify_account.await_args.kwargs["user_id"] == composio_user_id(
        connection.user_id
    )
    if available:
        assert spec is not None
        assert spec.allowed_tools == [_READ]
        assert spec.approval == "writes"
        assert spec.source_connection_id == connection.id
        assert spec.authorization_generation == connection.authorization_generation
        assert spec.source_url == connection.url
        assert spec.credential_origin == _ORIGIN
        assert provider.create_session.await_args.kwargs["tools"] == [_READ]
    else:
        assert spec is None
        provider.create_session.assert_not_awaited()


@pytest.mark.parametrize("another_is_available", [True, False])
async def test_one_revoked_managed_account_does_not_lend_authority_to_another(
    monkeypatch, provider, another_is_available
):
    first = _connection(is_default=True)
    second = _connection(user_id=first.user_id, composio_account_id="ca_second", label="Personal")
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[first, second]),
    )
    provider.verify_account.side_effect = [
        SimpleNamespace(
            status="EXPIRED", is_disabled=False, auth_config=SimpleNamespace(is_disabled=False)
        ),
        SimpleNamespace(
            status="ACTIVE" if another_is_available else "EXPIRED",
            is_disabled=False,
            auth_config=SimpleNamespace(is_disabled=False),
        ),
    ]
    ref = PersonalMcpServerRef(account="personal", catalog_key="composio-gmail")

    own = await mcp_connection._own_specs(AsyncMock(), ref, user_id=first.user_id)

    if another_is_available:
        assert isinstance(own, list) and len(own) == 1
        assert own[0].spec.source_connection_id == second.id
        assert str(second.id) in own[0].label
        assert str(first.id) not in own[0].label
        assert provider.create_session.await_args.kwargs["account_id"] == "ca_second"
    else:
        assert own == "unauthorized"
        provider.create_session.assert_not_awaited()


@pytest.mark.parametrize("destination", ["provider", "another_origin"])
async def test_managed_preflight_and_execution_keep_the_credential_bound_to_its_origin(
    monkeypatch, provider, destination
):
    import mcp as mcp_sdk
    import mcp.client.streamable_http as http_transport

    spec = await _spec(_connection(), allowed_tools=[_READ])
    assert spec is not None
    if destination == "another_origin":
        spec = replace(spec, url="https://untrusted.example/mcp")
    sent = []
    clients = []

    def respond(request):
        sent.append(request)
        return httpx2.Response(200, json={"ok": True})

    client_type = httpx2.AsyncClient

    def client(**kwargs):
        opened = client_type(transport=httpx2.MockTransport(respond), **kwargs)
        clients.append(opened)
        return opened

    monkeypatch.setattr(mcp.httpx2, "AsyncClient", client)

    @asynccontextmanager
    async def streamable(url, *, http_client):
        # Exercise the actual HTTP client built through probe -> session -> transport.
        await http_client.get(url)
        yield "managed-read", "managed-write"

    monkeypatch.setattr(http_transport, "streamable_http_client", streamable)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(
        return_value=SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name=_READ,
                    description="Read email",
                    input_schema={"type": "object"},
                    annotations=SimpleNamespace(read_only_hint=True),
                )
            ]
        )
    )
    monkeypatch.setattr(mcp_sdk, "ClientSession", MagicMock(return_value=session))
    build = MagicMock(return_value=FunctionToolset())
    monkeypatch.setattr(mcp, "MCPToolset", build)

    try:
        resolved = await mcp.probe_toolsets([spec])
        assert len(clients) >= 1 and clients[0].is_closed
        if destination == "another_origin":
            assert resolved == [(spec, None)]
            assert sent == []
            build.assert_not_called()
            session.initialize.assert_not_awaited()
        else:
            assert resolved[0][0] is spec and resolved[0][1] is not None
            session.initialize.assert_awaited_once()
            session.list_tools.assert_awaited_once()
            assert len(sent) == 1
            assert str(sent[0].url) == spec.url
            assert sent[0].headers["x-api-key"] == "runtime-provider-key"
            assert len(clients) == 2
            execution = build.call_args.kwargs["http_client"]
            assert execution is clients[1] and not execution.is_closed
            assert build.call_args.kwargs["headers"] is None
            assert execution.headers["x-api-key"] == "runtime-provider-key"
            assert execution.follow_redirects is False
            with pytest.raises(httpx2.RequestError, match="cross-origin"):
                await execution.get("https://untrusted.example/collect")
            assert len(sent) == 1
    finally:
        for opened in clients:
            await opened.aclose()


@pytest.mark.parametrize(
    "target",
    ["https://untrusted.example/mcp", "http://backend.composio.dev/mcp", f"{_ORIGIN}:8443/mcp"],
)
async def test_project_credentials_never_reach_another_origin(monkeypatch, target):
    sent = []

    def respond(request):
        sent.append(request)
        return httpx2.Response(200, json={"ok": True})

    client_type = httpx2.AsyncClient
    transport = httpx2.MockTransport(respond)
    monkeypatch.setattr(
        mcp.httpx2, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )
    async with mcp._origin_bound_client(_ORIGIN, {"x-api-key": "private-key"}, timeout=5) as client:
        assert (await client.get(f"{_ORIGIN}/mcp")).status_code == 200
        with pytest.raises(httpx2.RequestError, match="cross-origin"):
            await client.get(target)

    assert len(sent) == 1
    assert sent[0].headers["x-api-key"] == "private-key"
    assert str(sent[0].url) == f"{_ORIGIN}/mcp"


async def test_redirects_cannot_forward_the_managed_project_credential(monkeypatch):
    sent = []

    def redirect(request):
        sent.append(request)
        return httpx2.Response(307, headers={"location": "https://untrusted.example/collect"})

    client_type = httpx2.AsyncClient
    transport = httpx2.MockTransport(redirect)
    monkeypatch.setattr(
        mcp.httpx2, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs)
    )
    async with mcp._origin_bound_client(_ORIGIN, {"x-api-key": "private-key"}, timeout=5) as client:
        assert (await client.get(f"{_ORIGIN}/mcp")).status_code == 307
        # Even a caller that opts into following redirects cannot weaken the origin pin.
        with pytest.raises(httpx2.RequestError, match="cross-origin"):
            await client.get(f"{_ORIGIN}/mcp", follow_redirects=True)

    assert len(sent) == 2
    assert all(str(request.url) == f"{_ORIGIN}/mcp" for request in sent)


async def test_assistant_app_bindings_preserve_explicit_ceilings_and_only_add_configured_apps():
    explicit = PersonalMcpServerRef(
        account="personal", catalog_key="composio-gmail", allowed_tools=[_DETAIL], approval="all"
    )
    spec = AgentSpec(name="Assistant", instructions="Custom instructions", mcp_servers=[explicit])
    updated = runtime.with_app_connection_bindings(spec)

    assert spec.mcp_servers == [explicit]
    assert spec.instructions == "Custom instructions"
    by_key = {ref.catalog_key: ref for ref in updated.mcp_servers}
    assert set(by_key) == {"composio-gmail", "composio-slack"}
    assert by_key["composio-gmail"] == explicit
    assert by_key["composio-slack"].approval == "writes"
    assert by_key["composio-slack"].allowed_tools
    assert runtime.with_app_connection_bindings(updated) is updated


async def test_any_agent_resolves_the_senders_gmail_and_gets_its_managed_app_note(
    monkeypatch, provider
):
    from app.services.agent_runner import _with_managed_app_notes

    sender_id = uuid4()
    organization_id = uuid4()
    agent = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    connection = _connection(user_id=sender_id, allowed_tools=[_READ])
    monkeypatch.setattr(
        agent_registry.organization_assistant_repo, "for_agent", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        agent_registry.mcp_connection_repo,
        "list_composio_for_user",
        AsyncMock(return_value=[connection]),
    )
    monkeypatch.setattr(runtime, "is_configured", lambda _toolkit: True)
    spec = await agent_registry.AgentRegistryService(AsyncMock()).with_assistant_guidance(
        agent, AgentSpec(name="Research"), sender_user_id=sender_id
    )
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[connection]),
    )

    async def probed(specs):
        return [(server, FunctionToolset()) for server in specs]

    monkeypatch.setattr(mcp_connection, "probe_toolsets", probed)
    resolved = await mcp_connection.build_toolsets_for_agent(
        AsyncMock(),
        organization_id=organization_id,
        refs=spec.mcp_servers,
        sender_user_id=sender_id,
    )
    noted = _with_managed_app_notes(spec, resolved.managed_apps)

    assert "Gmail is connected for this person" in noted.instructions
    assert "`composio_gmail_`" in noted.instructions
    assert "Gmail is connected for this person" not in spec.instructions


@pytest.mark.security
async def test_dynamic_bindings_keep_an_explicit_tool_ceiling_and_resolve_approval(
    monkeypatch, provider
):
    explicit = PersonalMcpServerRef(
        account="personal",
        catalog_key="composio-google_sheets",
        allowed_tools=[_DYNAMIC_TOOLS[1]],
        approval="none",
    )
    spec = AgentSpec(name="Assistant", mcp_servers=[explicit])

    updated = runtime.with_app_connection_bindings(
        spec,
        dynamic_catalog_keys=[
            "composio-google_sheets",
            "composio-gmail",
            "composio-invalid toolkit",
        ],
    )

    dynamic = [
        ref
        for ref in updated.mcp_servers
        if isinstance(ref, PersonalMcpServerRef) and ref.catalog_key == "composio-google_sheets"
    ]
    assert len(dynamic) == 1
    assert dynamic[0].allowed_tools == [_DYNAMIC_TOOLS[1]]
    assert not any(
        isinstance(ref, PersonalMcpServerRef) and ref.catalog_key == "composio-invalid toolkit"
        for ref in updated.mcp_servers
    )

    sender_id = uuid4()
    connection = _dynamic_connection(user_id=sender_id)
    monkeypatch.setattr(
        mcp_connection.mcp_connection_repo,
        "list_user_scoped_by_catalog_key",
        AsyncMock(return_value=[connection]),
    )

    def result() -> str:
        return "read"

    inner = FunctionToolset(
        [
            Tool(
                result,
                name=_DYNAMIC_TOOLS[1],
                metadata={"annotations": {"readOnlyHint": True}},
            )
        ]
    )
    monkeypatch.setattr(mcp, "MCPToolset", MagicMock(return_value=inner))
    monkeypatch.setattr(mcp, "probe_mcp_server", AsyncMock(return_value=[]))
    resolved = await mcp_connection.build_toolsets_for_agent(
        AsyncMock(),
        organization_id=uuid4(),
        refs=updated.mcp_servers,
        sender_user_id=sender_id,
    )
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())
    tools = await resolved.toolsets[0].get_tools(ctx)

    assert list(tools) == [f"{tool_prefix(dynamic[0].catalog_key)}_{_DYNAMIC_TOOLS[1]}"]
    assert tools[next(iter(tools))].tool_def.metadata[mcp.NEEDS_APPROVAL] is True


@pytest.mark.parametrize("missing", ["key", "blank_key", "configs", "blank_config", "reviewed_app"])
async def test_unconfigured_managed_apps_leave_assistant_specs_unchanged(monkeypatch, missing):
    if missing in {"key", "blank_key"}:
        monkeypatch.setattr(
            settings, "COMPOSIO_API_KEY", None if missing == "key" else SecretStr("  ")
        )
    else:
        configs = (
            {}
            if missing == "configs"
            else {"gmail": "  "}
            if missing == "blank_config"
            else {"unreviewed": "ac_other"}
        )
        monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIGS", configs)
    spec = AgentSpec(name="Assistant", instructions="Custom instructions")

    assert runtime.with_app_connection_bindings(spec) is spec


@pytest.mark.parametrize("identity", ["registered", "ordinary", "another_organization"])
async def test_every_agent_gets_only_its_sender_apps_unless_it_is_the_assistant(
    monkeypatch, identity
):
    organization_id = uuid4()
    sender_id = uuid4()
    agent = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    assistant = (
        None
        if identity == "ordinary"
        else SimpleNamespace(
            organization_id=organization_id if identity == "registered" else uuid4()
        )
    )
    monkeypatch.setattr(
        agent_registry.organization_assistant_repo, "for_agent", AsyncMock(return_value=assistant)
    )
    dynamic_lookup = AsyncMock(return_value=[_dynamic_connection(user_id=sender_id)])
    monkeypatch.setattr(
        agent_registry.mcp_connection_repo, "list_composio_for_user", dynamic_lookup
    )
    spec = AgentSpec(
        name="Assistant", mcp_servers=[PlatformMcpServerRef(account="platform", allowed_tools=[])]
    )
    db = AsyncMock()
    actual = await agent_registry.AgentRegistryService(db).with_assistant_guidance(
        agent, spec, sender_user_id=sender_id
    )
    personal = [ref for ref in actual.mcp_servers if isinstance(ref, PersonalMcpServerRef)]

    assert spec.mcp_servers == [PlatformMcpServerRef(account="platform", allowed_tools=[])]
    if identity == "registered":
        assert {ref.catalog_key for ref in personal} == {
            "composio-gmail",
            "composio-slack",
            "composio-google_sheets",
        }
    else:
        assert {ref.catalog_key for ref in personal} == {"composio-google_sheets"}
        assert all(ref.approval == "all" for ref in personal)
    dynamic_lookup.assert_awaited_once_with(db, user_id=sender_id)
    assert spec.mcp_servers == [PlatformMcpServerRef(account="platform", allowed_tools=[])]


async def test_registered_assistant_without_a_sender_does_not_discover_dynamic_apps(monkeypatch):
    organization_id = uuid4()
    agent = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    assistant = SimpleNamespace(organization_id=organization_id)
    monkeypatch.setattr(
        agent_registry.organization_assistant_repo, "for_agent", AsyncMock(return_value=assistant)
    )
    lookup = AsyncMock(return_value=[_dynamic_connection()])
    monkeypatch.setattr(agent_registry.mcp_connection_repo, "list_composio_for_user", lookup)
    spec = AgentSpec(
        name="Assistant", mcp_servers=[PlatformMcpServerRef(account="platform", allowed_tools=[])]
    )

    actual = await agent_registry.AgentRegistryService(AsyncMock()).with_assistant_guidance(
        agent, spec
    )

    lookup.assert_not_awaited()
    assert "composio-google_sheets" not in {
        ref.catalog_key for ref in actual.mcp_servers if isinstance(ref, PersonalMcpServerRef)
    }


async def test_registered_assistant_discovers_only_active_dynamic_apps_of_the_sender(monkeypatch):
    organization_id = uuid4()
    sender_id = uuid4()
    agent = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    assistant = SimpleNamespace(organization_id=organization_id)
    monkeypatch.setattr(
        agent_registry.organization_assistant_repo, "for_agent", AsyncMock(return_value=assistant)
    )
    dynamic = _dynamic_connection(user_id=sender_id)
    inactive = _dynamic_connection(
        user_id=sender_id,
        catalog_key="composio-dropbox",
        name="dropbox-account",
        url=f"{_ORIGIN}/api/v3.1/toolkits/dropbox",
        is_enabled=False,
    )
    not_active = _dynamic_connection(
        user_id=sender_id,
        catalog_key="composio-linear",
        name="linear-account",
        url=f"{_ORIGIN}/api/v3.1/toolkits/linear",
        composio_status="INITIATED",
    )
    lookup = AsyncMock(return_value=[dynamic, inactive, not_active])
    monkeypatch.setattr(agent_registry.mcp_connection_repo, "list_composio_for_user", lookup)
    spec = AgentSpec(
        name="Assistant", mcp_servers=[PlatformMcpServerRef(account="platform", allowed_tools=[])]
    )

    actual = await agent_registry.AgentRegistryService(AsyncMock()).with_assistant_guidance(
        agent, spec, sender_user_id=sender_id
    )

    lookup.assert_awaited_once()
    assert lookup.await_args.kwargs == {"user_id": sender_id}
    dynamic_refs = [
        ref
        for ref in actual.mcp_servers
        if isinstance(ref, PersonalMcpServerRef)
        and ref.catalog_key.startswith("composio-")
        and ref.catalog_key not in {"composio-gmail", "composio-slack"}
    ]
    assert [(ref.catalog_key, ref.allowed_tools, ref.approval) for ref in dynamic_refs] == [
        ("composio-google_sheets", None, "all")
    ]


async def test_generic_mcp_create_cannot_forge_dynamic_composio_keys():
    service = mcp_connection.McpConnectionService(AsyncMock())

    with pytest.raises(BadRequestError, match="from Connections"):
        await service.create(
            user_id=uuid4(),
            data=McpConnectionCreate(
                name="forged-app",
                url="https://backend.composio.dev/api/v3.1/toolkits/private",
                catalog_key="Composio-private_toolkit",
            ),
        )
