"""Read-only source tools with evidence that a watch actually read its account."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import JsonValue, TypeAdapter
from pydantic_ai import RunContext
from pydantic_ai.toolsets import WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from app.agents.mcp import NEEDS_APPROVAL, needs_approval
from app.agents.routine_authority import RoutineCheck
from app.core.exceptions import AuthorizationError, BadRequestError


@dataclass
class WatchReadReceipt:
    completed_calls: int = 0
    check: RoutineCheck | None = None
    failed_requests: set[str] = field(default_factory=set)
    activation_at: datetime | None = None


_ARGUMENTS = TypeAdapter(dict[str, JsonValue])


@dataclass
class WatchSourceTools[DepsT](WrapperToolset[DepsT]):
    receipt: WatchReadReceipt

    async def get_tools(self, ctx: RunContext[DepsT]) -> dict[str, ToolsetTool[DepsT]]:
        tools = await self.wrapped.get_tools(ctx)
        readable = {
            name: tool
            for name, tool in tools.items()
            if not needs_approval(tool.tool_def, "writes")
            # A read its binding asks before is left out: a watch checks with
            # nobody there to answer (#2884).
            and (tool.tool_def.metadata or {}).get(NEEDS_APPROVAL) is not True
        }
        if not readable:
            raise BadRequestError(message="The watched source has no available read-only tools.")
        return readable

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[DepsT],
        tool: ToolsetTool[DepsT],
    ) -> object:
        if needs_approval(tool.tool_def, "writes"):
            raise AuthorizationError(message="A watch cannot mutate its source.")
        arguments = _ARGUMENTS.validate_python(tool_args)
        request = hashlib.sha256(
            (name + json.dumps(arguments, sort_keys=True)).encode()
        ).hexdigest()
        try:
            result = await self.wrapped.call_tool(name, tool_args, ctx, tool)
        except Exception:
            self.receipt.failed_requests.add(request)
            raise
        self.receipt.failed_requests.discard(request)
        self.receipt.completed_calls += 1
        return result
