"""Computer use - an agent operating a desktop through screenshots, mouse and keyboard."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, JsonValue, model_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.computer_use._capability import ComputerUse
from app.agents.capabilities.computer_use._toolset import ToolPolicy
from app.core.config import settings
from app.core.sanitize import UrlRefusedError

__all__ = ["COMPUTER_USE_ID", "ComputerUse", "ComputerUseConfig", "validate_daemon_url"]

COMPUTER_USE_ID = "computer_use"

_DEFAULT_DAEMON_PORT = 8765


def _daemon_url_form(schema: dict[str, JsonValue]) -> None:
    """Hint the daemon from what the operator allowed, as the web browser does for its `cdp_url`."""
    schema["x-visible-when"] = {"field": "desktop", "equals": ["daemon"]}
    hosts = [host.strip() for host in settings.COMPUTER_DAEMON_ALLOWED_HOSTS if host.strip()]
    if not hosts:
        schema["x-placeholder"] = "Set COMPUTER_DAEMON_ALLOWED_HOSTS first"
        return
    schema["x-placeholder"] = f"http://{hosts[0]}:{_DEFAULT_DAEMON_PORT}"


class ComputerUseConfig(BaseModel):
    """Which desktop this agent works, and how much of it per run."""

    desktop: Literal["sandbox", "daemon"] = Field(
        default="sandbox",
        title="Desktop",
        description=(
            "The agent's own sandbox, with a desktop in it, or a computer you run. "
            "The sandbox needs the Sandbox capability on a sandbox connection."
        ),
        json_schema_extra={
            "x-enum-labels": {
                "sandbox": "The agent's sandbox (a Linux desktop in its container)",
                "daemon": "A computer you run (computerd: your Linux desktop or a Mac)",
            }
        },
    )
    daemon_url: str = Field(
        default="",
        title="Daemon URL",
        json_schema_extra=_daemon_url_form,
        description="The computerd endpoint of your desktop. Its host must be on COMPUTER_DAEMON_ALLOWED_HOSTS.",
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
    def _a_call_fits_in_a_run(self) -> ComputerUseConfig:
        if self.max_actions_per_call > self.max_actions:
            raise ValueError("max_actions_per_call cannot be larger than max_actions")
        return self


def validate_daemon_url(config: ComputerUseConfig) -> None:
    """Refuse a `daemon_url` this deployment's operator has not vetted.

    The same control as `BROWSER_CDP_ALLOWED_HOSTS`, for the same reason: the URL
    is in a spec an agent's editor writes, and this deployment sends its daemon
    token to whatever it names. Exact, case-folded host matching; an empty list
    refuses a daemon outright. The sandbox's desktop needs no URL.

    Raises:
        UrlRefusedError: The URL is missing, malformed, or names a host that is
            not allowed.
    """
    if config.desktop != "daemon":
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


@register(
    id=COMPUTER_USE_ID,
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
    # No `secret=`, as for `sandbox`: a desktop in the sandbox runs on a
    # connection, which carries its own credential, and a daemon's token is the
    # deployment's.
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    """Build the capability; a missing sandbox, URL or token is refused by the tool, in a sentence."""
    config = ctx.config if isinstance(ctx.config, ComputerUseConfig) else ComputerUseConfig()
    return ComputerUse(
        backend=config.desktop,
        daemon_url=config.daemon_url,
        daemon_token=settings.COMPUTER_DAEMON_TOKEN,
        policy=ToolPolicy(
            max_width=config.screen_width,
            max_height=config.screen_height,
            max_actions_per_call=config.max_actions_per_call,
            max_actions=config.max_actions,
            preview=config.preview,
        ),
    )
