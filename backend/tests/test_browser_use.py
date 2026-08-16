"""The browser_use capability: registration, config, the SSRF guard, and the seam.

Every test runs with the `browser-use` extra absent - the CI state - which is the
point: the capability must register, validate, build and enumerate its one tool
without it, reaching the engine only when `browse_web` is called. The engine is
substituted with a fake through `BrowserDelegateFactory`, so nothing here launches
a browser or makes a model request.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai._run_context import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.browser_use import BrowserUse, BrowserUseConfig
from app.agents.capabilities.browser_use._toolset import (
    BrowserDelegate,
    build_toolset,
    harness_kwargs,
)
from app.core.sanitize import SSRFBlockedError
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES

pytestmark = pytest.mark.anyio


def _run_context() -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


def _build(config: dict[str, Any]) -> BrowserUse:
    """Assemble the capability through its registered builder, as the runner would."""
    definition = get("browser_use")
    built = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="browser_use", config=config),
            config=definition.validate_config(config),
            resources={},
        )
    )
    assert isinstance(built, BrowserUse)
    return built


class _FakeDelegate:
    """Records the task it was handed and returns a canned result."""

    def __init__(self) -> None:
        self.tasks: list[str] = []

    async def browse_web(self, task: str) -> str:
        self.tasks.append(task)
        return f"result for: {task}"


async def _call_browse_web(built: BrowserUse, task: str) -> str:
    ctx = _run_context()
    toolset = built.get_toolset()
    tools = await toolset.get_tools(ctx)
    return await toolset.call_tool("browse_web", {"task": task}, ctx, tools["browse_web"])


def test_the_default_mode_is_playwright_and_needs_no_cdp_url():
    config = BrowserUseConfig()
    assert config.mode == "playwright"
    assert config.cdp_url is None


def test_remote_mode_without_a_cdp_url_is_refused():
    with pytest.raises(ValidationError):
        BrowserUseConfig(mode="remote")


def test_a_cdp_url_in_playwright_mode_is_refused():
    with pytest.raises(ValidationError):
        BrowserUseConfig(mode="playwright", cdp_url="http://browser.internal:9222")


def test_a_remote_cdp_url_on_a_private_address_is_refused():
    """The SSRF guard's first production caller (agenticos#33).

    A `cdp_url` is a URL this deployment connects to server-side, so a loopback
    endpoint - a debugger on the host, a metadata service - is refused before the
    agent is assembled, not reached.
    """
    with pytest.raises(SSRFBlockedError):
        _build({"mode": "remote", "cdp_url": "http://127.0.0.1:9222"})


def test_a_remote_cdp_url_on_a_public_address_builds():
    built = _build({"mode": "remote", "cdp_url": "http://8.8.8.8:9222"})
    assert built.mode == "remote"
    assert built.cdp_url == "http://8.8.8.8:9222"


def test_a_websocket_cdp_scheme_is_allowed():
    built = _build({"mode": "remote", "cdp_url": "ws://8.8.8.8:9222/devtools/browser"})
    assert built.cdp_url == "ws://8.8.8.8:9222/devtools/browser"


async def test_the_capability_offers_only_browse_web():
    built = _build({})
    tools = await built.get_toolset().get_tools(_run_context())
    assert set(tools) == {"browse_web"}


async def test_the_toolset_is_built_once_and_reused():
    built = _build({})
    assert built.get_toolset() is built.get_toolset()


def test_the_instructions_warn_that_page_content_is_untrusted():
    built = _build({})
    instructions = built.get_instructions()
    assert "browse_web" in instructions
    assert "untrusted" in instructions.lower()


async def test_building_the_capability_launches_no_browser():
    """The capability pays nothing until `browse_web` is called.

    Assembling it and enumerating its tool must not reach the engine: the factory
    is invoked only on a call, which is what keeps a bound-but-unused capability
    free and what lets it build with the `browser-use` extra absent.
    """
    calls: list[dict[str, Any]] = []

    def factory(kwargs: dict[str, Any]) -> BrowserDelegate:
        calls.append(kwargs)
        return _FakeDelegate()

    built = _build({})
    built.delegate_factory = factory
    toolset = built.get_toolset()
    await toolset.get_tools(_run_context())
    assert calls == []


async def test_browse_web_delegates_the_task_to_the_engine():
    fake = _FakeDelegate()
    built = BrowserUse(delegate_factory=lambda _kwargs: fake)
    result = await _call_browse_web(built, "find the price of the Pro plan")
    assert result == "result for: find the price of the Pro plan"
    assert fake.tasks == ["find the price of the Pro plan"]


async def test_browse_web_passes_the_mapped_config_to_the_engine():
    seen: dict[str, Any] = {}

    def factory(kwargs: dict[str, Any]) -> BrowserDelegate:
        seen.update(kwargs)
        return _FakeDelegate()

    built = BrowserUse(
        mode="remote",
        allowed_domains=["*.example.com"],
        max_steps=7,
        use_vision=False,
        cdp_url="http://8.8.8.8:9222",
        delegate_factory=factory,
    )
    await _call_browse_web(built, "go")
    assert seen == {
        "allowed_domains": ["*.example.com"],
        "max_steps": 7,
        "use_vision": False,
        "cdp_url": "http://8.8.8.8:9222",
    }


async def test_browse_web_fails_loudly_when_the_extra_is_absent():
    """A bound capability whose deployment lacks the extra fails the tool, with the fix."""

    def factory(_kwargs: dict[str, Any]) -> BrowserDelegate:
        raise ImportError("No module named 'browser_use'")

    built = BrowserUse(delegate_factory=factory)
    with pytest.raises(RuntimeError, match="browser-use"):
        await _call_browse_web(built, "go")


def test_harness_kwargs_maps_playwright_to_a_local_headless_launch():
    kwargs = harness_kwargs(
        mode="playwright",
        allowed_domains=None,
        max_steps=25,
        use_vision=True,
        headless=True,
        cdp_url=None,
    )
    assert kwargs == {
        "allowed_domains": None,
        "max_steps": 25,
        "use_vision": True,
        "headless": True,
    }


def test_harness_kwargs_maps_remote_to_a_cdp_attachment():
    kwargs = harness_kwargs(
        mode="remote",
        allowed_domains=["example.com"],
        max_steps=10,
        use_vision=False,
        headless=True,
        cdp_url="http://8.8.8.8:9222",
    )
    assert kwargs == {
        "allowed_domains": ["example.com"],
        "max_steps": 10,
        "use_vision": False,
        "cdp_url": "http://8.8.8.8:9222",
    }


def test_build_toolset_defaults_to_the_real_engine_factory():
    """With no factory, the toolset still builds (the engine is reached lazily)."""
    toolset = build_toolset(kwargs={"allowed_domains": None, "max_steps": 25, "use_vision": True})
    assert toolset is not None


def test_the_capabilitys_scope_is_granted_by_default():
    """A published browser_use agent is not refused for an ungranted scope."""
    assert get("browser_use").scopes <= DEFAULT_GRANTED_SCOPES
    assert "web:browse" in DEFAULT_GRANTED_SCOPES
