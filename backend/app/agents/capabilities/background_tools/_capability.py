"""`BackgroundTools`, with a background result screened like any other (#2108)."""

from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities.abstract import WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness import BackgroundTools as HarnessBackgroundTools

from app.agents.deps import AgentDeps

__all__ = ["BACKGROUND", "BackgroundTools"]

BACKGROUND = {"background": "optional"}
"""The metadata a capability puts on a slow tool: the model may send it to the background.

`optional` rather than `True`, so the model decides per call - a browse it needs
the answer of before it can say anything is better waited for, one it can work
around is better left running.
"""


@dataclass
class BackgroundTools(HarnessBackgroundTools[AgentDeps]):
    """Run a slow tool in the background, its result screened as a foreground one is.

    The library delivers a background result as a later message, which passes
    through none of the tool-result hooks - and those hooks are where this
    platform redacts secrets and personal data from a tool's output, refuses a
    blocked word in it, and cuts it to the agent's output limit. A browse left
    running would have handed the model a page those rules exist to keep out.

    So the background call runs the run's own `after_tool_execute` itself before
    its result goes anywhere: the tool manager's root capability, which is the
    per-run instance of every capability in the agent's order - the one the
    framework would have used, not a copy taken when the agent was built. A call
    left in the foreground is untouched: the framework runs those hooks on it
    already, and running them twice would truncate a truncation.
    """

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        if not await self._in_background(ctx, call, tool_def):
            return await handler(args)

        root = ctx.tool_manager.root_capability if ctx.tool_manager is not None else None

        async def screened(validated: dict[str, Any]) -> Any:
            result = await handler(validated)
            if root is None:  # pragma: no cover - a tool call always has its manager
                return result
            return await root.after_tool_execute(
                ctx, call=call, tool_def=tool_def, args=validated, result=result
            )

        return await super().wrap_tool_execute(
            ctx, call=call, tool_def=tool_def, args=args, handler=screened
        )

    async def _in_background(
        self, ctx: RunContext[AgentDeps], call: ToolCallPart, tool_def: ToolDefinition
    ) -> bool:
        """The library's own decision, read the way its `wrap_tool_execute` reads it."""
        mode = await self._prepared_mode(ctx, tool_def)
        if mode is None:
            return False
        return mode == "always" or call.args_as_dict().get("run_in_background") is True
