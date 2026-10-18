"""A remote A2A agent as a delegate, behind the same delegation tool (#2092).

The delegation library runs a delegate as a Pydantic AI agent, so a remote agent
is given one: an agent whose "model" is the remote agent itself. Each request the
library makes becomes one `message/send` - the latest thing it was asked - and the
answer comes back as the model's text. The conversation is kept on the remote side
by A2A's `contextId`, carried from one call to the next within the run.

What a call costs is the remote vendor's to price, and nothing publishes that
price, so each call is booked to the run's ledger as unpriced: the run says its
cost is partial rather than claiming a figure nobody computed. The run's ceiling
is checked before every call, as before every model request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.services.a2a_client import A2AClientError, send_message

_CONTINUED = frozenset({"input-required", "auth-required"})
"""A remote task waiting on the delegating side: the next message continues it."""

PROVIDER = "a2a"
"""What a remote agent's calls are booked under. No price source knows it."""


def latest_prompt(messages: list[ModelMessage]) -> str:
    """The last thing the delegate was asked, as text."""
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                if isinstance(part.content, str):
                    return part.content
                return "\n".join(item for item in part.content if isinstance(item, str))
    return ""


def a2a_delegate(
    *, handle: str, endpoint: str, bearer: str | None
) -> Callable[[], PydanticAgent[Any, str]]:
    """A builder for one remote agent's delegate. See the module docstring."""

    def build() -> PydanticAgent[Any, str]:
        # The remote conversation, and the task in it still waiting on input -
        # continued by the next message rather than left behind a new one.
        conversation: dict[str, str | None] = {"context": None, "task": None}

        async def reply_text(messages: list[ModelMessage]) -> str:
            prompt = latest_prompt(messages)
            await assert_ambient_budget()
            try:
                reply = await send_message(
                    endpoint,
                    prompt,
                    context_id=conversation["context"],
                    task_id=conversation["task"],
                    bearer=bearer,
                )
            except A2AClientError as failed:
                # An answer the delegating model reads, not a crash: it can try
                # another delegate, or say it could not get this one.
                return f"The remote agent {handle} did not answer: {failed}"
            finally:
                # Booked whether or not it answered: a call that dropped or came
                # back malformed may still have been worked on, and the unpriced
                # entry is what says the run's cost is a floor.
                record_ambient_usage(f"{PROVIDER}:{handle}", RequestUsage(), provider=PROVIDER)
            conversation["context"] = reply.context_id or conversation["context"]
            conversation["task"] = reply.task_id if reply.state in _CONTINUED else None
            return reply.text or "(The remote agent sent no text.)"

        async def answer(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart(await reply_text(messages))])

        async def stream(messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
            yield await reply_text(messages)

        model = FunctionModel(answer, stream_function=stream, model_name=f"{PROVIDER}:{handle}")
        return PydanticAgent(model, output_type=str, name=handle)

    return build
