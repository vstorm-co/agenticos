"""Computer use - an agent operating a desktop through screenshots, mouse and keyboard."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.computer_use._backends import check_daemon_url
from app.agents.capabilities.computer_use._capability import ComputerUse
from app.agents.capabilities.computer_use._toolset import ToolPolicy
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement

__all__ = ["COMPUTER_USE_ID", "ComputerUse", "ComputerUseConfig", "validate_daemon_url"]

COMPUTER_USE_ID = "computer_use"


def _daemon_url_form(schema: dict[str, JsonValue]) -> None:
    """Shown only for a daemon, with a placeholder that names no host.

    Not the first allowed host, as the web browser's `cdp_url` hints: the catalog
    is read by every organization on the deployment, and which desktops the
    operator allowed is not theirs to learn.
    """
    schema["x-visible-when"] = {"field": "desktop", "equals": ["daemon"]}
    schema["x-placeholder"] = "http://desktop.example:8765"


class ComputerUseConfig(BaseModel):
    """Which desktop this agent works, and how much of it per run."""

    desktop: Literal["auto", "e2b", "sandbox", "local", "daemon"] = Field(
        default="auto",
        title="Environment",
        description="Choose where this agent operates a desktop. The selected environment's requirements are shown below.",
        json_schema_extra={
            "x-widget": "computer-environment",
            "x-enum-labels": {
                "auto": "Automatic",
                "sandbox": "Docker / Sandbox",
                "daemon": "Remote computer",
                "local": "Local",
                "e2b": "E2B",
            },
            "x-enum-descriptions": {
                "auto": "Use Local when the chat works on this computer; otherwise E2B if this capability has a key, or the agent's sandbox.",
                "sandbox": "Use the agent's Sandbox connection (Docker or E2B) with the desktop runtime. Configure the connection in the Sandbox capability.",
                "daemon": "Connect to a computer running computerd. Set its approved address and select its access token below.",
                "local": "Use the person's paired desktop app. In chat, select local Computer use or work on This computer. The person must approve screen access.",
                "e2b": "Start a separate E2B desktop for this run. Select the organization's E2B key below; no Sandbox connection is needed.",
            },
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
    is in a spec an agent's editor writes, and the run sends the daemon's token to
    whatever it names. The sandbox's desktop needs no URL. The rules are
    `check_daemon_url`'s, which a run applies again when it opens the daemon.

    Raises:
        UrlRefusedError: The URL is missing, malformed, or names a host that is
            not allowed.
    """
    if config.desktop == "daemon":
        check_daemon_url(config.daemon_url)


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
            description="Act on the desktop: click, type, press keys, scroll, drag, open an app or wait.",
        ),
        CapabilityToolInfo(
            id="computer_apps",
            description="List the applications installed on the desktop, to open one with `launch`.",
            side_effecting=False,
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
        description=(
            "The token the daemon was started with (COMPUTERD_TOKEN), or the "
            "organization's E2B key for an E2B desktop"
        ),
        # The token, not the allowlist, is what lets an organization drive a
        # desktop: the allowlist is the deployment's, so every organization may
        # name an allowed host, and only the one holding the token gets in. A
        # desktop in the sandbox runs on a connection, which has its own.
        required_when=SecretCondition(field="desktop", equals=("daemon", "e2b")),
    ),
)
def _build(ctx: CapabilityBuildContext) -> AbstractCapability[object]:
    """Build the capability; a missing sandbox, URL or token is refused by the tool, in a sentence."""
    config = ctx.config if isinstance(ctx.config, ComputerUseConfig) else ComputerUseConfig()
    token = ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else ""
    local_session = ctx.resources.get("local_computer_session")
    return ComputerUse(
        backend=config.desktop,
        local_session_id=local_session if isinstance(local_session, UUID) else None,
        daemon_url=config.daemon_url,
        daemon_token=token,
        policy=ToolPolicy(
            max_width=config.screen_width,
            max_height=config.screen_height,
            max_actions_per_call=config.max_actions_per_call,
            max_actions=config.max_actions,
            preview=config.preview,
        ),
    )
