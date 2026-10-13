"""A real web browser the agent works step by step, on the run's own model."""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, JsonValue
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.browser_use._capability import WebBrowser
from app.agents.capabilities.browser_use._elements import HARD_CANDIDATE_CAP
from app.core.config import settings
from app.core.sanitize import UrlRefusedError

__all__ = ["BROWSER_CAPABILITY_ID", "WebBrowser", "WebBrowserConfig", "validate_cdp_url"]

BROWSER_CAPABILITY_ID = "browser_use"

_DEFAULT_CDP_PORT = 9222
"""Chromium's own default debugging port, which is what a suggestion should guess."""

_CDP_SCHEMES = frozenset({"http", "https", "ws", "wss"})
"""A CDP endpoint is reached over HTTP(S) or a WebSocket, and over nothing else.

What decides whether the *host* is acceptable
is the operator's allowlist - see :func:`validate_cdp_url` for why it is that
rather than the SSRF guard.
"""


def _cdp_url_form(schema: dict[str, JsonValue]) -> None:
    """Hint the endpoint from what the operator already declared.

    `BROWSER_CDP_ALLOWED_HOSTS` is the list of browsers this deployment permits,
    so an author typing a `cdp_url` is choosing from it whether the form says so
    or not - and a field that refuses at publish without ever having said what it
    would accept is a field that wastes somebody's afternoon.

    **A placeholder and not a default**, which is the correction to the first
    version of this. The Builder's schema form *shows* a schema default without
    writing it into the binding until somebody edits the field - so a default
    here produced a form that looked filled in and a publish that was refused for
    having no `cdp_url`, which is a worse afternoon than the one it was meant to
    save. Grey text that says what to type does not lie about what is stored.

    Read when the schema is generated rather than when this module is imported,
    because a deployment's allowlist is configuration and this file is code.
    """
    hosts = [host.strip() for host in settings.BROWSER_CDP_ALLOWED_HOSTS if host.strip()]
    if not hosts:
        schema["x-placeholder"] = "Set BROWSER_CDP_ALLOWED_HOSTS first"
        return
    schema["x-placeholder"] = f"http://{hosts[0]}:{_DEFAULT_CDP_PORT}"


class WebBrowserConfig(BaseModel):
    """How this agent works a web page.

    Where the browser is and where it may go, how far one call may go, and what is
    sent to whom. Every limit is here rather than a constant in the loop, because an
    agent that browses a slow internal tool and one that reads public docs want
    different numbers and neither should need a release to get them.
    """

    cdp_url: str = Field(
        title="DevTools endpoint",
        default="",
        json_schema_extra=_cdp_url_form,
        description=(
            "Chromium DevTools endpoint to drive - a browser service the operator "
            "runs, not a process in the API container."
        ),
    )
    """Defaulted rather than required, and the default is refused at publish.

    Every capability has to be buildable from an empty config - that is what the
    registry's drift test does to enumerate the tools each one offers. So the
    demand for an endpoint is made where it can be made with a sentence a person
    reads, in `validate_cdp_url`, and an agent that somehow holds a blank one gets
    a tool that refuses instead of one that fails on its first call.
    """
    allowed_domains: list[str] | None = Field(
        title="Allowed domains",
        default=None,
        description=(
            "Hosts the browser may be on; empty means no restriction. Globs like "
            "*.example.com are allowed. Checked on every step, not only the first."
        ),
    )
    max_steps: int = Field(
        title="Steps per call at most",
        default=50,
        ge=1,
        le=200,
        description=(
            "How many steps one call may take; each step is one model request. A "
            "task that needs more continues in the same tab on the next call."
        ),
    )
    vision: bool = Field(
        title="Show the model screenshots",
        default=False,
        description=(
            "Send each step's screenshot to the model as well as the page's "
            "elements. Better on visual pages, more tokens, and the model has to "
            "read images."
        ),
    )
    candidate_cap: int = Field(
        title="Elements offered per step",
        default=60,
        ge=2,
        le=HARD_CANDIDATE_CAP,
        description=(
            "How many of the page's elements may be offered as choices in one "
            "step. Lower is cheaper and blinder; the answer to a page too dense "
            "for the cap is to scroll."
        ),
        json_schema_extra={"x-advanced": True},
    )
    preview: bool = Field(
        title="Show a live preview",
        default=True,
        description=(
            "Send the viewport to the chat while the browse runs, so a person can "
            "watch it. Costs one JPEG per step on the socket."
        ),
    )
    preview_width: int = Field(
        title="Viewport width (pixels)",
        default=1024,
        ge=320,
        le=1920,
        description=(
            "The browser's viewport width in pixels, which is also how wide the "
            "frames are. It decides what the agent can see without scrolling."
        ),
        json_schema_extra={"x-advanced": True},
    )


def validate_cdp_url(config: WebBrowserConfig) -> None:
    """Refuse a `cdp_url` this deployment's operator has not vetted.

    `cdp_url` lives in an agent spec, which anyone holding `edit` on that agent
    writes, so it is tenant-controlled: the request is made by this deployment, to
    an address somebody else named. That is the shape `MEM0_ALLOWED_HOSTS` exists
    for, and this is the same control - the operator lists the hosts in
    `BROWSER_CDP_ALLOWED_HOSTS`, and an empty list refuses browser automation
    outright rather than defaulting to something.

    **Not the SSRF guard**, which is what this used to be and which is wrong here
    in both directions. `validate_webhook_url` admits only a *public* address, so
    it refused the isolated browser service on the deployment's own network that
    the reference page tells an operator to run - `http://browser:9222` in the
    same compose project resolves to a private address and was rejected - while
    accepting a CDP debugger exposed to the open internet, which is a worse
    posture than the one it forbade. A vetted host needs no address check; an
    unvetted one is refused whatever it resolves to.

    Matching is exact and case-folded, with no globs. A hostname is not a pattern,
    and `*.internal` on a security allowlist is a wildcard somebody will read as
    narrower than it is.

    This one no longer resolves DNS, so it does not block and the caller does not
    need a thread for it.

    Raises:
        UrlRefusedError: The URL is missing, malformed, not a CDP scheme, or names
            a host this deployment does not allow.
    """
    if not config.cdp_url:
        raise UrlRefusedError(
            "Browser automation needs a cdp_url: the Chromium DevTools endpoint "
            "of the browser service this agent should drive"
        )
    parsed = urlsplit(config.cdp_url)
    if parsed.scheme not in _CDP_SCHEMES or not parsed.hostname:
        raise UrlRefusedError("A cdp_url must be an http, https, ws or wss URL with a host")
    try:
        # Reading the port is what validates it. `urlsplit` parses
        # `http://browser:notaport` without complaint and answers the expected
        # hostname, so a check that never touched `.port` published happily and
        # failed on the first browse, inside somebody's conversation, when the
        # HTTP client parsed the same authority and refused it.
        _ = parsed.port
    except ValueError as exc:
        raise UrlRefusedError(f"The cdp_url has an invalid port: {exc}") from exc
    allowed = {host.strip().lower() for host in settings.BROWSER_CDP_ALLOWED_HOSTS}
    if parsed.hostname.lower() not in allowed:
        # The host is named: it came from a stored spec rather than from anything
        # the caller submitted, and the operator reading this problem is the one
        # who decides the allowlist, so telling them which host was asked for is
        # the difference between a fixable message and a puzzle.
        raise UrlRefusedError(
            f"This deployment does not allow browser automation against "
            f"'{parsed.hostname}'. Add it to BROWSER_CDP_ALLOWED_HOSTS"
        )


@register(
    id=BROWSER_CAPABILITY_ID,
    name="Web browser",
    category="research",
    description="Use a real web browser step by step - read, click, fill forms, search.",
    tools=(
        CapabilityToolInfo(
            id="browse_web",
            description="Carry out a task in a real web browser, step by step.",
            # Not held for approval by default, while the capability stays
            # `side_effecting` - the per-tool override exists for exactly this.
            # A browse is one tool call, and an approval would land before the
            # first page is fetched, on a task in natural language: the person
            # would be asked to approve actions nobody can see yet. The live
            # panel is the honest answer - every step names what it pressed and
            # why - and `allowed_domains` bounds where it can go at all. An
            # operator who wants the gate sets `tool_approval` on the binding.
            side_effecting=False,
        ),
    ),
    config_schema=WebBrowserConfig,
    side_effecting=True,
    scopes=("web:browse",),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    """Build the capability from the agent's config.

    Always a capability, never `None`, even with no endpoint. A builder that
    returns `None` is a capability the registry's drift check cannot enumerate,
    and a missing endpoint is refused by the tool, in a sentence, and earlier and
    better at publish.
    """
    config = ctx.config if isinstance(ctx.config, WebBrowserConfig) else WebBrowserConfig()
    return WebBrowser(
        cdp_url=config.cdp_url,
        allowed_domains=config.allowed_domains,
        max_steps=config.max_steps,
        candidate_cap=config.candidate_cap,
        vision=config.vision,
        preview=config.preview,
        preview_width=config.preview_width,
    )
