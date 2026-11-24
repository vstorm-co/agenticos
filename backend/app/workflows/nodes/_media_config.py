"""Permanent generation node schemas; provider execution owns no workflow authority."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.agents.capabilities.image_generation import ImageGenerationConfig
from app.agents.capabilities.video_generation import VideoGenerationConfig
from app.core.image_workflow_catalog import ImageWorkflowDefaults, ImageWorkflowSupport
from app.services.media_inspection import MediaInfo
from app.services.video_models import price_per_second
from app.services.workflow_media_catalog import (
    image_options,
    image_support,
    video_defaults,
    video_support,
)
from app.workflows.contracts.io import FileRef

type Filename = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$"
    ),
]


class MediaGenerateConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    secret_id: UUID = Field(
        title="Provider API key",
        description="An organization API key for the selected provider, used with your permissions",
        json_schema_extra={"x-resource": "secret", "x-secret-kind": "api_key"},
    )
    timeout_seconds: int = Field(default=180, ge=60, le=600)
    max_cost_usd: float | None = Field(default=None, gt=0, le=100_000, allow_inf_nan=False)
    max_output_bytes: int = Field(default=33_554_432, ge=1, le=268_435_456)
    max_output_pixels: int = Field(default=33_554_432, ge=1, le=134_217_728)


class ImageGenerateConfig(ImageWorkflowDefaults, MediaGenerateConfig):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    filename: Filename = "generated.png"

    @model_validator(mode="after")
    def admitted_options(self) -> ImageGenerateConfig:
        image_options(self.provider, self.model, self)
        return self

    def workflow_support(self) -> ImageWorkflowSupport:
        return image_support(self.provider, self.model)

    def request_config(self) -> ImageGenerationConfig:
        return ImageGenerationConfig(
            provider=self.provider,
            model=self.model,
            **image_options(self.provider, self.model, self).model_dump(),
        )

    def reservation_usd(self) -> Decimal:
        options = image_options(self.provider, self.model, self)
        return self.workflow_support().reservation_usd(size=options.size, quality=options.quality)


class VideoGenerateConfig(MediaGenerateConfig):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    resolution: str | None = None
    aspect_ratio: str | None = None
    seconds: int | None = Field(default=None, ge=1)
    audio: bool | None = None
    filename: Filename = "generated.mp4"
    max_output_bytes: int = Field(default=134_217_728, ge=1, le=268_435_456)

    @model_validator(mode="after")
    def admitted_options(self) -> VideoGenerateConfig:
        request = self.request_config()
        if video_support(request.chosen_model()) is None:
            raise ValueError("This video model has no current catalog price")
        return self

    def request_config(self) -> VideoGenerationConfig:
        request = VideoGenerationConfig(
            provider=self.provider,
            model=self.model,
            resolution=self.resolution,
            aspect_ratio=self.aspect_ratio,
            seconds=self.seconds,
            audio=self.audio,
            timeout_seconds=self.timeout_seconds,
        )
        defaults = video_defaults(request.chosen_model())
        return request.model_copy(
            update={
                "resolution": request.resolution or defaults.resolution,
                "aspect_ratio": request.aspect_ratio or defaults.aspect_ratio,
                "seconds": request.seconds or defaults.seconds,
                "audio": defaults.audio if request.audio is None else request.audio,
            }
        )

    def requested_seconds(self) -> int | None:
        return self.request_config().seconds

    def reservation_usd(self) -> Decimal:
        request = self.request_config()
        model = request.chosen_model()
        rate = price_per_second(model, request.resolved_resolution(), on=datetime.now(UTC).date())
        if rate is None:
            raise ValueError("This video model has no current catalog price")
        return rate * (self.requested_seconds() or model.max_seconds)


class MediaGenerateInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16_000)
    ]
    reference_image: FileRef | None = None


class MediaGenerationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    provider: str
    model: str
    submitted_at: datetime
    cost_source: Literal["reported", "catalog_estimate"]
    cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    held_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    outcome: Literal["stored"] = "stored"


class ImageGenerationOutput(MediaInfo):
    kind: Literal["image"] = "image"
    file: FileRef
    receipt: MediaGenerationReceipt


class VideoGenerationOutput(MediaInfo):
    kind: Literal["video"] = "video"
    file: FileRef
    receipt: MediaGenerationReceipt
