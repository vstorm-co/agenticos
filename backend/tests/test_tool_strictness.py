"""An ordinary tool whose schema a strict grammar cannot express is sent non-strict (#259)."""

import uuid
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps
from app.agents.factory import _tool_strictness, build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.browser_fill import BrowserFillSelection
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio


async def browser_fill_credential(
    ctx: RunContext[None],
    secret_id: UUID,
    authorization_generation: UUID,
    selection: BrowserFillSelection,
) -> str:
    """Fill a saved credential."""
    return ""


async def lookup(ctx: RunContext[None], query: str) -> str:
    """Look something up."""
    return ""


async def _outgoing(*funcs: Any) -> dict[str, Mapping[str, Any]]:
    """The tool definitions an OpenAI-style chat request carries, built without a network call."""
    toolset = FunctionToolset()
    for func in funcs:
        toolset.add_function(func, takes_ctx=True)
    defs = [tool.tool_def for tool in toolset.tools.values()]
    prepared = await _tool_strictness(None, defs)  # type: ignore[arg-type]
    model = OpenAIChatModel(
        "claude-x", provider=OpenAIProvider(base_url="http://gateway.invalid/v1", api_key="unused")
    )
    _, params = model.prepare_request(None, ModelRequestParameters(function_tools=prepared))
    return {
        tool.name: model._map_tool_definition(tool, {})["function"]
        for tool in params.function_tools
    }


async def test_inexpressible_tool_schema_is_sent_non_strict() -> None:
    sent = (await _outgoing(browser_fill_credential))["browser_fill_credential"]

    assert "maxItems" in str(sent["parameters"])
    assert not sent.get("strict")


async def test_expressible_tool_schema_keeps_the_provider_default() -> None:
    sent = (await _outgoing(lookup))["lookup"]

    assert sent.get("strict") is True


class _OffersBrowserFill(AbstractCapability[AgentDeps]):
    """A capability that brings its own tool, as the browser capability does."""

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps]()
        toolset.add_function(browser_fill_credential, name="capability_fill", takes_ctx=True)
        return toolset


async def test_built_agent_sends_inexpressible_tools_non_strict() -> None:
    """Through `build_agent`, so it fails if `PrepareTools(_tool_strictness)` leaves the capability list."""
    from_toolset = FunctionToolset[AgentDeps]()
    from_toolset.add_function(browser_fill_credential, name="toolset_fill", takes_ctx=True)
    from_toolset.add_function(
        browser_fill_credential, name="explicit_fill", takes_ctx=True, strict=True
    )
    from_toolset.add_function(lookup, takes_ctx=True)
    built = build_agent(
        AgentSpec(name="Support"),
        ModelRequestSpec(
            profile_id=uuid.uuid4(),
            label="gateway",
            provider="openai",
            model="claude-x",
            params={},
            credential=ResolvedCredential(
                provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
            ),
            fallbacks=[],
        ),
        organization_id=uuid.uuid4(),
        extra_toolsets=[from_toolset],
        extra_capabilities=[_OffersBrowserFill()],
    )
    sent: dict[str, bool | None] = {}

    def capture(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        sent.update({tool.name: tool.strict for tool in info.function_tools})
        return ModelResponse(parts=[TextPart("done")])

    with built.agent.override(model=FunctionModel(capture)):
        await built.agent.run("hi", deps=built.deps)

    assert sent["toolset_fill"] is False
    assert sent["capability_fill"] is False
    assert sent["explicit_fill"] is True
    assert sent["lookup"] is None
