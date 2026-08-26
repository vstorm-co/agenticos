"""Keyless scale fixture for the factory's MCP tool-search assembly seam."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from app.agents.capabilities import load_builtins
from app.agents.factory import BuiltAgent, build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import NoSecret

pytestmark = pytest.mark.anyio

_TARGET_INDEX = 7
_TARGET_NAME = "catalog_lookup_record_0007"
_FIRST_REQUEST_BYTES = {12: 3_480, 100: 28_736, 1000: 287_036}
# 786 before `search_tools` was given a return shape. The tool a model reaches
# for when it is already lost is the worst place to leave it guessing what an
# empty answer means, and 238 bytes is what saying so costs on the one request
# that carries this tool alone.
_SEARCH_ONLY_BYTES = 1_024
_REVEALED_TARGET_BYTES = 1_346


@dataclass(frozen=True)
class _ToolCall:
    index: int
    record_id: str
    include_history: bool


@dataclass
class _Observation:
    requests: list[list[ToolDefinition]]
    calls: list[_ToolCall]


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _model_spec() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="Keyless fixture",
        provider="ollama",
        model="fixture",
        params={},
        credential=ResolvedCredential(
            provider="ollama",
            secret=NoSecret(),
            base_url="http://127.0.0.1:11434/v1",
        ),
        fallbacks=[],
    )


def _lookup_tool(index: int, calls: list[_ToolCall]) -> Callable[[str, bool], str]:
    def lookup(record_id: str, include_history: bool = False) -> str:
        calls.append(_ToolCall(index=index, record_id=record_id, include_history=include_history))
        return f"record-{index:04d}:{record_id}"

    return lookup


def _catalog(tool_count: int) -> tuple[AbstractToolset[Any], list[_ToolCall]]:
    calls: list[_ToolCall] = []
    toolset: FunctionToolset[Any] = FunctionToolset()
    for index in range(tool_count):
        description = f"Read deterministic café record {index:04d}."
        if index == _TARGET_INDEX:
            description += " Needle target for reveal and call."
        toolset.add_function(
            _lookup_tool(index, calls),
            takes_ctx=False,
            name=f"lookup_record_{index:04d}",
            description=description,
        )
    return toolset.prefixed("catalog"), calls


def _build(tool_count: int, *, with_search: bool) -> tuple[BuiltAgent, list[_ToolCall]]:
    toolset, calls = _catalog(tool_count)
    capabilities: list[dict[str, Any]] = []
    if with_search:
        capabilities.append(
            {"id": "tool_search", "config": {"strategy": "keywords", "max_results": 1}}
        )
    built = build_agent(
        AgentSpec(name="Tool search scale fixture", capabilities=capabilities),
        _model_spec(),
        organization_id=uuid.uuid4(),
        extra_toolsets=[toolset],
    )
    return built, calls


def _canonical_schema_bytes(tools: list[ToolDefinition]) -> int:
    """Measure a stable UTF-8 JSON projection of model-visible function schemas."""
    payload = [
        {
            "description": tool.description,
            "name": tool.name,
            "parameters_json_schema": tool.parameters_json_schema,
        }
        for tool in sorted(tools, key=lambda item: item.name)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return len(encoded)


async def _observe_without_search(tool_count: int) -> _Observation:
    built, calls = _build(tool_count, with_search=False)
    requests: list[list[ToolDefinition]] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        requests.append(list(info.function_tools))
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond, model_name="gpt-4.1")):
        await built.agent.run("Find the needle record.", deps=built.deps)
    return _Observation(requests=requests, calls=calls)


async def _observe_search_then_call(tool_count: int) -> _Observation:
    built, calls = _build(tool_count, with_search=True)
    requests: list[list[ToolDefinition]] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        requests.append(list(info.function_tools))
        if len(requests) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_tools",
                        args={"queries": ["needle target"]},
                        tool_call_id="search-1",
                    )
                ]
            )
        if len(requests) == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=_TARGET_NAME,
                        args={"record_id": "fixed", "include_history": True},
                        tool_call_id="target-1",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(respond, model_name="gpt-4.1")):
        await built.agent.run("Find the needle record.", deps=built.deps)
    return _Observation(requests=requests, calls=calls)


@pytest.mark.parametrize("tool_count", [12, 100, 1000])
async def test_tool_search_bounds_first_request_schema_bytes_and_reveals_a_callable_target(
    tool_count: int,
) -> None:
    """Byte snapshots are wire-neutral regression data, not token, cost, or quality claims."""
    unbound = await _observe_without_search(tool_count)
    searched = await _observe_search_then_call(tool_count)

    assert len(unbound.requests) == 1
    assert len(unbound.requests[0]) == tool_count
    assert "search_tools" not in {tool.name for tool in unbound.requests[0]}
    assert _canonical_schema_bytes(unbound.requests[0]) == _FIRST_REQUEST_BYTES[tool_count]

    assert len(searched.requests) == 3
    assert [tool.name for tool in searched.requests[0]] == ["search_tools"]
    assert _canonical_schema_bytes(searched.requests[0]) == _SEARCH_ONLY_BYTES
    expected_revealed_names = [
        _TARGET_NAME,
        "search_tools",
    ]
    for request in searched.requests[1:]:
        assert sorted(tool.name for tool in request) == expected_revealed_names
        assert _canonical_schema_bytes(request) == _REVEALED_TARGET_BYTES
    assert searched.calls == [
        _ToolCall(index=_TARGET_INDEX, record_id="fixed", include_history=True)
    ]
