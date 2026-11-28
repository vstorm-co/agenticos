"""The MCP Apps page of a stored call, and what it relays (#3450).

The refusals are the point: a page reaches only the connection its call was made
through, a person's own connection only for that person, and a tool only as far
as the run that made the call could - its binding's list, the connection's list
as it is now, and its approvals, where one that would wait for a person is
refused rather than run - and only as far as the agent's binding lets it now.
"""

import base64
import hashlib
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from mcp.types import Tool, ToolAnnotations
from pydantic_ai.mcp import MCPError

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.core.security import create_mcp_app_view_token
from app.db.models.agent import AgentStatus
from app.services import mcp_app as module
from app.services.mcp_app import McpAppService

pytestmark = pytest.mark.anyio

PAGE = "ui://charts/viewer.html"
GENERATION = "6f1c1f4e-1111-4c8a-9a54-0d1e1c1f4e11"
HTML = "<!doctype html><title>chart</title>"


def _ctx(user_id: Any = None) -> AuthContext:
    return AuthContext(user_id=user_id or uuid4(), organization_id=uuid4(), role=OrgRoleName.MEMBER)


def _record(connection_id: Any, **overrides: Any) -> dict[str, Any]:
    return {
        "resource_uri": PAGE,
        "tool_input": {"source": "asset:1"},
        "result": {"content": [], "isError": False},
        "connection_id": str(connection_id),
        "tool_name": "data_query",
        "allowed_tools": None,
        "approval": "writes",
        "tool_approval": {},
        "endpoint_hash": hashlib.sha256(b"https://charts.example.com/mcp").hexdigest(),
        "authorization_generation": GENERATION,
        "agent_id": None,
        "binding_key": None,
        **overrides,
    }


def _connection(ctx: AuthContext, **overrides: Any) -> MagicMock:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "name": "charts",
        "url": "https://charts.example.com/mcp",
        "purpose": "mcp",
        "is_enabled": True,
        "mcp_apps": True,
        "scope": "org",
        "user_id": None,
        "organization_id": ctx.organization_id,
        "allowed_tools": None,
        "authorization_generation": UUID(GENERATION),
    }
    return MagicMock(**(fields | overrides))


def _tool(name: str, *, meta: dict[str, Any] | None = None, read_only: bool = True) -> Tool:
    return Tool(
        name=name,
        input_schema={"type": "object"},
        annotations=ToolAnnotations(readOnlyHint=read_only),
        _meta=meta,
    )


class FakeServer:
    """The connection's server, as the relay's `MCPToolset` reaches it."""

    def __init__(self, *, tools: list[Tool] | None = None, fail: BaseException | None = None):
        self.tools = tools or []
        self.fail = fail
        self.called: tuple[str, dict[str, Any]] | None = None
        self.read: str | None = None
        self.page: dict[str, Any] = {
            "contents": [{"uri": PAGE, "mimeType": "text/html;profile=mcp-app", "text": HTML}]
        }

    async def __aenter__(self) -> FakeServer:
        if self.fail is not None:
            raise self.fail
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_tools(self) -> list[Tool]:
        return self.tools

    async def call_tool_for_app(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.called = (name, arguments)
        return {"content": [], "structuredContent": {"value": 3}, "isError": False}

    async def read_resource_for_app(self, uri: str) -> dict[str, Any]:
        self.read = uri
        return self.page


@pytest.fixture
def world(monkeypatch):
    """A conversation the reader may read, a stored call with a page, and its connection."""
    ctx = _ctx()
    connection = _connection(ctx)
    call = MagicMock(id=uuid4(), mcp_app=_record(connection.id))
    server = FakeServer(tools=[_tool("data_query")])
    get_conversation = AsyncMock()
    audit = AsyncMock()
    built: dict[str, Any] = {}

    def _toolset(client: Any, **kwargs: Any) -> FakeServer:
        built.update(client=client, **kwargs)
        return server

    monkeypatch.setattr(
        module.ConversationService,
        "get_conversation",
        lambda self, *a, **k: get_conversation(*a, **k),
    )
    monkeypatch.setattr(module.conversation_repo, "get_app_tool_call", AsyncMock(return_value=call))
    monkeypatch.setattr(
        module.conversation_repo, "get_app_tool_call_by_id", AsyncMock(return_value=call)
    )
    monkeypatch.setattr(module.mcp_connection_repo, "get_by_id", AsyncMock(return_value=connection))
    monkeypatch.setattr(
        module, "resolve_auth_headers", AsyncMock(return_value={"Authorization": "Bearer t"})
    )
    monkeypatch.setattr(module, "MCPToolset", _toolset)
    monkeypatch.setattr(module, "app_client", lambda url, headers, **_: ("client", url, headers))
    monkeypatch.setattr(module, "record_audit", audit)
    audit_sessions: list[Any] = []

    @asynccontextmanager
    async def _own_session():
        session = MagicMock(name="audit session")
        audit_sessions.append(session)
        yield session

    monkeypatch.setattr(module, "get_db_context", _own_session)
    return MagicMock(
        ctx=ctx,
        connection=connection,
        call=call,
        server=server,
        get_conversation=get_conversation,
        audit=audit,
        audit_sessions=audit_sessions,
        built=built,
        service=McpAppService(MagicMock()),
    )


async def _relay(world: Any, name: str = "data_query", arguments: dict[str, Any] | None = None):
    return await world.service.call_tool(
        world.ctx,
        conversation_id=uuid4(),
        tool_call_id="call-1",
        name=name,
        arguments=arguments or {},
    )


class TestFrame:
    async def test_a_reader_gets_a_signed_address_on_the_content_origin(self, world):
        frame = await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

        assert "/api/v1/artifact-content/mcp-app/" in frame.url
        assert world.get_conversation.await_args.kwargs["for_write"] is False

    async def test_a_call_without_a_page_has_none(self, world, monkeypatch):
        monkeypatch.setattr(
            module.conversation_repo, "get_app_tool_call", AsyncMock(return_value=None)
        )

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

    async def test_an_unreadable_stored_record_is_no_page(self, world):
        world.call.mcp_app = {"resource_uri": PAGE}

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

    async def test_nobody_in_particular_gets_no_page(self, world):
        anonymous = AuthContext(
            user_id=None, organization_id=world.ctx.organization_id, role="member"
        )

        with pytest.raises(NotFoundError):
            await world.service.frame(anonymous, conversation_id=uuid4(), tool_call_id="call-1")

    @pytest.mark.parametrize(
        "change",
        [
            {"purpose": "account"},
            {"is_enabled": False},
            {"mcp_apps": False},
            {"organization_id": "another organization"},
        ],
    )
    async def test_a_connection_that_no_longer_shows_pages_here_has_none(self, world, change):
        for key, value in change.items():
            setattr(world.connection, key, value)

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

    async def test_a_connection_repointed_at_another_server_has_none(self, world):
        """Its page and tools are another server's, which this call never had."""
        world.connection.url = "https://elsewhere.example.com/mcp"

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

    async def test_a_connection_signed_in_again_has_none(self, world):
        """A replaced token or a new sign-in may be another account."""
        world.connection.authorization_generation = uuid4()

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

    async def test_a_deleted_connection_has_none(self, world, monkeypatch):
        monkeypatch.setattr(module.mcp_connection_repo, "get_by_id", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

    async def test_a_persons_own_connection_answers_to_that_person_alone(self, world):
        world.connection.scope = "user"
        world.connection.user_id = uuid4()

        with pytest.raises(NotFoundError):
            await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")

        world.connection.user_id = world.ctx.user_id
        assert await world.service.frame(world.ctx, conversation_id=uuid4(), tool_call_id="call-1")


class TestPage:
    def _token(self, world: Any) -> str:
        from datetime import timedelta

        return create_mcp_app_view_token(
            world.call.id,
            user_id=world.ctx.user_id,
            organization_id=world.ctx.organization_id,
            expires_in=timedelta(minutes=5),
        )

    async def test_the_page_is_read_from_its_server_with_the_connections_credential(self, world):
        page = await world.service.page(self._token(world))

        assert page.document == HTML.encode()
        assert world.server.read == PAGE
        assert world.built["client"] == (
            "client",
            world.connection.url,
            {"Authorization": "Bearer t"},
        )

    async def test_a_blob_that_is_not_base64_is_no_page_not_a_failure(self, world):
        world.server.page = {
            "contents": [
                {"uri": PAGE, "mimeType": "text/html;profile=mcp-app", "blob": "not*base64"}
            ]
        }

        with pytest.raises(NotFoundError):
            await world.service.page(self._token(world))

    async def test_a_page_sent_as_a_blob_is_decoded(self, world):
        world.server.page = {
            "contents": [
                {
                    "uri": PAGE,
                    "mimeType": "text/html;profile=mcp-app",
                    "blob": base64.b64encode(HTML.encode()).decode(),
                }
            ]
        }

        assert (await world.service.page(self._token(world))).document == HTML.encode()

    @pytest.mark.parametrize(
        "contents",
        [
            [],
            [{"uri": PAGE, "mimeType": "text/html", "text": HTML}],
            [{"uri": PAGE, "mimeType": "text/html;profile=mcp-app"}],
            "not a list",
        ],
    )
    async def test_anything_but_an_mcp_apps_page_is_not_served(self, world, contents):
        world.server.page = {"contents": contents}

        with pytest.raises(NotFoundError):
            await world.service.page(self._token(world))

    async def test_a_forged_or_foreign_address_is_refused(self, world):
        with pytest.raises(NotFoundError):
            await world.service.page("not-a-token")

    async def test_an_address_for_a_call_that_is_gone_is_refused(self, world, monkeypatch):
        monkeypatch.setattr(
            module.conversation_repo, "get_app_tool_call_by_id", AsyncMock(return_value=None)
        )

        with pytest.raises(NotFoundError):
            await world.service.page(self._token(world))

    async def test_a_connection_switched_off_since_the_address_was_minted_serves_nothing(
        self, world
    ):
        token = self._token(world)
        world.connection.mcp_apps = False

        with pytest.raises(NotFoundError):
            await world.service.page(token)

    async def test_a_credential_that_no_longer_works_serves_nothing(self, world, monkeypatch):
        monkeypatch.setattr(module, "resolve_auth_headers", AsyncMock(return_value=None))

        with pytest.raises(NotFoundError):
            await world.service.page(self._token(world))


class TestToolCall:
    async def test_a_tool_the_run_could_reach_is_relayed_and_audited(self, world):
        result = await _relay(world, arguments={"widget_id": "w1"})

        assert result["structuredContent"] == {"value": 3}
        assert world.server.called == ("data_query", {"widget_id": "w1"})
        assert world.get_conversation.await_args.kwargs["for_write"] is True
        audit = world.audit.await_args.kwargs
        assert audit["action"] == "mcp_connection.app_tool_called"
        assert audit["target_id"] == str(world.connection.id)
        assert audit["details"]["tool"] == "data_query"
        assert "widget_id" not in str(audit["details"])
        # In a session of its own, which commits whatever the request does after.
        assert world.audit.await_args.args[0] is world.audit_sessions[0]

    async def test_a_call_is_audited_before_it_goes_out(self, world):
        """A server can carry out a write and lose the answer: the entry is there."""

        async def lost(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            world.audit.assert_awaited_once()
            raise OSError("connection reset after the write")

        world.server.call_tool_for_app = lost

        with pytest.raises(ExternalServiceError):
            await _relay(world)
        world.audit.assert_awaited_once()

    async def test_a_refused_tool_is_not_audited_as_called(self, world):
        with pytest.raises(AuthorizationError):
            await _relay(world, name="drop_tables")
        world.audit.assert_not_awaited()

    async def test_a_tool_the_server_does_not_list_is_refused(self, world):
        with pytest.raises(AuthorizationError):
            await _relay(world, name="drop_tables")
        assert world.server.called is None

    async def test_a_tool_listed_for_the_model_alone_is_refused(self, world):
        world.server.tools = [_tool("data_query", meta={"ui": {"visibility": ["model"]}})]

        with pytest.raises(AuthorizationError):
            await _relay(world)

    async def test_a_tool_outside_the_runs_list_is_refused(self, world):
        world.call.mcp_app = _record(world.connection.id, allowed_tools=["chart_show"])

        with pytest.raises(AuthorizationError):
            await _relay(world)
        assert world.server.called is None

    async def test_a_tool_taken_off_the_connections_list_since_is_refused(self, world):
        world.connection.allowed_tools = ["chart_show"]

        with pytest.raises(AuthorizationError):
            await _relay(world)

    async def test_a_page_only_tool_of_the_same_page_is_relayed_though_on_no_list(self, world):
        world.call.mcp_app = _record(world.connection.id, allowed_tools=["data_query"])
        world.connection.allowed_tools = ["data_query"]
        world.server.tools = [
            _tool("widget_data", meta={"ui": {"resourceUri": PAGE, "visibility": ["app"]}})
        ]

        await _relay(world, name="widget_data")

        assert world.server.called == ("widget_data", {})

    async def test_a_page_only_tool_is_refused_once_its_pages_tool_is_off_the_connection(
        self, world
    ):
        """Narrowing the connection's list takes the page's own calls with it."""
        world.connection.allowed_tools = ["chart_show"]
        world.server.tools = [
            _tool("widget_data", meta={"ui": {"resourceUri": PAGE, "visibility": ["app"]}})
        ]

        with pytest.raises(AuthorizationError):
            await _relay(world, name="widget_data")
        assert world.server.called is None

    async def test_a_page_only_tool_of_another_page_is_refused(self, world):
        world.server.tools = [
            _tool(
                "widget_data",
                meta={"ui": {"resourceUri": "ui://other/page.html", "visibility": ["app"]}},
            )
        ]

        with pytest.raises(AuthorizationError):
            await _relay(world, name="widget_data")

    async def test_a_write_under_the_writes_policy_is_refused_not_parked(self, world):
        """A page is not a way around an approval card."""
        world.server.tools = [_tool("data_query", read_only=False)]

        with pytest.raises(AuthorizationError) as refused:
            await _relay(world)
        assert refused.value.details == {"tool": "data_query", "approval_required": True}
        assert world.server.called is None

    async def test_a_tool_the_binding_always_asks_about_is_refused(self, world):
        world.call.mcp_app = _record(world.connection.id, tool_approval={"data_query": "required"})

        with pytest.raises(AuthorizationError):
            await _relay(world)

    async def test_a_tool_without_annotations_is_treated_as_a_write(self, world):
        world.server.tools = [Tool(name="data_query", input_schema={"type": "object"})]

        with pytest.raises(AuthorizationError):
            await _relay(world)


@pytest.mark.security
class TestTheAgentsBindingNow:
    """A page is held to the binding as the agent has it now, as well as to the run's."""

    @pytest.fixture
    def agent(self, world, monkeypatch):
        agent = MagicMock(
            id=uuid4(), status=AgentStatus.PUBLISHED.value, current_version_id=uuid4()
        )
        key = f"organization:{world.connection.id}"
        world.call.mcp_app = _record(world.connection.id, agent_id=str(agent.id), binding_key=key)
        binding: dict[str, Any] = {"connection_id": str(world.connection.id)}
        version = MagicMock()
        version.spec = {"name": "Analyst", "mcp_servers": [binding]}
        get = AsyncMock(return_value=agent)
        get_version = AsyncMock(return_value=version)
        monkeypatch.setattr(module.agent_repo, "get", get)
        monkeypatch.setattr(module.agent_repo, "get_version", get_version)
        return MagicMock(
            agent=agent, binding=binding, version=version, get=get, get_version=get_version
        )

    async def test_a_tool_the_binding_still_allows_is_relayed(self, world, agent):
        await _relay(world)

        assert world.server.called == ("data_query", {})
        assert agent.get.await_args.args[1] == agent.agent.id
        assert agent.get.await_args.kwargs == {"organization_id": world.ctx.organization_id}
        assert agent.get_version.await_args.args[1] == agent.agent.current_version_id

    async def test_a_tool_taken_off_the_agents_list_since_is_refused(self, world, agent):
        agent.binding["allowed_tools"] = ["chart_show"]

        with pytest.raises(AuthorizationError):
            await _relay(world)
        assert world.server.called is None
        world.audit.assert_not_awaited()

    async def test_approvals_switched_to_all_since_refuse_a_read(self, world, agent):
        """Read-only, and so let through by the run's `writes`: asked about now."""
        agent.binding["approval"] = "all"

        with pytest.raises(AuthorizationError) as refused:
            await _relay(world)
        assert refused.value.details == {"tool": "data_query", "approval_required": True}

    async def test_a_tool_the_agent_now_always_asks_about_is_refused(self, world, agent):
        agent.binding["tool_approval"] = {"data_query": "required"}

        with pytest.raises(AuthorizationError):
            await _relay(world)

    async def test_a_page_only_tool_goes_with_its_pages_tool_off_the_agents_list(
        self, world, agent
    ):
        agent.binding["allowed_tools"] = ["chart_show"]
        world.server.tools = [
            _tool("widget_data", meta={"ui": {"resourceUri": PAGE, "visibility": ["app"]}})
        ]

        with pytest.raises(AuthorizationError):
            await _relay(world, name="widget_data")
        assert world.server.called is None

    async def test_loosening_the_agent_since_does_not_loosen_the_run(self, world, agent):
        """Either refusing is a refusal: the run's own approvals still hold."""
        agent.binding["approval"] = "none"
        world.server.tools = [_tool("data_query", read_only=False)]

        with pytest.raises(AuthorizationError):
            await _relay(world)

    async def test_an_agent_without_the_binding_any_more_lets_the_page_call_nothing(
        self, world, agent
    ):
        agent.version.spec = {"name": "Analyst", "mcp_servers": []}

        with pytest.raises(AuthorizationError):
            await _relay(world)
        assert world.server.called is None

    async def test_the_same_service_as_a_persons_own_binding_is_another_binding(self, world, agent):
        agent.version.spec = {
            "name": "Analyst",
            "mcp_servers": [{"account": "personal", "catalog_key": "charts"}],
        }

        with pytest.raises(AuthorizationError):
            await _relay(world)

    @pytest.mark.parametrize("gone", ["deleted", "archived", "unpublished", "version"])
    async def test_an_agent_that_no_longer_runs_lets_the_page_call_nothing(
        self, world, agent, gone
    ):
        if gone == "deleted":
            agent.get.return_value = None
        elif gone == "archived":
            agent.agent.status = AgentStatus.ARCHIVED.value
        elif gone == "unpublished":
            agent.agent.current_version_id = None
        else:
            agent.get_version.return_value = None

        with pytest.raises(AuthorizationError):
            await _relay(world)
        assert world.server.called is None

    async def test_a_call_made_outside_an_agents_binding_is_held_to_the_run_alone(
        self, world, agent
    ):
        world.call.mcp_app = _record(world.connection.id)

        await _relay(world)

        agent.get.assert_not_awaited()
        assert world.server.called == ("data_query", {})


class TestResourceRead:
    async def test_a_ui_resource_of_the_server_is_relayed(self, world):
        result = await world.service.read_resource(
            world.ctx, conversation_id=uuid4(), tool_call_id="call-1", uri="ui://charts/other.html"
        )

        assert result == world.server.page
        assert world.server.read == "ui://charts/other.html"

    async def test_any_other_address_is_refused_before_anything_is_read(self, world):
        with pytest.raises(BadRequestError):
            await world.service.read_resource(
                world.ctx, conversation_id=uuid4(), tool_call_id="call-1", uri="file:///etc/passwd"
            )
        world.get_conversation.assert_not_awaited()


class TestServerFailures:
    async def test_a_protocol_error_is_the_servers_refusal(self, world):
        world.server.fail = MCPError(message="no", code=-32602)

        with pytest.raises(ExternalServiceError) as failed:
            await _relay(world)
        assert failed.value.details == {"code": -32602}

    async def test_a_network_failure_is_said_once_without_its_text(self, world):
        world.server.fail = OSError("connect to 10.0.0.5 refused")

        with pytest.raises(ExternalServiceError) as failed:
            await _relay(world)
        assert "10.0.0.5" not in str(failed.value.message)

    async def test_a_refusal_raised_inside_the_session_comes_out_as_it_is(self, world):
        world.server.fail = ExceptionGroup(
            "session", [ExceptionGroup("inner", [AuthorizationError(message="This page may not")])]
        )

        with pytest.raises(AuthorizationError):
            await _relay(world)

    async def test_a_group_of_network_failures_is_one_failure(self, world):
        world.server.fail = ExceptionGroup("session", [OSError("reset")])

        with pytest.raises(ExternalServiceError):
            await _relay(world)

    async def test_a_cancellation_is_not_swallowed(self, world):
        import asyncio

        world.server.fail = BaseExceptionGroup("session", [asyncio.CancelledError()])

        with pytest.raises(BaseExceptionGroup):
            await _relay(world)
