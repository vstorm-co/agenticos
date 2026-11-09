"""The approval gate's trusted routine policy, independent of surfaces."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai.tools import ToolDefinition

from app.agents.spec import AgentSpec


@dataclass(frozen=True)
class RoutineToolDecision:
    required: bool = False
    consented_by: UUID | None = None


RoutineToolCheck = Callable[[UUID, AgentSpec, ToolDefinition], Awaitable[RoutineToolDecision]]
RoutineToolPolicy = Callable[[ToolDefinition], Awaitable[RoutineToolDecision]]
