"""Opt-in channel observation, independent of an agent's published spec."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChannelObservationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    model_profile_id: UUID | None = None
    instructions: str = Field(default="", max_length=8000)
    unmentioned_interval_minutes: int = Field(default=20, ge=1, le=1440)
    mentioned_interval_minutes: int = Field(default=1, ge=1, le=1440)

    @model_validator(mode="after")
    def configured(self) -> Self:
        if self.enabled and self.model_profile_id is None:
            raise ValueError("Select the model that decides whether the agent should join")
        return self


class ObservedChannelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1, max_length=256)
    author_id: str = Field(min_length=1, max_length=256)
    text: str = Field(max_length=2000)
    received_at: datetime


class ChannelJoinDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    join: bool
    reason: str = Field(max_length=500)
