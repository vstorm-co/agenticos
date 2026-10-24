"""A real web browser the agent works step by step, on the run's own model."""

from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, field_validator
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.browser_use._capability import WebBrowser
from app.agents.capabilities.browser_use._elements import HARD_CANDIDATE_CAP
from app.agents.capabilities.browser_use._local import page_factory as local_page_factory
from app.agents.capabilities.browser_use._route import (
    Connection,
    address_problem,
    route_for,
    timezone_problem,
)
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement

__all__ = [
    "BROWSER_CAPABILITY_ID",
    "BROWSER_STEP_MODEL_RESOURCE",
    "WebBrowser",
    "WebBrowserConfig",
    "connection_problems",
    "validate_cdp_url",
]

BROWSER_CAPABILITY_ID = "browser_use"

BROWSER_STEP_MODEL_RESOURCE = "browser_step_model"
"""The built model `browse_web` asks for each step, resolved by the runner from
`step_model_profile_id` - building one needs the database and the vault, which a
capability builder does not have."""

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
    # A hosted browser is its own endpoint, so the field says nothing there.
    schema["x-visible-when"] = {"field": "connection", "equals": ["built_in", "proxy"]}
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
    step_model_profile_id: UUID | None = Field(
        title="Model for each browse step",
        default=None,
        description=(
            "A model profile `browse_web` asks for each step instead of the agent's own. "
            "Steps are most of a browse's time and cost, so a cheaper model here makes a "
            "long browse cheaper, and quicker where its provider answers quickly - "
            "measure it, since a small model through a slow gateway is no faster. Empty "
            "uses the agent's model. The agent's own browser tools always use it."
        ),
        json_schema_extra={"x-widget": "model-profile", "x-advanced": True},
    )
    connection: Connection = Field(
        title="How the browser reaches the web",
        default="built_in",
        description=(
            "Built in uses the deployment's browser and its address. A proxy sends "
            "the browses through an address of your own - a residential or regional "
            "one sites block less. A hosted browser runs them in a browser service "
            "you pay for, reached over CDP."
        ),
        json_schema_extra={
            "x-enum-labels": {
                "built_in": "Built in",
                "proxy": "Through a proxy",
                "hosted": "A hosted browser",
                "local": "This computer (desktop app)",
            }
        },
    )
    proxy_url: str = Field(
        title="Proxy address",
        default="",
        description=(
            "http://, https:// or socks5:// with the host and port. Its "
            "username:password goes in the vault, picked below; Chromium cannot "
            "sign in to a SOCKS proxy."
        ),
        json_schema_extra={
            "x-placeholder": "http://proxy.example.com:8080",
            "x-visible-when": {"field": "connection", "equals": ["proxy"]},
        },
    )
    hosted_url: str = Field(
        title="Hosted browser address",
        default="",
        description=(
            "The service's wss:// CDP address. Its key goes in the vault, picked "
            "below, and is added to the address's query when the browse connects."
        ),
        json_schema_extra={
            "x-placeholder": "wss://connect.browserbase.com",
            "x-visible-when": {"field": "connection", "equals": ["hosted"]},
        },
    )
    hosted_key_param: str = Field(
        title="Query parameter for the key",
        default="apiKey",
        min_length=1,
        max_length=64,
        description="What the hosted browser calls its key in the address's query.",
        json_schema_extra={
            "x-advanced": True,
            "x-visible-when": {"field": "connection", "equals": ["hosted"]},
        },
    )
    timezone: str | None = Field(
        title="Time zone the browser reports",
        default=None,
        description=(
            "An IANA time zone such as Europe/Warsaw. Set it to match the proxy's "
            "region: a browser whose clock and address disagree reads as a bot."
        ),
        json_schema_extra={"x-advanced": True, "x-placeholder": "Europe/Warsaw"},
    )
    locale: str | None = Field(
        title="Language the browser reports",
        default=None,
        max_length=35,
        description="A language tag such as pl-PL, sent as Accept-Language and navigator.language.",
        json_schema_extra={"x-advanced": True, "x-placeholder": "pl-PL"},
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

    @field_validator("timezone", "locale", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """An emptied field in the Builder arrives as `""`, which means none."""
        return None if value == "" else value


def connection_problems(config: WebBrowserConfig, *, has_secret: bool) -> list[str]:
    """What is wrong with how this binding says its browses reach the web.

    The addresses are checked on their face here; where they point is checked by
    `_route.check_address` at publish and again as each browse starts.
    """
    problems: list[str] = []
    if config.connection == "proxy":
        if not config.proxy_url:
            problems.append("Say which proxy the browser goes through")
        elif (problem := address_problem(config.proxy_url, kind="proxy")) is not None:
            problems.append(f"The proxy address cannot be used: {problem}")
        elif has_secret and urlsplit(config.proxy_url).scheme == "socks5":
            # Chromium has no way to sign in to a SOCKS proxy: the browse would
            # fail on its first request, inside somebody's conversation.
            problems.append(
                "Chromium cannot sign in to a SOCKS proxy; use an HTTP proxy for one "
                "that needs a password"
            )
    if config.connection == "hosted":
        if not config.hosted_url:
            problems.append("Say where the hosted browser is")
        elif (problem := address_problem(config.hosted_url, kind="hosted")) is not None:
            problems.append(f"The hosted browser's address cannot be used: {problem}")
    if (problem := timezone_problem(config.timezone)) is not None:
        problems.append(problem)
    return problems


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
    if config.connection in ("hosted", "local"):
        # The hosted browser is the endpoint; `connection_problems` checks it.
        return
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
    voice="hand_off",
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
        # The agent's own hands on the same tab: one action a call, chosen by
        # the run's model in its own turn. Not held either, for the reason
        # above - each is watched as it happens - and an operator gates one
        # through `tool_approval` like any tool.
        CapabilityToolInfo(
            id="browser_open",
            description="Open a page in this turn's browser tab and read it.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="browser_read",
            description="Read the open page again - after waiting for it, or to see it as it is now.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="browser_click",
            description="Click an element of the open page, by its number in the last page read.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="browser_type",
            description="Type into a field of the open page, replacing what it held.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="browser_select",
            description="Choose one of a dropdown's options on the open page.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="browser_scroll",
            description="Scroll the open page by about one screen.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="browser_back",
            description="Go back to the previous page in the open tab.",
            side_effecting=False,
        ),
    ),
    config_schema=WebBrowserConfig,
    side_effecting=True,
    scopes=("web:browse",),
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The hosted browser's key, or the proxy's username:password",
        # A hosted browser always authenticates; a proxy may or may not, so its
        # credential is optional and the built-in browser takes none.
        required_when=SecretCondition(field="connection", equals=("hosted",)),
        optional_when=SecretCondition(field="connection", equals=("proxy",)),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    """Build the capability from the agent's config.

    Always a capability, never `None`, even with no endpoint. A builder that
    returns `None` is a capability the registry's drift check cannot enumerate,
    and a missing endpoint is refused by the tool, in a sentence, and earlier and
    better at publish.
    """
    config = ctx.config if isinstance(ctx.config, WebBrowserConfig) else WebBrowserConfig()
    step_model = ctx.resources.get(BROWSER_STEP_MODEL_RESOURCE)
    credential = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    local_session = ctx.resources.get("local_browser_session")
    return WebBrowser(
        page_factory=local_page_factory(local_session) if isinstance(local_session, UUID) else None,
        step_model=step_model if isinstance(step_model, Model) else None,
        route=route_for(
            connection=config.connection,
            proxy_url=config.proxy_url,
            hosted_url=config.hosted_url,
            hosted_key_param=config.hosted_key_param,
            timezone=config.timezone,
            locale=config.locale,
            credential=credential,
        ),
        cdp_url="" if config.connection == "local" else config.cdp_url,
        allowed_domains=config.allowed_domains,
        max_steps=config.max_steps,
        candidate_cap=config.candidate_cap,
        vision=config.vision,
        preview=config.preview,
        preview_width=config.preview_width,
    )
