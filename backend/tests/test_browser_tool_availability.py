"""Browser actions follow live tab state without hiding opening or restoration."""

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.capabilities._overrides import ToolOverrides
from app.agents.capabilities.browser_use import WebBrowser
from app.agents.deps import AgentDeps
from tests.test_browser_use import BROWSER_TOOLS, _Opener

pytestmark = pytest.mark.anyio

ENTRY_TOOLS = {"browse_web", "browser_open", "browser_new_tab", "browser_read", "browser_tabs"}


@pytest.mark.parametrize("renamed", [False, True])
async def test_opening_and_closing_a_tab_changes_the_offered_actions(renamed: bool) -> None:
    opener = _Opener()
    browser = WebBrowser(id="browser_use", cdp_url="http://browser:9222", page_factory=opener)
    close_name = "close_page" if renamed else "browser_close_tab"
    capability = (
        ToolOverrides(wrapped=browser, names={"browser_close_tab": close_name})
        if renamed
        else browser
    )
    offered: list[set[str]] = []

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        match len(offered):
            case 1:
                return ModelResponse(
                    parts=[ToolCallPart("browser_open", {"url": "https://example.test/"})]
                )
            case 2:
                return ModelResponse(parts=[ToolCallPart(close_name, {"tab_id": "main"})])
            case _:
                return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(respond), capabilities=[capability], deps_type=AgentDeps)
    result = await agent.run("Open and close the page.", deps=AgentDeps())
    assert result.output == "done"
    assert offered[0] == ENTRY_TOOLS
    assert offered[1] == (set(BROWSER_TOOLS) - {"browser_close_tab"}) | {close_name}
    assert offered[2] == ENTRY_TOOLS
    assert opener.closed == 1


async def test_a_parked_tab_keeps_switch_and_close_but_not_page_actions() -> None:
    from dataclasses import replace

    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import ToolDefinition

    from app.agents.capabilities.browser_use._toolset import BROWSER_TAB_REQUIREMENT
    from tests.test_browser_use import _direct, _tool_context

    browser = WebBrowser(id="browser_use", cdp_url="http://browser:9222", page_factory=_Opener())
    toolset = browser.get_toolset()
    ctx = _tool_context(TestModel())
    async with toolset:
        await _direct(toolset, "browser_open", {"url": "https://example.test/"})
        await toolset.park()
        definitions = [
            replace(tool.tool_def, capability_id="browser_use")
            for tool in (await toolset.get_tools(ctx)).values()
        ]
        foreign = ToolDefinition(
            name="another_capability",
            capability_id="other",
            metadata={BROWSER_TAB_REQUIREMENT: "active"},
        )
        offered = await browser.prepare_tools(ctx, [*definitions, foreign])
        assert {tool.name for tool in offered} == ENTRY_TOOLS | {
            "browser_switch_tab",
            "browser_close_tab",
            "another_capability",
        }


async def test_calling_a_tab_action_before_opening_cannot_execute_it() -> None:
    opener = _Opener()
    browser = WebBrowser(id="browser_use", cdp_url="http://browser:9222", page_factory=opener)
    calls = 0

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart("browser_close_tab", {"tab_id": "main"})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(FunctionModel(respond), capabilities=[browser], deps_type=AgentDeps)
    await agent.run("Close a nonexistent tab.", deps=AgentDeps())
    assert opener.opened == [] and opener.closed == 0
    assert calls == 2


async def test_search_cannot_discover_tab_actions_until_a_tab_is_open() -> None:
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    from app.agents.capabilities.tool_search import ConfiguredToolSearch

    browser = WebBrowser(id="browser_use", cdp_url="http://browser:9222", page_factory=_Opener())
    search = ConfiguredToolSearch(
        defer_capabilities=True,
        capability_tool_names=frozenset(BROWSER_TOOLS),
        max_results=12,
    )
    step = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal step
        step += 1
        if step == 2:
            returns = [
                part.content
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            assert "browser_close_tab" not in str(returns)
        match step:
            case 1:
                call = ToolCallPart("search_tools", {"queries": ["browser_close_tab"]})
            case 2:
                call = ToolCallPart("search_tools", {"queries": ["browser_open"]})
            case 3:
                call = ToolCallPart("browser_open", {"url": "https://example.test/"})
            case 4:
                call = ToolCallPart("search_tools", {"queries": ["browser_close_tab"]})
            case 5:
                assert "browser_close_tab" in {tool.name for tool in info.function_tools}
                call = ToolCallPart("browser_close_tab", {"tab_id": "main"})
            case _:
                assert "browser_close_tab" not in {tool.name for tool in info.function_tools}
                return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[call])

    agent = Agent(FunctionModel(respond), capabilities=[browser, search], deps_type=AgentDeps)
    await agent.run("Use the browser.", deps=AgentDeps())
    assert step == 6


async def test_enumerating_before_initialization_does_not_open_a_browser() -> None:
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import ToolDefinition

    from app.agents.capabilities.browser_use._toolset import BROWSER_TAB_REQUIREMENT
    from tests.test_browser_use import _tool_context

    opener = _Opener()
    browser = WebBrowser(id="browser_use", cdp_url="http://browser:9222", page_factory=opener)
    definitions = [
        ToolDefinition(name="browser_open", capability_id="browser_use"),
        ToolDefinition(
            name="browser_close_tab",
            capability_id="browser_use",
            metadata={BROWSER_TAB_REQUIREMENT: "any"},
        ),
        ToolDefinition(
            name="browser_click",
            capability_id="browser_use",
            metadata={BROWSER_TAB_REQUIREMENT: "active"},
        ),
    ]
    offered = await browser.prepare_tools(_tool_context(TestModel()), definitions)
    assert [tool.name for tool in offered] == ["browser_open"]
    assert opener.opened == []
