"""Unavailable tools recover through routes the current runtime actually offers."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability, ToolSearch
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_core import SchemaValidator, core_schema

from app.agents.code_mode import CodeCalls, code_mode
from app.agents.deps import AgentDeps
from app.agents.manifest import RunRecorder
from app.agents.tool_errors import ToolErrorEnvelope, ToolErrors
from app.agents.voice import AnswerUnknownTools, _ToolsOrUnavailable

pytestmark = pytest.mark.anyio


def _model(*calls: ToolCallPart) -> FunctionModel:
    remaining = iter(calls)

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        call = next(remaining, None)
        return ModelResponse(parts=[call] if call is not None else [TextPart("done")])

    return FunctionModel(respond)


def _failures(messages: list[ModelMessage]) -> list[ToolErrorEnvelope]:
    parts = [
        part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert all(part.outcome != "retried" for part in parts)
    return [
        ToolErrorEnvelope.model_validate_json(part.content)
        for part in parts
        if part.outcome == "failed"
    ]


async def test_a_hidden_tool_can_be_discovered_and_called_after_its_structured_refusal() -> None:
    invoked: list[bool] = []
    agent = Agent[AgentDeps, str](
        _model(
            ToolCallPart("hidden", {}, "early"),
            ToolCallPart("search_tools", {"queries": ["hidden"]}, "search"),
            ToolCallPart("hidden", {}, "ready"),
        ),
        capabilities=[
            ToolSearch(strategy="keywords"),
            ToolErrors(),
            AnswerUnknownTools(structured=True),
        ],
    )

    @agent.tool_plain(defer_loading=True)
    def hidden() -> str:
        """Read the hidden record."""
        invoked.append(True)
        return "found"

    result = await agent.run("read the hidden record", deps=AgentDeps())

    (failure,) = _failures(result.all_messages())
    assert failure.error.code == "tool_unavailable"
    assert failure.error.execution == "not_started"
    assert "Discover this tool with `search_tools`" in failure.error.message
    assert invoked == [True]


async def test_repeated_calls_before_discovery_do_not_exhaust_the_run() -> None:
    invoked: list[bool] = []
    agent = Agent[AgentDeps, str](
        _model(*(ToolCallPart("hidden", {}, f"call-{number}") for number in range(4))),
        capabilities=[
            ToolSearch(strategy="keywords"),
            ToolErrors(),
            AnswerUnknownTools(structured=True),
        ],
    )

    @agent.tool_plain(defer_loading=True)
    def hidden() -> str:
        invoked.append(True)
        return "found"

    result = await agent.run("read hidden", deps=AgentDeps())

    failures = _failures(result.all_messages())
    assert len(failures) == 4
    assert all(failure.error.execution == "not_started" for failure in failures)
    assert invoked == []


async def test_an_unavailable_tool_does_not_name_a_loader_or_search_route_that_is_absent() -> None:
    ctx = MagicMock(spec=RunContext)
    ctx.is_tool_available.return_value = False
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    hidden = ToolsetTool(
        toolset=toolset,
        tool_def=ToolDefinition(name="hidden", defer_loading=True),
        max_retries=1,
        args_validator=SchemaValidator(core_schema.dict_schema()),
    )
    tool = _ToolsOrUnavailable({"hidden": hidden}, toolset, ctx, structured=True).get("hidden")

    with pytest.raises(ToolFailed) as failure:
        await AnswerUnknownTools(structured=True).before_tool_validate(
            ctx, call=ToolCallPart("hidden", {}), tool_def=tool.tool_def, args={}
        )

    envelope = ToolErrorEnvelope.model_validate_json(failure.value.message)
    assert (
        envelope.error.message
        == "This tool is not registered for direct invocation in the current context."
    )


async def test_a_name_absent_from_code_mode_does_not_get_an_invented_invocation_route() -> None:
    invoked: list[bool] = []
    agent = Agent[AgentDeps, str](
        _model(
            ToolCallPart("missing", {}, "missing"),
            ToolCallPart("run_code", {"code": "await read_record()"}, "supported"),
        ),
        capabilities=[
            ToolSearch(strategy="keywords"),
            ToolErrors(),
            AnswerUnknownTools(structured=True),
            code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=5),
            CodeCalls(recorder=RunRecorder()),
        ],
    )

    @agent.tool_plain
    def read_record() -> str:
        invoked.append(True)
        return "found"

    result = await agent.run("read a record", deps=AgentDeps())

    (failure,) = _failures(result.all_messages())
    assert failure.error.code == "tool_unavailable"
    assert (
        failure.error.message
        == "This tool is not registered for direct invocation in the current context."
    )
    assert "permission" not in failure.error.message
    assert invoked == [True]


@dataclass
class _DeferredTools(AbstractCapability[AgentDeps]):
    invoked: int = 0

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        def guarded() -> str:
            self.invoked += 1
            return "found"

        return FunctionToolset(tools=[guarded])


async def test_a_capability_gated_tool_names_its_registered_loader_then_executes_after_loading() -> (
    None
):
    capability = _DeferredTools(id="library", defer_loading=True)
    agent = Agent[AgentDeps, str](
        _model(
            ToolCallPart("guarded", {}, "early"),
            ToolCallPart("load_capability", {"id": "library"}, "load"),
            ToolCallPart("guarded", {}, "ready"),
        ),
        capabilities=[capability, ToolErrors(), AnswerUnknownTools(structured=True)],
    )

    result = await agent.run("read the guarded record", deps=AgentDeps())

    (failure,) = _failures(result.all_messages())
    assert "Load capability 'library' with `load_capability`" in failure.error.message
    assert failure.error.execution == "not_started"
    assert capability.invoked == 1
