"""The approval gate's trusted routine policy, independent of surfaces."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext, ToolDefinition

from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec


@dataclass(frozen=True)
class RoutineToolDecision:
    required: bool = False
    consented_by: UUID | None = None


RoutineToolCheck = Callable[[UUID, AgentSpec, ToolDefinition], Awaitable[RoutineToolDecision]]
RoutineToolPolicy = Callable[[ToolDefinition], Awaitable[RoutineToolDecision]]


@dataclass
class RoutineToolsOff(AbstractCapability[AgentDeps]):
    """Leave out of the model's tool list what a routine's owner turned off.

    Hiding is the courtesy; the routine's action policy refuses a call to such a
    tool all the same, so a model that names it anyway gains nothing.
    """

    hidden: Callable[[ToolDefinition], bool]

    async def prepare_tools(
        self, ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        return [tool for tool in tool_defs if not self.hidden(tool)]
