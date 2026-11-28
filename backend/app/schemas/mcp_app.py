"""The MCP Apps page of a tool call, and what it relays (#3450)."""

from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class McpAppRead(BaseSchema):
    """A call's page as the console draws it: where it is, and what it was called with."""

    resource_uri: str = Field(description="The page's `ui://` address on its server.")
    tool_input: dict[str, Any] = Field(description="The arguments the model called the tool with.")
    result: dict[str, Any] = Field(
        description="The server's `CallToolResult` in MCP wire form, as the page receives it."
    )


class McpAppFrameRead(BaseSchema):
    url: str = Field(description="A signed address of the page, valid for a few minutes.")


class McpAppToolCall(BaseSchema):
    """A page's `tools/call`, relayed to its server."""

    name: str = Field(min_length=1, max_length=128, description="The tool, by the server's name.")
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpAppResourceRead(BaseSchema):
    """A page's `resources/read` of one of its server's `ui://` resources."""

    uri: str = Field(min_length=1, max_length=2048)
