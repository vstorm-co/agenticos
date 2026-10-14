"""Which providers can turn speech into text, and which of their models to offer.

Shaped like :mod:`app.services.image_models`, and for the same reason: an id, a
name and a sentence saying when to reach for it is *data*, so it lives in
`app/core/catalog/speech_to_text_models.json` and adding a model released this
morning is one entry with no code. No provider listing answers this question -
`/v1/models` returns chat models, and none of them state which accept audio.

**One API shape, on purpose.** Every entry declares `api: "transcriptions"`,
meaning the provider serves OpenAI's `POST /audio/transcriptions`: multipart in,
`{"text": ...}` out. OpenAI defined it, Groq and Mistral serve it, and that is
what makes three providers one client rather than three. A provider whose only
route to audio is a multimodal chat call - Google's, today - is not in the file,
because the field is what says how to call it and there is no second shape yet.
When there is, it arrives as another `api` value and another branch, not as a
special case wired into the caller.

The key works the way `image_models`' does: the pair is a pick from this
catalog and the key is a vault secret named beside it, whose purpose is the
provider. Speech to text is configured at three levels rather than on one
binding - the organization, an agent, a channel bot - and each level names its
own key next to its own pair (`speech_to_text_settings`). Model profiles are not
read: they are what a text run uses.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter

from app.agents.model_resolver import PROVIDERS
from app.core import catalog
from app.core.secret_kinds import SecretKind

RecordingFormat = Literal["webm", "wav"]
"""What a browser records a dictation in for one provider.

`webm` is whatever `MediaRecorder` makes - WebM or Ogg Opus, or MP4 on Safari.
`wav` is 16 kHz mono 16-bit PCM the page builds itself, for a provider that
documents neither WebM nor Opus.
"""

DictationUnavailable = Literal["no_provider", "not_offered", "no_key"]
"""Why a recording for an agent would not reach a provider.

`no_provider`: no level names a pair. `not_offered`: the pair named was
withdrawn from the catalog. `no_key`: no usable key is named beside the pair -
it was never chosen, was deleted, or stopped being one that level may use - so
the fix is "choose a key".
"""


@dataclass(frozen=True)
class SpeechToTextModel:
    """One model that transcribes, as a picker renders it."""

    id: str
    name: str
    description: str


@dataclass(frozen=True)
class SpeechToTextEntry:
    """One provider's transcription models, as the catalog file states them."""

    provider: str
    base_url: str
    """Where this provider serves the endpoint.

    In the file because nothing else knows it: `ProviderSpec` carries no address -
    the SDK holds those, and this does not go through the SDK. Every recording
    for this provider goes here; a self-hosted server is not reachable yet.
    """

    models: tuple[SpeechToTextModel, ...]
    api: str = "transcriptions"
    """How this provider is called. `transcriptions` is OpenAI's endpoint shape.

    A field rather than an assumption, so the day a provider is worth offering
    whose only route to audio is a chat call, the catalog can say so and the
    client can branch on it - instead of the caller growing a name check.
    """

    response_format: str | None = None
    """The `response_format` to ask for, or `None` to send none (plain JSON).

    Only for the length of the recording (#1797). Groq states a recording's
    `duration` in `verbose_json` and nowhere else, while OpenAI's `gpt-4o-*`
    models refuse that format outright - so it is the provider's entry that says,
    and a provider whose plain answer already carries the length (OpenAI's
    `usage`, Mistral's) is sent nothing it might not accept.
    """

    recording_format: RecordingFormat = "webm"
    """What a browser records a dictation in for this provider (#1797).

    In the file rather than in each client, because three clients record - the
    console's composer, the hosted page and the plain-JS widget - and a list of
    WAV-only providers kept in each was three lists to keep in step. Mistral
    documents WAV and MP3 input and never WebM or Opus, so it is `wav`.
    """


CATALOG: tuple[SpeechToTextEntry, ...] = catalog.load(
    "speech_to_text_models.json", TypeAdapter(tuple[SpeechToTextEntry, ...])
)

SUPPORTED_APIS = frozenset({"transcriptions"})
"""API shapes there is a client for. An entry naming another one is dropped."""


@dataclass(frozen=True)
class SpeechToTextProvider:
    """One provider that can transcribe, with what may be chosen on it."""

    provider: str
    name: str
    api: str
    base_url: str
    models: tuple[SpeechToTextModel, ...]
    response_format: str | None = None
    recording_format: RecordingFormat = "webm"


def providers() -> tuple[SpeechToTextProvider, ...]:
    """Every provider that can transcribe, with the models the catalog lists.

    An entry is dropped where the platform does not know the provider, where it
    lists no models, where its API shape has no client, or where its credential is
    not a plain API key - the transcription client sends one `Authorization:
    Bearer`, so a provider wanting a service account or an AWS pair would fail on
    its first call. The file is data and data can be wrong; a picker entry that
    fails when somebody sends a voice note is worse than one that is absent.
    """
    found: list[SpeechToTextProvider] = []
    for entry in CATALOG:
        spec = PROVIDERS.get(entry.provider)
        if spec is None or not entry.models or entry.api not in SUPPORTED_APIS:
            continue
        if spec.secret_kind is not SecretKind.API_KEY:
            continue
        found.append(
            SpeechToTextProvider(
                provider=spec.id,
                name=spec.name,
                api=entry.api,
                base_url=entry.base_url,
                models=entry.models,
                response_format=entry.response_format,
                recording_format=entry.recording_format,
            )
        )
    return tuple(found)


def by_provider(provider: str) -> SpeechToTextProvider | None:
    """The offering for one provider id, or None where it cannot transcribe."""
    return next((entry for entry in providers() if entry.provider == provider), None)


def recording_format(provider: str | None) -> RecordingFormat:
    """The format a browser records a dictation in for `provider`.

    `webm` where no provider resolves or the catalog no longer offers it: the
    recording is then refused as `not_configured` whatever its format, so the
    answer only has to be one a browser can make.
    """
    entry = by_provider(provider) if provider is not None else None
    return entry.recording_format if entry is not None else "webm"


def is_offered(provider: str, model: str) -> bool:
    """Whether this provider can transcribe and the catalog lists this model.

    Both halves, so a value outside the catalog is refused at the form rather than
    when somebody sends a voice note - which is the wrong moment to learn about a
    typo, because the person who made it is not the person waiting.
    """
    entry = by_provider(provider)
    return entry is not None and any(candidate.id == model for candidate in entry.models)


def default_choice() -> tuple[str, str] | None:
    """The provider and model a bot starts on, or None if nothing is offered.

    The first model of the first capable provider, so the default follows the
    catalog rather than repeating an id that would then have to change twice.
    `None` is possible and is not an error: a build whose providers all want
    service accounts offers no transcription, and a caller has to say so rather
    than pick something that cannot run.
    """
    offered = providers()
    if not offered:
        return None
    return offered[0].provider, offered[0].models[0].id


LANGUAGES: tuple[str, ...] = (
    "af",
    "ar",
    "hy",
    "az",
    "be",
    "bs",
    "bg",
    "ca",
    "zh",
    "hr",
    "cs",
    "da",
    "nl",
    "en",
    "et",
    "fi",
    "fr",
    "gl",
    "de",
    "el",
    "he",
    "hi",
    "hu",
    "is",
    "id",
    "it",
    "ja",
    "kn",
    "kk",
    "ko",
    "lv",
    "lt",
    "mk",
    "ms",
    "mr",
    "mi",
    "ne",
    "no",
    "fa",
    "pl",
    "pt",
    "ro",
    "ru",
    "sr",
    "sk",
    "sl",
    "es",
    "sw",
    "sv",
    "tl",
    "ta",
    "th",
    "tr",
    "uk",
    "ur",
    "vi",
    "cy",
)
"""The languages a recording may be pinned to, as ISO-639-1 codes.

Whisper's supported list, in the order of the languages' English names, which
every catalogued provider accepts as the `language` form field. A code outside it
is refused at the organization's PATCH rather than sent to a provider that
answers with its own error text.
"""


def dictation_ready(
    *, engine: str, provider: str | None, model: str | None, secret_id: UUID | None
) -> bool:
    """Whether `/chat` dictation would reach a server engine, from settings alone.

    "Configured", not "working": it reads the organization's columns and this
    catalog and never opens the vault, because it is computed for every
    organization in a member's list. The key counts as named while its column
    holds one - a deleted key sets it null - and a key that went private since
    is caught when a recording arrives, as `not_configured`.
    """
    return (
        engine == "server"
        and provider is not None
        and model is not None
        and secret_id is not None
        and is_offered(provider, model)
    )
