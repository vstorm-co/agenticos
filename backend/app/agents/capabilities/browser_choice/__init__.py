"""Browser automation that chooses from a page instead of composing an action."""

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.browser_choice._capability import BrowserChoice
from app.agents.capabilities.browser_choice._elements import HARD_CANDIDATE_CAP
from app.core.sanitize import UrlRefusedError, validate_webhook_url
from app.core.secret_kinds import ApiKeySecret, SecretKind, SecretRequirement

__all__ = ["BrowserChoice", "BrowserChoiceConfig", "validate_cdp_url"]

_CDP_SCHEMES = frozenset({"http", "https", "ws", "wss"})
"""A CDP endpoint is reached over HTTP(S) or a WebSocket.

Everything else `validate_webhook_url` enforces - no userinfo, no private,
reserved or loopback address, DNS resolved to a public IP - applies unchanged.
The same four `browser_use` allows, and the same reason.
"""


class BrowserChoiceConfig(BaseModel):
    """How this agent works a web page.

    Three groups. Where the browser is and where it may go; which decision model
    picks and where it runs; and how far and how sure the loop has to be before it
    acts. Every limit is here rather than a constant in the loop, because an agent
    that browses a slow internal tool and one that browses a public docs site want
    different numbers and neither should need a release to get them.
    """

    cdp_url: str = Field(
        default="",
        description=(
            "Chromium DevTools endpoint to drive - a browser service the operator "
            "runs, not a process in the API container."
        ),
    )
    """Defaulted rather than required, and the default is refused at publish.

    Every capability has to be buildable from an empty config - that is what the
    registry's drift test does to enumerate the tools each one offers, and a
    required field makes the capability unenumerable rather than
    unconfigurable. So the demand for an endpoint is made where it can be made
    with a sentence a person reads, in `validate_cdp_url`, and an agent that
    somehow holds a blank one contributes no tool instead of one that fails on
    its first call.
    """
    allowed_domains: list[str] | None = Field(
        default=None,
        description=(
            "Hosts the browser may be on; null means no restriction. Globs like "
            "*.example.com are allowed. Checked on every step, not only the first."
        ),
    )
    decision_model: str = Field(
        default="jev-latest",
        description="The model that picks the operation and the element each step.",
    )
    decision_base_url: str | None = Field(
        default=None,
        description=(
            "Where that model runs, when it is not the vendor's public endpoint. "
            "Page content is sent here, so a deployment that may not send page "
            "content to a third party sets this."
        ),
    )
    max_steps: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Hard cap on steps per call; each step is one decision request.",
    )
    candidate_cap: int = Field(
        default=60,
        ge=2,
        le=HARD_CANDIDATE_CAP,
        description=(
            "How many of the page's elements may be offered as choices in one "
            "step. Lower is cheaper and blinder; the loop's answer to a page too "
            "dense for the cap is to scroll."
        ),
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Refuse to act on a pick the decision model scored below this, ending "
            "the browse as blocked. 0 acts on every pick and reports the score."
        ),
    )
    preview: bool = Field(
        default=True,
        description=(
            "Send the viewport to the chat while the browse runs, so a person can "
            "watch it. Costs one JPEG per step on the socket."
        ),
    )
    preview_width: int = Field(
        default=1024,
        ge=320,
        le=1920,
        description="How wide those frames are, in pixels.",
    )


def validate_cdp_url(config: BrowserChoiceConfig) -> None:
    """Refuse a `cdp_url` that SSRF protection blocks.

    A `cdp_url` is a URL this deployment connects to server-side, so it is exactly
    what `validate_webhook_url` exists to refuse - a metadata endpoint, a loopback
    debugger, an internal service.

    Run at publish, not at build: it resolves DNS through `socket.getaddrinfo`,
    which blocks, and a capability is built on the event loop inside a tool call.
    The caller runs it in a thread, so a run is refused once, at publish, off the
    loop - rather than re-resolved on every build. This is `browser_use`'s
    arrangement and the reasoning is written out there (agenticos#33).

    Raises:
        SSRFBlockedError: the endpoint is loopback, private, reserved or metadata.
        UrlRefusedError: the URL is missing or malformed.
    """
    if not config.cdp_url:
        raise UrlRefusedError(
            "Browser automation needs a cdp_url: the Chromium DevTools endpoint "
            "of the browser service this agent should drive"
        )
    validate_webhook_url(config.cdp_url, allowed_schemes=_CDP_SCHEMES)


@register(
    id="browser_choice",
    name="Browser automation (choose)",
    category="research",
    description="Work through a web page by choosing one of the actions it actually offers.",
    tools=(
        CapabilityToolInfo(
            id="browse_page",
            description="Work through a web page towards a goal, one chosen action at a time.",
            side_effecting=True,
        ),
    ),
    config_schema=BrowserChoiceConfig,
    side_effecting=True,
    scopes=("web:browse",),
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The API key for the decision model that picks each step",
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    """Build the capability from the agent's config and its vault secret.

    Always a capability, never `None`, even with no endpoint and no key. A builder
    that returns `None` is a capability the registry's drift check cannot
    enumerate, and that check is what catches an undeclared side-effecting tool -
    the failure it exists for is silent, so escaping it is worse than building
    something that will refuse. A missing endpoint or key is refused by the tool,
    in a sentence, and refused earlier and better at publish.
    """
    config = ctx.config if isinstance(ctx.config, BrowserChoiceConfig) else BrowserChoiceConfig()
    key = ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    return BrowserChoice(
        cdp_url=config.cdp_url,
        api_key=key,
        decision_model=config.decision_model,
        decision_base_url=config.decision_base_url,
        allowed_domains=config.allowed_domains,
        max_steps=config.max_steps,
        candidate_cap=config.candidate_cap,
        min_confidence=config.min_confidence,
        preview=config.preview,
        preview_width=config.preview_width,
    )
