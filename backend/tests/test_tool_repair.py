"""Malformed tool-call arguments are repaired before validation, and counted (#2105).

Each retry of a call whose JSON was merely broken is a paid model request, and
open-weight models served by Ollama or vLLM send broken JSON far more often than
frontier ones. The model here is scripted, so what reaches the tool - and how
many times the model was asked - is exactly what the run did.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent, InstrumentationSettings
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.approval import ApprovalGranted, ApprovalRequest
from app.agents.capabilities.approval import ApprovalGate
from app.agents.deps import AgentDeps
from app.agents.tool_repair import CountedRepair, RepairTally

pytestmark = pytest.mark.anyio


def _calls_once(args: str | dict[str, Any]):
    """A model that calls `send` with `args`, then answers with what it was told."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("send", args, tool_call_id="c1")])
        return ModelResponse(parts=[TextPart("done")])

    return respond


def _agent(
    model: FunctionModel, tally: RepairTally, *extra: Any
) -> tuple[Agent[AgentDeps, str], list[str]]:
    sent: list[str] = []
    agent = Agent[AgentDeps, str](model, capabilities=[CountedRepair(tally=tally), *extra])

    @agent.tool_plain
    def send(to: str) -> str:
        sent.append(to)
        return "sent"

    return agent, sent


async def test_a_trailing_comma_reaches_the_tool_without_a_retry() -> None:
    tally = RepairTally()
    asked: list[int] = []
    respond = _calls_once('{"to": "ada@example.com",}')

    def counting(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        asked.append(len(messages))
        return respond(messages, info)

    agent, sent = _agent(FunctionModel(counting), tally)
    result = await agent.run("mail Ada", deps=AgentDeps())

    assert sent == ["ada@example.com"]
    assert len(asked) == 2
    assert not any(
        isinstance(part, RetryPromptPart)
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
    )
    assert tally.count == 1


@pytest.mark.parametrize("args", ['{"to": "ada@example.com"}', {"to": "ada@example.com"}])
async def test_valid_or_parsed_arguments_are_left_alone(args: str | dict[str, Any]) -> None:
    tally = RepairTally()
    agent, sent = _agent(FunctionModel(_calls_once(args)), tally)

    await agent.run("mail Ada", deps=AgentDeps())

    assert sent == ["ada@example.com"]
    assert tally.count == 0


async def test_a_missing_field_still_fails_validation_and_retries() -> None:
    """Only the syntax is repaired; what the schema refuses is still refused."""
    tally = RepairTally()
    turns: list[int] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        turns.append(1)
        if len(turns) == 1:
            return ModelResponse(parts=[ToolCallPart("send", '{"recipient": "ada",}', "c1")])
        return ModelResponse(parts=[TextPart("gave up")])

    agent, sent = _agent(FunctionModel(respond), tally)
    result = await agent.run("mail Ada", deps=AgentDeps())

    assert sent == []
    # Repaired, but retried anyway: no retry was saved, so none is counted.
    assert tally.count == 0
    assert any(
        isinstance(part, RetryPromptPart)
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
    )


@pytest.mark.security
async def test_a_repaired_call_still_goes_through_the_approval_gate() -> None:
    """The gate is asked about the repaired call, with the arguments the tool will get."""
    asked: list[ApprovalRequest] = []

    async def approve(request: ApprovalRequest) -> ApprovalGranted:
        asked.append(request)
        return ApprovalGranted(tool_args=request.tool_args)

    tally = RepairTally()
    agent, sent = _agent(
        FunctionModel(_calls_once("{'to': 'ada@example.com'}")),
        tally,
        ApprovalGate(gate_every_tool=True),
    )
    await agent.run("mail Ada", deps=AgentDeps(request_approval=approve))

    assert [request.tool_args for request in asked] == [{"to": "ada@example.com"}]
    assert sent == ["ada@example.com"]
    assert tally.count == 1


async def test_the_repair_span_carries_no_arguments() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tally = RepairTally()
    agent, _ = _agent(FunctionModel(_calls_once('{"to": "secret@example.com",}')), tally)
    agent.instrument = InstrumentationSettings(tracer_provider=provider)

    await agent.run("mail Ada", deps=AgentDeps())

    (repair,) = [
        span for span in exporter.get_finished_spans() if span.name == "repair_tool_arguments"
    ]
    assert "secret@example.com" not in str(dict(repair.attributes or {}))
