"""Delegation to a locally registered ACP program."""

from pydantic import BaseModel, ConfigDict, Field

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.capabilities.external_acp._toolset import RUN_DESCRIPTION


class ExternalAcpConfig(BaseModel):
    """Reference a Desktop registration; never accept a remote command."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(
        title="Desktop agent ID",
        description="The ID registered under Desktop app settings on the initiating person's computer. Login and model settings belong to that program.",
        pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$",
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
    tools=(CapabilityToolInfo(id="run_acp_agent", description=RUN_DESCRIPTION),),
    config_schema=ExternalAcpConfig,
    scopes=("sandbox:execute",),
    side_effecting=True,
    tool_settings=False,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> ExternalAcp:
    # A required registration ID has no implicit or environment default.
    config = ExternalAcpConfig.model_validate(
        ctx.config.model_dump() if ctx.config is not None else {}
    )
    return ExternalAcp(agent_id=config.agent_id, timeout_seconds=config.timeout_minutes * 60)
