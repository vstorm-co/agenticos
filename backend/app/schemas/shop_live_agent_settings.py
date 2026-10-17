"""Shop live-agent settings (Studio parity with multi-agent read shape)."""

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopLiveAgentSettingsRead(BaseSchema):
    idle_release_minutes: int | None = Field(
        default=None,
        description="Org override; null = platform default; 0 = disabled",
    )
    idle_release_minutes_effective: int = Field(
        description="Resolved idle auto-release minutes (0 = disabled)",
    )
    platform_default_minutes: int = Field(
        description="Platform default from SHOP_LIVE_AGENT_IDLE_RELEASE_MINUTES",
    )
    round_robin_enabled: bool | None = Field(
        default=None,
        description="Org override; null = platform default",
    )
    round_robin_enabled_effective: bool = Field(description="Resolved round-robin flag")
    auto_assign_enabled: bool | None = Field(
        default=None,
        description="Auto-claim queued thread for picked CS; null = platform default",
    )
    auto_assign_enabled_effective: bool = Field(description="Resolved auto-assign flag")
    platform_default_round_robin: bool = Field(
        description="Platform default from SHOP_LIVE_AGENT_ROUND_ROBIN_ENABLED",
    )
    platform_default_auto_assign: bool = Field(
        description="Platform default from SHOP_LIVE_AGENT_AUTO_ASSIGN_ENABLED",
    )


class ShopLiveAgentSettingsPatch(BaseSchema):
    idle_release_minutes: int | None = Field(
        default=None,
        ge=0,
        le=1440,
        description="0 = disabled; null = reset to platform default",
    )
    round_robin_enabled: bool | None = Field(
        default=None,
        description="null = reset to platform default",
    )
    auto_assign_enabled: bool | None = Field(
        default=None,
        description="null = reset to platform default",
    )
