"""A routine's access review: the sources it may reach and a setting for each tool.

See `docs/design/routine-access.md`. The review is stored in
`agent_triggers.approved_sources` as a `RoutineSourcePolicy`; these are the
shapes the `/access` endpoint reads and writes.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import PlatformToolGroup
from app.schemas.routine_sources import Fingerprint, RoutineSourceItem
from app.schemas.routine_tool_keys import (
    MAX_ROUTINE_TOOLS,
    AgentToolSetting,
    AllowBlockedReason,
    RoutineAccessMode,
    RoutineCapabilityToolKey,
    RoutineDelegateSetting,
    RoutineMcpToolKey,
    RoutinePlatformToolKey,
    RoutineToolEffect,
    RoutineToolSetting,
    RoutineToolSettingValue,
    TrustBlockedReason,
)


class _ToolOption(BaseModel):
    name: str
    effect: bool = Field(description="The tool changes something; false for a read")
    agent: AgentToolSetting = Field(description="The agent's own setting for the tool")
    setting: RoutineToolSettingValue | None = Field(
        default=None,
        description=(
            "The routine's own setting; null where it has none and the mode's default applies. "
            "For a routine not reviewed yet, or one migrated before its first review, what "
            "saving the review proposes"
        ),
    )
    effective: RoutineToolEffect | None = Field(
        default=None,
        description=(
            "What a call does now, the agent's own approvals included; null before the "
            "routine's first review"
        ),
    )


class RoutineCapabilityToolOption(RoutineCapabilityToolKey, _ToolOption):
    capability_name: str


class RoutineMcpToolOption(RoutineMcpToolKey, _ToolOption):
    account_name: str
    account_scope: Literal["personal", "organization"]


class RoutinePlatformToolOption(RoutinePlatformToolKey, _ToolOption):
    group: PlatformToolGroup = Field(description="What the tool works on, as the Builder groups it")


type RoutineToolOption = (
    RoutineCapabilityToolOption | RoutineMcpToolOption | RoutinePlatformToolOption
)


type RoutineReviewReason = Literal[
    "setup",
    "sources",
    "routine_changed",
    "platform_identity",
    "unavailable",
    "trust_not_allowed",
]
"""Why the stored review does not admit the next run; none when it does."""


class RoutineAccessReview(BaseModel):
    """What the routine may reach and do, and what its creator may choose."""

    mode: RoutineAccessMode
    grandfathered: bool = Field(
        default=False,
        description=(
            "Migrated from the agent's own approval settings and not saved since: its tools "
            "run as the agent allows until the review is saved"
        ),
    )
    current: bool = Field(description="The stored review admits the next run as it stands")
    review_reason: RoutineReviewReason | None = None
    review_token: Fingerprint
    version_id: UUID
    sources: list[RoutineSourceItem]
    unavailable_sources: list[str] = Field(default_factory=list)
    required_unavailable_sources: list[str] = Field(
        default_factory=list, description="Unavailable sources that block every run"
    )
    tools: list[RoutineToolOption]
    unlisted_accounts: list[str] = Field(
        default_factory=list,
        description="Accounts whose tool list needs a connection check before it can be shown",
    )
    has_delegates: bool
    delegates: RoutineDelegateSetting
    can_allow: bool = Field(description="The caller may let an effectful tool run without asking")
    allow_blocked_reason: AllowBlockedReason | None = None
    can_trust: bool
    trust_blocked_reason: TrustBlockedReason | None = None


class RoutineAccessUpdate(BaseModel):
    """The whole review, replacing the previous one.

    A tool left out of `tools` gets no setting of its own, so the mode's default
    applies to it: in `reviewed` a read runs and a tool that changes something
    asks; in `trust_agent` the agent decides. A setting that would do the same as
    that default is not stored either.
    """

    model_config = ConfigDict(extra="forbid")

    review_token: Fingerprint
    mode: RoutineAccessMode = "reviewed"
    tools: list[RoutineToolSetting] = Field(default_factory=list, max_length=MAX_ROUTINE_TOOLS)
    delegates: RoutineDelegateSetting = "ask"
