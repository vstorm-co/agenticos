"""A refusal between tool iterations stops the next wire request, including delegates."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from app.agents.capabilities._metered import MeteredModel
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.manifest import RecordingModel, RunRecorder
from app.agents.model_context import check_model_context, checking_model_context

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("ambient", [False, True])
async def test_a_source_refused_during_a_tool_never_reaches_the_next_model(
    streamed, nested, ambient
):
    refused = False
    calls = 0
    child_calls = 0
    checks = 0

    async def check():
        nonlocal checks
        checks += 1
        if refused:
            raise GuardrailBlocked(edge="input", message="Source refused")

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[ToolCallPart("invalidate_context", {}, tool_call_id="call-1")])

    async def stream(messages, info):
        nonlocal calls
        calls += 1
        yield {0: DeltaToolCall(name="invalidate_context", json_args="{}", tool_call_id="call-1")}

    async def child_response(messages, info):
        nonlocal child_calls
        child_calls += 1
        return ModelResponse(parts=[TextPart("child response")])

    def wrapped(model):
        return MeteredModel(model) if ambient else RecordingModel(model, RunRecorder())

    child = Agent(wrapped(FunctionModel(child_response)))
    agent = Agent(wrapped(FunctionModel(respond, stream_function=stream)))

    @agent.tool_plain
    async def invalidate_context() -> str:
        nonlocal refused
        refused = True
        if nested:
            await child.run("copied source")
        return "done"

    with checking_model_context(check), pytest.raises(GuardrailBlocked):
        if streamed:
            async with agent.run_stream("source") as result:
                await result.get_output()
        else:
            await agent.run("source")

    assert calls == 1 and child_calls == 0 and checks == 2
    # The surrounding run's guard cannot leak into an unrelated task.
    assert (await child.run("unrelated")).output == "child response"


async def test_nested_contexts_keep_enclosing_checks_and_reset_after_cancellation():
    outer = AsyncMock()
    cancelled = AsyncMock(side_effect=asyncio.CancelledError)
    with checking_model_context(outer):
        with checking_model_context(None):
            await check_model_context()
        with pytest.raises(asyncio.CancelledError), checking_model_context(cancelled):
            await check_model_context()
        await check_model_context()
    await check_model_context()
    assert outer.await_count == 3
    cancelled.assert_awaited_once()
