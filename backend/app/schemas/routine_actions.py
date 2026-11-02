"""Human-granted exceptions to an unattended routine's per-action approvals."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ActionName = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RoutineActionKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: ActionName
    tool_id: ActionName


class RoutineActionConsent(RoutineActionKey):
    id: UUID
    consented_by: UUID
    version_id: UUID
    intent_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RoutineActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[RoutineActionKey] = Field(default_factory=list, max_length=100)
    review_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RoutineActionOption(RoutineActionKey):
    name: str
    consented: bool
    waivable: bool


class RoutineActionOptions(BaseModel):
    can_waive: bool
    review_token: str
    items: list[RoutineActionOption]
