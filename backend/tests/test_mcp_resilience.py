"""MCP outages remain failed services inside a live agent turn."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ModelRetry, ToolFailed
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from app.agents import mcp

pytestmark = pytest.mark.anyio


def _context() -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


@pytest.mark.parametrize("origin", ["fresh", "cached", "platform"])
async def test_an_unavailable_binding_cannot_abort_an_unrelated_turn(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    monkeypatch.setattr(mcp, "_answered", {})
    monkeypatch.setattr(mcp, "probe_mcp_server", AsyncMock(return_value=[]))
    inner = FunctionToolset(instructions="Service instructions")
    enter = AsyncMock(side_effect=ConnectionError("private transport details"))
    monkeypatch.setattr(inner, "__aenter__", enter)
    monkeypatch.setattr(mcp, "_make_toolset", lambda _spec: inner)
    spec = mcp.McpServerSpec(
        name="service", url="https://example.com/mcp", in_process=origin == "platform"
    )
    if origin == "cached":
        await mcp.build_mcp_toolsets([spec])
    [guard] = await mcp.build_mcp_toolsets([spec])
    seen: list[str | None] = []

    def answer(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions)
        return ModelResponse(parts=[TextPart("The rest of the answer still works.")])

    result = await Agent(FunctionModel(answer), toolsets=[guard]).run("Hello")
    assert result.output == "The rest of the answer still works."
    assert enter.await_count == 2
    assert seen[0] is not None and "service server is not available this turn" in seen[0]
    assert "private transport details" not in seen[0]


async def test_initialization_retries_once_and_closes_the_recovered_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inner = FunctionToolset()
    enter = AsyncMock(side_effect=[ConnectionError("temporary"), inner])
    leave = AsyncMock(return_value=None)
    monkeypatch.setattr(inner, "__aenter__", enter)
    monkeypatch.setattr(inner, "__aexit__", leave)
    guard = mcp.ResilientMcpToolset(inner, name="service")
    async with guard:
        assert not guard.down
    assert enter.await_count == 2
    leave.assert_awaited_once()


@pytest.mark.parametrize("stage", ["get_tools", "get_instructions"])
async def test_failed_discovery_is_briefed_and_nested_contexts_still_close(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    inner = FunctionToolset()
    leave = AsyncMock(return_value=None)
    monkeypatch.setattr(inner, stage, AsyncMock(side_effect=TimeoutError("private details")))
    monkeypatch.setattr(inner, "__aexit__", leave)
    guard = mcp.ResilientMcpToolset(inner, name="service")
    async with guard:
        if stage == "get_tools":
            assert await guard.get_tools(_context()) == {}
        else:
            assert "not available" in str(await guard.get_instructions(_context()))
        async with guard:
            assert await guard.get_tools(_context()) == {}
            assert "not available" in str(await guard.get_instructions(_context()))
        leave.assert_not_awaited()
    leave.assert_awaited_once()


async def test_an_uncertain_write_is_a_failed_tool_result_and_is_never_replayed() -> None:
    calls: list[str] = []

    def remote_write() -> str:
        calls.append("accepted")
        raise ConnectionError("secret remote response lost")

    inner = FunctionToolset(tools=[remote_write])
    guard = mcp.ResilientMcpToolset(inner, name="service")
    steps = 0
    seen: list[str] = []

    def answer(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal steps
        steps += 1
        seen.append(str(messages))
        if steps == 1:
            return ModelResponse(parts=[ToolCallPart("remote_write", {})])
        return ModelResponse(parts=[TextPart("The request outcome is unknown.")])

    result = await Agent(FunctionModel(answer), toolsets=[guard]).run("Write once")
    assert result.output == "The request outcome is unknown."
    assert calls == ["accepted"]
    assert "outcome is unknown" in seen[-1]
    assert "secret remote response lost" not in seen[-1]


@pytest.mark.parametrize(
    "signal",
    [ApprovalRequired(), CallDeferred(), ModelRetry("correct input"), ToolFailed("refused")],
)
async def test_tool_control_signals_are_preserved(signal: Exception) -> None:
    def operation() -> str:
        raise signal

    guard = mcp.ResilientMcpToolset(FunctionToolset(tools=[operation]), name="service")
    async with guard:
        tools = await guard.get_tools(_context())
        with pytest.raises(type(signal)):
            await guard.call_tool("operation", {}, _context(), tools["operation"])
    assert not guard.down


@pytest.mark.parametrize(
    "stage", ["__aenter__", "__aexit__", "get_tools", "get_instructions", "call_tool"]
)
@pytest.mark.parametrize("grouped", [False, True])
async def test_cancellation_is_preserved_at_every_mcp_boundary(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    grouped: bool,
) -> None:
    def operation() -> str:
        return "ok"

    inner = FunctionToolset(tools=[operation])
    guard = mcp.ResilientMcpToolset(inner, name="service")
    error = (
        BaseExceptionGroup("cancelled", [asyncio.CancelledError()])
        if grouped
        else asyncio.CancelledError()
    )
    failure = AsyncMock(side_effect=error)
    if stage == "__aenter__":
        monkeypatch.setattr(inner, stage, failure)
        with pytest.raises(type(error)):
            await guard.__aenter__()
    elif stage == "__aexit__":
        await guard.__aenter__()
        monkeypatch.setattr(inner, stage, failure)
        with pytest.raises(type(error)):
            await guard.__aexit__(None, None, None)
    else:
        async with guard:
            tools = await guard.get_tools(_context())
            monkeypatch.setattr(inner, stage, failure)
            with pytest.raises(type(error)):
                if stage == "get_tools":
                    await guard.get_tools(_context())
                elif stage == "get_instructions":
                    await guard.get_instructions(_context())
                else:
                    await guard.call_tool("operation", {}, _context(), tools["operation"])
    failure.assert_awaited_once()
    assert not guard.down


async def test_a_disconnect_failure_does_not_replace_a_completed_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inner = FunctionToolset()
    monkeypatch.setattr(inner, "__aexit__", AsyncMock(side_effect=ConnectionError("disconnect")))
    guard = mcp.ResilientMcpToolset(inner, name="service")

    def answer(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("The answer is complete.")])

    result = await Agent(FunctionModel(answer), toolsets=[guard]).run("Hello")
    assert result.output == "The answer is complete."
    assert guard.down
