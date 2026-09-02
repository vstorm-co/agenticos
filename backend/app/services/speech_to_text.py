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

The difference from `image_models` is where the credential comes from. Drawing is
a capability on an agent, so it seals its own key into the spec. Transcribing is
something a *channel bot* does to a voice note before there is an agent involved,
so it runs on the credential the organization already configured for that provider
in its model profiles - which is the store the vault and the profile list already
join. Nothing new to configure, and no second place a key can be wrong.
"""

from dataclasses import dataclass

from pydantic import TypeAdapter

from app.agents.model_resolver import PROVIDERS
from app.core import catalog
from app.core.secret_kinds import SecretKind


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
    the SDK holds those, and this does not go through the SDK - and a `base_url`
    on the organization's model profile overrides it, which is how a proxy or a
    self-hosted server is reached.
    """

    models: tuple[SpeechToTextModel, ...]
    api: str = "transcriptions"
    """How this provider is called. `transcriptions` is OpenAI's endpoint shape.

    A field rather than an assumption, so the day a provider is worth offering
    whose only route to audio is a chat call, the catalog can say so and the
    client can branch on it - instead of the caller growing a name check.
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
            )
        )
    return tuple(found)


def by_provider(provider: str) -> SpeechToTextProvider | None:
    """The offering for one provider id, or None where it cannot transcribe."""
    return next((entry for entry in providers() if entry.provider == provider), None)


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
