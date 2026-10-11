"""`connect_account`: a personal service connected while the run waits.

Driven through a real agent with a scripted model, because the point is what
the *same run* can do afterwards: the service's tools have to appear on the step
after the call and be callable there, not on the next message.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from app.agents.connect_on_use import (
    ConnectionRequest,
    ConnectOnUse,
    PendingService,
    ServiceOutcome,
)
from app.agents.deps import AgentDeps

pytestmark = pytest.mark.anyio

_NOTION = ConnectionRequest(catalog_key="notion", name="Notion", gap="not_connected")


def _notion_toolset() -> AbstractToolset[AgentDeps]:
    """What the person's own Notion connection resolves to, prefixed like MCP's."""

    def search(query: str) -> str:
        return f"3 pages about {query}"

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(search)
    return toolset.prefixed("notion")


def _returns(messages: list[ModelMessage]) -> dict[str, str]:
    return {
        part.tool_name: str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }


class _Script:
    """A model that calls `connect_account`, then the first Notion tool it sees."""

    def __init__(self, service: str = "notion") -> None:
        self.service = service
        self.seen: list[set[str]] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tools = {tool.name for tool in info.function_tools}
        self.seen.append(tools)
        returned = _returns(messages)
        if "connect_account" not in returned and len(self.seen) == 1:
            return ModelResponse(parts=[ToolCallPart("connect_account", {"service": self.service})])
        if "notion_search" in tools and "notion_search" not in returned:
            return ModelResponse(parts=[ToolCallPart("notion_search", {"query": "roadmap"})])
        return ModelResponse(parts=[TextPart("done")])


def _capability(
    connected: bool, outcome: ServiceOutcome | None = None
) -> tuple[ConnectOnUse, list[ConnectionRequest]]:
    """The capability over Notion, with the person answering `connected` every time."""
    asked: list[ConnectionRequest] = []

    async def request_connection(request: ConnectionRequest) -> bool:
        asked.append(request)
        # A real prompt waits for the person; yielding is what lets a second
        # call in the same response reach this point while the first waits.
        await asyncio.sleep(0)
        return connected

    async def resolve() -> ServiceOutcome:
        return _notion_toolset() if outcome is None else outcome

    capability = ConnectOnUse(
        services=[PendingService(request=_NOTION, resolve=resolve)],
        request_connection=request_connection,
    )
    return capability, asked


async def _run(capability: ConnectOnUse, script: _Script) -> list[ModelMessage]:
    agent = Agent(FunctionModel(script), deps_type=AgentDeps, capabilities=[capability])
    result = await agent.run("what is on our roadmap?", deps=AgentDeps())
    return result.all_messages()


async def test_a_connected_service_is_used_in_the_same_run():
    capability, asked = _capability(True)
    script = _Script()

    messages = await _run(capability, script)

    assert asked == [_NOTION]
    assert "notion_search" not in script.seen[0]
    assert "notion_search" in script.seen[1]
    returned = _returns(messages)
    assert "Notion is connected" in returned["connect_account"]
    assert returned["notion_search"] == "3 pages about roadmap"


async def test_a_skipped_connection_attaches_nothing_and_says_so():
    capability, asked = _capability(False)
    script = _Script()

    messages = await _run(capability, script)

    assert asked == [_NOTION]
    assert all("notion_search" not in tools for tools in script.seen)
    assert "did not connect Notion" in _returns(messages)["connect_account"]


async def test_a_skipped_service_is_not_asked_for_again_in_the_run():
    """A model that retries the call gets the same answer, not a second card."""
    capability, asked = _capability(False)

    def twice(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        calls = sum(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        )
        if calls < 2:
            return ModelResponse(parts=[ToolCallPart("connect_account", {"service": "notion"})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(twice), deps_type=AgentDeps, capabilities=[capability])
    result = await agent.run("roadmap?", deps=AgentDeps())

    assert asked == [_NOTION]
    returns = [
        str(part.content)
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "chose not to connect Notion earlier" in returns[1]


async def test_two_calls_in_one_response_put_up_one_card():
    """Tool calls in one response run concurrently; the second waits for the
    first and then reads what it decided."""
    capability, asked = _capability(False)

    def both(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart("connect_account", {"service": "notion"}, tool_call_id="a"),
                ToolCallPart("connect_account", {"service": "notion"}, tool_call_id="b"),
            ]
        )

    agent = Agent(FunctionModel(both), deps_type=AgentDeps, capabilities=[capability])
    result = await agent.run("roadmap?", deps=AgentDeps())

    assert asked == [_NOTION]
    returns = sorted(
        str(part.content)
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    )
    assert "chose not to connect Notion earlier" in returns[0]
    assert "did not connect Notion" in returns[1]


async def test_a_service_already_connected_is_not_asked_for_again():
    capability, asked = _capability(True)

    def twice(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        calls = sum(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        )
        if calls < 2:
            return ModelResponse(parts=[ToolCallPart("connect_account", {"service": "notion"})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(twice), deps_type=AgentDeps, capabilities=[capability])
    result = await agent.run("roadmap?", deps=AgentDeps())

    assert asked == [_NOTION]
    last = [
        str(part.content)
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ][-1]
    assert last == "Notion is already connected; its tools are available."


@pytest.mark.parametrize(
    ("outcome", "said"),
    [
        ("not_connected", "is still not connected"),
        ("undecided", "mark one as default"),
        ("unauthorized", "authorize it again"),
        ("unreachable", "its server did not answer"),
    ],
)
async def test_a_connection_that_still_does_not_work_attaches_nothing(
    outcome: ServiceOutcome, said: str
):
    """They said they connected it, and reading it again says otherwise."""
    capability, _asked = _capability(True, outcome)
    script = _Script()

    messages = await _run(capability, script)

    assert all("notion_search" not in tools for tools in script.seen)
    assert said in _returns(messages)["connect_account"]


async def test_a_service_nobody_offered_is_steered_back_to_the_ones_there_are():
    capability, asked = _capability(True)
    script = _Script(service="jira")

    messages = await _run(capability, script)

    assert asked == []
    retries = [
        part.content
        for message in messages
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]
    assert retries == ["There is no service 'jira' to connect. Use one of: \"notion\"."]


async def test_the_model_is_told_to_connect_when_needed_not_up_front():
    capability, _asked = _capability(True)

    instructions = capability.get_instructions()

    assert "Do not raise it up front" in instructions
    assert 'call `connect_account` with service="notion"' in instructions
    assert "they have not connected it" in instructions
