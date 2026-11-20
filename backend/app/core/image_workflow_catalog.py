"""Verified workflow options and conservative reservation inputs in the image catalog.

Legacy agent bindings keep their original option schema. A model with no workflow
entry is still readable there, but it has no admitted workflow generation contract.
"""

from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai.native_tools import ImageAspectRatio

type ImageQuality = Literal["low", "medium", "high"]
type ImageSize = Literal["1024x1024", "1024x1536", "1536x1024", "512", "1K", "2K", "4K"]
type ImageBackground = Literal["opaque", "transparent", "auto"]
type ImageFormat = Literal["png", "webp", "jpeg"]
type Price = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
type TokenLimit = Annotated[int, Field(gt=0, le=2_000_000)]


class ImageWorkflowDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quality: ImageQuality | None = None
    size: ImageSize | None = None
    aspect_ratio: ImageAspectRatio | None = None
    background: ImageBackground | None = None
    output_format: ImageFormat | None = None


class ImageOutputPrice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    size: ImageSize
    quality: ImageQuality
    output_estimate_usd: Price
    output_ceiling_usd: Price

    @model_validator(mode="after")
    def ceiling_covers_estimate(self) -> ImageOutputPrice:
        if self.output_ceiling_usd < self.output_estimate_usd:
            raise ValueError("An image output ceiling cannot be below its estimate")
        return self


class ImageWorkflowSupport(BaseModel):
    """One admitted request's options, and the dated bounds its hold is derived from.

    The input cap is the provider's context limit, not a prompt-size prediction.
    Output tokens are a request parameter enforced by the shared strict executor.
    Separate image-tool output fees are added only for providers that use that API.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference_image: bool
    qualities: tuple[ImageQuality, ...] = ()
    sizes: tuple[ImageSize, ...] = ()
    aspect_ratios: tuple[ImageAspectRatio, ...] = ()
    backgrounds: tuple[ImageBackground, ...] = ()
    output_formats: tuple[ImageFormat, ...] = ()
    defaults: ImageWorkflowDefaults
    max_input_tokens: TokenLimit
    max_output_tokens: TokenLimit
    input_usd_per_million: Price
    output_usd_per_million: Price
    tool_prompt_max_characters: int = Field(default=0, ge=0, le=32_000)
    tool_input_usd_per_million: Price = Decimal(0)
    output_prices: tuple[ImageOutputPrice, ...] = ()
    pricing_as_of: date
    sources: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_options(self) -> ImageWorkflowSupport:
        for name, choices in (
            ("quality", self.qualities),
            ("size", self.sizes),
            ("aspect_ratio", self.aspect_ratios),
            ("background", self.backgrounds),
            ("output_format", self.output_formats),
        ):
            default = getattr(self.defaults, name)
            if (default is None) != (not choices) or (choices and default not in choices):
                raise ValueError(f"The default {name} must match the catalog's supported options")
            if len(set(choices)) != len(choices):
                raise ValueError(f"Duplicate image {name} option")
        priced = {(row.size, row.quality) for row in self.output_prices}
        if len(priced) != len(self.output_prices):
            raise ValueError("Duplicate image output price")
        if self.tool_prompt_max_characters:
            expected = {(size, quality) for size in self.sizes for quality in self.qualities}
            if self.reference_image or not expected or priced != expected:
                raise ValueError("A text-only native tool needs every size/quality output price")
        elif self.output_prices or self.tool_input_usd_per_million:
            raise ValueError("Native image-tool fees need a bounded tool prompt")
        return self

    def reservation_usd(self, *, size: str | None, quality: str | None) -> Decimal:
        """A conservative catalog ceiling, distinct from an incurred cost or prediction."""
        amount = (
            self.max_input_tokens * self.input_usd_per_million
            + self.max_output_tokens * self.output_usd_per_million
            # A provider-limited Unicode prompt has at most four UTF-8 bytes per
            # character. Byte-level text tokens cannot exceed that byte count.
            + 4 * self.tool_prompt_max_characters * self.tool_input_usd_per_million
        ) / Decimal(1_000_000)
        if self.output_prices:
            selected = next(
                (row for row in self.output_prices if row.size == size and row.quality == quality),
                None,
            )
            if selected is None:
                raise ValueError("This image size and quality have no verified output ceiling")
            amount += selected.output_ceiling_usd
        return amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
