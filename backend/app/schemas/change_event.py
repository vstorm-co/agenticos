"""What the console hears when a resource changes somewhere else (#2061)."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

ChangeResource = Literal[
    "agent",
    "skill",
    "context",
    "knowledge_base",
    "artifact",
    "member",
    "invitation",
    "group",
    "organization",
    "trigger",
    "channel",
    "notification",
    "secret",
    "mcp_connection",
    "run",
]
"""What changed. A `trigger` event names the agent whose routines changed, since
that is what a subscriber's access to them is decided by; a `run` event is a run
moving through its states (started, parked, finished), which no request made."""
ChangeAction = Literal["created", "updated", "deleted"]
ChangeSurface = Literal["console", "api_key", "mcp", "assistant", "run"]
"""Where a change came from: a console session, an organization API key, an MCP
client signed in over OAuth, the in-app Architect, or a run itself as it moved
from one state to the next."""


class ChangeEvent(BaseSchema):
    organization_id: UUID
    resource: ChangeResource
    id: UUID | None = Field(
        description="The changed row; absent when the write did not name one it can be read back by"
    )
    action: ChangeAction
    surface: ChangeSurface
    actor_user_id: UUID | None = Field(
        description="The member the change was made as; for a run, the member it runs as, absent when it runs as nobody"
    )
    actor_name: str | None = Field(description="The member's display name; absent for a run")
    origin_tab: str | None = Field(
        default=None,
        description="The console tab that made the change, so that tab can tell its own echo",
    )
