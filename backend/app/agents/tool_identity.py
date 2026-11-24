"""Capture trusted tool definitions before names leave the runtime."""

from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition

from app.agents.capabilities import get as capability_def
from app.agents.capabilities._registry import FRAMEWORK_TOOL_NAMES
from app.agents.deps import AgentDeps
from app.agents.mcp import NEEDS_APPROVAL, PLATFORM_TOOL, tool_origin
from app.agents.spec import AgentSpec
from app.core.tool_identity import GENERIC_TOOL, ToolIdentity


@dataclass
class CaptureToolIdentity(AbstractCapability[AgentDeps]):
    """Persist registry ids only for platform-owned tool definitions.

    MCP metadata is stamped by our adapter, outside the server's annotations.
    It takes precedence over names, including names matching a built-in tool.
    """

    registered: dict[str, str]

    @classmethod
    def for_spec(cls, spec: AgentSpec) -> CaptureToolIdentity:
        return cls(
            registered={
                tool.name: tool.id
                for binding in spec.capabilities
                if binding.enabled
                for tool in capability_def(binding.id).effective_tools(binding.tool_overrides)
                if tool.name not in FRAMEWORK_TOOL_NAMES
            }
        )

    def identity(self, tool: ToolDefinition) -> ToolIdentity:
        if (tool.metadata or {}).get(PLATFORM_TOOL) is True:
            return ToolIdentity(presentation_kind="platform")
        if tool_origin(tool) is not None or NEEDS_APPROVAL in (tool.metadata or {}):
            return GENERIC_TOOL
        if tool.capability_id is not None:
            stable = self.registered.get(tool.name)
            return ToolIdentity(stable, "draft" if stable == "write_draft" else None)
        if tool.name in FRAMEWORK_TOOL_NAMES or tool.tool_kind is not None:
            return ToolIdentity()
        return GENERIC_TOOL

    async def prepare_tools(
        self, ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        ctx.deps.tool_definitions.update({tool.name: self.identity(tool) for tool in tool_defs})
        return tool_defs

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        ctx.deps.tool_identities[call.tool_call_id] = self.identity(tool_def)
        return await handler(args)
