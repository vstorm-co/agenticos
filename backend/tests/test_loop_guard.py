"""Tool-call loops are warned about, then stopped, and say why (#2086).

The model is scripted, so whether it looped - and what it was told - is exactly
what the run did.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.deps import AgentDeps
from app.agents.loop_guard import Loop, LoopGuard, ToolLoopStopped, find_loop, run_calls

pytestmark = pytest.mark.anyio


def _call(tool: str, **args: Any) -> tuple[str, str]:
    return run_calls([ModelResponse(parts=[ToolCallPart(tool, args)], run_id="r")], "r")[0]


class TestFindingALoop:
    def test_one_call_made_again_and_again_is_a_loop(self) -> None:
        calls = [_call("search", q="refund")] * 4
        assert find_loop(calls, repeats=4, cycles=3) == Loop(tools=("search",), times=4)

    def test_reads_with_different_arguments_are_not(self) -> None:
        """Reading ten pages is ten calls, not a loop."""
        calls = [_call("read_page", url=f"https://example.com/{n}") for n in range(10)]
        assert find_loop(calls, repeats=4, cycles=3) is None

    @pytest.mark.parametrize("period", [2, 3])
    def test_a_short_cycle_gone_round_and_round_is_a_loop(self, period: int) -> None:
        cycle = [_call(f"tool_{n}", n=n) for n in range(period)]
        loop = find_loop(cycle * 3, repeats=4, cycles=3)
        assert loop == Loop(tools=tuple(f"tool_{n}" for n in range(period)), times=3)

    def test_a_loop_the_agent_already_left_is_not_one_it_is_in(self) -> None:
        calls = [_call("search", q="x")] * 4 + [_call("answer", text="done")]
        assert find_loop(calls, repeats=4, cycles=3) is None

    def test_the_same_arguments_in_another_order_are_the_same_call(self) -> None:
        a = run_calls(
            [ModelResponse(parts=[ToolCallPart("s", '{"a": 1, "b": 2}')], run_id="r")], "r"
        )
        b = run_calls([ModelResponse(parts=[ToolCallPart("s", {"b": 2, "a": 1})], run_id="r")], "r")
        assert a == b
        broken = run_calls([ModelResponse(parts=[ToolCallPart("s", "{not json")], run_id="r")], "r")
        assert broken == [("s", "{not json")]

    def test_only_this_runs_calls_count(self) -> None:
        """An earlier turn's calls are in the history too, and a person asking
        the same thing twice is not the agent looping."""
        earlier = ModelResponse(parts=[ToolCallPart("search", {"q": "x"})], run_id="before")
        mine = ModelResponse(parts=[ToolCallPart("search", {"q": "x"})], run_id="now")
        assert run_calls([earlier, ModelRequest(parts=[]), mine], "now") == [
            ("search", '{"q": "x"}')
        ]


def _looping_model(seen: list[list[ModelMessage]], *, changes_after_warning: bool):
    """A model that calls `search` with the same query until told to stop."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        warned = any(
            isinstance(part, UserPromptPart) and "change approach" in str(part.content).lower()
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if warned and changes_after_warning:
            return ModelResponse(parts=[TextPart("I could not find it; here is what I have.")])
        return ModelResponse(parts=[ToolCallPart("search", {"q": "secret customer name"})])

    return respond


def _agent(model: FunctionModel) -> Agent[AgentDeps, str]:
    agent = Agent[AgentDeps, str](model, capabilities=[LoopGuard(repeats=3, cycles=3)])

    @agent.tool_plain
    def search(q: str) -> str:
        return "nothing found"

    return agent


async def test_a_looping_run_is_warned_then_stopped_and_says_why() -> None:
    seen: list[list[ModelMessage]] = []
    agent = _agent(FunctionModel(_looping_model(seen, changes_after_warning=False)))

    with pytest.raises(ToolLoopStopped) as stopped:
        await agent.run("find the customer", deps=AgentDeps())

    message = str(stopped.value)
    assert "`search`" in message
    assert "after it was told it was looping" in message
    # Tool names, never the arguments: they may carry what the agent read.
    assert "secret customer name" not in message
    # Warned on the fourth request, after three identical calls; three more
    # after the warning, and the seventh request is never sent.
    assert len(seen) == 6


async def test_a_run_that_changes_approach_after_the_warning_finishes() -> None:
    seen: list[list[ModelMessage]] = []
    agent = _agent(FunctionModel(_looping_model(seen, changes_after_warning=True)))

    result = await agent.run("find the customer", deps=AgentDeps())

    assert result.output.startswith("I could not find it")
    # The warning reached the model on one request and never entered the history.
    assert not any(
        isinstance(part, UserPromptPart) and "change approach" in str(part.content).lower()
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


async def test_each_run_of_one_agent_is_judged_on_its_own_calls() -> None:
    """A delegate's agent is built once and run per delegation: two runs of two
    identical calls are not one run of four."""
    seen: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        calls = sum(
            isinstance(part, ToolCallPart)
            for message in messages
            if isinstance(message, ModelResponse)
            for part in message.parts
        )
        if calls < 2:
            return ModelResponse(parts=[ToolCallPart("search", {"q": "same"})])
        return ModelResponse(parts=[TextPart("done")])

    agent = _agent(FunctionModel(respond))
    await agent.run("first", deps=AgentDeps())
    await agent.run("second", deps=AgentDeps())

    assert not any(
        isinstance(part, UserPromptPart) and "change approach" in str(part.content).lower()
        for messages in seen
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def test_a_cycle_is_described_by_its_calls_in_order() -> None:
    loop = Loop(tools=("search", "open"), times=3)
    assert loop.describe() == "went round the same calls (`search` → `open`) 3 times"


async def test_a_provider_resume_turn_is_passed_through_untouched() -> None:
    """A tail that is a suspended response is echoed to the provider verbatim, so
    nothing may be added to it - and it is not a request this run makes."""
    resumed = MagicMock(messages=[ModelResponse(parts=[TextPart("partial")])])
    guard = LoopGuard()
    assert await guard.before_model_request(MagicMock(run_id="r"), resumed) is resumed


async def test_a_loop_is_seen_even_when_compaction_cut_the_history() -> None:
    """A summarising or sliding compaction runs first and removes the very
    responses a loop is made of, so the guard keeps the calls itself."""

    class _KeepsTheLastTwo(AbstractCapability[AgentDeps]):
        async def before_model_request(self, ctx, request_context):
            messages = request_context.messages
            return replace(
                request_context, messages=messages[-2:] if len(messages) > 2 else messages
            )

    seen: list[list[ModelMessage]] = []
    agent = Agent[AgentDeps, str](
        FunctionModel(_looping_model(seen, changes_after_warning=False)),
        capabilities=[_KeepsTheLastTwo(), LoopGuard(repeats=3, cycles=3)],
    )

    @agent.tool_plain
    def search(q: str) -> str:
        return "nothing found"

    with pytest.raises(ToolLoopStopped):
        await agent.run("find the customer", deps=AgentDeps())
