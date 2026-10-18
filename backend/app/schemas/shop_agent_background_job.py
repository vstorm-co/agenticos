"""Shop background agent job schemas (D3 B62 — Studio parity with multi-agent)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

JobTypeLiteral = Literal["report", "digest"]
JobStatusLiteral = Literal["pending", "running", "completed", "failed"]
NotifyChannelLiteral = Literal["in_app", "email", "zalo", "telegram"]


class ShopAgentBackgroundJobCreate(BaseSchema):
    job_type: JobTypeLiteral = "report"
    goal: str = Field(..., min_length=3, max_length=4000)
    notify_channels: list[NotifyChannelLiteral] = Field(default_factory=lambda: ["in_app"])
    digest_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    conversation_id: UUID | None = None


class ShopAgentBackgroundJobRead(BaseSchema):
    id: UUID
    tenant_id: UUID
    organization_id: UUID | None
    conversation_id: UUID | None
    job_type: str
    goal: str
    status: str
    notify_channels: list[str] | None
    result_summary: str | None
    error_message: str | None
    digest_interval_hours: int | None
    next_run_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ShopAgentBackgroundJobList(BaseSchema):
    items: list[ShopAgentBackgroundJobRead]
    total: int
