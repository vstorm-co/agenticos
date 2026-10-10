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
]
ChangeAction = Literal["created", "updated", "deleted"]
ChangeSurface = Literal["console", "api_key", "mcp", "assistant"]
"""Where a change came from: a console session, an organization API key, an MCP
client signed in over OAuth, or the in-app Platform assistant."""


class ChangeEvent(BaseSchema):
    organization_id: UUID
    resource: ChangeResource
    id: UUID | None = Field(
        description="The changed row; absent when the write did not name one it can be read back by"
    )
    action: ChangeAction
    surface: ChangeSurface
    actor_user_id: UUID = Field(description="The member the change was made as")
    actor_name: str
    origin_tab: str | None = Field(
        default=None,
        description="The console tab that made the change, so that tab can tell its own echo",
    )
