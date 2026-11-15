"""Agent environment schemas - named pointers at published versions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

# The same shape an agent slug has, for the same reasons: it becomes the
# Logfire environment tag and appears in URLs, and "Production (EU)" and
# "production-eu" must not be two different environments.
_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


class EnvironmentConnectionWrite(BaseSchema):
    """One binding this environment answers with a test system.

    `production_id` is the id the agent's spec names - an organization MCP
    connection or a vault secret - and `test_id` is what runs in its place here,
    or null for nothing at all. Only ids travel: a secret's value stays in the
    vault either way.
    """

    kind: Literal["mcp", "secret"]
    production_id: UUID = Field(description="The connection or secret the spec binds")
    test_id: UUID | None = Field(
        description=(
            "The connection or secret this environment uses instead. Null switches the "
            "binding off in this environment - it never falls back to the production one."
        )
    )


class EnvironmentConnectionRead(BaseSchema):
    kind: Literal["mcp", "secret"]
    production_id: UUID
    test_id: UUID | None = Field(
        default=None,
        description=(
            "Null once the test connection or secret was deleted. The binding is then "
            "off in this environment - it never falls back to the production one."
        ),
    )


class EnvironmentCreate(BaseSchema):
    """A new named environment, pinned from birth.

    `version_id` is optional only as shorthand: omitted, the environment starts
    at the version the default environment serves. There is no unpinned state.
    """

    name: str = Field(pattern=_NAME_PATTERN, max_length=64)
    version_id: UUID | None = None
    tracks_latest: bool = Field(
        default=False,
        description=(
            "Whether a publish repoints this environment on its own. False - the "
            "default - waits to be promoted onto, because publishing mints a "
            "version and putting it somewhere is a separate decision."
        ),
    )
    logfire_token_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The vault key holding a Logfire write token - this environment's "
            "runs trace into that project. The Logfire environment tag is "
            "always this environment's name."
        ),
    )
    service_name: str | None = Field(default=None, max_length=128)
    connections: list[EnvironmentConnectionWrite] = Field(
        default_factory=list,
        max_length=64,
        description="Bindings this environment answers with test systems instead",
    )


class EnvironmentUpdate(BaseSchema):
    """Repoint (promote), rename, or re-aim an environment's traces.

    All fields optional; for the observability pair an explicit null clears
    the override and the spec's own block takes over again.
    """

    name: str | None = Field(default=None, pattern=_NAME_PATTERN, max_length=64)
    version_id: UUID | None = None
    tracks_latest: bool | None = None
    logfire_token_secret_id: UUID | None = None
    service_name: str | None = Field(default=None, max_length=128)
    connections: list[EnvironmentConnectionWrite] | None = Field(
        default=None,
        max_length=64,
        description="The whole set of overrides, replacing the current one. Omit to keep it.",
    )
    guard_suite_ids: list[UUID] | None = Field(
        default=None,
        max_length=20,
        description=(
            "The agent's eval suites this environment requires to pass on a version "
            "before it takes it - the whole set, replacing the current one. Empty "
            "unguards it; omit to keep it. Changing it needs `promotions:override`."
        ),
    )
    override_reason: str | None = Field(
        default=None,
        min_length=10,
        max_length=2000,
        description=(
            "Why this version is promoted although its guards have not passed on it. "
            "Needs `promotions:override`, and is recorded in the audit log and on the "
            "version. Ignored when every guard passed."
        ),
    )


class EnvironmentRead(BaseSchema):
    id: UUID
    agent_id: UUID
    name: str
    version_id: UUID
    version: int = Field(description="The version's number, as the history names it")
    is_default: bool
    tracks_latest: bool = Field(
        default=False,
        description="Whether a publish repoints this environment on its own",
    )
    behind_by: int = Field(
        default=0,
        description=(
            "How many published versions are newer than the one this environment "
            "serves. Zero for an environment on the newest version, and for one "
            "that follows publishes. It is what tells 'pinned on purpose' from "
            "'forgotten' at a glance."
        ),
    )
    logfire_token_secret_id: UUID | None = None
    service_name: str | None = None
    connections: list[EnvironmentConnectionRead] = Field(default_factory=list)
    guard_suite_ids: list[UUID] = Field(
        default_factory=list,
        description="The eval suites that must pass on a version before this environment takes it",
    )
    created_at: datetime


class EnvironmentList(BaseSchema):
    items: list[EnvironmentRead]
    total: int
