"""The MCP Apps page shown with a tool call, and the calls it makes back (#3450).

A page is a server's own HTML, written for the MCP Apps bridge. It runs in the
reader's browser under the app sandbox - an opaque origin, no network - so it
cannot reach its server; the console relays what it asks for through here:

- **The page itself**, read from the server on every load through a signed
  address (:meth:`McpAppService.frame`, then :meth:`McpAppService.page`).
- **Its tool calls** (:meth:`McpAppService.call_tool`), held to what the run that
  made the original call allowed: the binding's tools and approvals, recorded with
  the call, and the connection as it is now. A call that would wait for a person
  is refused, never run: an approval card belongs to the conversation, and a
  page is not a way around one.
- **Its resource reads** (:meth:`McpAppService.read_resource`), `ui://` only.

Everything is decided per request against a stored call the reader may see. A
page reaches only the connection its call was made through, and a person's own
connection only for that person.
"""

import base64
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic_ai.mcp import MCPError, MCPToolset
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import CONNECT_TIMEOUT_SECS, approval_needed, carries_base_exception
from app.agents.mcp_apps import (
    APP_MIME_TYPE,
    McpAppRecord,
    app_client,
    stored_record,
    visible_to_model,
)
from app.core.audit import record_audit
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.core.security import create_mcp_app_view_token, read_uuid_claim, verify_special_token
from app.db.models.conversation import ToolCall
from app.db.models.mcp_connection import McpConnection
from app.repositories import conversation as conversation_repo
from app.repositories import mcp_connection as mcp_connection_repo
from app.services.artifact import content_address
from app.services.conversation import ConversationService
from app.services.mcp_connection import resolve_auth_headers

logger = logging.getLogger(__name__)

PAGE_ADDRESS_LIFETIME = timedelta(minutes=5)
"""How long a page's signed address may be loaded: one frame's load and a reload or two."""

_GONE = "This page is not available"


@dataclass(frozen=True)
class McpAppFrame:
    """Where the console frames a call's page."""

    url: str


@dataclass(frozen=True)
class McpAppPage:
    """A page as read from its server, ready to serve."""

    document: bytes


class McpAppService:
    """Pages of MCP tool calls, and the calls they make back."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def frame(
        self, ctx: AuthContext, *, conversation_id: UUID, tool_call_id: str
    ) -> McpAppFrame:
        """A signed address for the page of a call in a conversation the reader may read.

        Raises:
            NotFoundError: No readable conversation, no such call with a page, or
                its connection no longer shows pages to this reader.
        """
        call, _, _ = await self._authorized(
            ctx, conversation_id=conversation_id, tool_call_id=tool_call_id
        )
        token = create_mcp_app_view_token(
            call.id,
            user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            expires_in=PAGE_ADDRESS_LIFETIME,
        )
        return McpAppFrame(url=content_address(f"mcp-app/{token}"))

    async def page(self, token: str) -> McpAppPage:
        """The page behind a signed address, read from its server now.

        The address carries who it was minted for; the connection is checked
        again here, so a page switched off since does not load.

        Raises:
            NotFoundError: The address is invalid or expired, the call or its
                connection is gone, or the server has no such page.
            ExternalServiceError: The server could not be reached.
        """
        payload = verify_special_token(token, "mcp_app_view")
        call_id = read_uuid_claim(payload, "sub") if payload is not None else None
        user_id = read_uuid_claim(payload, "uid") if payload is not None else None
        organization_id = read_uuid_claim(payload, "org") if payload is not None else None
        if call_id is None or user_id is None or organization_id is None:
            raise NotFoundError(message=_GONE)
        call = await conversation_repo.get_app_tool_call_by_id(self.db, call_id)
        record = stored_record(call.mcp_app) if call is not None else None
        if record is None:
            raise NotFoundError(message=_GONE)
        connection = await self._connection(
            record, user_id=user_id, organization_id=organization_id
        )
        read = await self._relay(
            connection, lambda toolset: toolset.read_resource_for_app(record["resource_uri"])
        )
        return McpAppPage(document=_page_document(read))

    async def call_tool(
        self,
        ctx: AuthContext,
        *,
        conversation_id: UUID,
        tool_call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Relay a page's `tools/call` to its server, as the run allowed, and audit it.

        Returns:
            The server's `CallToolResult` in wire form, `isError` included: the page
            reads a failed call as one.

        Raises:
            NotFoundError: As for :meth:`frame`, or the person may read but not
                take part in the conversation.
            AuthorizationError: The tool is not one the page may call: not offered
                to pages, outside the run's or the connection's tool list, or one
                that waits for a person's approval.
            ExternalServiceError: The server could not be reached.
        """
        call, record, connection = await self._authorized(
            ctx, conversation_id=conversation_id, tool_call_id=tool_call_id, for_write=True
        )

        async def relay(toolset: MCPToolset[Any]) -> dict[str, Any]:
            tool = next((t for t in await toolset.list_tools() if t.name == name), None)
            if tool is None:
                raise AuthorizationError(
                    message="This page may not use that tool", details={"tool": name}
                )
            _check_tool(
                record,
                connection,
                name=name,
                meta=tool.meta,
                read_only=_read_only(tool.annotations),
            )
            return await toolset.call_tool_for_app(name, arguments)

        result = await self._relay(connection, relay)
        # The tool and where it was asked from, never its arguments: those are the
        # page's, and as likely to hold a person's data as a model's would.
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="mcp_connection.app_tool_called",
            target_type="mcp_connection",
            target_id=str(connection.id),
            details={
                "tool": name,
                "conversation_id": str(conversation_id),
                "tool_call_id": str(call.id),
                "is_error": result.get("isError") is True,
            },
        )
        return result

    async def read_resource(
        self, ctx: AuthContext, *, conversation_id: UUID, tool_call_id: str, uri: str
    ) -> dict[str, Any]:
        """Relay a page's `resources/read` of one of its server's `ui://` resources.

        Raises:
            NotFoundError: As for :meth:`frame`.
            BadRequestError: The address is not a `ui://` one.
            ExternalServiceError: The server could not be reached.
        """
        if not uri.startswith("ui://"):
            raise BadRequestError(message="A page reads only its server's ui:// resources")
        _, _, connection = await self._authorized(
            ctx, conversation_id=conversation_id, tool_call_id=tool_call_id
        )
        return await self._relay(connection, lambda toolset: toolset.read_resource_for_app(uri))

    async def _authorized(
        self, ctx: AuthContext, *, conversation_id: UUID, tool_call_id: str, for_write: bool = False
    ) -> tuple[ToolCall, McpAppRecord, McpConnection]:
        """The stored call, its record and its connection, for a reader of the conversation.

        `for_write` asks for a participant, as adding a turn does: a call made on
        a page acts with the connection's credential, which reading a shared
        transcript is no licence for.
        """
        await ConversationService(self.db).get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            for_write=for_write,
            turn=for_write,
            include_favourite=False,
            ctx=ctx,
        )
        call = await conversation_repo.get_app_tool_call(
            self.db, conversation_id=conversation_id, tool_call_id=tool_call_id
        )
        record = stored_record(call.mcp_app) if call is not None else None
        if call is None or record is None or ctx.user_id is None:
            raise NotFoundError(message=_GONE)
        connection = await self._connection(
            record, user_id=ctx.user_id, organization_id=ctx.organization_id
        )
        return call, record, connection

    async def _connection(
        self, record: McpAppRecord, *, user_id: UUID, organization_id: UUID
    ) -> McpConnection:
        """The call's connection, while it still shows pages to this person.

        A person's own connection answers to that person alone: a colleague
        reading the conversation does not get to use somebody else's account.
        """
        connection = await mcp_connection_repo.get_by_id(self.db, UUID(record["connection_id"]))
        if (
            connection is None
            or connection.purpose != "mcp"
            or not connection.is_enabled
            or not connection.mcp_apps
            or (connection.scope == "user" and connection.user_id != user_id)
            or (connection.scope == "org" and connection.organization_id != organization_id)
        ):
            raise NotFoundError(message=_GONE)
        return connection

    async def _relay[T](
        self, connection: McpConnection, act: Callable[[MCPToolset[Any]], Awaitable[T]]
    ) -> T:
        """Run `act` against the connection's server, with its credential, in a session of its own.

        A refusal `act` raises comes out as it is, from inside the session's task
        group as well; anything else the server or the network does is the
        server's failure, said once, without its text.
        """
        headers = await resolve_auth_headers(connection)
        if headers is None:
            raise NotFoundError(message=_GONE)
        toolset: MCPToolset[Any] = MCPToolset(
            app_client(connection.url, headers, init_timeout=CONNECT_TIMEOUT_SECS),
            tool_error_behavior="failed",
        )
        try:
            async with toolset:
                return await act(toolset)
        except AppException:
            raise
        except MCPError as exc:
            logger.warning("MCP Apps relay to %r failed: %s", connection.name, exc)
            raise ExternalServiceError(
                message="The server behind this page refused the request",
                details={"code": exc.code},
            ) from exc
        except (Exception, BaseExceptionGroup) as exc:
            if carries_base_exception(exc):
                raise
            if isinstance(exc, BaseExceptionGroup):
                ours, _ = exc.split(AppException)
                if ours is not None:
                    raise _first(ours) from exc
            logger.warning("MCP Apps relay to %r could not connect: %r", connection.name, exc)
            raise ExternalServiceError(
                message="The server behind this page could not be reached"
            ) from exc


def _first(group: BaseExceptionGroup[Any]) -> BaseException:
    inner = group.exceptions[0]
    return _first(inner) if isinstance(inner, BaseExceptionGroup) else inner


def _read_only(annotations: ToolAnnotations | None) -> bool:
    return annotations is not None and annotations.read_only_hint is True


def _ui(meta: object) -> dict[str, object]:
    """A tool's `_meta.ui`, or empty where it has none."""
    ui = meta.get("ui") if isinstance(meta, dict) else None
    return ui if isinstance(ui, dict) else {}


def _check_tool(
    record: McpAppRecord, connection: McpConnection, *, name: str, meta: object, read_only: bool
) -> None:
    """Refuse a page's call that the run's binding, the connection or approvals would not let through.

    A tool the server offers to pages alone is never on a binding's list - the
    model never sees it to pick - so it is held to the page instead: it must
    belong to the same page as the call it was asked from, and the tool that
    brought the page must still be on the connection's list.
    """
    refused = AuthorizationError(message="This page may not use that tool", details={"tool": name})
    ui = _ui(meta)
    visibility = ui.get("visibility")
    if isinstance(visibility, list) and "app" not in visibility:
        raise refused
    if visible_to_model(meta):
        for allowed in (record["allowed_tools"], connection.allowed_tools):
            if allowed is not None and name not in allowed:
                raise refused
    elif ui.get("resourceUri") != record["resource_uri"] or (
        connection.allowed_tools is not None and record["tool_name"] not in connection.allowed_tools
    ):
        raise refused
    own = record["tool_approval"].get(name, "default")
    if approval_needed(record["approval"], read_only=read_only, own=own):
        raise AuthorizationError(
            message="This needs a person's approval: ask the agent in the conversation instead",
            details={"tool": name, "approval_required": True},
        )


def _page_document(read: dict[str, Any]) -> bytes:
    """The HTML of a `resources/read` answer, when it is a page written for MCP Apps."""
    contents = read.get("contents")
    first = contents[0] if isinstance(contents, list) and contents else None
    if not isinstance(first, dict) or first.get("mimeType") != APP_MIME_TYPE:
        raise NotFoundError(message=_GONE)
    if isinstance(first.get("text"), str):
        return first["text"].encode()
    if isinstance(first.get("blob"), str):
        return base64.b64decode(first["blob"])
    raise NotFoundError(message=_GONE)
