"""Agent environment schemas - named pointers at published versions."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

# The same shape an agent slug has, for the same reasons: it becomes the
# Logfire environment tag and appears in URLs, and "Production (EU)" and
# "production-eu" must not be two different environments.
_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


class EnvironmentCreate(BaseSchema):
    """A new named environment, pinned from birth.

    `version_id` is optional only as shorthand: omitted, the environment starts
    at the version the default environment serves. There is no unpinned state.
    """

    name: str = Field(pattern=_NAME_PATTERN, max_length=64)
    version_id: UUID | None = None
    logfire_token_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The vault key holding a Logfire write token - this environment's "
            "runs trace into that project. The Logfire environment tag is "
            "always this environment's name."
        ),
    )
    service_name: str | None = Field(default=None, max_length=128)


class EnvironmentUpdate(BaseSchema):
    """Repoint (promote), rename, or re-aim an environment's traces.

    All fields optional; for the observability pair an explicit null clears
    the override and the spec's own block takes over again.
    """

    name: str | None = Field(default=None, pattern=_NAME_PATTERN, max_length=64)
    version_id: UUID | None = None
    logfire_token_secret_id: UUID | None = None
    service_name: str | None = Field(default=None, max_length=128)


class EnvironmentRead(BaseSchema):
    id: UUID
    agent_id: UUID
    name: str
    version_id: UUID
    version: int = Field(description="The pinned version's number, as the history names it")
    is_default: bool
    logfire_token_secret_id: UUID | None = None
    service_name: str | None = None
    created_at: datetime


class EnvironmentList(BaseSchema):
    items: list[EnvironmentRead]
    total: int
