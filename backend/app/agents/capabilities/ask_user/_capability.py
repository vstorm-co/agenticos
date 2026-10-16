"""`AskUser` from pydantic-ai-harness, answered by whichever surface is running the agent."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import AgentToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai_harness.ask_user import (
    AskUser,
    AskUserRequest,
    AskUserResponse,
    AskUserToolset,
)

from app.agents.deps import AgentDeps, QuestionsCallback

_channel: ContextVar[QuestionsCallback | None] = ContextVar("ask_user_channel", default=None)
"""The surface's question channel, for the length of one `ask_user_question` call.

The harness hands its answerer the questions and nothing else, while the channel
belongs to the run - so the call sets it here, from `ctx.deps`, around itself."""


async def through_the_surface(request: AskUserRequest) -> AskUserResponse:
    """Put the questions to the person on the surface running the agent.

    A surface with nobody to ask answers as a decline, which the model is told and
    carries on from - it must not decide on its own that nobody minds.
    """
    channel = _channel.get()
    if channel is None:
        return AskUserResponse(cancelled=True)
    return await channel(request)


class SurfaceQuestions(AskUserToolset[AgentDeps]):
    """The harness's `ask_user_question`, with the run's channel bound around each call."""

    def __init__(self) -> None:
        super().__init__(answerer=through_the_surface)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> Any:
        token = _channel.set(ctx.deps.ask_questions)
        try:
            return await super().call_tool(name, tool_args, ctx, tool)
        finally:
            _channel.reset(token)


@dataclass(kw_only=True)
class AskTheUser(AskUser[AgentDeps]):
    """Ask the person running the agent one or more multiple-choice questions."""

    def get_toolset(self) -> AgentToolset[AgentDeps]:
        return SurfaceQuestions()


__all__ = ["AskTheUser", "SurfaceQuestions", "through_the_surface"]
