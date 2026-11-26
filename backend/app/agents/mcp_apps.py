"""MCP Apps (SEP-1865): the page a server shows with a tool's result (#3450).

A server marks a tool with `_meta.ui.resourceUri`, a `ui://` address of an HTML
page. Pydantic AI's `MCPToolset` keeps such a call's raw result for the page under
`ToolReturn.metadata["mcp_app"]` whether or not anyone asked for it; this module
decides what happens to it here:

- On a connection with `mcp_apps` off, the record is dropped at the toolset, so
  nothing downstream - the stream, the transcript, a channel - ever sees it.
- On one with it on, the record is kept, stamped with the connection it came
  from, and stored with the tool call; web chat draws the page under the answer.

The page and the calls it makes back go through `app.services.mcp_app`.
"""

import dataclasses
import json
from collections.abc import Mapping
from typing import Any, Final, TypedDict
from uuid import UUID

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.client.extension import advertise
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPAppToolResult
from pydantic_ai.messages import ToolReturn
from pydantic_ai.toolsets import ToolsetTool, WrapperToolset

from app.agents.spec import ApprovalMode, McpApproval

UI_EXTENSION: Final = "io.modelcontextprotocol/ui"
"""The MCP Apps extension's identifier, announced in the client's capabilities."""

APP_MIME_TYPE: Final = "text/html;profile=mcp-app"
"""The only page type a host shows: HTML written for the MCP Apps bridge."""

MAX_PAGE_EVENT_BYTES: Final = 8 * 1024 * 1024
"""The largest single message read from a server with pages on.

The MCP SDK refuses a server-sent event over 1 MiB by default, and a page is one
event: a self-contained page with its scripts inlined is easily more than that.
"""

MCP_APP_METADATA_KEY: Final = "mcp_app"
"""Where `MCPToolset` puts a page's record in `ToolReturn.metadata`, and where it stays here."""

_RECORD: TypeAdapter[MCPAppToolResult] = TypeAdapter(MCPAppToolResult)

MAX_RECORD_BYTES: Final = 1024 * 1024
"""The largest record kept for a page, after binary content is dropped.

It is stored with the tool call and sent to the browser; a result past this is
shown as text only, as on a connection without pages.
"""


class McpAppRecord(TypedDict):
    """What is kept with a tool call to draw its page, live and after a reload.

    With the page's data it keeps what the run allowed of the connection, so a
    call the page makes back is held to the same: the binding's tool list and its
    approvals as they were when the model called the tool.
    """

    resource_uri: str
    """The page's `ui://` address on the server."""
    tool_input: dict[str, Any]
    """The arguments the model called the tool with."""
    result: dict[str, Any]
    """The server's `CallToolResult` in wire form: `content`, `structuredContent`, `_meta`, `isError`."""
    connection_id: str
    """The connection the page is read from, and its calls go to. Never sent to the browser."""
    tool_name: str
    """The tool's name on the server, unprefixed."""
    allowed_tools: list[str] | None
    """The tools the run could reach on this server, by the server's names; `None` for all."""
    approval: McpApproval
    """The binding's approval policy for this server."""
    tool_approval: dict[str, ApprovalMode]
    """The binding's per-tool approvals, by the server's names."""


_STORED: TypeAdapter[McpAppRecord] = TypeAdapter(McpAppRecord)


def app_record(metadata: object) -> McpAppRecord | None:
    """The page record kept in a tool return's metadata or a stored call, or `None`."""
    value = metadata.get(MCP_APP_METADATA_KEY) if isinstance(metadata, dict) else None
    return stored_record(value)


def stored_record(value: object) -> McpAppRecord | None:
    """A page record as it was stored, or `None` for a call with none (or one unreadable)."""
    if value is None:
        return None
    try:
        return _STORED.validate_python(value)
    except ValidationError:
        return None


class McpAppView(TypedDict):
    """What a browser gets of a page record: everything but the connection behind it."""

    resource_uri: str
    tool_input: dict[str, Any]
    result: dict[str, Any]


def page_view(record: McpAppRecord) -> McpAppView:
    """The record as the page's host in the browser sees it."""
    return McpAppView(
        resource_uri=record["resource_uri"],
        tool_input=record["tool_input"],
        result=record["result"],
    )


def visible_to_model(meta: object) -> bool:
    """Whether a tool is one the model may call, per its `_meta.ui.visibility`.

    A tool listed for the page alone (`["app"]`) is never offered to the model -
    Pydantic AI leaves it out of the agent's tools - so it is not one to pick on a
    connection either. A tool without the list is visible to both.
    """
    match meta:
        case {"ui": {"visibility": list() as visibility}}:
            return "model" in visibility
        case _:
            return True


def app_client(url: str, headers: dict[str, str], *, init_timeout: float) -> Client[Any]:
    """A client for a server with pages on: it says it shows them, and reads a whole page.

    Streamable HTTP only, which is what MCP Apps servers speak; `MCPToolset` takes
    the client as it is, so the headers go on the transport here.
    """
    transport = StreamableHttpTransport(
        url, headers=headers, max_sse_event_size=MAX_PAGE_EVENT_BYTES
    )
    return Client(
        transport,
        extensions=[advertise(UI_EXTENSION, {"mimeTypes": [APP_MIME_TYPE]})],
        init_timeout=init_timeout,
    )


def _toolset_record(metadata: dict[str, Any]) -> MCPAppToolResult | None:
    try:
        return _RECORD.validate_python(metadata.get(MCP_APP_METADATA_KEY))
    except ValidationError:
        return None


def _without_binary(result: dict[str, Any]) -> dict[str, Any]:
    """The result with image, audio and blob data dropped: the page gets the rest.

    In wire form they are base64 strings, kept with the call for ever and sent to
    every reader; a page that needs one reads it from the server instead.
    """
    content = result.get("content")
    if not isinstance(content, list):
        return result
    blocks: list[Any] = []
    for block in content:
        match block:
            case {"type": "image" | "audio"}:
                blocks.append({key: value for key, value in block.items() if key != "data"})
            case {"type": "resource", "resource": {"blob": _} as resource}:
                blocks.append(
                    {
                        **block,
                        "resource": {
                            key: value for key, value in resource.items() if key != "blob"
                        },
                    }
                )
            case _:
                blocks.append(block)
    return {**result, "content": blocks}


def _without_record(result: ToolReturn[Any]) -> Any:
    rest = {key: value for key, value in result.metadata.items() if key != MCP_APP_METADATA_KEY}
    if rest or result.content is not None:
        return dataclasses.replace(result, metadata=rest or None)
    return result.return_value


@dataclasses.dataclass
class McpAppResults(WrapperToolset[Any]):
    """Keep a tool's page record on a connection with pages on, and drop it elsewhere.

    Wraps the server's `MCPToolset` directly, under every filter and prefix, so the
    tool name it records is the server's own.
    """

    connection_id: UUID | None = None
    """The connection to stamp on a record; `None` drops every record (pages off)."""
    allowed_tools: list[str] | None = None
    approval: McpApproval = "none"
    tool_approval: Mapping[str, ApprovalMode] = dataclasses.field(default_factory=dict)

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[Any], tool: ToolsetTool[Any]
    ) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)
        if not isinstance(result, ToolReturn) or not isinstance(result.metadata, dict):
            return result
        found = _toolset_record(result.metadata)
        if found is None:
            return result
        if self.connection_id is None:
            return _without_record(result)
        record = McpAppRecord(
            resource_uri=found["resource_uri"],
            tool_input=found["tool_input"],
            result=_without_binary(found["result"]),
            connection_id=str(self.connection_id),
            tool_name=name,
            allowed_tools=self.allowed_tools,
            approval=self.approval,
            tool_approval=dict(self.tool_approval),
        )
        if len(json.dumps(record, default=str)) > MAX_RECORD_BYTES:
            return _without_record(result)
        return dataclasses.replace(
            result, metadata={**result.metadata, MCP_APP_METADATA_KEY: record}
        )
