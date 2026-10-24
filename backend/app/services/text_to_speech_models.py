"""Which providers can speak a text aloud, with which models, voices and formats.

Shaped like :mod:`app.services.speech_to_text`, and for the same reason: an id, a
name and a sentence saying when to reach for it is *data*, so it lives in
`app/core/catalog/text_to_speech_models.json` and a model released this morning is
one entry with no code (#2259).

**Three API shapes, named per entry.** OpenAI's `POST /audio/speech`, ElevenLabs'
`POST /text-to-speech/{voice}` and Gemini's Interactions endpoint have nothing in
common past "text in, audio out", so an entry says which one it speaks and an
entry naming a shape with no client is dropped rather than offered and failed.

**A provider is a purpose, not a model provider.** ElevenLabs runs no chat model,
so it is not in `model_resolver.PROVIDERS`; what the catalog has to agree with is
the vault's list of what a key can be for, which holds both. A provider whose
purpose is missing, or takes anything other than a plain API key, is dropped: the
capability seals one `ApiKeySecret`, and a picker entry nobody can key is worse
than one that is absent.

**Voices.** OpenAI's and Gemini's are fixed sets and are listed. ElevenLabs' belong
to the account - its shared defaults expire on 2026-12-31 - so its list is empty,
which means a binding names one of its own voices by id.

**Prices are per character, dated - and per token where that is the bill.** Every
provider here bills either characters or audio tokens. Every model is listed at
its price per million characters of typical speech, which is what can be known
before the call is made and is what the budget is checked against. A model billed
by the audio it returns also lists its token rates, and each piece is booked from
the length of the audio that came back: a direction to speak slowly makes the
same text cost more, and a character price cannot see that (#2351). A price
carries the day it took effect, because Gemini's double on 2027-01-01 and a budget
that kept the old one would let a run spend twice what its cap says.
"""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import TypeAdapter

from app.core import catalog, secret_purposes
from app.core.secret_kinds import SecretKind


@dataclass(frozen=True)
class SpeechPrice:
    """What a model costs from one day on."""

    since: date
    usd_per_million_characters: Decimal
    """The estimate a call is checked against, and the bill where nothing else is."""

    usd_per_million_input_tokens: Decimal | None = None
    usd_per_million_audio_tokens: Decimal | None = None
    audio_tokens_per_second: int | None = None
    """Set together, for a model billed by text tokens in and audio tokens out."""

    def __post_init__(self) -> None:
        token_rates = (
            self.usd_per_million_input_tokens,
            self.usd_per_million_audio_tokens,
            self.audio_tokens_per_second,
        )
        if any(rate is None for rate in token_rates) and any(
            rate is not None for rate in token_rates
        ):
            raise ValueError("A token-billed price states all three token rates or none")


@dataclass(frozen=True)
class SpeechVoice:
    """One voice a provider offers to every account."""

    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class SpeechModel:
    """One model that speaks, as a picker renders it and the tool calls it."""

    id: str
    name: str
    description: str
    max_characters: int
    """The most text one request takes. Longer text is sent in parts."""

    prices: tuple[SpeechPrice, ...]
    takes_instructions: bool = False
    """Whether the model reads a direction on how to speak - tone, pace, accent."""

    voices: tuple[str, ...] = ()
    """The provider's voices this model can use, where it cannot use all of them."""


@dataclass(frozen=True)
class TextToSpeechEntry:
    """One provider's speech models, as the catalog file states them."""

    provider: str
    api: str
    base_url: str
    """Where the provider serves its endpoint, which no other table records."""

    formats: tuple[Literal["mp3", "wav"], ...]
    """Audio formats the provider returns, named by file extension. Only the two
    whose pieces join - an entry naming another is refused when the file loads."""

    models: tuple[SpeechModel, ...]
    voices: tuple[SpeechVoice, ...] = ()


CATALOG: tuple[TextToSpeechEntry, ...] = catalog.load(
    "text_to_speech_models.json", TypeAdapter(tuple[TextToSpeechEntry, ...])
)

SUPPORTED_APIS = frozenset({"openai_speech", "elevenlabs", "gemini_interactions"})
"""API shapes there is a client for. An entry naming another one is dropped."""


@dataclass(frozen=True)
class TextToSpeechProvider:
    """One provider that can speak, with what may be chosen on it."""

    provider: str
    name: str
    api: str
    base_url: str
    formats: tuple[Literal["mp3", "wav"], ...]
    models: tuple[SpeechModel, ...]
    voices: tuple[SpeechVoice, ...]

    @property
    def account_voices(self) -> bool:
        """Whether voices belong to the account, so a binding names one by id."""
        return not self.voices

    def model(self, model_id: str) -> SpeechModel | None:
        """One of this provider's models, or None where the catalog lists no such id."""
        return next((model for model in self.models if model.id == model_id), None)

    def voices_for(self, model: SpeechModel) -> tuple[SpeechVoice, ...]:
        """The voices a model can speak in, in the catalog's order."""
        if not model.voices:
            return self.voices
        return tuple(voice for voice in self.voices if voice.id in model.voices)


def providers() -> tuple[TextToSpeechProvider, ...]:
    """Every provider that can speak, with the models, voices and formats it offers.

    An entry is dropped where the vault has no purpose for its provider, where that
    purpose takes anything but a plain API key, where it lists no models or no
    formats, or where its API shape has no client. The file is data and data can
    be wrong; a picker entry that fails on the first call is worse than none.
    """
    found: list[TextToSpeechProvider] = []
    for entry in CATALOG:
        purpose = secret_purposes.get(entry.provider)
        if purpose is None or purpose.kind is not SecretKind.API_KEY:
            continue
        if not entry.models or not entry.formats or entry.api not in SUPPORTED_APIS:
            continue
        found.append(
            TextToSpeechProvider(
                provider=entry.provider,
                name=purpose.label,
                api=entry.api,
                base_url=entry.base_url,
                formats=entry.formats,
                models=entry.models,
                voices=entry.voices,
            )
        )
    return tuple(found)


def by_provider(provider: str) -> TextToSpeechProvider | None:
    """The offering for one provider id, or None where it cannot speak."""
    return next((entry for entry in providers() if entry.provider == provider), None)


def default_choice() -> tuple[str, str]:
    """The provider and model a binding starts on: the catalog's first of each.

    The first offered provider rather than a constant, so the default follows the
    file instead of repeating an id that would then have to change in two places.
    """
    first = providers()[0]
    return first.provider, first.models[0].id


CHARACTERS_PER_TEXT_TOKEN = 4
"""Roughly, for the text half of a token-billed piece. The provider reports no count,
and the text side is a fraction of the bill - at Gemini's rates a second of audio
costs what about 450 characters of text in do."""


def _price_on(model: SpeechModel, on: date) -> SpeechPrice | None:
    """The latest price whose day has come, so a scheduled change takes effect on its
    date without a release."""
    current = [price for price in model.prices if price.since <= on]
    if not current:
        return None
    return max(current, key=lambda price: price.since)


def price_per_character(model: SpeechModel, *, on: date) -> Decimal | None:
    """What one character costs on a day, or None where no price had started.

    `None` books the call as unpriced rather than free.
    """
    price = _price_on(model, on)
    return None if price is None else price.usd_per_million_characters / 1_000_000


def piece_cost(
    model: SpeechModel, *, on: date, characters: int, seconds: float | None
) -> Decimal | None:
    """What one spoken piece cost, or None where no price had started.

    From the audio that came back where the model is billed by it and its length is
    known; from the characters otherwise.
    """
    price = _price_on(model, on)
    if price is None:
        return None
    if (
        seconds is None
        or price.usd_per_million_input_tokens is None
        or price.usd_per_million_audio_tokens is None
        or price.audio_tokens_per_second is None
    ):
        return price.usd_per_million_characters * characters / 1_000_000
    text_tokens = math.ceil(characters / CHARACTERS_PER_TEXT_TOKEN)
    audio_tokens = Decimal(str(seconds)) * price.audio_tokens_per_second
    return (
        text_tokens * price.usd_per_million_input_tokens
        + audio_tokens * price.usd_per_million_audio_tokens
    ) / 1_000_000
