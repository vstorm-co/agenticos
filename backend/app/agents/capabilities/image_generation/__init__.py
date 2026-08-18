"""Image generation capability - draw an image from a prompt."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_ai.native_tools import ImageAspectRatio

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.image_generation._capability import ImageGeneration
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE
from app.core.secret_kinds import ApiKeySecret, SecretKind, SecretRequirement
from app.services.image_models import (
    default_choice,
    image_providers,
    is_offered,
    resolved_model_id,
    tool_model,
)

__all__ = ["ImageGeneration", "ImageGenerationConfig"]


class ImageGenerationConfig(BaseModel):
    """How this agent generates images.

    `model` is the whole required decision - which image model draws, and (with
    it) which provider the API key belongs to. The rest are optional refinements
    the provider fills in with its own defaults when left unset, so an agent that
    turns the capability on and nothing else generates images immediately.
    """

    provider: str = Field(
        default_factory=lambda: default_choice()[0],
        description=(
            "Whose model draws. Only providers whose model class honours the image tool are "
            "accepted - three today - and which those are is asked of the SDK rather than "
            "listed here."
        ),
    )
    model: str = Field(
        default_factory=lambda: default_choice()[1],
        description=(
            "Which of that provider's image models draws, by the ids in "
            "`app/core/catalog/image_models.json`. A model outside the catalog is refused: "
            "the tool answers a model that cannot draw with an error its author only sees "
            "mid-run."
        ),
    )

    @model_validator(mode="after")
    def _must_be_offered(self) -> "ImageGenerationConfig":
        """Refuse a pair the platform does not offer.

        Both halves, because both fail differently: a provider whose class lacks
        the tool fails on the first call with "not supported by this model", and a
        model its provider does not have fails as a bad request. `together:flux` is
        a real model and neither check would pass it.
        """
        if not is_offered(self.provider, self.model):
            offered = ", ".join(
                f"{entry.provider}: {', '.join(model.id for model in entry.models)}"
                for entry in image_providers()
            )
            raise ValueError(
                f"{self.provider}/{self.model} cannot generate images. Offered: {offered}."
            )
        return self

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
            # The tool's own `model`, which is not always the model chosen: for
            # OpenAI the chosen one is what draws and some Responses model has to
            # call it, so the id names the caller and this names the drawer.
            "model": tool_model(self.provider, self.model),
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
        model_id=resolved_model_id(config.provider, config.model),
        tool_settings=config.to_tool_kwargs(),
        api_key=api_key,
        workspace_backend=ctx.resources.get(WORKSPACE_BACKEND_RESOURCE),
    )
