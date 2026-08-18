"""Web fetch capability - read the page behind a URL."""

import re

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    ProviderExecuted,
    register,
)
from app.agents.capabilities.web_fetch._capability import (
    FETCH_DESCRIPTION,
    PROVIDER_EXECUTED_METHODS,
    FetchMethod,
    a_label,
    build_web_fetch,
)

__all__ = ["PROVIDER_EXECUTED_METHODS", "WebFetchConfig"]

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
    def _bare_hostnames(cls, value: list[str] | None, info: ValidationInfo) -> list[str] | None:
        """Settle every entry's spelling, and refuse one that could never match.

        A filter entry the comparison cannot match is silent in both directions:
        it leaves a hole in a denylist, and takes a page out of an allowlist. So
        anything that is not a bare hostname is refused here, and anything that
        is one is stored in the single spelling DNS would be asked for - lower
        case, no root label, IDNA-encoded. What the filter is *handed* at build
        time is wider than what is stored; :func:`a_label` has the whole of it.

        An empty list means different things on the two fields, so it is not
        answered the same way. An empty allowlist allows nothing, which is an
        agent holding a tool that refuses every URL - `null` is how unrestricted
        is said, and the refusal is what stops the two being confused. An empty
        denylist denies nothing, which *is* what `null` means, so it is read as
        `null` rather than refused: an imported spec or an API caller
        representing "no denied hosts" as `[]` is saying something true.
        """
        if value is None:
            return None
        if not value:
            if info.field_name == "blocked_domains":
                return None
            raise ValueError("use null for no restriction; an empty list allows nothing")
        cleaned: list[str] = []
        bad: list[str] = []
        for entry in value:
            try:
                canonical = a_label(entry)
            except UnicodeError:
                bad.append(entry)
                continue
            if _HOSTNAME.match(canonical):
                cleaned.append(canonical)
            else:
                bad.append(canonical)
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
    provider_executed=ProviderExecuted(
        tools=("web_fetch",),
        field="method",
        equals=tuple(sorted(PROVIDER_EXECUTED_METHODS)),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    config = ctx.config if isinstance(ctx.config, WebFetchConfig) else WebFetchConfig()
    return build_web_fetch(
        method=config.method,
        max_content_chars=config.max_content_chars,
        allowed_domains=config.allowed_domains,
        blocked_domains=config.blocked_domains,
    )
