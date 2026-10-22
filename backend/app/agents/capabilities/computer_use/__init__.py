"""Computer use - an agent operating a desktop through screenshots, mouse and keyboard."""

from typing import Literal, get_args
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, JsonValue, model_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.computer_use._capability import ComputerUse
from app.agents.capabilities.computer_use._toolset import ToolPolicy
from app.agents.capabilities.media import CONVERSATION_RESOURCE, ORGANIZATION_RESOURCE
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement

__all__ = ["ComputerUse", "ComputerUseConfig", "validate_daemon_url"]

_DEFAULT_DAEMON_PORT = 8765


def _daemon_url_form(schema: dict[str, JsonValue]) -> None:
    """Hint the daemon from what the operator allowed, as the web browser does for its `cdp_url`."""
    schema["x-visible-when"] = {"field": "desktop", "equals": ["local"]}
    hosts = [host.strip() for host in settings.COMPUTER_DAEMON_ALLOWED_HOSTS if host.strip()]
    if not hosts:
        schema["x-placeholder"] = "Set COMPUTER_DAEMON_ALLOWED_HOSTS first"
        return
    schema["x-placeholder"] = f"http://{hosts[0]}:{_DEFAULT_DAEMON_PORT}"


_ON_E2B: dict[str, JsonValue] = {"x-visible-when": {"field": "cloud_provider", "equals": ["e2b"]}}

E2BTemplate = Literal["desktop"]
"""The E2B templates a computer use desktop starts from.

Only a template with Xvfb, XFCE and xdotool installed can be driven, because
that is what `_desktop_start` runs. A team's own template built on E2B's
`desktop` one belongs here when it is added.
"""

_E2B_TEMPLATE_NAMES: dict[str, JsonValue] = {"desktop": "Desktop (Ubuntu with XFCE)"}


def _e2b_template_form(schema: dict[str, JsonValue]) -> None:
    """Offer the templates as choices, for an E2B desktop only.

    Rewritten from `const` for the same reason as the provider: while one
    template is listed, Pydantic writes the field as a value with nothing to
    choose, and the Builder hides it.
    """
    schema.pop("const", None)
    schema["enum"] = list(get_args(E2BTemplate))
    schema["x-enum-labels"] = _E2B_TEMPLATE_NAMES
    schema["x-advanced"] = True
    schema.update(_ON_E2B)


def _cloud_provider_form(schema: dict[str, JsonValue]) -> None:
    """Offer the providers as choices, shown only for a cloud desktop.

    Pydantic writes a one-value `Literal` as `const`, which the Builder takes for a
    field with nothing to choose and hides; the choices it renders are an `enum`.
    A provider stops being allowed when the desktop turns local, so the form
    clears it rather than keep a choice it no longer shows.
    """
    schema["anyOf"] = [{"enum": ["e2b"], "type": "string"}, {"type": "null"}]
    schema["x-enum-labels"] = {"e2b": "E2B"}
    schema["x-visible-when"] = {"field": "desktop", "equals": ["cloud"]}
    schema["x-enum-when"] = {"field": "desktop", "choices": {"local": [], "cloud": ["e2b"]}}


class ComputerUseConfig(BaseModel):
    """Which desktop this agent works, and how much of it per run."""

    desktop: Literal["local", "cloud"] = Field(
        default="local",
        title="Desktop",
        description="A computer you run, or one a cloud provider starts for each conversation.",
        json_schema_extra={
            "x-enum-labels": {
                "local": "A computer you run (computerd: a Linux container or a Mac)",
                "cloud": "A cloud desktop, one per conversation",
            }
        },
    )
    daemon_url: str = Field(
        default="",
        title="Daemon URL",
        json_schema_extra=_daemon_url_form,
        description="The computerd endpoint of your desktop. Its host must be on COMPUTER_DAEMON_ALLOWED_HOSTS.",
    )
    cloud_provider: Literal["e2b"] | None = Field(
        default=None,
        title="Cloud provider",
        description="Who runs the cloud desktop.",
        json_schema_extra=_cloud_provider_form,
    )
    e2b_template: E2BTemplate = Field(
        default="desktop",
        title="E2B template",
        description="The E2B template the desktop starts from.",
        json_schema_extra=_e2b_template_form,
    )
    e2b_timeout_seconds: int = Field(
        default=900,
        title="E2B idle timeout (seconds)",
        ge=60,
        le=86_400,
        description="How long an idle E2B desktop lives after its last use. E2B's Hobby plan caps this at an hour.",
        json_schema_extra={"x-advanced": True, **_ON_E2B},
    )
    screen_width: int = Field(
        default=1280,
        title="Screenshot width",
        ge=640,
        le=1920,
        description="The widest screenshot the model is shown; larger screens are scaled down to fit.",
    )
    screen_height: int = Field(
        default=800,
        title="Screenshot height",
        ge=480,
        le=1200,
        description="The tallest screenshot the model is shown.",
    )
    max_actions_per_call: int = Field(
        default=20,
        title="Actions per call",
        ge=1,
        le=50,
        description="How many actions one call may send.",
    )
    max_actions: int = Field(
        default=200,
        title="Actions per run",
        ge=1,
        le=2000,
        description="How many actions one run may take in total.",
    )
    preview: bool = Field(
        default=True,
        title="Live preview",
        description="Show the desktop live in the chat while the agent works it.",
    )

    @model_validator(mode="after")
    def _a_cloud_desktop_has_a_provider(self) -> ComputerUseConfig:
        # Dropped rather than refused for a local desktop: the field is hidden
        # there, so a provider left from a cloud one is a value nobody can see.
        if self.desktop == "local":
            self.cloud_provider = None
        elif self.cloud_provider is None:
            raise ValueError("A cloud desktop needs a cloud_provider")
        return self

    @model_validator(mode="after")
    def _a_call_fits_in_a_run(self) -> ComputerUseConfig:
        if self.max_actions_per_call > self.max_actions:
            raise ValueError("max_actions_per_call cannot be larger than max_actions")
        return self


def validate_daemon_url(config: ComputerUseConfig) -> None:
    """Refuse a `daemon_url` this deployment's operator has not vetted.

    The same control as `BROWSER_CDP_ALLOWED_HOSTS`, for the same reason: the URL
    is in a spec an agent's editor writes, and this deployment sends its daemon
    token to whatever it names. Exact, case-folded host matching; an empty list
    refuses a local desktop outright. A cloud desktop needs no URL.

    Raises:
        UrlRefusedError: The URL is missing, malformed, or names a host that is
            not allowed.
    """
    if config.desktop != "local":
        return
    if not config.daemon_url:
        raise UrlRefusedError(
            "Computer use needs a daemon_url: the computerd endpoint of the desktop to drive"
        )
    parsed = urlsplit(config.daemon_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlRefusedError("A daemon_url must be an http or https URL with a host")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise UrlRefusedError(f"The daemon_url has an invalid port: {exc}") from exc
    allowed = {host.strip().lower() for host in settings.COMPUTER_DAEMON_ALLOWED_HOSTS}
    if parsed.hostname.lower() not in allowed:
        raise UrlRefusedError(
            f"This deployment does not allow computer use against '{parsed.hostname}'. "
            f"Add it to COMPUTER_DAEMON_ALLOWED_HOSTS"
        )


def _session(organization: object, conversation: object) -> str:
    """Which E2B desktop a run gets: its conversation's, or one of its own.

    The organization is part of the key so two tenants sharing one E2B account
    can never be handed each other's desktop, whatever their conversation ids.
    """
    org = str(organization) if isinstance(organization, UUID) else "none"
    thread = str(conversation) if isinstance(conversation, UUID) else f"run-{uuid4()}"
    return f"{org}:{thread}"


@register(
    id="computer_use",
    voice="hand_off",
    name="Computer use",
    category="research",
    description="Operate a desktop - any application, not only web pages - through screenshots, mouse and keyboard.",
    tools=(
        CapabilityToolInfo(
            id="computer_screenshot",
            description="Take a screenshot of the desktop.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="computer_act",
            description="Act on the desktop: click, type, press keys, scroll, drag or wait.",
        ),
        CapabilityToolInfo(
            id="computer_save_screenshot",
            description="Save a screenshot of the desktop for the user: shown in the chat and kept.",
            side_effecting=False,
        ),
    ),
    config_schema=ComputerUseConfig,
    side_effecting=True,
    scopes=("computer:use",),
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The E2B API key that starts this agent's cloud desktops",
        purpose="e2b",
        required_when=SecretCondition(field="cloud_provider", equals=("e2b",)),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    """Build the capability; a missing URL or key is refused by the tool, in a sentence."""
    config = ctx.config if isinstance(ctx.config, ComputerUseConfig) else ComputerUseConfig()
    key = ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    return ComputerUse(
        backend=config.cloud_provider or "daemon",
        daemon_url=config.daemon_url,
        daemon_token=settings.COMPUTER_DAEMON_TOKEN,
        e2b_key=key,
        e2b_session=_session(
            ctx.resources.get(ORGANIZATION_RESOURCE), ctx.resources.get(CONVERSATION_RESOURCE)
        ),
        e2b_template=config.e2b_template,
        e2b_timeout_seconds=config.e2b_timeout_seconds,
        policy=ToolPolicy(
            max_width=config.screen_width,
            max_height=config.screen_height,
            max_actions_per_call=config.max_actions_per_call,
            max_actions=config.max_actions,
            preview=config.preview,
        ),
    )
