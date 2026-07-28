"""Web research capability - search the public web."""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability, WebSearch

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.web_research._capability import WebResearch
from app.core.secret_kinds import (
    ApiKeySecret,
    SecretCondition,
    SecretKind,
    SecretRequirement,
)

__all__ = ["WebResearch", "WebResearchConfig"]

# Which methods authenticate. `native` uses the model provider's own search and
# DuckDuckGo needs no account, so a key is neither required nor read for either.
KEYED_METHODS = frozenset({"tavily", "brave", "exa"})


class WebResearchConfig(BaseModel):
    """How this agent searches the web.

    `method` is the whole decision, and it is offered as a list rather than a
    text field because every value is either a named service or a property of
    the model - none of it is something to type correctly.
    """

    method: Literal["duckduckgo", "native", "tavily", "brave", "exa"] = Field(
        default="duckduckgo",
        description=(
            "duckduckgo: free, no account, results rendered as clickable sources. "
            "native: the model provider searches with its own index and citations "
            "(only on models that support it). "
            "tavily: summarised for a model to read. "
            "brave: an index of its own. "
            "exa: search by meaning rather than keywords."
        ),
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="How many results one search returns; ignored for native search.",
    )


@register(
    id="web_research",
    name="Web search",
    category="research",
    description="Look up current information on the public web.",
    tools=(
        CapabilityToolInfo(
            id="web_search",
            description="Search the public web for current information.",
        ),
    ),
    config_schema=WebResearchConfig,
    scopes=("web:read",),
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The API key for the chosen search service",
        # Only the paid services need one. A flat requirement would either lock
        # the free default behind an account, or let a Tavily agent publish with
        # nothing to authenticate with and fail on its first search.
        required_when=SecretCondition(field="method", equals=tuple(sorted(KEYED_METHODS))),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    config = ctx.config if isinstance(ctx.config, WebResearchConfig) else WebResearchConfig()

    if config.method == "native":
        # Pydantic AI's own capability: the request never reaches us, so there is
        # no key to hold and no payload to normalise. It raises on a model with
        # no native search, which is the right moment to find that out.
        return WebSearch()

    key = ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    return WebResearch(provider=config.method, max_results=config.max_results, api_key=key)
