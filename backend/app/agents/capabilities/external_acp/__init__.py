"""Delegation to a locally registered ACP program."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.capabilities.external_acp._toolset import INSPECT_DESCRIPTION, RUN_DESCRIPTION


class ExternalAcpConfig(BaseModel):
    """Reference a Desktop registration; never accept a remote command."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(
        title="Desktop agent ID",
        description="The ID registered under Desktop app settings on the initiating person's computer. Login and model settings belong to that program.",
        pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$",
    )
    auth_method: Literal["configured", "oauth-personal"] = Field(
        default="configured",
        title="Authentication mode",
        description="Use the program's configured account, or explicitly select Antigravity Google personal sign-in. A missing method fails without switching to an API key or another account.",
        json_schema_extra={
            "x-enum-labels": {
                "configured": "Program setting",
                "oauth-personal": "Antigravity Google personal sign-in",
            }
        },
    )
    model_id: str | None = Field(
        default=None,
        title="External model ID",
        description="Optional exact ID from inspect_acp_agent on this account. Empty keeps the program's own model. This selects a runtime model, not an AgenticOS model profile.",
        min_length=1,
        max_length=256,
        pattern=r"^\S+$",
    )
    timeout_minutes: int = Field(
        title="Time limit (minutes)",
        description="How long one task may run before it is stopped.",
        default=15,
        ge=1,
        le=60,
    )


@register(
    id="external_acp",
    name="External ACP agent",
    category="analysis",
    description="Hand a task to an ACP program registered on this computer. It runs with your local account's access and its own login.",
    tools=(
        CapabilityToolInfo(id="run_acp_agent", description=RUN_DESCRIPTION),
        CapabilityToolInfo(id="inspect_acp_agent", description=INSPECT_DESCRIPTION),
    ),
    config_schema=ExternalAcpConfig,
    scopes=("sandbox:execute",),
    side_effecting=True,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> ExternalAcp:
    # A required registration ID has no implicit or environment default.
    config = ExternalAcpConfig.model_validate(
        ctx.config.model_dump() if ctx.config is not None else {}
    )
    return ExternalAcp(
        agent_id=config.agent_id,
        timeout_seconds=config.timeout_minutes * 60,
        auth_method=None if config.auth_method == "configured" else config.auth_method,
        model_id=config.model_id,
    )
