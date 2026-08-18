"""Browser automation - delegate an open-ended web task to an autonomous browser agent."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.browser_use._capability import BrowserUse
from app.core.sanitize import validate_webhook_url

__all__ = ["BrowserUse", "BrowserUseConfig", "validate_cdp_url"]

# A CDP endpoint is reached over HTTP(S) or a WebSocket, so the SSRF check allows
# those four rather than webhook's http/https default. Everything else it enforces
# - no userinfo, no private/reserved/loopback address, DNS resolved to a public IP -
# applies unchanged.
_CDP_SCHEMES = frozenset({"http", "https", "ws", "wss"})


class BrowserUseConfig(BaseModel):
    """How this agent browses the web.

    `mode` is the whole decision. `playwright` launches a headless Chromium next to
    the agent; `remote` attaches to a browser an operator runs elsewhere - a
    hardened, isolated service a self-hosted deployment points at instead of giving
    the app container a browser process. `remote` needs a `cdp_url`; `playwright`
    forbids one.
    """

    mode: Literal["playwright", "remote"] = Field(
        default="playwright",
        description=(
            "playwright: launch a headless browser locally. "
            "remote: attach to a browser running elsewhere via its CDP endpoint."
        ),
    )
    cdp_url: str | None = Field(
        default=None,
        description="Chromium DevTools endpoint to attach to; required by (and only valid in) remote mode.",
    )
    allowed_domains: list[str] | None = Field(
        default=None,
        description="Domains the agent may navigate to; null means no restriction. Globs like *.example.com are allowed.",
    )
    max_steps: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Hard cap on the browser agent's steps per call; each step is one model request.",
    )
    use_vision: bool = Field(
        default=True,
        description="Send page screenshots to the browser agent's model; better on visual layouts, more tokens.",
    )
    headless: bool = Field(
        default=True,
        description="Run a locally launched browser without a visible window (playwright mode only).",
    )

    @model_validator(mode="after")
    def _cdp_url_matches_mode(self) -> "BrowserUseConfig":
        if self.mode == "remote" and not self.cdp_url:
            raise ValueError(
                "mode 'remote' requires a cdp_url pointing at a Chromium DevTools endpoint"
            )
        if self.mode == "playwright" and self.cdp_url:
            raise ValueError(
                "cdp_url is only valid in mode 'remote'; a playwright browser is launched locally"
            )
        return self


def validate_cdp_url(config: BrowserUseConfig) -> None:
    """Refuse a remote `cdp_url` that SSRF protection blocks.

    A `cdp_url` is a URL this deployment connects to server-side, so it is exactly
    what `validate_webhook_url` exists to refuse - a metadata endpoint, a loopback
    debugger, an internal service. Nothing to check in `playwright` mode, where the
    config validator has already forbidden a `cdp_url`.

    Run at publish, not at build: it resolves DNS through `socket.getaddrinfo`,
    which blocks, and the build path runs on the event loop inside a tool call. The
    caller runs it in a thread (`asyncio.to_thread`) so a run is refused once, at
    publish, off the loop - rather than re-resolved on every build.

    Raises:
        SSRFBlockedError: the endpoint is loopback, private, reserved or metadata.
        UrlRefusedError: the URL is malformed. `_browser_use_problems` quotes the
            message into a publish problem a person reads, which is safe because
            every refusal `validate_webhook_url` raises is one written there
            rather than by the standard library about the caller's text (#861).
    """
    if config.mode == "remote" and config.cdp_url is not None:
        validate_webhook_url(config.cdp_url, allowed_schemes=_CDP_SCHEMES)


@register(
    id="browser_use",
    name="Browser automation",
    category="research",
    description="Delegate an open-ended web task to an autonomous browser agent.",
    tools=(
        CapabilityToolInfo(
            id="browse_web",
            description="Delegate an open-ended web task to an autonomous browser agent.",
            side_effecting=True,
        ),
    ),
    config_schema=BrowserUseConfig,
    side_effecting=True,
    scopes=("web:browse",),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    # No I/O here: `build` runs on the event loop inside a tool call, and the SSRF
    # check resolves DNS. The remote `cdp_url` is refused at publish instead, by
    # `validate_cdp_url` run off the loop - see agenticos#33.
    config = ctx.config if isinstance(ctx.config, BrowserUseConfig) else BrowserUseConfig()
    return BrowserUse(
        mode=config.mode,
        allowed_domains=config.allowed_domains,
        max_steps=config.max_steps,
        use_vision=config.use_vision,
        headless=config.headless,
        cdp_url=config.cdp_url,
    )
