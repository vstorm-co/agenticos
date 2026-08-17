"""Web fetch capability - read the page behind a URL."""

import re

from pydantic import BaseModel, Field, field_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.web_fetch._capability import (
    FETCH_DESCRIPTION,
    FetchMethod,
    build_web_fetch,
)

__all__ = ["WebFetchConfig"]

# A bare hostname, lower case, which is the only thing the filter can ever match:
# it compares against the hostname `urlparse` read off the URL. Anything else -
# a scheme, a path, a port, a `*.example.com` glob copied from `browser_use`,
# whose engine does support them - matches nothing, and an agent configured with
# an allowlist that matches nothing can fetch no page at all.
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


class WebFetchConfig(BaseModel):
    """How this agent reads a URL.

    `method` is the whole decision; the rest bounds what one call can cost and
    where it may go.
    """

    method: FetchMethod = Field(
        default="local",
        description=(
            "local: we fetch the page, identically on every model. "
            "native: the model provider fetches it with its own egress and citations "
            "(only on models that support it). "
            "auto: native where the model has it, ours everywhere else."
        ),
        json_schema_extra={
            "x-enum-labels": {
                "local": "This deployment fetches the page",
                "native": "The model provider fetches it",
                "auto": "The provider where it can, this deployment otherwise",
            }
        },
    )
    max_content_chars: int = Field(
        default=50_000,
        ge=1_000,
        le=200_000,
        description=(
            "How much of a page one fetch returns before it is truncated; roughly "
            "four characters per token. Ignored under native fetch, which the "
            "provider bounds itself."
        ),
    )
    allowed_domains: list[str] | None = Field(
        default=None,
        description=(
            "Bare hostnames the agent may fetch, e.g. docs.example.com; null means "
            "any. Matched exactly - no wildcards, no subdomains."
        ),
    )
    blocked_domains: list[str] | None = Field(
        default=None,
        description="Bare hostnames the agent may never fetch, matched exactly.",
    )

    @field_validator("allowed_domains", "blocked_domains")
    @classmethod
    def _bare_hostnames(cls, value: list[str] | None) -> list[str] | None:
        """Refuse a filter entry that could never match, and the empty list.

        Both failures are silent otherwise. An entry the comparison cannot match
        leaves a hole in a denylist or takes a page out of an allowlist, and an
        empty allowlist is not "unrestricted" - it allows nothing, so the agent
        holds a tool that refuses every URL. `null` is how unrestricted is said.
        """
        if value is None:
            return None
        if not value:
            raise ValueError("use null for no restriction; an empty list allows nothing")
        cleaned = [entry.strip().lower() for entry in value]
        bad = [entry for entry in cleaned if not _HOSTNAME.match(entry)]
        if bad:
            raise ValueError(
                f"not bare hostnames: {', '.join(bad)}. Give a host on its own, "
                "like docs.example.com - no scheme, path, port or wildcard"
            )
        return cleaned


@register(
    id="web_fetch",
    name="Web fetch",
    category="research",
    description="Read the page behind a URL, so an agent can follow a link it found.",
    tools=(
        CapabilityToolInfo(
            id="web_fetch",
            description=FETCH_DESCRIPTION,
        ),
    ),
    config_schema=WebFetchConfig,
    # Its own scope rather than `web_research`'s `web:read`. Searching reaches one
    # API this deployment chose; fetching dereferences whatever URL a model asks
    # for, from inside the container - so an operator who allows the first and not
    # the second has somewhere to say so.
    scopes=("web:fetch",),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    config = ctx.config if isinstance(ctx.config, WebFetchConfig) else WebFetchConfig()
    return build_web_fetch(
        method=config.method,
        max_content_chars=config.max_content_chars,
        allowed_domains=config.allowed_domains,
        blocked_domains=config.blocked_domains,
    )
