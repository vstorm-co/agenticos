"""What a person watches in their own connections, as the console reads and writes it (#2301)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.db.models.watch import MIN_WATCH_MINUTES, WatchAttemptStatus
from app.schemas.base import BaseSchema
from app.schemas.routine_notifications import ExternalNotificationChannel, WatchReportMode

MAX_WATCH_MINUTES = 10080
"""A week: a watch read less often than that is a routine's job."""

MAX_EXCLUSIONS = 20
WatchStopped = Literal["watches_off", "connection_disabled", "needs_agent"]


class WatchCreate(BaseSchema):
    max_failures: int | None = Field(
        default=3,
        ge=1,
        le=20,
        description="Pause after this many consecutive unsuccessful executions; null disables this limit. Waiting and delivery failures do not count.",
    )
    notification_channels: list[ExternalNotificationChannel] | None = Field(
        default=None, max_length=9
    )
    report_mode: WatchReportMode = "changes"
    agent_id: UUID = Field(
        description="The selected published agent; no separate proactivity model is substituted."
    )
    environment_id: UUID | None = None
    pinned_version_id: UUID | None = None
    ends_at: AwareDatetime | None = None
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

    @model_validator(mode="after")
    def _one_version(self) -> Self:
        if self.environment_id is not None and self.pinned_version_id is not None:
            raise ValueError("Choose an environment or a pinned version, not both")
        return self


class WatchUpdate(BaseSchema):
    """Partial changes; null clears a version/end or disables the failure limit."""

    max_failures: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Pause after this many consecutive unsuccessful executions; null disables this limit. Waiting and delivery failures do not count.",
    )

    notification_channels: list[ExternalNotificationChannel] | None = Field(
        default=None, max_length=9
    )
    report_mode: WatchReportMode | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    agent_id: UUID | None = None
    environment_id: UUID | None = None
    pinned_version_id: UUID | None = None
    ends_at: AwareDatetime | None = None
    review_sources: bool = Field(
        default=False, description="Explicitly approve this agent's current attached sources again."
    )
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
        sent_null = sorted(
            name
            for name in self.model_fields_set
            if getattr(self, name) is None
            and name
            not in {
                "environment_id",
                "pinned_version_id",
                "ends_at",
                "notification_channels",
                "max_failures",
            }
        )
        if sent_null:
            raise ValueError(f"Cannot be null: {', '.join(sent_null)}")
        return self


class WatchRead(BaseSchema):
    max_failures: int | None = Field(
        default=3,
        ge=1,
        le=20,
        description="Pause after this many consecutive unsuccessful executions; null disables this limit. Waiting and delivery failures do not count.",
    )
    consecutive_failures: int = 0
    auto_stopped_at: datetime | None = None
    notification_channels: list[ExternalNotificationChannel] | None = Field(
        default=None, max_length=9
    )
    report_mode: WatchReportMode = "changes"
    id: UUID
    agent_id: UUID | None = None
    environment_id: UUID | None = None
    pinned_version_id: UUID | None = None
    ends_at: datetime | None = None
    source_conversation_id: UUID | None = None
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
    last_attempt_at: datetime | None = None
    last_attempt_status: WatchAttemptStatus | None = Field(
        default=None,
        description=(
            "The latest attempted check. Only completed advances last_run_at; "
            "not_completed means no valid reading, including unavailable models or budget. "
            "Null for watches not attempted since attempt tracking was introduced."
        ),
    )
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
