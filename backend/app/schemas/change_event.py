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
    "table",
    "workflow",
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
    "eval_suite",
    "eval_run",
    "dataset",
    "knowledge_gap",
    "improvement",
]
"""What changed. A `trigger` or `eval_suite` event names the agent whose routines
or suites changed, since that is what a subscriber's access to them is decided by;
a `run` event is a run moving through its states (started, parked, finished),
which no request made; a `dataset` event is any write to a dataset, its cases, its
grading, its scores or its drafts - one a request made, or a generation finishing
on its own; a `knowledge_gap` event is a topic dismissed, reopened or drafted, or -
naming no topic - a grouping pass that placed new questions; an `improvement` event
names the agent whose improvement session moved to another stage or finished."""
ChangeAction = Literal["created", "updated", "deleted"]
ChangeSurface = Literal["console", "api_key", "mcp", "assistant", "run", "system"]
"""Where a change came from: a console session, an organization API key, an MCP
client signed in over OAuth, the in-app Architect, a run itself as it moved
from one state to the next, or work the platform does on its own schedule."""


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
