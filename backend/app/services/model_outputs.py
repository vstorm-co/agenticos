"""What a model emits, and whether an agent can run on it (#2487).

A model profile names any model a provider serves, and some of those cannot hold
a conversation: `gpt-4o-mini-tts` speaks, `gpt-image-1` draws,
`text-embedding-3-small` answers with vectors, `whisper-1` transcribes. An agent
on one fails on its first turn.

Two sources say which is which, and neither is asked over the network here:

**The catalog files.** The realtime voice, text-to-speech, transcription, video and embedding
catalogs, and the image catalog's entries whose model is drawn *with* rather than
talked to (OpenAI's, where a separate `caller` invokes the tool). A model listed
there is known to be one of those and nothing else. They are the same in every
process, so they alone decide a refusal: :func:`model_outputs`.

**A provider listing already cached.** OpenRouter and the Hugging Face router
state `output_modalities` per model; when :mod:`app.services.model_catalog` has
fetched one, a model it lists without `text` is not a chat model. That cache is
per process and empties on a restart, so it only marks what a picker offers -
:func:`listed_model_outputs` - and never refuses a publish.

Everything else is unknown, and unknown is allowed. A custom endpoint, an Ollama
on this network, a model shipped this morning: the platform cannot see what they
emit, and a picker that refused what it could not classify would hide models
that work - the same rule `CatalogModel.output_modalities` states. A profile with
a `base_url` is a custom endpoint whatever its provider says: the catalogs
describe the vendor's own API, and an OpenAI-compatible server may serve a chat
model under an id the vendor uses for speech, so every answer here is unknown
for one.
"""

from dataclasses import dataclass
from functools import cache

from app.services import (
    image_models,
    realtime_models,
    speech_to_text,
    text_to_speech_models,
    video_models,
)
from app.services.model_catalog import cached_listing
from app.services.rag import embedding_providers


@dataclass(frozen=True, slots=True)
class ModelOutputs:
    """What one model emits, as far as the platform knows."""

    modalities: tuple[str, ...]
    """What it emits - `("text",)`, `("audio",)`. Empty means not known."""

    chat: bool
    """Whether an agent can run on it. True for every model not known otherwise."""

    kind: str | None = None
    """What it is instead, for a refusal to name: `"a text-to-speech model"`."""


_UNKNOWN = ModelOutputs(modalities=(), chat=True)


@cache
def _from_catalogs() -> dict[tuple[str, str], ModelOutputs]:
    """Every catalog-listed model that is not a chat model, by provider and id.

    Built once: the files are read at import and fixed until a redeploy.
    Google's image models are left out deliberately - the chosen model there
    *is* the one the capability talks to, and it answers in text as well.
    """
    known: dict[tuple[str, str], ModelOutputs] = {}

    def record(provider: str, model: str, outputs: ModelOutputs) -> None:
        known.setdefault((provider, model), outputs)

    speech = ModelOutputs(modalities=("audio",), chat=False, kind="a text-to-speech model")
    for entry in text_to_speech_models.CATALOG:
        for model in entry.models:
            record(entry.provider, model.id, speech)

    drawing = ModelOutputs(modalities=("image",), chat=False, kind="an image model")
    for entry in image_models.CATALOG:
        if entry.caller:
            for model in entry.models:
                record(entry.provider, model.id, drawing)

    realtime = ModelOutputs(modalities=("text", "audio"), chat=False, kind="a realtime voice model")
    for entry in realtime_models.CATALOG:
        # Azure's model value is a deployment name, not this base-model id.
        if entry.deployment:
            continue
        for model in entry.models:
            record(entry.provider, model.id, realtime)

    video = ModelOutputs(modalities=("video",), chat=False, kind="a video model")
    for entry in video_models.CATALOG:
        for model in entry.models:
            record(entry.provider, model.id, video)

    # It does emit text - a transcript - but only of a recording it is sent, and
    # through an endpoint that takes no conversation.
    transcription = ModelOutputs(modalities=("text",), chat=False, kind="a transcription model")
    for entry in speech_to_text.CATALOG:
        for model in entry.models:
            if not model.chat:
                record(entry.provider, model.id, transcription)

    vectors = ModelOutputs(modalities=("embedding",), chat=False, kind="an embedding model")
    for entry in embedding_providers.CATALOG:
        for model in entry.models:
            record(entry.provider, model.model, vectors)

    return known


def model_outputs(provider: str, model: str, *, base_url: str | None = None) -> ModelOutputs:
    """What the catalogs say this model emits, and whether an agent can run on it.

    The answer publish, rollback and the runner act on: the same on every
    replica. An OpenRouter id is `<provider>/<model>`, so it is also looked up as
    the upstream model it routes to: `openai/gpt-4o-mini-tts` is the same speech
    model under another name. With a `base_url` - a custom endpoint - the
    answer is unknown: the catalogs describe the vendor's API, not that server.
    """
    if base_url:
        return _UNKNOWN
    # These transports share the vendor's model ids; pricing's other aliases
    # (for example Bedrock) do not imply an identical model namespace.
    provider = {"openai_codex": "openai", "google_cloud": "google"}.get(provider, provider)
    known = _from_catalogs()
    found = known.get((provider, model))
    if found is None and provider == "openrouter" and "/" in model:
        upstream, _, bare = model.partition("/")
        found = known.get((upstream, bare))
    return _UNKNOWN if found is None else found


def stated_outputs(provider: str, model: str, modalities: tuple[str, ...]) -> ModelOutputs:
    """The catalogs' answer, or else what a provider listing states the model emits."""
    found = model_outputs(provider, model)
    if not found.chat or not modalities:
        return found
    if "text" in modalities:
        return ModelOutputs(modalities=modalities, chat=True)
    return ModelOutputs(
        modalities=modalities,
        chat=False,
        kind=f"a model that emits only {', '.join(modalities)}",
    )


def listed_model_outputs(provider: str, model: str, *, base_url: str | None = None) -> ModelOutputs:
    """:func:`model_outputs`, completed from this process's cached listing.

    For what a picker offers only: another replica, or this one after a restart,
    may not hold the listing and answers unknown. A custom endpoint is unknown
    here too - the listing is the vendor's, not that server's.
    """
    if base_url:
        return _UNKNOWN
    listed = next((entry for entry in cached_listing(provider) if entry.id == model), None)
    return stated_outputs(provider, model, () if listed is None else listed.output_modalities)


def not_chat_refusal(label: str, model: str, outputs: ModelOutputs) -> str:
    """The sentence a refusal of a non-chat model says, wherever it is refused."""
    return (
        f"Model '{label}' ({model}) is {outputs.kind}, not a chat model - an agent "
        "cannot run on it. Pick a chat model"
    )
