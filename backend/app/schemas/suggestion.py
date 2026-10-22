"""What the platform proposes to a person, as the console reads it (#2301)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

SuggestionKindName = Literal["routine", "agent", "profile", "role_pack"]
SuggestionStatusName = Literal["open", "accepted", "dismissed"]


class SuggestionRead(BaseSchema):
    """One proposal, where it stands, and what accepting it needs."""

    id: UUID
    kind: SuggestionKindName
    status: SuggestionStatusName = "open"
    title: str
    detail: str | None = None
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "What accepting it does: `prompt` and `cadence` for a routine, `request` for an "
            "agent, the profile fields for a profile, `pack` for a role pack."
        ),
    )
    created_at: datetime


class SuggestionList(BaseSchema):
    items: list[SuggestionRead]
    total: int
