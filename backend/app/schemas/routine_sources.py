"""Explicit source ceilings for recurring work, independent of write exceptions."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Fingerprint = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ToolName = Annotated[
    str, StringConstraints(min_length=1, max_length=1000, pattern=r"^[^\x00-\x1f\x7f]+$")
]


class RoutineSourceAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint_hash: Fingerprint
    authorization_generation: UUID
    tool_prefix: str | None = Field(default=None, max_length=128)
    tool_ids: tuple[ToolName, ...] = Field(default=(), max_length=4096)


class RoutineSourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    consented_by: UUID
    reviewed_at: AwareDatetime
    version_id: UUID
    scope_hash: Fingerprint
    spec_hash: Fingerprint
    mcp_sources: dict[UUID, RoutineSourceAccount] = Field(default_factory=dict, max_length=100)
    mirage_accounts: dict[UUID, UUID] = Field(default_factory=dict, max_length=100)
    secret_sources: dict[UUID, UUID] = Field(default_factory=dict, max_length=100)
    phone_sources: dict[UUID, Fingerprint] = Field(default_factory=dict, max_length=100)
    project_id: UUID | None = None
    project_hash: Fingerprint | None = None
    root_mcp_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    external_sources: dict[UUID, Fingerprint] = Field(default_factory=dict, max_length=100)
    input_connection_id: UUID | None = None
    input_source: RoutineSourceAccount | None = None

    @model_validator(mode="after")
    def pair_input_source(self) -> Self:
        if (self.project_id is None) != (self.project_hash is None):
            raise ValueError("A project source requires its exact workspace identity")
        if (self.input_connection_id is None) != (self.input_source is None):
            raise ValueError("An input source requires its exact account identity")
        return self


class RoutineSourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_token: Fingerprint
    version_id: UUID
    current: bool
    resources: list[str]
    accounts: list[str]
    unavailable_sources: list[str]


class RoutineSourceConsent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_token: Fingerprint
