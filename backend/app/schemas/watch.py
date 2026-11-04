"""What a person watches in their own connections, as the console reads and writes it (#2301)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.db.models.watch import MIN_WATCH_MINUTES
from app.schemas.base import BaseSchema

MAX_WATCH_MINUTES = 10080
"""A week: a watch read less often than that is a routine's job."""

MAX_EXCLUSIONS = 20
WatchStopped = Literal["watches_off", "connection_disabled"]


class WatchCreate(BaseSchema):
    connection_id: UUID = Field(description="One of the caller's own MCP connections.")
    preset_key: str | None = Field(
        default=None,
        max_length=64,
        description="The catalog preset it is made from, for that connection's server.",
    )
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(
        min_length=1, max_length=2000, description="What to look for, in plain words."
    )
    urgent: bool = Field(
        default=False,
        description="Send what the model judges urgent at once, not in the morning briefing.",
    )
    interval_minutes: int = Field(ge=MIN_WATCH_MINUTES, le=MAX_WATCH_MINUTES)


class WatchUpdate(BaseSchema):
    """Any of its fields; `null` is refused for each, since none of them can be empty."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = Field(default=None, min_length=1, max_length=2000)
    urgent: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=MIN_WATCH_MINUTES, le=MAX_WATCH_MINUTES)
    is_active: bool | None = None
    exclusions: list[str] | None = Field(
        default=None,
        max_length=MAX_EXCLUSIONS,
        description="What not to report again, one line each.",
    )

    @field_validator("exclusions")
    @classmethod
    def _lines(cls, lines: list[str] | None) -> list[str] | None:
        """Trimmed, blank lines dropped, each said once, in the order the person gave."""
        if lines is None:
            return None
        kept: list[str] = []
        for line in (raw.strip() for raw in lines):
            if len(line) > 200:
                raise ValueError("Each line is at most 200 characters")
            if line and line not in kept:
                kept.append(line)
        return kept

    @model_validator(mode="after")
    def _no_explicit_null(self) -> Self:
        sent_null = sorted(name for name in self.model_fields_set if getattr(self, name) is None)
        if sent_null:
            raise ValueError(f"Cannot be null: {', '.join(sent_null)}")
        return self


class WatchRead(BaseSchema):
    id: UUID
    connection_id: UUID
    connection_name: str = Field(description="The connection, as its person calls it.")
    server: str | None = Field(description="Its catalog key; null for a custom server.")
    preset_key: str | None
    title: str
    instructions: str
    exclusions: list[str]
    urgent: bool
    interval_minutes: int
    is_active: bool
    stopped: WatchStopped | None = Field(
        default=None,
        description=(
            "Why it is not being read although it is on: the organization turned "
            "watches off, no longer allows its server, or the connection is off."
        ),
    )
    next_run_at: datetime
    last_run_at: datetime | None
    waiting: int = Field(default=0, description="Its findings still open in the person's inbox.")
    created_at: datetime


class WatchList(BaseSchema):
    items: list[WatchRead]
    total: int


class WatchPresetRead(BaseSchema):
    key: str
    server: str = Field(description="The catalog server it is for.")
    instructions: str
    interval_minutes: int
    urgent: bool


class WatchPresetList(BaseSchema):
    items: list[WatchPresetRead]
    total: int
