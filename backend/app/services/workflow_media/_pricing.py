"""Freeze the admitted price basis; distinguish observed fees from unresolved holds."""

from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic_ai.messages import FilePart, ModelResponse

from app.agents.capabilities.budget import SpendLedger
from app.core.image_workflow_catalog import ImageWorkflowDefaults, ImageWorkflowSupport
from app.services.workflow_media_catalog import image_options, video_support
from app.workflows.nodes._media_config import ImageGenerateConfig, VideoGenerateConfig

type USD = Annotated[Decimal, Field(ge=0, le=999_999.999999, allow_inf_nan=False)]
_UNIT = Decimal("0.000001")
_MILLION = Decimal(1_000_000)


class ImagePriceBasis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["image"] = "image"
    catalog: ImageWorkflowSupport
    options: ImageWorkflowDefaults


class VideoPriceBasis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["video"] = "video"
    pricing_as_of: date
    usd_per_second: USD
    resolution: str = Field(min_length=1, max_length=32)
    requested_seconds: int | None = Field(ge=1, le=3600)
    maximum_seconds: int = Field(ge=1, le=3600)


type PriceBasis = Annotated[ImagePriceBasis | VideoPriceBasis, Field(discriminator="kind")]
price_basis_adapter = TypeAdapter(PriceBasis)


class ImageCostEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["image"] = "image"
    input_tokens: int = Field(ge=0, le=10_000_000)
    output_tokens: int = Field(ge=0, le=10_000_000)
    cache_read_tokens: int = Field(ge=0, le=10_000_000)
    caller_priced: bool
    image_returned: bool
    unexpected_service_tier: bool = False
    tool_input_reconciled: Literal[False] = False


class VideoCostEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["video"] = "video"
    seconds: Decimal = Field(gt=0, le=3600, allow_inf_nan=False)


class CostFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    incurred_usd: USD
    held_usd: USD
    source: Literal["reported", "catalog_estimate"]
    complete: bool
    evidence: ImageCostEvidence | VideoCostEvidence

    @model_validator(mode="after")
    def complete_has_no_unknown_fee(self) -> CostFact:
        if self.complete and self.held_usd:
            raise ValueError("Complete media accounting cannot retain an unknown fee")
        return self


def snapshot(config: ImageGenerateConfig | VideoGenerateConfig) -> PriceBasis:
    if isinstance(config, ImageGenerateConfig):
        return ImagePriceBasis(
            catalog=config.workflow_support(),
            options=image_options(config.provider, config.model, config),
        )
    request = config.request_config()
    model = request.chosen_model()
    support = video_support(model)
    if support is None:
        raise ValueError("This video model has no current catalog price")
    return VideoPriceBasis(
        pricing_as_of=support.pricing_as_of,
        usd_per_second=support.usd_per_second[request.resolved_resolution()],
        resolution=request.resolved_resolution(),
        requested_seconds=config.requested_seconds(),
        maximum_seconds=model.max_seconds,
    )


def image_cost(basis: ImagePriceBasis, response: ModelResponse) -> CostFact:
    """Reuse the canonical usage pricer; a missing fee remains a separate hold.

    Responses' returned revised prompt does not prove the complete billed native
    tool input. Its ceiling remains held even when the output was received. No
    prompt text or raw native-tool return is persisted as accounting evidence.
    OpenAI's explicit standard request tier is part of the admitted price basis;
    an unexpected reported tier preserves the whole hold for reconciliation.
    """
    support = basis.catalog
    usage = response.usage
    entry = SpendLedger().record(response.model_name or "unknown", usage, response.provider_name)
    unexpected_tier = bool(support.output_prices) and (
        (response.provider_details or {}).get("service_tier") not in (None, "default")
    )
    priced = (
        not unexpected_tier
        and entry.priced
        and bool(usage.input_tokens or usage.output_tokens or entry.provider_reported)
    )
    image_returned = any(
        isinstance(part, FilePart) and part.content.media_type.startswith("image/")
        for part in response.parts
    )
    incurred = entry.cost_usd if priced else Decimal(0)
    held = (
        Decimal(0)
        if priced
        else (
            support.max_input_tokens * support.input_usd_per_million
            + support.max_output_tokens * support.output_usd_per_million
        )
        / _MILLION
    )
    source: Literal["reported", "catalog_estimate"] = (
        "reported" if entry.provider_reported and priced else "catalog_estimate"
    )
    if support.output_prices:
        chosen = next(
            price
            for price in support.output_prices
            if price.size == basis.options.size and price.quality == basis.options.quality
        )
        held += (
            4 * support.tool_prompt_max_characters * support.tool_input_usd_per_million / _MILLION
        )
        if image_returned and not unexpected_tier:
            incurred += chosen.output_estimate_usd
        else:
            held += chosen.output_ceiling_usd
        source = "catalog_estimate"
    return CostFact(
        incurred_usd=incurred.quantize(_UNIT, rounding=ROUND_CEILING),
        held_usd=held.quantize(_UNIT, rounding=ROUND_CEILING),
        source=source,
        complete=held == 0,
        evidence=ImageCostEvidence(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            caller_priced=priced,
            image_returned=image_returned,
            unexpected_service_tier=unexpected_tier,
        ),
    )


def video_cost(basis: VideoPriceBasis, *, seconds: float | Decimal) -> CostFact:
    """Price observed/generated duration, never an unused maximum reservation."""
    evidence = VideoCostEvidence(seconds=Decimal(str(seconds)))
    return CostFact(
        incurred_usd=(basis.usd_per_second * evidence.seconds).quantize(
            _UNIT, rounding=ROUND_CEILING
        ),
        held_usd=Decimal(0),
        source="catalog_estimate",
        complete=True,
        evidence=evidence,
    )
