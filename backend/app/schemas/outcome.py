"""Schemas for the shared state of what needs a person's attention (#2575)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.base import BaseSchema

OutcomeStatusName = Literal["open", "acknowledged", "resolved", "muted"]
OutcomeAction = Literal["acknowledge", "resolve", "mute"]


class OutcomeRead(BaseSchema):
    id: UUID
    kind: str
    summary: str
    context_url: str | None = None
    status: OutcomeStatusName
    source_conversation_id: UUID | None = None
    created_at: datetime
    settled_at: datetime | None = None
    settled_via: str | None = None


class OutcomeList(BaseSchema):
    items: list[OutcomeRead]


class OutcomeSettle(BaseModel):
    action: OutcomeAction
    via: Literal["inbox", "chat"] = "inbox"
    """Where the person did it: stored, so a later spoken report can say it was already seen."""
