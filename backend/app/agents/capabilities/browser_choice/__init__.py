"""Browser automation that chooses from a page instead of composing an action."""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.browser_choice._capability import BrowserChoice
from app.agents.capabilities.browser_choice._elements import HARD_CANDIDATE_CAP
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import ApiKeySecret, SecretKind, SecretRequirement
from app.services.decision_models import DEFAULT_DECISION_MODEL, decision_model_schema

__all__ = ["BrowserChoice", "BrowserChoiceConfig", "validate_cdp_url"]

_DEFAULT_CDP_PORT = 9222
"""Chromium's own default debugging port, which is what a suggestion should guess."""

VENDOR_DECISION_ENDPOINT = "https://api.typesafe.ai"
"""Where the decision model runs when nothing says otherwise.

Named here rather than left implicit in the SDK, because "empty" is the setting
with the largest consequence in this capability - it is the difference between
page content staying inside a deployment and leaving it - and a field whose
default destination is invisible is a field nobody audits.
"""

_CDP_SCHEMES = frozenset({"http", "https", "ws", "wss"})
"""A CDP endpoint is reached over HTTP(S) or a WebSocket, and over nothing else.

The same four `browser_use` allows. What decides whether the *host* is acceptable
is the operator's allowlist - see :func:`validate_cdp_url` for why it is that
rather than the SSRF guard.
"""


def _cdp_url_form(schema: dict[str, object]) -> None:
    """Prefill and hint the endpoint from what the operator already declared.

    `BROWSER_CDP_ALLOWED_HOSTS` is the list of browsers this deployment permits,
    so an author typing a `cdp_url` is choosing from it whether the form says so
    or not - and a field that refuses at publish without ever having said what it
    would accept is a field that wastes somebody's afternoon. With one host
    allowed, which is the ordinary case, the form arrives filled in.

    Read when the schema is generated rather than when this module is imported,
    because a deployment's allowlist is configuration and this file is code.
    """
    hosts = [host.strip() for host in settings.BROWSER_CDP_ALLOWED_HOSTS if host.strip()]
    if not hosts:
        schema["x-placeholder"] = "Set BROWSER_CDP_ALLOWED_HOSTS first"
        return
    schema["x-placeholder"] = f"http://{hosts[0]}:{_DEFAULT_CDP_PORT}"
    if len(hosts) == 1:
        schema["default"] = f"http://{hosts[0]}:{_DEFAULT_CDP_PORT}"


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
        json_schema_extra=_cdp_url_form,
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
        default=DEFAULT_DECISION_MODEL,
        json_schema_extra=decision_model_schema(),
        description="The model that picks the operation and the element each step.",
    )
    """A picker over the catalog, and a string in validation - both deliberately.

    `app/core/catalog/decision_models.json` is what the Builder offers, because a
    moving alias is what almost every agent wants and typing one is a chance to
    typo. The field stays a `str` so a pinned build (`jev-1.13.0`) is still
    storable: TypeSafe accepts one, an agent whose confidence floor was tuned
    against a version needs one, and nobody should wait for a release of this
    platform to use a release of that one.
    """
    decision_base_url: str | None = Field(
        default=None,
        json_schema_extra={"x-placeholder": VENDOR_DECISION_ENDPOINT},
        description=(
            "Where that model runs. Empty is the vendor's own public endpoint "
            f"({VENDOR_DECISION_ENDPOINT}), which is where page content goes "
            "unless this says otherwise - so a deployment that may not send page "
            "content to a third party fills this in with an endpoint of its own."
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
        description=(
            "The browser's viewport width in pixels, which is also how wide the "
            "frames are. It decides what the agent can see without scrolling."
        ),
    )


def _refuse_unvetted_decision_endpoint(base_url: str | None) -> None:
    """Refuse to send the vault key to a decision endpoint nobody vetted.

    `decision_base_url` is a field in the agent spec, and the key it
    authenticates with is unsealed server-side and put in a request header to
    whatever it names. So an author who may *bind* a shared TypeSafe key -
    binding is not reading, and the API never returns the value - could point it
    at a server of their own and read it out of the header. Approval is no help:
    the same author publishes the binding.

    That is `MEM0_ALLOWED_HOSTS`'s problem exactly, and this is its answer.
    `None` is the vendor's own endpoint and always allowed; anything else needs
    its host on `DECISION_MODEL_ALLOWED_HOSTS`, and the empty default therefore
    permits only the vendor.

    Raises:
        UrlRefusedError: The URL is malformed, or names a host this deployment
            has not allowed.
    """
    if base_url is None:
        return
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlRefusedError("A decision_base_url must be an http or https URL with a host")
    allowed = {host.strip().lower() for host in settings.DECISION_MODEL_ALLOWED_HOSTS}
    if parsed.hostname.lower() not in allowed:
        raise UrlRefusedError(
            f"This deployment does not allow a decision model at '{parsed.hostname}'. "
            f"Leave decision_base_url empty for the vendor's endpoint, or add the "
            f"host to DECISION_MODEL_ALLOWED_HOSTS"
        )


def validate_cdp_url(config: BrowserChoiceConfig) -> None:
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
    _refuse_unvetted_decision_endpoint(config.decision_base_url)
    if not config.cdp_url:
        raise UrlRefusedError(
            "Browser automation needs a cdp_url: the Chromium DevTools endpoint "
            "of the browser service this agent should drive"
        )
    parsed = urlsplit(config.cdp_url)
    if parsed.scheme not in _CDP_SCHEMES or not parsed.hostname:
        raise UrlRefusedError("A cdp_url must be an http, https, ws or wss URL with a host")
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
    id="browser_choice",
    name="Browser automation (choose)",
    category="research",
    description="Work through a web page by choosing one of the actions it actually offers.",
    tools=(
        CapabilityToolInfo(
            id="browse_page",
            description="Work through a web page towards a goal, one chosen action at a time.",
            # Not held for approval by default, while the capability above stays
            # `side_effecting` - which is the per-tool override existing for
            # exactly this shape of disagreement.
            #
            # The capability's flag is true because it is: a browse presses
            # buttons on pages nobody here wrote. What does not follow is asking
            # a person before every browse. A browse is one tool call and the
            # approval would land *before* the first page is even fetched, on a
            # goal in natural language and a URL - so the person is asked to
            # approve something whose actions nobody can see yet, which is
            # consent without information. The panel is the honest answer: the
            # browse is watched while it happens, every step names what was
            # chosen and how sure the engine was, and `allowed_domains` bounds
            # where it can go at all.
            #
            # An operator who wants the gate sets `tool_approval` on the binding,
            # which beats this, and `min_confidence` is the automatic version of
            # the same instinct.
            side_effecting=False,
        ),
    ),
    config_schema=BrowserChoiceConfig,
    side_effecting=True,
    scopes=("web:browse",),
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The API key for the decision model that picks each step",
        # Named, so the Builder asks for a TypeSafe key rather than "a key for
        # Browser automation", and the picker offers the TypeSafe secrets rather
        # than every `api_key` in the vault. A key added from that picker is
        # stored under this purpose, which is what makes the second agent's
        # question a choice instead of another paste.
        purpose="typesafe",
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
