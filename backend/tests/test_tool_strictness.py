"""An ordinary tool whose schema a strict grammar cannot express is sent non-strict (#259)."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import FunctionToolset

from app.agents.factory import _tool_strictness
from app.core.browser_fill import BrowserFillSelection

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
