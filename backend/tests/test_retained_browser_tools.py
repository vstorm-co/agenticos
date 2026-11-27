"""Live-tab tools retain actual identity and keep the selected manual view in sync."""

from contextlib import asynccontextmanager

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.browser_use import WebBrowser
from app.agents.capabilities.browser_use._loop import LoopPolicy
from app.agents.capabilities.browser_use._page import PagePolicy
from app.agents.capabilities.browser_use._toolset import RetainedBrowser, build_toolset
from app.agents.deps import AgentDeps
from tests.test_browser_use import _element, _FakePage, _snapshot

pytestmark = pytest.mark.anyio


class LiveTabs:
    def __init__(self):
        self.pages = {name: _FakePage(_snapshot(_element(0))) for name in ("a", "b", "c")}
        self.active = "c"
        self.opened = []
        self.finished = 0

    @asynccontextmanager
    async def open(self, *, retained_tab_id, start_url, **options):
        self.opened.append((retained_tab_id, start_url, options))
        if retained_tab_id not in self.pages:
            self.pages[retained_tab_id] = _FakePage(_snapshot(_element(0)))
            self.active = retained_tab_id
        yield self.pages[retained_tab_id]

    async def tabs(self):
        return tuple(self.pages), self.active

    async def select(self, tab):
        self.active = tab

    async def close(self, tab):
        del self.pages[tab]
        self.active = next(reversed(self.pages), "main")

    async def finish(self):
        self.finished += 1

    def resource(self):
        return RetainedBrowser(self.open, self.tabs, self.select, self.close, self.finish)


async def call(tools, name, **args):
    ctx = RunContext(
        deps=AgentDeps(), model=TestModel(), usage=RunUsage(), tool_call_id="actual-test-tool"
    )
    offered = await tools.get_tools(ctx)
    return await tools.call_tool(name, args, ctx, offered[name])


def toolset(owner):
    return build_toolset(
        cdp_url="http://browser:9222",
        page_policy=PagePolicy(allowed_domains=None, candidate_cap=60, preview_width=1024),
        loop_policy=LoopPolicy(max_steps=1, preview=False, vision=False),
        retained=owner.resource(),
    )


async def test_browser_read_attaches_all_owned_targets_without_navigation_or_checkpoint_replay():
    owner = LiveTabs()
    tools = toolset(owner)
    async with tools:
        await call(tools, "browser_read")
        assert tools.session.page is owner.pages["c"]
        assert list(tools.sessions()) == ["a", "b", "c"]
        assert all(url is None for _, url, _ in owner.opened)
        assert tools.checkpoint is None
        assert all(
            not any(action.startswith("navigate:") for action in page.done)
            for page in owner.pages.values()
        )
    assert owner.finished == 1
    assert len(owner.pages) == 3


async def test_closing_selected_tab_keeps_environment_preview_on_the_agents_actual_next_tab():
    owner = LiveTabs()
    tools = toolset(owner)
    async with tools:
        await call(tools, "browser_read")
        await call(tools, "browser_switch_tab", tab_id="a")
        await call(tools, "browser_switch_tab", tab_id="b")
        assert owner.active == tools.tab_id == "b"
        await call(tools, "browser_close_tab", tab_id="b")
        assert "b" not in owner.pages
        assert tools.tab_id == "a"
        assert owner.active == tools.tab_id


async def test_explicit_navigation_and_new_tab_do_not_silently_replace_retained_tabs():
    owner = LiveTabs()
    tools = toolset(owner)
    async with tools:
        await call(tools, "browser_open", url="https://example.com/next")
        assert "navigate:https://example.com/next" in owner.pages["c"].done
        await call(tools, "browser_new_tab", url="https://example.com/new")
        assert len(owner.pages) == 4
        assert owner.active == tools.tab_id


async def test_live_capability_instructions_describe_actual_dom_not_checkpoint_copy():
    capability = WebBrowser(retained=LiveTabs().resource())
    assert "same live tabs" in capability.get_instructions()
    assert "Remote tabs close after each turn" not in capability.get_instructions()
    assert capability.get_toolset() is capability.get_toolset()
