"""Human-granted exceptions to an unattended routine's per-action approvals."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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


type RoutineAction = RoutineActionKey | RoutineMcpActionKey
type RoutineConsent = RoutineActionConsent | RoutineMcpActionConsent


class RoutineActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[RoutineAction] = Field(default_factory=list, max_length=MAX_ROUTINE_ACTIONS)
    review_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RoutineActionOption(RoutineActionKey):
    name: str
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


type RoutineOption = RoutineActionOption | RoutineMcpActionOption


type RoutineReviewChange = Literal["version", "intent", "instructions", "actions"]


class RoutineActionOptions(BaseModel):
    max_actions: int = MAX_ROUTINE_ACTIONS
    review_changes: list[RoutineReviewChange] = Field(default_factory=list)
    can_waive: bool
    review_token: str
    items: list[RoutineOption]
    unavailable_sources: list[str] = Field(
        default_factory=list,
        description="Accounts whose tool inventory needs a connection check before review.",
    )
