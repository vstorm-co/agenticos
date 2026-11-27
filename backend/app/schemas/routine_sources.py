"""A routine's stored access review: the sources it may reach and a setting per tool.

See `docs/design/routine-access.md`.
"""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.routine_tool_keys import (
    MAX_ROUTINE_TOOLS,
    RoutineAccessMode,
    RoutineDelegateSetting,
    RoutineToolSetting,
)

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
    account: str | None = Field(
        default=None,
        max_length=254,
        description=(
            "The provider account behind the connection, where it is known. A reconnect "
            "to the same account passes the review; to another, or unknown, it does not."
        ),
    )
    personal: bool = Field(
        default=False, description="The creator's own connection rather than the organization's"
    )


class RoutineSourcePolicy(BaseModel):
    """The reviewed ceiling and, at the top level, the current state within it.

    `approved_ceiling` is what the creator reviewed. The top level is refreshed
    at admission within it - an account reconnected as itself, a source removed -
    so a run's snapshot names the identities it will actually meet. A review
    saved before the ceiling existed has none and is its own ceiling.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: RoutineAccessMode = "reviewed"
    approved_ceiling: RoutineSourcePolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    tools: tuple[RoutineToolSetting, ...] = Field(default=(), max_length=MAX_ROUTINE_TOOLS)
    delegates: RoutineDelegateSetting = "ask"
    intent_hash: Fingerprint | None = Field(
        default=None,
        description="What the routine does, as reviewed; null for a review migrated without it",
    )
    grandfathered: bool = Field(
        default=False,
        description=(
            "Migrated from `action_mode = agent`: tools without a setting follow the agent "
            "without the permission check, until the creator saves the review."
        ),
    )
    platform: bool = Field(
        default=False, description="The platform's own server, acting as the creator, is reviewed"
    )
    id: UUID
    consented_by: UUID
    reviewed_at: AwareDatetime
    version_id: UUID
    scope_hash: Fingerprint
    spec_hash: Fingerprint
    behavior: dict[str, Fingerprint] | None = Field(default=None, max_length=10000)
    mcp_sources: dict[UUID, RoutineSourceAccount] = Field(default_factory=dict, max_length=100)
    mirage_accounts: dict[UUID, UUID] = Field(default_factory=dict, max_length=100)
    secret_sources: dict[UUID, UUID] = Field(default_factory=dict, max_length=100)
    channel_sources: dict[UUID, Fingerprint] = Field(default_factory=dict, max_length=100)
    phone_sources: dict[UUID, Fingerprint] = Field(default_factory=dict, max_length=100)
    project_id: UUID | None = None
    project_hash: Fingerprint | None = None
    root_mcp_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    external_sources: dict[UUID, Fingerprint] = Field(default_factory=dict, max_length=100)
    input_connection_id: UUID | None = None
    input_source: RoutineSourceAccount | None = None

    @model_validator(mode="after")
    def pair_input_source(self) -> Self:
        if self.approved_ceiling is not None and (
            self.approved_ceiling.approved_ceiling is not None or self.approved_ceiling.tools
        ):
            raise ValueError("An approved ceiling is one non-nested snapshot of sources")
        if (self.project_id is None) != (self.project_hash is None):
            raise ValueError("A project source requires its exact workspace identity")
        if (self.input_connection_id is None) != (self.input_source is None):
            raise ValueError("An input source requires its exact account identity")
        return self


type RoutineSourceKind = Literal[
    "capability",
    "skill",
    "context",
    "knowledge",
    "table",
    "delegate",
    "remote_agent",
    "platform",
    "mcp_account",
    "chat_connection",
    "phone",
    "terminal_account",
    "terminal_credential",
    "event_source",
]


class RoutineSourceItem(BaseModel):
    """One reviewed source, named as the console names it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RoutineSourceKind
    id: str | None = Field(default=None, description="Its identifier, where it has one")
    name: str | None = Field(
        default=None,
        description="Its name, or null when it no longer exists or is not visible here",
    )
    detail: str | None = Field(
        default=None, description="What it is granted, such as a table's operations"
    )
