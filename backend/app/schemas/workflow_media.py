"""Safe media estimates and durable operation status for existing workflow views."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.core.image_workflow_catalog import ImageQuality, ImageSize
from app.schemas.base import BaseSchema
from app.workflows.nodes._media_config import ImageGenerateConfig, VideoGenerateConfig

type WorkflowMediaPhase = Literal[
    "prepared", "submitting", "submitted", "collecting", "stored", "unknown", "failed", "cancelled"
]
type WorkflowMediaRetryEffect = Literal[
    "collect_existing",
    "recover_output",
    "new_billable_submission",
    "reconciliation_required",
    "none",
]
type MediaUSD = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class ImageMediaEstimateRequest(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["image"]
    config: ImageGenerateConfig


class VideoMediaEstimateRequest(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["video"]
    config: VideoGenerateConfig


type WorkflowMediaEstimateRequest = Annotated[
    ImageMediaEstimateRequest | VideoMediaEstimateRequest, Field(discriminator="kind")
]


class SimpleMediaEstimateAssumption(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "conservative_reservation",
        "single_submission",
        "dispatch_limits_rechecked",
        "unresolved_hold_retained",
        "text_only",
    ]


class ImageTokenCeilingAssumption(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    code: Literal["image_token_ceiling"] = "image_token_ceiling"
    max_input_tokens: int = Field(gt=0, le=10_000_000)
    max_output_tokens: int = Field(gt=0, le=10_000_000)


class ImageToolCeilingAssumption(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    code: Literal["image_tool_ceiling"] = "image_tool_ceiling"
    prompt_max_characters: int = Field(gt=0, le=32_000)
    quality: ImageQuality
    size: ImageSize
    output_estimate_usd: MediaUSD
    output_ceiling_usd: MediaUSD


class VideoDurationRateAssumption(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    code: Literal["video_duration_rate"] = "video_duration_rate"
    seconds: int = Field(gt=0, le=3600)
    resolution: str = Field(min_length=1, max_length=32)
    usd_per_second: MediaUSD
    uses_model_maximum: bool
    sound_on_ceiling: bool


type WorkflowMediaEstimateAssumption = Annotated[
    SimpleMediaEstimateAssumption
    | ImageTokenCeilingAssumption
    | ImageToolCeilingAssumption
    | VideoDurationRateAssumption,
    Field(discriminator="code"),
]


class WorkflowMediaEstimateRead(BaseSchema):
    kind: Literal["image", "video"]
    provider: str
    model: str
    reservation_usd: MediaUSD
    reserved_bytes: int = Field(gt=0)
    pricing_as_of: date
    configured_max_cost_usd: MediaUSD | None
    sufficient_max_cost_usd: bool
    deficit_usd: MediaUSD
    assumptions: list[WorkflowMediaEstimateAssumption]


class WorkflowMediaOperationRead(BaseSchema):
    """Only journal facts; no credential, provider payload, prompt, or private URL.

    Retry effect describes what an already authorized retry would do. It grants
    no permission to resolve a step. The total also includes superseded unknown
    operations: a later submission never hides an earlier unresolved charge.
    """

    operation_id: UUID
    phase: WorkflowMediaPhase
    held_usd: MediaUSD
    incurred_usd: MediaUSD
    booked_usd: MediaUSD
    cost_source: Literal["reported", "catalog_estimate"] | None
    accounting_complete: bool
    node_unresolved_usd: MediaUSD
    has_receipt: bool
    retry_effect: WorkflowMediaRetryEffect


class WorkflowMediaCharged(BaseSchema):
    """The provider's own billing shows this submission was charged this amount."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["charged"]
    charged_usd: Annotated[
        Decimal, Field(gt=0, le=Decimal("999999.999999"), decimal_places=6, allow_inf_nan=False)
    ]


class WorkflowMediaNotCharged(BaseSchema):
    """The provider's own billing shows this submission was never charged."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["not_charged"]


WorkflowMediaResolve = Annotated[
    WorkflowMediaCharged | WorkflowMediaNotCharged, Field(discriminator="outcome")
]
