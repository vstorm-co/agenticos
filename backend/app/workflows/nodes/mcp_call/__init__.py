"""`mcp.call` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.mcp_call._handler import (
    McpCallConfig,
    McpCallInput,
    McpCallOutput,
    check_resources,
    handle,
)

__all__ = ["McpCallConfig", "McpCallInput", "McpCallOutput"]

register(
    NodeDefinition(
        id="mcp.call",
        version=1,
        name="Call an MCP tool",
        category="mcp",
        description="Call one tool on one of the organization's MCP servers, "
        "asking a person first before it changes anything.",
        kind="action",
        config_schema=McpCallConfig,
        input_schema=McpCallInput,
        output_schema=McpCallOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=McpCallOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
        resource_check=check_resources,
    )
)
