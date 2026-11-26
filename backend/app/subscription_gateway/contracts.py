"""Credential-free data shared by the subscription gateway and its backend client."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UsageWindow(BaseModel):
    kind: Literal["primary", "secondary", "five_hour", "seven_day", "provider"]
    label: str | None = Field(default=None, max_length=250)
    remaining_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    duration_minutes: int | None = Field(default=None, gt=0)
    resets_at: datetime | None = None


class AccountUsage(BaseModel):
    status: Literal["available", "stale", "unavailable"] = "unavailable"
    observed_at: datetime | None = None
    windows: list[UsageWindow] = Field(default_factory=list)
