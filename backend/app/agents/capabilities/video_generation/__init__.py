"""Video generation capability - make a short video from a description."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.agents.capabilities._config_refusal import refused_at
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

AlibabaRegion = Literal[
    "ap-southeast-1", "us-east-1", "eu-central-1", "ap-northeast-1", "cn-beijing", "cn-hongkong"
]
"""The regions Alibaba's Model Studio serves Wan from, by its own ids."""
"""A clip's length when nothing says otherwise: long enough to show something
happen, short enough to be cheap on every model here."""


class VideoGenerationConfig(BaseModel):
    """How this agent makes video.

    `provider` and `model` are the decision. The resolution, shape, length and
    sound are defaults the agent may override per clip, bounded only by the
    highest resolution and the longest clip; each defaults to what the catalog
    lists first for that model, so turning the capability on is enough to make a
    clip.
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
        description=(
            "The resolution a clip is made at unless the agent asks for another; left "
            "empty, the model's first. Higher costs more per second."
        ),
    )
    max_resolution: str | None = Field(
        title="Highest resolution",
        default=None,
        description=(
            "The highest resolution the agent may ask for, at least the usual one; it caps "
            "what a second can cost. Left empty, the agent may ask for any resolution the "
            "model renders."
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
            "Whether clips carry sound unless the agent asks otherwise, where the model makes "
            "it optional; left empty, the provider's default."
        ),
    )
    alibaba_workspace: str | None = Field(
        title="Alibaba workspace",
        default=None,
        # One DNS label: it becomes the first label of an `aliyuncs.com` host, so
        # anything else could point the key at a host nobody chose.
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
        description=(
            "Alibaba only: the Model Studio workspace id, which Wan 3.0 is called "
            "through. Left empty, the shared DashScope endpoint, which Alibaba keeps "
            "for existing integrations."
        ),
    )
    alibaba_region: AlibabaRegion = Field(
        title="Alibaba region",
        default="ap-southeast-1",
        description="Alibaba only: the region the workspace is in.",
    )
    timeout_seconds: int = Field(
        title="Time limit",
        default=600,
        ge=60,
        le=1800,
        description=(
            "How long to wait for a clip, in seconds. A job not finished by then is "
            "cancelled where the provider allows it and booked at its estimate."
        ),
    )

    @model_validator(mode="after")
    def _must_be_offered(self) -> VideoGenerationConfig:
        """Refuse a choice the provider would refuse on the first call.

        Each at its own field, so the Builder can mark the control it is about
        rather than calling the whole configuration invalid.
        """
        title = type(self).__name__
        entry = by_provider(self.provider)
        model = entry.model(self.model) if entry is not None else None
        if entry is None or model is None:
            offered = "; ".join(
                f"{candidate.provider}: {', '.join(item.id for item in candidate.models)}"
                for candidate in providers()
            )
            reason = f"{self.provider}/{self.model} cannot make video. Offered: {offered}."
            raise refused_at(title, [(("model",), reason, self.model)])
        if self.resolution is not None and self.resolution not in model.resolutions:
            reason = f"{self.model} renders {', '.join(model.resolutions)}, not {self.resolution}."
            raise refused_at(title, [(("resolution",), reason, self.resolution)])
        if self.max_resolution is not None:
            if self.max_resolution not in model.resolutions:
                reason = (
                    f"{self.model} renders {', '.join(model.resolutions)}, "
                    f"not {self.max_resolution}."
                )
                raise refused_at(title, [(("max_resolution",), reason, self.max_resolution)])
            usual = self.resolved_resolution()
            if resolution_lines(usual) > resolution_lines(self.max_resolution):
                reason = (
                    f"The highest resolution, {self.max_resolution}, cannot be lower than "
                    f"the usual one, {usual}."
                )
                raise refused_at(title, [(("max_resolution",), reason, self.max_resolution)])
        if self.aspect_ratio is not None and self.aspect_ratio not in model.aspect_ratios:
            reason = (
                f"{self.model} renders {', '.join(model.aspect_ratios)}, not {self.aspect_ratio}."
            )
            raise refused_at(title, [(("aspect_ratio",), reason, self.aspect_ratio)])
        lengths = (("seconds", self.seconds), ("max_seconds", self.max_seconds))
        if not model.duration_choosable:
            reason = f"{self.model} decides its own length, so a length has no effect."
            refused = [((name,), reason, value) for name, value in lengths if value is not None]
            if refused:
                raise refused_at(title, refused)
        if self.audio is not None and model.audio != "optional":
            has = "always have" if model.audio == "always" else "never have"
            reason = f"{self.model} has no sound setting: its clips {has} sound."
            raise refused_at(title, [(("audio",), reason, self.audio)])
        for name, value in lengths:
            if value is not None and not model.min_seconds <= value <= model.max_seconds:
                reason = (
                    f"{self.model} makes {model.min_seconds} to {model.max_seconds} seconds, "
                    f"so {name} cannot be {value}."
                )
                raise refused_at(title, [((name,), reason, value)])
        if (
            self.seconds is not None
            and self.max_seconds is not None
            and self.seconds > self.max_seconds
        ):
            reason = "The usual length cannot be longer than the longest clip."
            raise refused_at(title, [(("seconds",), reason, self.seconds)])
        return self

    def chosen_model(self) -> VideoModel:
        """The catalog's model this configuration was validated against."""
        entry = by_provider(self.provider)
        model = entry.model(self.model) if entry is not None else None
        if model is None:
            raise ValueError(f"{self.provider}/{self.model} is no longer offered for video")
        return model

    def endpoint(self) -> str | None:
        """The API base a workspace binding is called at, or `None` for the catalog's.

        Only Alibaba has one: Model Studio serves Wan from a host named after the
        workspace and its region (#2350).
        """
        if self.provider != "alibaba" or self.alibaba_workspace is None:
            return None
        return f"https://{self.alibaba_workspace}.{self.alibaba_region}.maas.aliyuncs.com/api/v1"

    def resolved_resolution(self) -> str:
        """The usual resolution: the one chosen, or the model's first."""
        return self.resolution or self.chosen_model().resolutions[0]

    def offered_resolutions(self) -> tuple[str, ...]:
        """What the agent may ask for, shortest first: every resolution up to the
        highest, or - with none set - every one the model renders."""
        model = self.chosen_model()
        return up_to(model, self.max_resolution or max(model.resolutions, key=resolution_lines))


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
    # A clip takes minutes, which a voice call cannot sit silent through, and may
    # start from an image in the workspace a call does not open: the call hands
    # it to the agent's text twin, as it does the sandbox.
    voice="hand_off",
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
        resolution=config.resolved_resolution(),
        resolutions=config.offered_resolutions(),
        aspect_ratio=config.aspect_ratio or model.aspect_ratios[0],
        aspect_ratios=model.aspect_ratios,
        seconds=config.seconds
        or min(max(USUAL_SECONDS, model.min_seconds), config.max_seconds or model.max_seconds),
        max_seconds=config.max_seconds or model.max_seconds,
        audio=config.audio,
        audio_optional=model.audio == "optional",
        timeout_seconds=config.timeout_seconds,
        base_url=config.endpoint(),
        api_key=api_key,
    )
