"""The AI Architect as the console's widget and settings page read it (#2063)."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

AssistantStatus = Literal["ready", "needs_model", "disabled", "unavailable"]


class AssistantRead(BaseSchema):
    status: AssistantStatus = Field(
        description=(
            "`ready` to talk to; `needs_model` until the organization has a model "
            "to run it on; `disabled` when an administrator switched it off; "
            "`unavailable` when it could not be installed (the agent ceiling)"
        )
    )
    agent_id: UUID | None
    slug: str | None = Field(
        default=None, description="Its handle, which its default face is drawn from"
    )
    name: str
    named_by_default: bool = Field(
        default=True,
        description=(
            "Whether it still has the name it was installed with, so the console "
            "shows its own name for it in the reader's language; false once an "
            "administrator renamed it"
        ),
    )
    greeting: str | None
    avatar_url: str | None = None
    avatar_color: int | None = None
    wears_mark: bool = Field(
        default=True,
        description=(
            "Whether it still wears the mark it shipped with, which the console draws "
            "in the theme's colours; false once somebody gave it a picture of its own"
        ),
    )
    can_use: bool = Field(
        description="Whether the caller may talk to it - `agents:run`, as for any agent"
    )
    can_configure: bool = Field(description="Whether the caller may change its settings")


class AssistantUpdate(BaseSchema):
    """What the organization decides about its assistant that is not the agent's own.

    Its name, model, knowledge and the rest of its spec are the agent's, edited in
    the Builder like any agent's.
    """

    enabled: bool | None = None
    greeting: str | None = Field(default=None, max_length=500)


class AssistantSignals(BaseSchema):
    """What the widget's bubble may speak to on any page (#2063)."""

    pending_approvals: int = Field(
        description="Tool calls waiting on a decision; 0 without `approvals:decide`"
    )
    has_agents: bool = Field(
        description="Whether the caller can see an agent; false without `agents:view`"
    )
    failed_run_id: UUID | None = Field(
        description=("The caller's latest failed run of the last day; null without `runs:view`")
    )
