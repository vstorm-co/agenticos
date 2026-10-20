"""Which providers can generate a video, with which models, lengths and prices.

The video counterpart of :mod:`app.services.text_to_speech_models`, shaped the
same way for the same reasons: what may be chosen is *data*, in
`app/core/catalog/video_models.json`, so a model released this morning is one
entry with no code (#2260).

**One API shape per entry.** Gemini's Interactions endpoint answers in one call;
BytePlus, xAI and Alibaba each take a job and are polled for it, each with its
own paths and fields. An entry names the shape it speaks and an entry naming a
shape with no client is dropped rather than offered and failed.

**A provider is a vault purpose.** Google, xAI and Alibaba Cloud are model
providers already; BytePlus is a service in `services.json`. A provider whose
purpose is missing, or takes anything but a plain API key, is dropped.

**What a model can make is stated per model** - the lengths it takes, the
aspect ratios, the resolutions, whether its clips carry sound and whether it
starts from an image - because the providers differ on every one and a tool
call asking for a length the model refuses is a call that fails mid-run.

**Prices are per second and per resolution, and dated.** Every provider here
bills a second of video, at a rate that rises with the resolution; token-billed
models are listed at the per-second figure their own pricing converts to. A
price carries the day it applies from - the day it was read off the provider's
price list, where the provider states none - so a scheduled change lands on its
date.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import TypeAdapter

from app.core import catalog, secret_purposes
from app.core.secret_kinds import SecretKind


@dataclass(frozen=True)
class VideoPrice:
    """What a second of video costs, per resolution, from one day on."""

    since: date
    usd_per_second: dict[str, Decimal]


@dataclass(frozen=True)
class VideoModel:
    """One model that makes video, as a picker renders it and the tool calls it."""

    id: str
    name: str
    description: str
    min_seconds: int
    max_seconds: int
    """The clip lengths it takes, in whole seconds, both ends included."""

    aspect_ratios: tuple[str, ...]
    """Aspect ratios it renders; the first is the default."""

    resolutions: tuple[str, ...]
    """Resolutions it renders; the first is the default."""

    prices: tuple[VideoPrice, ...]
    audio: Literal["always", "optional", "never"] = "never"
    """Whether a clip carries sound: always, on request, or never."""

    first_frame: bool = False
    """Whether it can start from an image the agent hands it."""

    duration_choosable: bool = True
    """Whether a call may ask for a length. Where it cannot - Gemini Omni decides
    its own - a clip is priced at `max_seconds` before the call, the most it can
    cost."""


@dataclass(frozen=True)
class VideoEntry:
    """One provider's video models, as the catalog file states them."""

    provider: str
    api: str
    base_url: str
    models: tuple[VideoModel, ...]


CATALOG: tuple[VideoEntry, ...] = catalog.load(
    "video_models.json", TypeAdapter(tuple[VideoEntry, ...])
)

SUPPORTED_APIS = frozenset(
    {"gemini_interactions", "byteplus_tasks", "xai_videos", "dashscope_tasks"}
)
"""API shapes there is a client for. An entry naming another one is dropped."""


@dataclass(frozen=True)
class VideoProvider:
    """One provider that can make video, with what may be chosen on it."""

    provider: str
    name: str
    api: str
    base_url: str
    models: tuple[VideoModel, ...]

    def model(self, model_id: str) -> VideoModel | None:
        """One of this provider's models, or None where the catalog lists no such id."""
        return next((model for model in self.models if model.id == model_id), None)


def providers() -> tuple[VideoProvider, ...]:
    """Every provider that can make video, with the models it offers.

    An entry is dropped where the vault has no purpose for its provider, where that
    purpose takes anything but a plain API key, where it lists no models, or where
    its API shape has no client.
    """
    found: list[VideoProvider] = []
    for entry in CATALOG:
        purpose = secret_purposes.get(entry.provider)
        if purpose is None or purpose.kind is not SecretKind.API_KEY:
            continue
        if not entry.models or entry.api not in SUPPORTED_APIS:
            continue
        found.append(
            VideoProvider(
                provider=entry.provider,
                name=purpose.label,
                api=entry.api,
                base_url=entry.base_url,
                models=entry.models,
            )
        )
    return tuple(found)


def by_provider(provider: str) -> VideoProvider | None:
    """The offering for one provider id, or None where it cannot make video."""
    return next((entry for entry in providers() if entry.provider == provider), None)


def default_choice() -> tuple[str, str]:
    """The provider and model a binding starts on: the catalog's first of each."""
    first = providers()[0]
    return first.provider, first.models[0].id


def price_per_second(model: VideoModel, resolution: str, *, on: date) -> Decimal | None:
    """What a second at this resolution costs on a day, or None where it is unpriced.

    The latest price whose day has come. `None` - no price started yet, or none
    for this resolution - books the clip as unpriced rather than free.
    """
    current = [price for price in model.prices if price.since <= on]
    if not current:
        return None
    return max(current, key=lambda price: price.since).usd_per_second.get(resolution)
