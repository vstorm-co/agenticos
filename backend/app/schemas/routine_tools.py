"""A routine's narrowing of its agent's tool settings: ask first, or off."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.agent import PlatformToolGroup
from app.schemas.routine_actions import RoutineActionKey, RoutinePlatformActionKey

MAX_ROUTINE_TOOL_SETTINGS = 1000

type RoutineToolSettingValue = Literal["ask", "off"]
"""`ask` waits for approval before every call; `off` hides the tool and refuses it."""

type AgentToolSetting = Literal["free", "ask"]
"""What the agent's own spec decides for the tool, before any routine narrowing."""


class RoutineMcpToolKey(BaseModel):
    """One MCP connection's tool, by the name the server gives it.

    Keyed by the connection alone, not its authorization: a narrowing that
    reconnecting the account silently dropped would release the tool.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_id: UUID
    tool_id: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


type RoutineToolKey = RoutineActionKey | RoutineMcpToolKey | RoutinePlatformActionKey


class RoutineCapabilityToolSetting(RoutineActionKey):
    setting: RoutineToolSettingValue


class RoutineMcpToolSetting(RoutineMcpToolKey):
    setting: RoutineToolSettingValue


class RoutinePlatformToolSetting(RoutinePlatformActionKey):
    setting: RoutineToolSettingValue


type RoutineToolSetting = (
    RoutineCapabilityToolSetting | RoutineMcpToolSetting | RoutinePlatformToolSetting
)


class RoutineToolSettings(BaseModel):
    """The whole narrowing, replacing the previous one. Empty follows the agent."""

    model_config = ConfigDict(extra="forbid")

    settings: list[RoutineToolSetting] = Field(
        default_factory=list, max_length=MAX_ROUTINE_TOOL_SETTINGS
    )


class _ToolOption(BaseModel):
    name: str
    effect: bool = Field(description="The tool changes something; false for a read")
    agent: AgentToolSetting = Field(description="The agent's own setting for the tool")
    setting: RoutineToolSettingValue | None = Field(
        default=None, description="This routine's narrowing; null follows the agent"
    )


class RoutineCapabilityToolOption(RoutineActionKey, _ToolOption):
    capability_name: str


class RoutineMcpToolOption(RoutineMcpToolKey, _ToolOption):
    account_name: str
    account_scope: Literal["personal", "organization"]


class RoutinePlatformToolOption(RoutinePlatformActionKey, _ToolOption):
    group: PlatformToolGroup


type RoutineToolOption = (
    RoutineCapabilityToolOption | RoutineMcpToolOption | RoutinePlatformToolOption
)


class RoutineToolOptions(BaseModel):
    items: list[RoutineToolOption]
    unavailable_sources: list[str] = Field(
        default_factory=list,
        description="Accounts whose tool list needs a connection check before it can be shown.",
    )
