"""How a routine names its agent's tools, and the setting it gives each.

Shared by the stored review (`RoutineSourcePolicy.tools`) and the `/access`
endpoint, so neither imports the other.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_ROUTINE_TOOLS = 2000

ToolId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
McpToolId = Annotated[str, StringConstraints(min_length=1, max_length=1000)]

type RoutineAccessMode = Literal["reviewed", "trust_agent"]
"""`reviewed` stops for a new review when access grows; `trust_agent` follows the agent."""

type RoutineToolSettingValue = Literal["allow", "ask", "off"]
"""`allow` runs where the agent lets it, `ask` waits for approval, `off` hides and refuses it."""

type RoutineDelegateSetting = Literal["allow", "ask"]
"""Whether delegate agents' effectful tools may run without asking."""

type AgentToolSetting = Literal["free", "ask"]
"""What the agent's own settings decide for the tool, before the routine's."""

type AllowBlockedReason = Literal["console", "permission", "organization"]
type TrustBlockedReason = Literal["console", "permission", "organization", "event"]


class RoutineCapabilityToolKey(BaseModel):
    """A capability's tool, by its stable id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: ToolId
    tool_id: ToolId


class RoutineMcpToolKey(BaseModel):
    """One MCP connection's tool, by the name the server gives it.

    Keyed by the connection alone: reconnecting the same account keeps the
    setting, and a different account is caught by the source review.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_id: UUID
    tool_id: McpToolId


class RoutinePlatformToolKey(BaseModel):
    """One of this platform's own MCP tools, by its name on the platform's server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["platform"]
    tool_id: ToolId


type RoutineToolKey = RoutineCapabilityToolKey | RoutineMcpToolKey | RoutinePlatformToolKey


class RoutineCapabilityToolSetting(RoutineCapabilityToolKey):
    setting: RoutineToolSettingValue


class RoutineMcpToolSetting(RoutineMcpToolKey):
    setting: RoutineToolSettingValue


class RoutinePlatformToolSetting(RoutinePlatformToolKey):
    setting: RoutineToolSettingValue


type RoutineToolSetting = (
    RoutineCapabilityToolSetting | RoutineMcpToolSetting | RoutinePlatformToolSetting
)
