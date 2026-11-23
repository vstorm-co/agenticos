"""A deployment browser can be absent without taking the assistant down."""

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.capabilities.browser_use import (
    WebBrowser,
    WebBrowserConfig,
    cdp_endpoint,
    validate_cdp_url,
)
from app.agents.capabilities.browser_use._toolset import NO_ENDPOINT, UNREACHABLE
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from tests.test_browser_use import _build_capability, _Opener


def test_builtin_uses_the_operator_endpoint_and_an_explicit_choice_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222")
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    config = WebBrowserConfig()
    validate_cdp_url(config)
    built = _build_capability({})
    assert isinstance(built, WebBrowser) and built.cdp_url == "http://browser:9222"
    assert cdp_endpoint(WebBrowserConfig(cdp_url="http://custom:9222")) == "http://custom:9222"
    assert cdp_endpoint(WebBrowserConfig(connection="local")) == ""
    assert cdp_endpoint(WebBrowserConfig(connection="proxy")) == ""


@pytest.mark.security
def test_inherited_endpoints_still_require_the_operator_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://unapproved:9222")
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    with pytest.raises(UrlRefusedError, match="BROWSER_CDP_ALLOWED_HOSTS"):
        validate_cdp_url(WebBrowserConfig())


@pytest.mark.anyio
@pytest.mark.parametrize("browse", [False, True])
@pytest.mark.parametrize("configured", [False, True])
async def test_a_missing_browser_is_local_to_its_tool_call(
    monkeypatch: pytest.MonkeyPatch, browse: bool, configured: bool
) -> None:
    monkeypatch.setattr(
        settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222" if configured else ""
    )
    browser = _build_capability({})
    assert isinstance(browser, WebBrowser)
    opener = _Opener(fails=httpx.ConnectError("container unavailable"))
    # A configured endpoint fails on connection; an absent endpoint never dials.
    browser.page_factory = opener if configured else None
    calls = 0
    other_calls: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        assert "browser_open" in {tool.name for tool in info.function_tools}
        if calls == 1 and browse:
            return ModelResponse(
                parts=[ToolCallPart("browser_open", {"url": "https://example.test/"})]
            )
        if calls == (2 if browse else 1):
            if browse:
                returned = [
                    part.content
                    for message in messages
                    if isinstance(message, ModelRequest)
                    for part in message.parts
                    if isinstance(part, ToolReturnPart)
                ]
                assert (UNREACHABLE if configured else NO_ENDPOINT) in returned
            return ModelResponse(parts=[ToolCallPart("other_work", {})])
        return ModelResponse(parts=[TextPart("Other work completed")])

    def other_work() -> str:
        """Do independent work without a browser."""
        other_calls.append("done")
        return "done"

    agent = Agent(
        FunctionModel(respond), capabilities=[browser], tools=[other_work], deps_type=AgentDeps
    )
    result = await agent.run("Help with this task", deps=AgentDeps())
    assert result.output == "Other work completed"
    assert other_calls == ["done"]
    assert len(opener.opened) == (1 if browse and configured else 0)
