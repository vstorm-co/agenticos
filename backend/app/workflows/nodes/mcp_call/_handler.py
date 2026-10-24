"""`mcp.call`: call one tool on one of the organization's MCP servers.

The step names a connection and a tool, and its arguments are bound from earlier
steps. The connection must be the organization's own - never a member's, for the
reason a published agent may not bind one: a workflow's reach cannot depend on
whose account happens to start it - and enabled when the step runs. Its headers
come from the vault exactly as an agent's toolset gets them.

A tool that changes something can wait for a person first. `approval` decides
which: `writes` (the default) asks before every tool the server does not mark
read-only, `all` before any, `none` never. Asking writes a `workflow_approvals`
request keyed by the step's `NodeRun` - the one `human.approval` writes, so the
same inbox, decision and wake apply - and the step calls the tool once the
request is approved, or fails with `MCP_CALL_REJECTED`. A server's read-only mark
is its own claim; `all` is for a server that is not trusted to make it.

A crash after the call and before the step settles calls the tool again on the
retry: MCP has no idempotency key to send, so the step is at least once.
"""

import asyncio
import base64
import binascii
import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote, quote_plus
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import carries_base_exception, mcp_session, probe_error_message
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm, role_has
from app.db.models.mcp_connection import McpConnection
from app.db.models.notification import NotificationChannel, NotificationEventType
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.db.session import get_worker_db_context
from app.repositories import member as member_repo
from app.repositories import workflow_approval as approval_repo
from app.services.mcp_connection import McpConnectionService, resolve_auth_headers
from app.services.notification_center import NotificationCenterService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError

if TYPE_CHECKING:
    from mcp.types import CallToolResult

MAX_TEXT = 100_000
"""The most of a tool's text answer a step keeps - a page, not a dump."""

MAX_STRUCTURED_BYTES = 1_048_576
"""The most a tool's structured answer may take as JSON. The answer is stored with the
step's attempt, so a larger one fails the step instead of being kept."""


class McpCallConfig(BaseModel):
    """Which server, which tool, and when a person approves the call first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connection_id: UUID = Field(
        title="Server",
        json_schema_extra={"x-resource": "mcp_connection"},
        description="One of the organization's MCP servers.",
    )
    tool: str = Field(
        min_length=1,
        max_length=200,
        json_schema_extra={"x-mcp-tool": "connection_id"},
        description="The tool to call, as the server names it.",
    )
    approval: Literal["writes", "all", "none"] = Field(
        default="writes",
        title="Ask for approval",
        description="Before a tool the server does not mark read-only, before every call, "
        "or never.",
        json_schema_extra={
            "x-enum-labels": {
                "writes": "Before a tool that can change something",
                "all": "Before every call",
                "none": "Never",
            }
        },
    )
    approvers: tuple[UUID, ...] = Field(
        default=(),
        max_length=50,
        json_schema_extra={"x-resource": "member"},
        title="Approvers",
        description="Who may approve the call. Anyone who decides approvals when empty.",
    )
    timeout_seconds: int = Field(
        default=60, ge=1, le=300, description="How long the tool may take to answer."
    )
    on_tool_error: Literal["fail", "complete"] = Field(
        default="fail",
        title="When the tool answers with an error",
        description="Whether an error the tool answers with fails the step or is its output.",
        json_schema_extra={
            "x-enum-labels": {"fail": "Fail the step", "complete": "Hand the error on"}
        },
    )


class McpCallInput(BaseModel):
    """The tool's arguments, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arguments: dict[str, Any] | None = Field(
        default=None, description="An object matching the tool's own input schema."
    )


class McpCallOutput(BaseModel):
    """What the tool answered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(description="The answer's text, every text part joined")
    structured: dict[str, Any] | None = Field(
        default=None, description="The answer as data, when the tool returns some"
    )
    is_error: bool = Field(description="Whether the tool answered with an error")


async def _connection(
    db: AsyncSession, ctx: AuthContext, connection_id: UUID
) -> McpConnection | None:
    try:
        return await McpConnectionService(db).get_org_connection(ctx, connection_id)
    except NotFoundError:
        return None


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a server that is not the organization's own, and a tool it did not offer."""
    if not isinstance(config, McpCallConfig):
        return []
    problems: list[tuple[str, str]] = []
    connection = await _connection(db, ctx, config.connection_id)
    if connection is None:
        problems.append(("connection_id", "This is not one of the organization's MCP servers"))
    elif not connection.is_enabled:
        problems.append(("connection_id", "This MCP server is turned off"))
    elif connection.allowed_tools is not None and config.tool not in connection.allowed_tools:
        problems.append(("tool", "This tool is not allowed on this MCP connection"))
    elif connection.last_tools is not None and config.tool not in {
        tool.get("name") for tool in connection.last_tools
    }:
        problems.append(("tool", "The server did not offer this tool when it was last tested"))
    problems.extend(await _approver_problems(db, ctx, config))
    return problems


async def _approver_problems(
    db: AsyncSession, ctx: AuthContext, config: McpCallConfig
) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    for index, user_id in enumerate(config.approvers):
        member = await member_repo.get_active(
            db, organization_id=ctx.organization_id, user_id=user_id
        )
        if member is None:
            problems.append(
                (f"approvers.{index}", "This person is not a member of the organization")
            )
        elif not role_has(member.role, Perm.APPROVALS_DECIDE):
            problems.append(
                (f"approvers.{index}", "This person cannot decide approvals in the organization")
            )
    return problems


def _failed(code: str, message: str, **details: str) -> Failed:
    return Failed(error=WorkflowError(code=code, message=message, details=dict(details)))


def _credential_forms(headers: dict[str, str]) -> tuple[str, ...]:
    forms: set[str] = set()
    for value in headers.values():
        if not value:
            continue
        forms.add(value)
        scheme, _, credential = value.partition(" ")
        if scheme.lower() in {"bearer", "basic"} and credential:
            forms.add(credential)
            if scheme.lower() == "basic":
                try:
                    decoded = base64.b64decode(credential, validate=True).decode()
                except binascii.Error, UnicodeDecodeError:
                    continue
                forms.add(decoded)
                password = decoded.partition(":")[2]
                if password:
                    forms.add(password)
    forms |= {quote(value, safe="") for value in forms} | {
        quote_plus(value, safe="") for value in forms
    }
    return tuple(sorted(forms, key=len, reverse=True))


def _scrub_text(text: str, forms: tuple[str, ...]) -> str:
    for value in forms:
        text = text.replace(value, "[redacted]")
    return text


def _scrub_data(value: JsonValue, forms: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return _scrub_text(value, forms)
    if isinstance(value, list):
        return [_scrub_data(item, forms) for item in value]
    if isinstance(value, dict):
        return {_scrub_text(key, forms): _scrub_data(item, forms) for key, item in value.items()}
    return value


def _answer(result: CallToolResult, forms: tuple[str, ...] = ()) -> McpCallOutput | Failed:
    """A `CallToolResult` as the step's output: its text parts, its data, its error flag.

    Text is joined only up to `MAX_TEXT`, so a server's gigabyte of parts costs no more
    than the page kept. Data past `MAX_STRUCTURED_BYTES` fails the step with
    `MCP_RESULT_TOO_LARGE`.
    """
    from mcp.types import TextContent

    pieces: list[str] = []
    size = 0
    for part in result.content:
        if size >= MAX_TEXT:
            break
        if isinstance(part, TextContent):
            # Look beyond the display boundary before truncating, so a token
            # crossing it cannot leave an almost-complete credential behind.
            lookahead = max((len(value) for value in forms), default=0)
            pieces.append(_scrub_text(part.text[: MAX_TEXT + lookahead], forms)[:MAX_TEXT])
            size += len(pieces[-1]) + 2
    structured = result.structured_content
    if isinstance(structured, dict) and (
        len(json.dumps(structured, default=str)) > MAX_STRUCTURED_BYTES
    ):
        return _failed(
            "MCP_RESULT_TOO_LARGE",
            f"The tool's structured answer is larger than {MAX_STRUCTURED_BYTES} bytes",
            limit_bytes=str(MAX_STRUCTURED_BYTES),
        )
    try:
        scrubbed = _scrub_data(TypeAdapter(JsonValue).validate_python(structured), forms)
    except ValidationError:
        return _failed("MCP_RESULT_INVALID", "The tool's structured answer is not JSON")
    return McpCallOutput(
        text=_scrub_text("\n\n".join(pieces)[:MAX_TEXT], forms),
        structured=scrubbed if isinstance(scrubbed, dict) else None,
        is_error=bool(result.is_error),
    )


async def _call(
    config: McpCallConfig,
    url: str,
    headers: dict[str, str],
    arguments: dict[str, Any] | None,
    *,
    ask_first: bool,
) -> McpCallOutput | Literal["ask"] | Failed:
    """Call the tool - or, when `ask_first` and the server does not mark it
    read-only, report `"ask"` without calling it."""
    from mcp.types import CallToolResult

    try:
        async with asyncio.timeout(config.timeout_seconds), mcp_session(url, headers) as session:
            if ask_first:
                listed = await session.list_tools()
                tool = next((tool for tool in listed.tools if tool.name == config.tool), None)
                if tool is None:
                    return _failed(
                        "MCP_TOOL_NOT_FOUND",
                        "The server does not offer this tool",
                        tool=config.tool,
                    )
                if not (tool.annotations is not None and tool.annotations.read_only_hint):
                    return "ask"
            result = await session.call_tool(config.tool, arguments or {})
    except (Exception, BaseExceptionGroup) as exc:
        if carries_base_exception(exc):
            raise
        return _failed("MCP_CALL_FAILED", probe_error_message(exc), tool=config.tool)
    if not isinstance(result, CallToolResult):
        return _failed(
            "MCP_CALL_FAILED",
            "The server asked for more before answering, which a workflow cannot give",
            tool=config.tool,
        )
    return _answer(result, _credential_forms(headers))


async def _ask(
    db: AsyncSession, config: McpCallConfig, server: str, arguments: dict[str, Any] | None
) -> Failed | None:
    current = context.current()
    if await _approver_problems(db, current.auth, config):
        return _failed("APPROVER_UNAVAILABLE", "A named approver can no longer decide approvals")
    if current.workflow_id is None:  # pragma: no cover - every dispatch carries its workflow
        raise RuntimeError("A workflow step dispatched with no workflow")
    title = f"Call {config.tool} on {server}?"[:200]
    await approval_repo.create(
        db,
        organization_id=current.organization_id,
        workflow_id=current.workflow_id,
        workflow_run_id=current.workflow_run_id,
        node_run_id=current.node_run_id,
        title=title,
        details=json.dumps(arguments or {}, indent=2, default=str)[:4000],
        approver_user_ids=list(config.approvers),
        expires_at=None,
    )
    if config.approvers:
        await NotificationCenterService(db).write(
            recipients=list(dict.fromkeys(config.approvers)),
            event_type=NotificationEventType.WORKFLOW_NOTIFICATION,
            occurrence_id="workflow-approval:"
            + hashlib.sha256(current.idempotency_key.encode()).hexdigest(),
            summary=f"Approval needed: {title}",
            organization_id=current.organization_id,
            actor_user_id=current.auth.user_id,
            channels={NotificationChannel.IN_APP},
        )
    return None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Call the tool, ask before calling it, or act on the answer to asking."""
    if not isinstance(config, McpCallConfig):
        return _failed("MCP_CALL_NOT_CONFIGURED", "This step names no server or tool")
    arguments = node_input.arguments if isinstance(node_input, McpCallInput) else None
    current = context.current()
    async with get_worker_db_context() as db:
        connection = await _connection(db, current.auth, config.connection_id)
        if connection is None or not connection.is_enabled:
            return _failed(
                "MCP_SERVER_UNAVAILABLE",
                "The MCP server is gone or turned off",
                connection_id=str(config.connection_id),
            )
        if connection.allowed_tools is not None and config.tool not in connection.allowed_tools:
            return _failed(
                "MCP_TOOL_NOT_ALLOWED",
                "This tool is not allowed on this MCP connection",
                tool=config.tool,
            )
        headers = await resolve_auth_headers(db, connection)
        if headers is None:
            return _failed(
                "MCP_SERVER_UNAUTHORIZED",
                "The MCP server needs to be authorized again",
                connection_id=str(config.connection_id),
            )
        # Read now: the session closes before the call, and the row with it.
        url, server = connection.url, connection.label or connection.name
        approval = await approval_repo.get_for_node_run_for_update(db, current.node_run_id)
        if approval is not None and approval.status == WorkflowApprovalStatus.PENDING.value:
            return Waiting(reason="approval", resume_token=str(current.node_run_id))
        if approval is not None and approval.status != WorkflowApprovalStatus.APPROVED.value:
            return _failed(
                "MCP_CALL_REJECTED",
                "The call was not approved",
                tool=config.tool,
            )
        if approval is None and config.approval == "all":
            refused = await _ask(db, config, server, arguments)
            if refused is not None:
                return refused
            return Waiting(reason="approval", resume_token=str(current.node_run_id))
    answer = await _call(
        config,
        url,
        headers,
        arguments,
        ask_first=approval is None and config.approval == "writes",
    )
    if answer == "ask":
        async with get_worker_db_context() as db:
            refused = await _ask(db, config, server, arguments)
            if refused is not None:
                return refused
        return Waiting(reason="approval", resume_token=str(current.node_run_id))
    if isinstance(answer, Failed):
        return answer
    if answer.is_error and config.on_tool_error == "fail":
        return _failed("MCP_TOOL_ERROR", answer.text[:500] or "The tool answered with an error")
    return Completed[McpCallOutput](output=answer)
