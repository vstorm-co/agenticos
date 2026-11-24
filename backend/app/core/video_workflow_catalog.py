"""The dated video catalog fields a workflow may use for a bounded request."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class VideoWorkflowDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution: str
    aspect_ratio: str
    seconds: int | None = Field(ge=1)
    audio: bool | None


class VideoWorkflowSupport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference_image: bool
    defaults: VideoWorkflowDefaults
    pricing_as_of: date
    usd_per_second: dict[str, Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]]
