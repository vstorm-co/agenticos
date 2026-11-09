"""Clearing tool results cannot erase an actionable failure before it is read."""

import json
from uuid import UUID

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.compaction import ClearToolResults, TieredCompaction

from app.agents.capabilities.compaction import CompactionConfig, build_strategy
from app.agents.deps import AgentDeps
from app.agents.ephemeral_media import dump_messages
from app.agents.tool_errors import ToolErrors, controlled_tool_error, tool_error
from app.services.transcript import tool_calls_in

pytestmark = pytest.mark.anyio


async def test_clearing_without_controlled_errors_still_reduces_ordinary_results() -> None:
    strategy = build_strategy(CompactionConfig(strategy="clear_tool_results", keep_tool_pairs=0))
    assert isinstance(strategy, ClearToolResults)
    original = ToolReturnPart("read_file", "ordinary result " * 1_000, tool_call_id="read")
    messages: list[ModelMessage] = [
        ModelResponse(parts=[ToolCallPart("read_file", {}, "read")]),
        ModelRequest(parts=[original]),
    ]
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), messages=messages)

    compacted = await strategy.compact(messages, ctx)

    result = compacted[-1].parts[0]
    assert isinstance(result, ToolReturnPart)
    assert result.tool_call_id == "read"
    assert result.content == "[tool result cleared]"
    assert original.content == "ordinary result " * 1_000


@pytest.mark.parametrize("strategy_name", ["clear_tool_results", "tiered"])
@pytest.mark.parametrize("serialized", [False, True])
async def test_clearing_keeps_controlled_errors_and_still_reduces_other_output(
    strategy_name: str, serialized: bool
) -> None:
    config = CompactionConfig.model_validate(
        {"strategy": strategy_name, "keep_tool_pairs": 0, "context_window": 1_000}
    )
    strategy = build_strategy(config)
    assert isinstance(strategy, ClearToolResults | TieredCompaction)
    error = tool_error(
        tool="run_workflow",
        code="invalid_arguments",
        execution="not_started",
        message="Invalid workflow_id: expected UUID.",
        recovery="correct_arguments",
    )
    messages: list[ModelMessage] = [
        ModelResponse(
            parts=[
                ToolCallPart("vendor_lookup", {}, "vendor"),
                ToolCallPart("run_workflow", {"workflow_id": "netverify"}, "workflow"),
                ToolCallPart("read_file", {}, "read"),
            ]
        ),
        ModelRequest(
            parts=[
                # Copying the error shape cannot preserve an external failure.
                ToolReturnPart(
                    "vendor_lookup", str(error), tool_call_id="vendor", outcome="failed"
                ),
                ToolReturnPart("run_workflow", error, tool_call_id="workflow", outcome="failed"),
                ToolReturnPart("read_file", "ordinary result " * 1_000, tool_call_id="read"),
                UserPromptPart("Continue after correcting the argument."),
            ]
        ),
    ]
    if serialized:
        messages = ModelMessagesTypeAdapter.validate_python(dump_messages(messages))
    original = messages[-1].parts[1]
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), messages=messages)

    compacted = await strategy.compact(messages, ctx)

    parts = compacted[-1].parts
    assert isinstance(parts[0], ToolReturnPart)
    assert parts[0].content == "[tool result cleared]"
    assert parts[1] is original
    assert isinstance(parts[1], ToolReturnPart)
    assert json.loads(parts[1].content) == json.loads(error)
    assert isinstance(parts[2], ToolReturnPart)
    assert parts[2].content == "[tool result cleared]"
    assert isinstance(parts[3], UserPromptPart)
    assert parts[3].content == "Continue after correcting the argument."
    recorded = tool_calls_in(compacted)
    assert recorded[1].result is not None
    assert json.loads(recorded[1].result) == json.loads(error)


async def test_a_zero_pair_setting_still_delivers_the_correction_to_the_next_model_request() -> (
    None
):
    received: list[str] = []
    executed: list[UUID] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if returned:
            envelope = controlled_tool_error(returned[-1])
            assert envelope is not None
            assert envelope.error.execution == "not_started"
            assert envelope.error.issues[0].field == "workflow_id"
            assert envelope.error.issues[0].expected_type == "UUID"
            received.append(envelope.error.id)
            return ModelResponse(parts=[TextPart("Please supply a workflow ID.")])
        return ModelResponse(
            parts=[ToolCallPart("run_workflow", {"workflow_id": "netverify"}, "workflow")]
        )

    agent = Agent(
        FunctionModel(respond),
        capabilities=[
            ToolErrors(),
            build_strategy(
                CompactionConfig(
                    strategy="clear_tool_results",
                    keep_tool_pairs=0,
                    max_fraction=0.05,
                    context_window=1_000,
                )
            ),
        ],
    )

    @agent.tool_plain
    def run_workflow(workflow_id: UUID) -> str:
        executed.append(workflow_id)
        return "started"

    result = await agent.run("Run it.", deps=AgentDeps())

    assert executed == []
    assert len(received) == 1
    (recorded,) = tool_calls_in(result.new_messages())
    assert recorded.result is not None
    assert json.loads(recorded.result)["error"]["id"] == received[0]
