"""Video generation capability - make a short video from a description."""

from pydantic import BaseModel, Field, model_validator

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.video_generation._capability import VideoGeneration
from app.core.secret_kinds import ApiKeySecret, SecretCondition, SecretKind, SecretRequirement
from app.services.video_models import (
    VideoModel,
    by_provider,
    default_choice,
    providers,
    resolution_lines,
    up_to,
)

__all__ = ["VideoGeneration", "VideoGenerationConfig"]

USUAL_SECONDS = 5
"""A clip's length when nothing says otherwise: long enough to show something
happen, short enough to be cheap on every model here."""


class VideoGenerationConfig(BaseModel):
    """How this agent makes video.

    `provider` and `model` are the decision; everything else defaults to what the
    catalog lists first for that model, so turning the capability on is enough to
    make a clip.
    """

    provider: str = Field(
        title="Provider",
        default_factory=lambda: default_choice()[0],
        description=(
            "Whose model makes the video. Offered: the providers in "
            "`app/core/catalog/video_models.json` whose key the vault can hold."
        ),
    )
    model: str = Field(
        title="Video model",
        default_factory=lambda: default_choice()[1],
        description=(
            "Which of that provider's video models makes the clip. A model outside the "
            "catalog is refused here rather than mid-run."
        ),
    )
    resolution: str | None = Field(
        title="Resolution",
        default=None,
        description="Left empty, the model's first. Higher costs more per second.",
    )
    max_resolution: str | None = Field(
        title="Highest resolution",
        default=None,
        description=(
            "The highest resolution the agent may ask for, which caps what a second can "
            "cost; it may also ask for any lower one. Left empty, every clip is made at "
            "the resolution above."
        ),
    )
    aspect_ratio: str | None = Field(
        title="Aspect ratio",
        default=None,
        description="The shape a clip takes unless the agent asks for another; left empty, the model's first.",
    )
    seconds: int | None = Field(
        title="Length",
        default=None,
        ge=1,
        description=(
            "Seconds a clip runs unless the agent asks for another length; left empty, five, "
            "or the nearest the model makes. Not for a model that decides its own length."
        ),
    )
    max_seconds: int | None = Field(
        title="Longest clip",
        default=None,
        ge=1,
        description=(
            "The longest clip the agent may ask for, which caps what one call can cost; "
            "left empty, the model's own limit. Not for a model that decides its own length."
        ),
    )
    audio: bool | None = Field(
        title="Sound",
        default=None,
        description=(
            "Whether clips carry sound, where the model makes it optional; left empty, the "
            "provider's default."
        ),
    )
    timeout_seconds: int = Field(
        title="Time limit",
        default=600,
        ge=60,
        le=1800,
        description=(
            "How long to wait for a clip, in seconds. A job not finished by then is "
            "cancelled where the provider allows it, and the call fails."
        ),
    )

    @model_validator(mode="after")
    def _must_be_offered(self) -> "VideoGenerationConfig":
        """Refuse a choice the provider would refuse on the first call."""
        entry = by_provider(self.provider)
        model = entry.model(self.model) if entry is not None else None
        if entry is None or model is None:
            offered = "; ".join(
                f"{candidate.provider}: {', '.join(item.id for item in candidate.models)}"
                for candidate in providers()
            )
            raise ValueError(f"{self.provider}/{self.model} cannot make video. Offered: {offered}.")
        if self.resolution is not None and self.resolution not in model.resolutions:
            raise ValueError(
                f"{self.model} renders {', '.join(model.resolutions)}, not {self.resolution}."
            )
        if self.max_resolution is not None:
            if self.max_resolution not in model.resolutions:
                raise ValueError(
                    f"{self.model} renders {', '.join(model.resolutions)}, "
                    f"not {self.max_resolution}."
                )
            usual = self.resolution or model.resolutions[0]
            if resolution_lines(usual) > resolution_lines(self.max_resolution):
                raise ValueError(
                    f"The usual resolution, {usual}, cannot be higher than the highest, "
                    f"{self.max_resolution}."
                )
        if self.aspect_ratio is not None and self.aspect_ratio not in model.aspect_ratios:
            raise ValueError(
                f"{self.model} renders {', '.join(model.aspect_ratios)}, not {self.aspect_ratio}."
            )
        if not model.duration_choosable and (
            self.seconds is not None or self.max_seconds is not None
        ):
            raise ValueError(
                f"{self.model} decides its own length, so a length and a longest clip have no effect."
            )
        if self.audio is not None and model.audio != "optional":
            has = "always have" if model.audio == "always" else "never have"
            raise ValueError(f"{self.model} has no sound setting: its clips {has} sound.")
        for name, value in (("seconds", self.seconds), ("max_seconds", self.max_seconds)):
            if value is not None and not model.min_seconds <= value <= model.max_seconds:
                raise ValueError(
                    f"{self.model} makes {model.min_seconds} to {model.max_seconds} seconds, "
                    f"so {name} cannot be {value}."
                )
        if (
            self.seconds is not None
            and self.max_seconds is not None
            and self.seconds > self.max_seconds
        ):
            raise ValueError("The usual length cannot be longer than the longest clip.")
        return self

    def chosen_model(self) -> VideoModel:
        """The catalog's model this configuration was validated against."""
        entry = by_provider(self.provider)
        model = entry.model(self.model) if entry is not None else None
        if model is None:
            raise ValueError(f"{self.provider}/{self.model} is no longer offered for video")
        return model

    def offered_resolutions(self) -> tuple[str, ...]:
        """What the agent may ask for, shortest first: the usual one alone, or every
        one up to the highest."""
        model = self.chosen_model()
        usual = self.resolution or model.resolutions[0]
        return up_to(model, self.max_resolution) if self.max_resolution else (usual,)


@register(
    id="video_generation",
    name="Video generation",
    category="analysis",
    description="Make a short video from a text description.",
    tools=(
        CapabilityToolInfo(
            id="generate_video",
            description="Make a short video from a written description.",
        ),
    ),
    config_schema=VideoGenerationConfig,
    # A clip costs more than any other single call an agent makes and produces
    # content a person may publish, so every call is a candidate for approval.
    side_effecting=True,
    secret=SecretRequirement(
        kind=SecretKind.API_KEY,
        description="The API key for the chosen video provider",
        # Every provider needs a key; this tells the Builder the chosen provider
        # *is* the key's purpose, so the picker offers only its keys (#2258).
        required_when=SecretCondition(
            field="provider", equals=tuple(entry.provider for entry in providers())
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> VideoGeneration:
    config = (
        ctx.config if isinstance(ctx.config, VideoGenerationConfig) else VideoGenerationConfig()
    )
    model = config.chosen_model()
    api_key = (
        ctx.secret.api_key.get_secret_value() if isinstance(ctx.secret, ApiKeySecret) else None
    )
    return VideoGeneration(
        provider=config.provider,
        model=config.model,
        resolution=config.resolution or model.resolutions[0],
        resolutions=config.offered_resolutions(),
        aspect_ratio=config.aspect_ratio or model.aspect_ratios[0],
        aspect_ratios=model.aspect_ratios,
        seconds=config.seconds
        or min(max(USUAL_SECONDS, model.min_seconds), config.max_seconds or model.max_seconds),
        max_seconds=config.max_seconds or model.max_seconds,
        audio=config.audio,
        timeout_seconds=config.timeout_seconds,
        api_key=api_key,
    )
