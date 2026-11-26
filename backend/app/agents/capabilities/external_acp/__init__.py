"""Delegation to a locally registered ACP program."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.external_acp._capability import ExternalAcp
from app.agents.capabilities.external_acp._toolset import INSPECT_DESCRIPTION, RUN_DESCRIPTION
from app.agents.pi_keys import NativeKeyProvider
from app.core.secret_kinds import PurposesByValue, SecretCondition, SecretKind, SecretRequirement


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
    api_provider: NativeKeyProvider | None = Field(
        default=None,
        title="Vault-key provider",
        description="Optional vault API key for the native runtime: Inception, DeepSeek or OpenRouter through a Pi key template, or Gemini through the Antigravity Gemini API key template. Requires the matching native template and the initiating member's independent vault visibility. It never imports a CLI's saved credentials.",
    )

    @model_validator(mode="after")
    def selected_key_needs_model(self) -> ExternalAcpConfig:
        if self.api_provider is not None and self.auth_method != "configured":
            raise ValueError("A vault-key lane uses the program setting for authentication")
        if self.api_provider is None or self.api_provider == "gemini":
            return self
        if not self.model_id or not re.fullmatch(
            rf"{self.api_provider}/[A-Za-z0-9._:/@+\-]+", self.model_id
        ):
            raise ValueError("The Pi model ID must belong to the selected API-key provider")
        return self

    platform_tools: bool = Field(
        default=False,
        title="Forward platform tools",
        description="Allow this native runtime to call the tools already admitted to this AgenticOS run. Platform permissions, budgets, approvals and result screening still apply. Requires the initiating member's private approved computer.",
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
    secret=SecretRequirement(
        description="The selected provider API key, exported only to a member with independent vault visibility and native template consent.",
        kind=SecretKind.API_KEY,
        required_when=SecretCondition(
            field="api_provider", equals=("inception", "deepseek", "openrouter", "gemini")
        ),
        purposes_by=PurposesByValue(
            field="api_provider",
            purposes={
                "inception": ("custom",),
                "deepseek": ("deepseek",),
                "openrouter": ("openrouter",),
                "gemini": ("google",),
            },
        ),
    ),
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
        api_provider=config.api_provider,
        secret_id=ctx.binding.secret_id,
        platform_tools=config.platform_tools,
    )
