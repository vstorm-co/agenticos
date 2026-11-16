"""Opt-in channel observation, independent of an agent's published spec."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChannelObservationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    model_profile_id: UUID | None = None
    instructions: str = Field(default="", max_length=8000)
    decision_mode: Literal["llm", "native"] = "llm"
    threshold_percent: float = Field(default=80, ge=0, le=100)
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

    score: int = Field(
        ge=0,
        le=100,
        description="How useful and timely joining is, from 0 (stay silent) to 100 (join)",
    )
    reason: str = Field(max_length=500)


class NativeChannelJoinDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probability: float = Field(
        ge=0,
        le=1,
        description="Should the agent join this conversation now, following the operator focus?",
    )
