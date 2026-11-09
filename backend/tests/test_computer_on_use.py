"""`request_computer_access`: the person's computer asked for when the agent needs it."""

import asyncio
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.computer_on_use import (
    REQUEST_COMPUTER_ACCESS,
    ComputerAccessRequest,
    RequestComputerOnUse,
)
from app.agents.deps import AgentDeps

pytestmark = pytest.mark.anyio


def _returns(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == REQUEST_COMPUTER_ACCESS
    ]


def _model(calls: int) -> FunctionModel:
    """Calls the tool `calls` times, then answers."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert REQUEST_COMPUTER_ACCESS in {tool.name for tool in info.function_tools}
        made = sum(isinstance(part, ToolCallPart) for message in messages for part in message.parts)
        if made < calls:
            return ModelResponse(
                parts=[ToolCallPart(REQUEST_COMPUTER_ACCESS, {"reason": "  Read README  "})]
            )
        return ModelResponse(parts=[TextPart("Continuing with your files.")])

    return FunctionModel(respond)


async def _run(capability: RequestComputerOnUse, calls: int) -> list[str]:
    agent = Agent(_model(calls), deps_type=AgentDeps, capabilities=[capability])
    result = await agent.run("Summarize my README", deps=AgentDeps())
    return _returns(result.all_messages())


async def test_a_grant_ends_the_turn_so_the_next_opens_the_folder():
    asked: list[ComputerAccessRequest] = []

    async def grant(request: ComputerAccessRequest) -> bool:
        asked.append(request)
        return True

    returns = await _run(RequestComputerOnUse(request_access=grant), calls=2)

    assert asked == [ComputerAccessRequest(reason="Read README")]
    assert "They granted access" in returns[0]
    # Asked once: the second call is told it already happened.
    assert "already granted" in returns[1]


async def test_a_decline_is_not_asked_again_in_the_same_turn():
    asked = 0

    async def decline(_request: ComputerAccessRequest) -> bool:
        nonlocal asked
        asked += 1
        return False

    returns = await _run(RequestComputerOnUse(request_access=decline), calls=2)

    assert asked == 1
    assert "did not grant access" in returns[0]
    assert "declined earlier" in returns[1]


async def test_two_calls_in_one_step_put_up_one_dialog():
    pending: list[asyncio.Future[bool]] = []
    asked = asyncio.Event()

    async def wait(_request: ComputerAccessRequest) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        pending.append(future)
        asked.set()
        return await future

    capability = RequestComputerOnUse(request_access=wait)
    first = asyncio.create_task(capability._request(MagicMock(), "a"))
    second = asyncio.create_task(capability._request(MagicMock(), "b"))
    await asked.wait()
    pending[0].set_result(True)
    assert "They granted access" in await first
    assert "already granted" in await second
    assert len(pending) == 1


def test_the_model_is_told_not_to_raise_it_up_front():
    async def never(_request: ComputerAccessRequest) -> bool:
        return False

    assert (
        "Do not raise it up front" in RequestComputerOnUse(request_access=never).get_instructions()
    )
