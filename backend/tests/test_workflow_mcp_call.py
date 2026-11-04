"""`mcp.call` around a stubbed server: what it calls, when it asks first, and what it refuses."""

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
    ImageContent,
    ListToolsResult,
    TextContent,
    Tool,
    ToolAnnotations,
)

from app.core.permissions import AuthContext
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.repositories import mcp_connection_repo
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, Uncertain, Waiting
from app.workflows.nodes.mcp_call import _handler as node

pytestmark = pytest.mark.anyio

CONNECTION = uuid.uuid4()
APPROVER = uuid.uuid4()


def _dispatch(idempotency_key: str = "op-key-1") -> context.DispatchContext:
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
        idempotency_key=idempotency_key,
    )


def _tool(name: str, *, read_only: bool | None, input_schema: dict[str, Any] | None = None) -> Tool:
    return Tool(
        name=name,
        input_schema=input_schema or {"type": "object"},
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
            visibility="org",
            allowed_tools=None,
            last_tools=[{"name": "find_lead"}, {"name": "create_lead"}],
        )
    )
    headers: dict[str, str] | None = field(
        default_factory=lambda: {"Authorization": "Bearer fixture-credential-9382"}
    )
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
    connect_failure: BaseException | None = None
    delay: float = 0
    attempted: int = 0
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
            state.attempted += 1
            if state.failure is not None:
                raise state.failure
            if state.delay:
                await asyncio.sleep(state.delay)
            state.calls.append((name, arguments))
            return state.result

    @asynccontextmanager
    async def mcp_session(url: str, headers: dict[str, str] | None):
        state.opened_with.append((url, headers))
        if state.connect_failure is not None:
            raise state.connect_failure
        yield _Session()

    async def create(_db, **kwargs):
        state.asked.append(kwargs)

    async def write(**kwargs):
        state.notified.append(kwargs)

    monkeypatch.setattr(node, "get_worker_db_context", worker_session)
    monkeypatch.setattr(node, "mcp_session", mcp_session)
    monkeypatch.setattr(
        mcp_connection_repo,
        "get_org_scoped_by_id",
        AsyncMock(side_effect=lambda _db, **_kw: state.connection),
    )
    monkeypatch.setattr(
        node, "resolve_auth_headers", AsyncMock(side_effect=lambda _c: state.headers)
    )
    monkeypatch.setattr(
        node.approval_repo,
        "get_for_node_run_for_update",
        AsyncMock(side_effect=lambda _db, _id: state.approval),
    )
    monkeypatch.setattr(node.approval_repo, "create", create)
    monkeypatch.setattr(node, "NotificationCenterService", lambda _db: SimpleNamespace(write=write))
    monkeypatch.setattr(
        node.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace(role="owner"))
    )
    return state


def _config(tool: str = "find_lead", **overrides: Any) -> node.McpCallConfig:
    return node.McpCallConfig(connection_id=CONNECTION, tool=tool, **overrides)


async def _run(config: Any, arguments: dict[str, Any] | None = None, *, key: str = "op-key-1"):
    with context.dispatching_as(_dispatch(key)):
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
    assert server.opened_with == [
        ("https://mcp.example.com/mcp", {"Authorization": "Bearer fixture-credential-9382"})
    ]
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
    server.connection.allowed_tools = ["create_lead"]
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
@pytest.mark.parametrize("connection", [None, SimpleNamespace(is_enabled=False, visibility="org")])
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


_BROKEN = ExceptionGroup("task group", [ConnectionError("reset by peer")])
_KEYED = {
    "type": "object",
    "properties": {"request_id": {"type": "string"}, "count": {"type": "integer"}},
}


def _keyed_tool(name: str = "create_lead", **kwargs: Any) -> Tool:
    return _tool(name, read_only=False, input_schema=_KEYED, **kwargs)


def _failure(result: Any) -> Failed:
    assert isinstance(result, Failed)
    return result


async def test_a_server_that_cannot_be_reached_fails_for_a_retry(server):
    server.connect_failure = ExceptionGroup("task group", [ConnectionError("refused")])

    result = _failure(await _run(_config("create_lead", approval="none")))

    assert result.error.code == "MCP_CALL_FAILED" and result.error.retryable is True
    assert result.error.message == "refused"
    assert server.attempted == 0


async def test_an_unkeyed_write_that_breaks_mid_call_is_uncertain(server):
    server.failure = _BROKEN

    result = await _run(_config("create_lead", approval="none"))

    assert isinstance(result, Uncertain)
    assert result.detail == "The tool was called and no answer came back; it may have acted"
    assert "reset by peer" not in result.detail and server.attempted == 1


async def test_a_keyed_write_that_breaks_mid_call_fails_for_a_retry(server):
    server.failure = _BROKEN
    server.tools = [_keyed_tool()]

    result = _failure(
        await _run(_config("create_lead", approval="none", idempotency_key_argument="request_id"))
    )

    assert result.error.code == "MCP_CALL_FAILED" and result.error.retryable is True
    assert result.error.message == "reset by peer"


async def test_a_read_only_tool_that_breaks_mid_call_fails_for_a_retry(server):
    server.failure = _BROKEN

    result = _failure(await _run(_config()))

    assert result.error.code == "MCP_CALL_FAILED" and result.error.retryable is True
    assert result.error.message == "reset by peer" and server.attempted == 1


async def test_a_tool_recorded_read_only_is_retried_without_listing(server):
    server.connection.last_tools = [{"name": "find_lead", "read_only": True}]
    server.failure = _BROKEN
    server.tools = []  # a listing would say the tool is gone

    result = _failure(await _run(_config(approval="none")))

    assert result.error.retryable is True and server.attempted == 1


async def test_the_listing_is_read_before_the_recorded_mark(server):
    server.connection.last_tools = [{"name": "find_lead", "read_only": False}]
    server.failure = _BROKEN

    result = _failure(await _run(_config()))  # approval "writes" lists the tools

    assert result.error.retryable is True


async def test_a_tool_recorded_read_only_but_listed_a_write_is_asked_not_called(server):
    # The live listing wins, so an unkeyed call is never made on a stale read-only mark -
    # and so no failure after the call can be judged retryable by it.
    server.connection.last_tools = [{"name": "create_lead", "read_only": True}]
    server.failure = _BROKEN

    result = await _run(_config("create_lead"))

    assert isinstance(result, Waiting) and server.attempted == 0


async def test_an_approved_write_resumed_on_a_stale_read_only_record_is_still_a_write(server):
    # The first dispatch asked because the live listing said "write". The resume
    # does not list again, so the stale record must not turn the failure after the
    # call into a retry - that would send the write twice.
    server.connection.last_tools = [{"name": "create_lead", "read_only": True}]
    server.failure = _BROKEN
    server.approval = _decided(WorkflowApprovalStatus.APPROVED)

    result = await _run(_config("create_lead"))

    assert isinstance(result, Uncertain) and server.attempted == 1


async def test_a_timeout_after_the_call_is_classified_like_a_break(server):
    server.delay = 5
    unkeyed = _config("create_lead", approval="none").model_copy(update={"timeout_seconds": 0.01})
    read = _config().model_copy(update={"timeout_seconds": 0.01})

    assert isinstance(await _run(unkeyed), Uncertain)
    assert _failure(await _run(read)).error.retryable is True


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
            ImageContent(type="image", data="aGk=", mimeType="image/png"),
            TextContent(type="text", text="two"),
        ],
        structured_content=None,
    )

    result = await _run(_config())

    assert isinstance(result, Completed)
    assert result.output.text == "one\n\ntwo" and result.output.structured is None


async def test_parts_past_the_cap_are_never_read_or_joined(server):
    # A part built without its text raises if anything reads it: the old code joined
    # every part before slicing, and so did.
    unread = TextContent.model_construct(type="text")
    server.result = CallToolResult(
        content=[TextContent(type="text", text="x" * (node.MAX_TEXT * 3)), unread, unread],
        structured_content=None,
    )

    result = await _run(_config())

    assert isinstance(result, Completed) and len(result.output.text) == node.MAX_TEXT


async def test_a_structured_answer_over_the_cap_fails_instead_of_being_stored(server, monkeypatch):
    monkeypatch.setattr(node, "MAX_STRUCTURED_BYTES", 20)
    server.result = CallToolResult(
        content=[TextContent(type="text", text="ok")], structured_content={"rows": "y" * 100}
    )

    result = await _run(_config())

    assert isinstance(result, Failed) and result.error.code == "MCP_RESULT_TOO_LARGE"


async def test_a_step_with_no_config_fails():
    with context.dispatching_as(_dispatch()):
        result = await node.handle(None, None)

    assert isinstance(result, Failed) and result.error.code == "MCP_CALL_NOT_CONFIGURED"


class TestPublishing:
    @pytest.fixture
    def found(self, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        state = SimpleNamespace(
            connection=SimpleNamespace(
                is_enabled=True,
                visibility="org",
                allowed_tools=None,
                last_tools=[{"name": "find_lead"}],
            ),
            members={APPROVER},
            role="owner",
        )
        monkeypatch.setattr(
            mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(side_effect=lambda _db, **_kw: state.connection),
        )
        monkeypatch.setattr(
            node.member_repo,
            "get_active",
            AsyncMock(
                side_effect=lambda _db, *, organization_id, user_id: (
                    SimpleNamespace(role=state.role) if user_id in state.members else None
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

    @pytest.mark.parametrize("role", ["member", "builder"])
    @pytest.mark.security
    async def test_an_approver_without_decision_permission_is_refused(self, found, role):
        found.role = role
        problems = await self._problems(_config(approvers=(APPROVER,)))
        assert [field for field, _ in problems] == ["approvers.0"]

    async def test_an_approver_who_is_not_a_member_is_refused(self, found):
        stranger = uuid.uuid4()

        problems = await self._problems(_config(approvers=(APPROVER, stranger)))

        assert [field for field, _ in problems] == ["approvers.1"]

    async def test_another_steps_config_is_not_this_checks_business(self, found):
        assert await self._problems(SimpleNamespace()) == []


@pytest.mark.parametrize("approval", ["all", "writes"])
@pytest.mark.parametrize("role", ["member", "builder"])
async def test_an_ineligible_named_approver_fails_before_parking(
    server, monkeypatch, approval, role
):
    monkeypatch.setattr(
        node.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace(role=role))
    )
    result = await _run(_config("create_lead", approval=approval, approvers=(APPROVER,)))
    assert isinstance(result, Failed) and result.error.code == "APPROVER_UNAVAILABLE"
    assert server.asked == [] and server.notified == [] and server.calls == []


@pytest.mark.security
@pytest.mark.parametrize("scheme", ["Bearer", "Basic", "X-Api-Key"])
async def test_credentials_are_removed_from_text_and_nested_tool_data(server, scheme):
    import base64
    from urllib.parse import quote

    token = "sensitive+/credential=42"
    value = (
        "Bearer " + token
        if scheme == "Bearer"
        else "Basic " + base64.b64encode(("user:" + token).encode()).decode()
        if scheme == "Basic"
        else token
    )
    server.headers = {"Authorization" if scheme != "X-Api-Key" else scheme: value}
    server.result = CallToolResult(
        content=[
            TextContent(
                type="text",
                text=f"Header: {value}; token: {token}; encoded: {quote(token, safe='')}",
            )
        ],
        structured_content={token: {"items": [value, token, True, 42, None]}},
    )
    result = await _run(_config())
    assert isinstance(result, Completed)
    serialized = result.output.model_dump_json()
    assert token not in serialized and value not in serialized
    assert quote(token, safe="") not in serialized
    assert "[redacted]" in result.output.text
    assert result.output.structured == {
        "[redacted]": {"items": ["[redacted]", "[redacted]", True, 42, None]}
    }


@pytest.mark.parametrize("header", ["Basic not-base64!", "Basic /w==", "Basic dXNlcg==", "Bearer "])
async def test_malformed_basic_headers_do_not_break_result_redaction(server, header):
    server.headers = {"Authorization": header, "Empty": ""}
    result = await _run(_config())
    assert isinstance(result, Completed)


async def test_non_json_structured_tool_data_is_a_typed_refusal(server):
    server.result = CallToolResult(content=[], structured_content={"bad": object()})
    result = await _run(_config())
    assert isinstance(result, Failed) and result.error.code == "MCP_RESULT_INVALID"


@pytest.mark.security
async def test_a_credential_crossing_the_text_cap_is_scrubbed_before_truncation(
    server, monkeypatch
):
    token = "credential-crossing-the-boundary"
    server.headers = {"Authorization": "Bearer " + token}
    monkeypatch.setattr(node, "MAX_TEXT", 40)
    server.result = CallToolResult(content=[TextContent(type="text", text="x" * 12 + token)])
    result = await _run(_config())
    assert isinstance(result, Completed)
    assert token[:-5] not in result.output.text
    assert result.output.text == "x" * 12 + "[redacted]"


async def test_an_unauthenticated_mcp_connection_preserves_ordinary_tool_output(server):
    server.headers = {}
    server.result = CallToolResult(
        content=[TextContent(type="text", text="Public information")],
        structured_content={"rows": [True, 42, None, "public"]},
    )
    result = await _run(_config())
    assert isinstance(result, Completed)
    assert result.output.text == "Public information"
    assert result.output.structured == {"rows": [True, 42, None, "public"]}
    assert server.opened_with == [("https://mcp.example.com/mcp", {})]


@pytest.mark.security
@pytest.mark.parametrize("allowed", [[], ["find_lead"]])
async def test_a_tool_outside_the_connections_allowlist_never_unseals_credentials(
    server, allowed, monkeypatch
):
    server.connection.allowed_tools = allowed
    headers = AsyncMock(
        side_effect=AssertionError("An unauthorized tool must not unseal credentials")
    )
    monkeypatch.setattr(node, "resolve_auth_headers", headers)
    with context.dispatching_as(_dispatch()):
        result = await node.handle(_config("create_lead", approval="none"), None)
    assert isinstance(result, Failed) and result.error.code == "MCP_TOOL_NOT_ALLOWED"
    assert server.calls == server.opened_with == []
    headers.assert_not_awaited()


@pytest.mark.security
async def test_publish_refuses_a_cached_tool_outside_the_connections_allowlist(server):
    server.connection.allowed_tools = []
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    assert await node.check_resources(MagicMock(), ctx, _config()) == [
        ("tool", "This tool is not allowed on this MCP connection")
    ]


class TestIdempotencyKey:
    def _keyed(self, server, **overrides: Any) -> node.McpCallConfig:
        server.tools = [_keyed_tool()]
        return _config(
            "create_lead", approval="none", idempotency_key_argument="request_id", **overrides
        )

    async def test_a_keyed_call_sends_the_steps_key_in_the_named_argument(self, server):
        result = await _run(self._keyed(server), {"name": "Ada"}, key="op-7")

        assert isinstance(result, Completed)
        assert server.calls == [("create_lead", {"name": "Ada", "request_id": "op-7"})]

    @pytest.mark.security
    async def test_the_steps_key_wins_over_a_bound_value_of_the_same_argument(self, server):
        await _run(self._keyed(server), {"request_id": "chosen-by-a-binding"}, key="op-7")

        assert server.calls == [("create_lead", {"request_id": "op-7"})]

    async def test_a_retry_sends_the_same_key(self, server):
        config = self._keyed(server)

        await _run(config, key="op-7")
        await _run(config, key="op-7")
        await _run(config, key="op-8")

        assert [args["request_id"] for _, args in server.calls] == ["op-7", "op-7", "op-8"]

    @pytest.mark.parametrize(
        "schema",
        [
            {"type": "object"},
            {"type": "object", "properties": {"request_id": {"type": "integer"}}},
            {"type": "object", "properties": {"request_id": "string"}},
        ],
    )
    async def test_a_key_argument_the_tool_does_not_declare_fails_before_calling(
        self, server, schema
    ):
        server.tools = [_tool("create_lead", read_only=False, input_schema=schema)]

        result = _failure(
            await _run(
                _config("create_lead", approval="none", idempotency_key_argument="request_id")
            )
        )

        assert result.error.code == "MCP_IDEMPOTENCY_ARGUMENT_UNDECLARED"
        assert result.error.retryable is False
        assert "op-key-1" not in result.error.model_dump_json()
        assert server.calls == [] and server.attempted == 0

    @pytest.mark.parametrize("schema", [{"properties": ["request_id"]}, {"properties": "x"}])
    async def test_a_malformed_schema_declares_nothing_at_run_time(self, server, schema):
        server.tools = [_tool("create_lead", read_only=False, input_schema=schema)]

        result = _failure(
            await _run(
                _config("create_lead", approval="none", idempotency_key_argument="request_id")
            )
        )

        assert result.error.code == "MCP_IDEMPOTENCY_ARGUMENT_UNDECLARED"
        assert server.attempted == 0

    @pytest.mark.parametrize("declared", [{}, {"type": ["null", "string"]}, {"type": "string"}])
    async def test_a_text_or_untyped_property_is_declared(self, server, declared):
        server.tools = [
            _tool(
                "create_lead",
                read_only=False,
                input_schema={"properties": {"request_id": declared}},
            )
        ]

        result = await _run(
            _config("create_lead", approval="none", idempotency_key_argument="request_id")
        )

        assert isinstance(result, Completed)

    async def test_a_keyed_call_lists_the_tools_even_without_approval(self, server):
        server.tools = []

        result = _failure(
            await _run(
                _config("create_lead", approval="none", idempotency_key_argument="request_id")
            )
        )

        assert result.error.code == "MCP_TOOL_NOT_FOUND" and server.attempted == 0

    @pytest.mark.security
    async def test_the_key_never_reaches_the_approval_details(self, server):
        server.tools = [_keyed_tool()]
        result = await _run(
            _config("create_lead", idempotency_key_argument="request_id"),
            {"name": "Ada"},
            key="op-secret-key",
        )

        assert isinstance(result, Waiting)
        assert "op-secret-key" not in server.asked[0]["details"]
        assert "request_id" not in server.asked[0]["details"]

    async def test_a_keyed_step_is_idempotent_and_an_unkeyed_one_at_least_once(self):
        assert node.retry_guarantee_for(_config()) == "at_least_once"
        assert node.retry_guarantee_for(None) == "at_least_once"
        assert (
            node.retry_guarantee_for(_config(idempotency_key_argument="request_id")) == "idempotent"
        )

    @pytest.mark.parametrize("name", ["a b", "", "1abc", "x" * 65, "a;b"])
    def test_a_key_argument_that_is_not_a_name_is_refused(self, name):
        with pytest.raises(ValueError):
            _config(idempotency_key_argument=name)


class TestPublishingAKeyArgument:
    @pytest.fixture
    def found(self, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        state = SimpleNamespace(
            connection=SimpleNamespace(
                is_enabled=True,
                visibility="org",
                allowed_tools=None,
                last_tools=[{"name": "create_lead", "input_schema": _KEYED}],
            )
        )
        monkeypatch.setattr(
            mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(side_effect=lambda _db, **_kw: state.connection),
        )
        return state

    async def _problems(self, config: Any) -> list[tuple[str, str]]:
        ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
        return await node.check_resources(MagicMock(), ctx, config)

    def _keyed(self, argument: str) -> node.McpCallConfig:
        return _config("create_lead", idempotency_key_argument=argument)

    async def test_publish_accepts_a_declared_text_argument(self, found):
        assert await self._problems(self._keyed("request_id")) == []

    @pytest.mark.parametrize("argument", ["missing", "count"])
    async def test_publish_refuses_a_key_argument_the_recorded_tool_does_not_take(
        self, found, argument
    ):
        assert await self._problems(self._keyed(argument)) == [
            ("idempotency_key_argument", "The tool does not take this argument as text")
        ]

    async def test_publish_accepts_a_key_argument_when_the_schema_was_not_recorded(self, found):
        found.connection.last_tools = [{"name": "create_lead"}]
        assert await self._problems(self._keyed("anything")) == []

    @pytest.mark.parametrize("schema", [{"properties": ["request_id"]}, {"properties": None}])
    async def test_publish_refuses_a_malformed_schema_without_raising(self, found, schema):
        found.connection.last_tools = [{"name": "create_lead", "input_schema": schema}]
        assert [f for f, _ in await self._problems(self._keyed("request_id"))] == [
            "idempotency_key_argument"
        ]

    async def test_publish_does_not_hold_a_server_never_tested_to_a_schema(self, found):
        found.connection.last_tools = None
        assert await self._problems(self._keyed("anything")) == []

    async def test_a_tool_the_list_lacks_is_one_problem_not_two(self, found):
        problems = await self._problems(
            _config("drop_tables", idempotency_key_argument="request_id")
        )
        assert [field for field, _ in problems] == ["tool"]
