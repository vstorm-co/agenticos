"""MCP initialize instructions reach the model only when a connection opts in."""

import re

import pytest
from fastmcp import Client, FastMCP
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets.abstract import AbstractToolset

from app.agents.mcp import McpServerSpec, _make_toolset

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("include", [True, False])
@pytest.mark.parametrize("name", ["creo-digital-mcp-org", "notion-personal", "io.example:docs"])
async def test_server_instructions_survive_the_real_collection_path(
    include: bool, name: str
) -> None:
    instructions = "Search the company handbook before answering."
    server = FastMCP(name, instructions=instructions)
    toolset = _make_toolset(
        McpServerSpec(name=name, url="https://example.com/mcp", include_instructions=include)
    )
    mcp = toolset.wrapped.wrapped.wrapped.wrapped
    assert isinstance(mcp, MCPToolset)
    mcp.client = Client(server)
    seen: list[str | None] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions)
        return ModelResponse(parts=[TextPart("ok")])

    result = await Agent[None, str](FunctionModel(answer), toolsets=[toolset]).run(
        "Find the policy."
    )

    assert result.output == "ok"
    if include:
        assert len(seen) == 1
        assert seen[0] is not None
        assert instructions in seen[0]
    else:
        assert seen == [None]


async def test_two_connections_on_the_same_host_keep_distinct_instruction_sources() -> None:
    toolsets: list[AbstractToolset[None]] = []
    for name, instructions in (("work", "Use the work handbook."), ("personal", "Use my notes.")):
        toolset = _make_toolset(
            McpServerSpec(name=name, url="https://example.com/mcp", include_instructions=True)
        )
        mcp = toolset.wrapped.wrapped.wrapped.wrapped
        assert isinstance(mcp, MCPToolset)
        mcp.client = Client(FastMCP(name, instructions=instructions))
        toolsets.append(toolset)
    seen: list[str | None] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info.instructions)
        return ModelResponse(parts=[TextPart("ok")])

    await Agent[None, str](FunctionModel(answer), toolsets=toolsets).run("Find the policy.")

    assert len(seen) == 1
    assert seen[0] is not None
    assert "Use the work handbook." in seen[0]
    assert "Use my notes." in seen[0]
    sources = re.findall(r'<context id="([^"]+)">', seen[0])
    assert len(sources) == len(set(sources)) == 2
