"""`mcp.call` around a stubbed server: what it calls, when it asks first, and what it refuses."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
    ToolAnnotations,
)

from app.core.permissions import AuthContext
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, Waiting
from app.workflows.nodes.mcp_call import _handler as node

pytestmark = pytest.mark.anyio

CONNECTION = uuid.uuid4()
APPROVER = uuid.uuid4()


def _dispatch() -> context.DispatchContext:
    org = uuid.uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=None,
        workflow_id=uuid.uuid4(),
    )


def _tool(name: str, *, read_only: bool | None) -> Tool:
    return Tool(
        name=name,
        input_schema={"type": "object"},
        annotations=None if read_only is None else ToolAnnotations(read_only_hint=read_only),
    )


@dataclass
class _Server:
    """One MCP server as the step sees it: its row, its tools, and what it was asked."""

    connection: Any = field(
        default_factory=lambda: SimpleNamespace(
            url="https://mcp.example.com/mcp",
            name="crm",
            label="Acme CRM",
            is_enabled=True,
            last_tools=[{"name": "find_lead"}, {"name": "create_lead"}],
        )
    )
    headers: dict[str, str] | None = field(default_factory=lambda: {"Authorization": "Bearer t"})
    tools: list[Tool] = field(
        default_factory=lambda: [
            _tool("find_lead", read_only=True),
            _tool("create_lead", read_only=False),
            _tool("unmarked", read_only=None),
        ]
    )
    result: Any = field(
        default_factory=lambda: CallToolResult(
            content=[TextContent(type="text", text="Lead 42")],
            structured_content={"id": 42},
        )
    )
    failure: BaseException | None = None
    approval: Any = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    asked: list[dict[str, Any]] = field(default_factory=list)
    notified: list[dict[str, Any]] = field(default_factory=list)
    opened_with: list[tuple[str, dict[str, str] | None]] = field(default_factory=list)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    state = _Server()

    @asynccontextmanager
    async def worker_session():
        yield MagicMock()

    class _Session:
        async def list_tools(self) -> ListToolsResult:
            return ListToolsResult(tools=state.tools)

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            if state.failure is not None:
                raise state.failure
            state.calls.append((name, arguments))
            return state.result

    @asynccontextmanager
    async def mcp_session(url: str, headers: dict[str, str] | None):
        state.opened_with.append((url, headers))
        yield _Session()

    async def create(_db, **kwargs):
        state.asked.append(kwargs)

    async def write(**kwargs):
        state.notified.append(kwargs)

    monkeypatch.setattr(node, "get_worker_db_context", worker_session)
    monkeypatch.setattr(node, "mcp_session", mcp_session)
    monkeypatch.setattr(
        node.mcp_connection_repo,
        "get_org_scoped_by_id",
        AsyncMock(side_effect=lambda _db, **_kw: state.connection),
    )
    monkeypatch.setattr(
        node, "resolve_auth_headers", AsyncMock(side_effect=lambda _db, _c: state.headers)
    )
    monkeypatch.setattr(
        node.approval_repo,
        "get_for_node_run_for_update",
        AsyncMock(side_effect=lambda _db, _id: state.approval),
    )
    monkeypatch.setattr(node.approval_repo, "create", create)
    monkeypatch.setattr(node, "NotificationCenterService", lambda _db: SimpleNamespace(write=write))
    return state


def _config(tool: str = "find_lead", **overrides: Any) -> node.McpCallConfig:
    return node.McpCallConfig(connection_id=CONNECTION, tool=tool, **overrides)


async def _run(config: Any, arguments: dict[str, Any] | None = None):
    with context.dispatching_as(_dispatch()):
        return await node.handle(config, node.McpCallInput(arguments=arguments))


def _decided(status: WorkflowApprovalStatus) -> Any:
    return SimpleNamespace(status=status.value)


async def test_a_read_only_tool_is_called_with_its_arguments_and_answers(server):
    result = await _run(_config(), {"email": "a@b.co"})

    assert isinstance(result, Completed)
    assert result.output == node.McpCallOutput(
        text="Lead 42", structured={"id": 42}, is_error=False
    )
    assert server.calls == [("find_lead", {"email": "a@b.co"})]
    assert server.opened_with == [("https://mcp.example.com/mcp", {"Authorization": "Bearer t"})]
    assert server.asked == []


@pytest.mark.security
@pytest.mark.parametrize("tool", ["create_lead", "unmarked"])
async def test_a_tool_not_marked_read_only_waits_for_approval_without_being_called(server, tool):
    result = await _run(_config(tool, approvers=(APPROVER,)), {"name": "Ada"})

    assert isinstance(result, Waiting) and result.reason == "approval"
    assert server.calls == []
    request = server.asked[0]
    assert request["title"] == f"Call {tool} on Acme CRM?"
    assert '"name": "Ada"' in request["details"]
    assert request["approver_user_ids"] == [APPROVER]
    assert server.notified[0]["recipients"] == [APPROVER]


async def test_a_server_with_no_label_is_named_by_its_name(server):
    server.connection.label = None

    await _run(_config("create_lead"))

    assert server.asked[0]["title"] == "Call create_lead on crm?"


async def test_asking_for_every_call_asks_before_even_a_read(server):
    result = await _run(_config(approval="all"))

    assert isinstance(result, Waiting)
    assert server.calls == [] and server.opened_with == []
    assert server.notified == []


async def test_never_asking_calls_a_write_straight_away(server):
    result = await _run(_config("create_lead", approval="none"))

    assert isinstance(result, Completed)
    assert server.calls == [("create_lead", {})]


async def test_an_approved_call_is_made_without_asking_again(server):
    server.approval = _decided(WorkflowApprovalStatus.APPROVED)

    result = await _run(_config("create_lead"))

    assert isinstance(result, Completed)
    assert server.calls == [("create_lead", {})]
    assert server.asked == []


async def test_a_request_still_pending_keeps_the_step_waiting(server):
    server.approval = _decided(WorkflowApprovalStatus.PENDING)

    result = await _run(_config("create_lead"))

    assert isinstance(result, Waiting)
    assert server.calls == [] and server.asked == []


@pytest.mark.parametrize(
    "status", [WorkflowApprovalStatus.REJECTED, WorkflowApprovalStatus.EXPIRED]
)
async def test_a_call_not_approved_fails_the_step_uncalled(server, status):
    server.approval = _decided(status)

    result = await _run(_config("create_lead"))

    assert isinstance(result, Failed) and result.error.code == "MCP_CALL_REJECTED"
    assert server.calls == []


async def test_a_tool_the_server_does_not_offer_fails_rather_than_asking(server):
    result = await _run(_config("drop_tables"))

    assert isinstance(result, Failed) and result.error.code == "MCP_TOOL_NOT_FOUND"
    assert server.asked == []


@pytest.mark.security
@pytest.mark.parametrize("connection", [None, SimpleNamespace(is_enabled=False)])
async def test_a_server_that_is_not_the_organizations_or_is_off_is_not_reached(server, connection):
    server.connection = connection

    result = await _run(_config())

    assert isinstance(result, Failed) and result.error.code == "MCP_SERVER_UNAVAILABLE"
    assert server.opened_with == []


async def test_a_server_whose_credential_cannot_be_used_says_so(server):
    server.headers = None

    result = await _run(_config())

    assert isinstance(result, Failed) and result.error.code == "MCP_SERVER_UNAUTHORIZED"
    assert server.opened_with == []


async def test_an_error_the_tool_answers_with_fails_or_completes_as_configured(server):
    server.result = CallToolResult(
        content=[TextContent(type="text", text="No such lead")], is_error=True
    )

    failed = await _run(_config())
    kept = await _run(_config(on_tool_error="complete"))

    assert isinstance(failed, Failed) and failed.error.code == "MCP_TOOL_ERROR"
    assert failed.error.message == "No such lead"
    assert isinstance(kept, Completed) and kept.output.is_error is True


async def test_a_server_that_breaks_mid_call_fails_with_the_root_cause(server):
    server.failure = ExceptionGroup("task group", [ConnectionError("reset by peer")])

    result = await _run(_config())

    assert isinstance(result, Failed) and result.error.code == "MCP_CALL_FAILED"
    assert result.error.message == "reset by peer"


async def test_cancellation_inside_the_call_is_not_swallowed(server):
    server.failure = BaseExceptionGroup("task group", [asyncio.CancelledError()])

    with pytest.raises(BaseExceptionGroup):
        await _run(_config())


async def test_a_server_asking_for_more_than_a_workflow_can_give_fails(server):
    server.result = SimpleNamespace(content=[])

    result = await _run(_config())

    assert isinstance(result, Failed) and result.error.code == "MCP_CALL_FAILED"


async def test_only_text_parts_make_the_text_and_only_an_object_is_structured(server):
    server.result = CallToolResult(
        content=[
            TextContent(type="text", text="one"),
            TextContent(type="text", text="two"),
        ],
        structured_content=None,
    )

    result = await _run(_config())

    assert isinstance(result, Completed)
    assert result.output.text == "one\n\ntwo" and result.output.structured is None


async def test_a_step_with_no_config_fails():
    with context.dispatching_as(_dispatch()):
        result = await node.handle(None, None)

    assert isinstance(result, Failed) and result.error.code == "MCP_CALL_NOT_CONFIGURED"


class TestPublishing:
    @pytest.fixture
    def found(self, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        state = SimpleNamespace(
            connection=SimpleNamespace(is_enabled=True, last_tools=[{"name": "find_lead"}]),
            members={APPROVER},
        )
        monkeypatch.setattr(
            node.mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(side_effect=lambda _db, **_kw: state.connection),
        )
        monkeypatch.setattr(
            node.member_repo,
            "get_active",
            AsyncMock(
                side_effect=lambda _db, *, organization_id, user_id: (
                    object() if user_id in state.members else None
                )
            ),
        )
        return state

    async def _problems(self, config: Any) -> list[tuple[str, str]]:
        org = uuid.uuid4()
        ctx = AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner")
        return await node.check_resources(MagicMock(), ctx, config)

    async def test_an_organization_server_offering_the_tool_publishes(self, found):
        assert await self._problems(_config(approvers=(APPROVER,))) == []

    @pytest.mark.security
    async def test_a_server_that_is_not_the_organizations_is_refused(self, found):
        found.connection = None

        assert [field for field, _ in await self._problems(_config())] == ["connection_id"]

    async def test_a_server_turned_off_is_refused(self, found):
        found.connection.is_enabled = False

        assert [field for field, _ in await self._problems(_config())] == ["connection_id"]

    async def test_a_tool_the_last_test_did_not_list_is_refused(self, found):
        assert [field for field, _ in await self._problems(_config("drop_tables"))] == ["tool"]

    async def test_a_server_never_tested_cannot_be_held_to_a_list(self, found):
        found.connection.last_tools = None

        assert await self._problems(_config("anything")) == []

    async def test_an_approver_who_is_not_a_member_is_refused(self, found):
        stranger = uuid.uuid4()

        problems = await self._problems(_config(approvers=(APPROVER, stranger)))

        assert [field for field, _ in problems] == ["approvers.1"]

    async def test_another_steps_config_is_not_this_checks_business(self, found):
        assert await self._problems(SimpleNamespace()) == []
