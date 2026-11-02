"""A live routine's authority is checked again at each tool boundary."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from app.agents.approval import refusal
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError

RoutineCheck = Callable[[UUID], Awaitable[None]]


@dataclass
class RoutineGuard(AbstractCapability[AgentDeps]):
    check: RoutineCheck
    agent_id: UUID

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, object],
        handler: WrapToolExecuteHandler,
    ) -> object:
        """Refuse a revoked routine before the tool, preserving ordinary tool failures."""
        try:
            await self.check(self.agent_id)
        except AuthorizationError as error:
            return refusal(tool_def.name, error.message)
        return await handler(args)


def guard_for(check: RoutineCheck | None, *, agent_id: UUID) -> tuple[RoutineGuard, ...]:
    return () if check is None else (RoutineGuard(check=check, agent_id=agent_id),)
