"""Image generation capability - draw an image from a prompt."""

from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai.native_tools import ImageAspectRatio

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.image_generation._capability import ImageGeneration
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE
from app.core.secret_kinds import ApiKeySecret, SecretKind, SecretRequirement

__all__ = ["ImageGeneration", "ImageGenerationConfig"]

# Every model this capability can actually drive, and the reason the list is
# this short is the SDK rather than the market: `ImageGenerationTool` is honoured
# by exactly two model classes, `OpenAIResponsesModel` and `GoogleModel`
# (`pydantic_ai.models.openai` / `.google`), and Google's refuses a model without
# `image` in its name. Offering Together's or Fireworks' image models here would
# be a menu whose every third entry fails at run time with "not supported by this
# model", which is why there is no catalog of twenty providers behind this field.
ImageModel = Literal[
    "openai-responses:gpt-5.4",
    "google:gemini-3-pro-image",
    "google:gemini-3.1-flash-image",
    "google:gemini-3.1-flash-lite-image",
    "google:gemini-2.5-flash-image",
]

# What OpenAI's own image models are called, from the SDK's `ImageGenerationModelName`.
# Google has no equivalent: there the image model *is* the model above, where for
# OpenAI the model above is the Responses model that calls the tool and this is
# what the tool draws with.
OpenAIImageModel = Literal["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"]


class ImageGenerationConfig(BaseModel):
    """How this agent generates images.

    `model` is the whole required decision - which image model draws, and (with
    it) which provider the API key belongs to. The rest are optional refinements
    the provider fills in with its own defaults when left unset, so an agent that
    turns the capability on and nothing else generates images immediately.
    """

    model: ImageModel = Field(
        default="openai-responses:gpt-5.4",
        json_schema_extra={
            "x-enum-labels": {
                "openai-responses:gpt-5.4": "OpenAI · GPT-5.4 (Responses)",
                "google:gemini-3-pro-image": "Google · Nano Banana Pro (Gemini 3 Pro Image)",
                "google:gemini-3.1-flash-image": "Google · Nano Banana 2 (Gemini 3.1 Flash Image)",
                "google:gemini-3.1-flash-lite-image": (
                    "Google · Nano Banana 2 Lite (Gemini 3.1 Flash Lite Image)"
                ),
                "google:gemini-2.5-flash-image": "Google · Nano Banana (Gemini 2.5 Flash Image)",
            }
        },
    )
    image_model: OpenAIImageModel | None = Field(
        default=None,
        description=(
            "Which OpenAI image model draws, when the model above is an OpenAI one. "
            "Unset leaves OpenAI's own default. Ignored by Google, where the model above "
            "is itself the image model."
        ),
        json_schema_extra={
            "x-enum-labels": {
                "gpt-image-2": "GPT Image 2",
                "gpt-image-1.5": "GPT Image 1.5",
                "gpt-image-1": "GPT Image 1",
                "gpt-image-1-mini": "GPT Image 1 mini",
            }
        },
    )
    quality: Literal["low", "medium", "high", "auto"] | None = Field(
        default=None, description="Rendering quality; higher is slower and dearer."
    )
    size: Literal["auto", "1024x1024", "1024x1536", "1536x1024", "512", "1K", "2K", "4K"] | None = (
        Field(
            default=None,
            description="Output size. OpenAI uses the pixel values, Google the K values.",
        )
    )
    background: Literal["transparent", "opaque", "auto"] | None = Field(
        default=None, description="Background type; transparent needs a png or webp output."
    )
    output_format: Literal["png", "webp", "jpeg"] | None = Field(
        default=None, description="Image file format."
    )
    aspect_ratio: ImageAspectRatio | None = Field(
        default=None, description="Aspect ratio, e.g. 16:9 or 1:1."
    )

    def to_tool_kwargs(self) -> dict[str, Any]:
        """The image settings that were set, as `ImageGenerationTool` keywords.

        Only non-`None` fields, so an unset one leaves the provider's own default
        in place rather than overriding it with a null.
        """
        candidates = {
            # The tool's own `model`, which is not the model above: for OpenAI the
            # model above is the Responses model that *calls* the tool, and this is
            # what it draws with.
            "model": self.image_model,
            "quality": self.quality,
            "size": self.size,
            "background": self.background,
            "output_format": self.output_format,
            "aspect_ratio": self.aspect_ratio,
        }
        return {key: value for key, value in candidates.items() if value is not None}


@register(
    id="image_generation",
    name="Image generation",
    category="analysis",
    description="Generate an image from a text description.",
    tools=(
        CapabilityToolInfo(
            id="generate_image",
            description="Generate an image from a written description.",
        ),
    ),
    config_schema=ImageGenerationConfig,
    # Drawing an image spends real money on a provider key and produces content a
    # person may publish, so every call is a candidate for the approval gate.
    side_effecting=True,
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The API key for the chosen image generation provider",
    ),
)
def _build(ctx: CapabilityBuildContext) -> ImageGeneration:
    config = (
        ctx.config if isinstance(ctx.config, ImageGenerationConfig) else ImageGenerationConfig()
    )
    api_key = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    return ImageGeneration(
        model_id=config.model,
        tool_settings=config.to_tool_kwargs(),
        api_key=api_key,
        workspace_backend=ctx.resources.get(WORKSPACE_BACKEND_RESOURCE),
    )
