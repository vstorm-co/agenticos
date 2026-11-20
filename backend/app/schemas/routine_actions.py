"""Human-granted exceptions to an unattended routine's per-action approvals."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.agent import PlatformToolGroup

MAX_ROUTINE_ACTIONS = 1000

ActionName = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RoutineActionKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: ActionName
    tool_id: ActionName


class RoutineMcpActionKey(BaseModel):
    """One concrete account authorization and the server's unprefixed action name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_id: UUID
    authorization_generation: UUID
    endpoint_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    tool_id: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class RoutinePlatformActionKey(BaseModel):
    """One of this platform's own MCP tools, by its name on the platform's server.

    It has no account to name: the routine's runs call the platform as its
    creator, the only person who can review its consent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["platform"]
    tool_id: ActionName


class ConsentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    consented_by: UUID
    version_id: UUID
    intent_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    instructions_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RoutineActionConsent(RoutineActionKey, ConsentIdentity):
    pass


class RoutineMcpActionConsent(RoutineMcpActionKey, ConsentIdentity):
    pass


class RoutinePlatformActionConsent(RoutinePlatformActionKey, ConsentIdentity):
    pass


type RoutineAction = RoutineActionKey | RoutineMcpActionKey | RoutinePlatformActionKey
type RoutineConsent = RoutineActionConsent | RoutineMcpActionConsent | RoutinePlatformActionConsent


class RoutineActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[RoutineAction] = Field(default_factory=list, max_length=MAX_ROUTINE_ACTIONS)
    review_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RoutineActionOption(RoutineActionKey):
    name: str
    capability_name: str | None = Field(
        default=None, description="The capability's name, which the review groups its actions under"
    )
    consented: bool
    previously_consented: bool = Field(
        default=False,
        description="Previously selected by this owner; not current authority or automatic consent.",
    )
    waivable: bool


class RoutineMcpActionOption(RoutineMcpActionKey):
    name: str
    account_name: str
    account_scope: Literal["personal", "organization"]
    consented: bool
    previously_consented: bool = Field(
        default=False,
        description="Previously selected by this owner; not current authority or automatic consent.",
    )
    waivable: bool


class RoutinePlatformActionOption(RoutinePlatformActionKey):
    name: str
    group: PlatformToolGroup = Field(description="What the tool works on, as the Builder groups it")
    consented: bool
    previously_consented: bool = Field(
        default=False,
        description="Previously selected by this owner; not current authority or automatic consent.",
    )
    waivable: bool


type RoutineOption = RoutineActionOption | RoutineMcpActionOption | RoutinePlatformActionOption


type RoutineReviewChange = Literal["version", "intent", "instructions", "actions"]

type WaiveBlockedReason = Literal["permission", "organization"]


class RoutineActionOptions(BaseModel):
    max_actions: int = MAX_ROUTINE_ACTIONS
    review_changes: list[RoutineReviewChange] = Field(default_factory=list)
    can_waive: bool
    waive_blocked_reason: WaiveBlockedReason | None = Field(
        default=None,
        description=(
            "Why `can_waive` is false: the caller lacks `approvals:decide` (`permission`), "
            "or the organization does not allow standing consent (`organization`). "
            "Null when consent can be given."
        ),
    )
    review_token: str
    items: list[RoutineOption]
    unavailable_sources: list[str] = Field(
        default_factory=list,
        description="Accounts whose tool inventory needs a connection check before review.",
    )
