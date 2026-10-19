"""Saving a visual from the conversation as an app."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class VisualPublish(BaseSchema):
    """The app a visual is saved as. The same name again adds a version to that app."""

    name: str = Field(
        min_length=1,
        max_length=64,
        description="The app's handle: lower-case letters, digits and hyphens",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description="What the app is called; the visual's title when omitted",
    )


class VisualPublished(BaseSchema):
    """The app version a visual became."""

    artifact_id: UUID
    version: int
    name: str
    title: str
    created: bool
    unchanged: bool
    url: str = Field(description="Where the app opens in the console")


class VisualListItem(BaseSchema):
    """A drawing as the dashboard lists it: what it is, where it was drawn, nothing of it."""

    id: UUID
    conversation_id: UUID
    tool_call_id: str
    agent_id: UUID | None
    title: str
    kind: str
    revision_of: str | None
    artifact_id: UUID | None = Field(description="The app it was saved as, if it was")
    has_thumbnail: bool
    created_at: datetime


class VisualList(BaseSchema):
    items: list[VisualListItem]
