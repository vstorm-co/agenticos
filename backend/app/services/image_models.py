"""Which providers can draw an image, and which of their models to offer.

Two halves, deliberately from two places.

**Which providers can draw** is derived from the SDK, never listed:
`Model.supported_native_tools()` is a classmethod on every model class Pydantic AI
ships, so this asks rather than remembers - and an upgrade that teaches, say,
`XaiModel` the tool shows up in the console without anybody editing a list. Three
answer today: OpenAI (through the Responses API), Google, and Google through
Vertex.

**Which models** is data, in `app/core/catalog/image_models.json`, because that is
what it is: an id, a name and a sentence saying when to reach for it. No provider
listing answers this question - `/v1/models` returns chat models, and only
OpenRouter and the Hugging Face router state modalities at all - so a catalog file
beats both a hand-written enum in a schema and a substring match on a model name.
Adding a model released this morning is one entry, no code.

The two are combined rather than trusted separately: a provider in the file that
the SDK cannot drive is dropped. That is the guard against the file growing an
entry that would fail on its first call.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from pydantic import TypeAdapter
from pydantic_ai.models import infer_model
from pydantic_ai.native_tools import ImageGenerationTool

from app.agents.model_resolver import PROVIDERS
from app.core import catalog


@dataclass(frozen=True)
class ImageModel:
    """One model that draws, as a picker renders it."""

    id: str
    name: str
    description: str


@dataclass(frozen=True)
class ImageProviderEntry:
    """One provider\'s image models, as the catalog file states them."""

    provider: str
    # The prefix `infer_model` needs, which is not always the provider id: OpenAI\'s
    # image tool is a Responses feature, and Vertex is `google-cloud`.
    prefix: str
    models: tuple[ImageModel, ...]
    # The model that *calls* the tool, where the provider separates the two. OpenAI
    # does - the chosen image model is what the tool draws with, and some Responses
    # model has to invoke it - so that decision is data here rather than a constant
    # buried in the capability. Empty for Google, where the chosen model is itself
    # the image model.
    caller: str = ""


CATALOG: tuple[ImageProviderEntry, ...] = catalog.load(
    "image_models.json", TypeAdapter(tuple[ImageProviderEntry, ...])
)


@dataclass(frozen=True)
class ImageProvider:
    """One provider that can draw, with what may be chosen on it."""

    provider: str
    name: str
    prefix: str
    caller: str
    models: tuple[ImageModel, ...]


class _StubProvider:
    """Enough of a `Provider` to construct a model class, and nothing more.

    `infer_model` is the only public route from a prefix to a model class, and it
    constructs one - which normally needs a credential. The constructors read a
    client and a profile and store them, so a stub gets the class out without a
    key, and the class is all this asks a question of.
    """

    name = "probe"
    base_url = "https://example.invalid"
    client = SimpleNamespace(chat=SimpleNamespace(completions=None), responses=None, models=None)

    def model_profile(self, _name: str) -> None:
        return None


def draws_images(prefix: str) -> bool:
    """Whether the model class behind this prefix honours `ImageGenerationTool`.

    A prefix the SDK cannot route, or a constructor that wants more than the stub
    offers, answers `False`: an unknown provider is not one to offer for drawing,
    and a probe that raises is not evidence of support. `test_image_models.py` pins
    the ones that must stay true, so a probe that starts failing everywhere is loud
    rather than a product that quietly offers nothing.
    """
    try:
        model = infer_model(f"{prefix}:probe", provider_factory=lambda _name: _StubProvider())  # ty: ignore[invalid-argument-type]
    except Exception:
        return False
    return ImageGenerationTool in type(model).supported_native_tools()


def image_providers() -> tuple[ImageProvider, ...]:
    """Every provider that can draw, with the models the catalog lists for it.

    A catalog entry whose provider the platform does not offer, or whose model
    class cannot honour the tool, is dropped - the file is data and data can be
    wrong, and a picker entry that fails on its first call is worse than one that
    is not there.
    """
    providers: list[ImageProvider] = []
    for entry in CATALOG:
        spec = PROVIDERS.get(entry.provider)
        if spec is None or not entry.models or not draws_images(entry.prefix):
            continue
        providers.append(
            ImageProvider(
                provider=spec.id,
                name=spec.name,
                prefix=entry.prefix,
                caller=entry.caller,
                models=entry.models,
            )
        )
    return tuple(providers)


def by_provider(provider: str) -> ImageProvider | None:
    """The offering for one provider id, or None where it cannot draw."""
    return next((entry for entry in image_providers() if entry.provider == provider), None)


def default_choice() -> tuple[str, str]:
    """The provider and model a binding starts on.

    The first entry of the first capable provider, so the default follows the
    catalog rather than repeating an id that would have to change in two places
    when the file moves on.
    """
    first = image_providers()[0]
    return first.provider, first.models[0].id


def is_offered(provider: str, model: str) -> bool:
    """Whether this provider can draw and the catalog lists this model.

    Both halves, unlike the chat model field, which stays free text: the image tool
    refuses a model that cannot draw with an error its author only sees mid-run, so
    a value outside the catalog is refused at the form instead.
    """
    entry = by_provider(provider)
    return entry is not None and any(candidate.id == model for candidate in entry.models)


def resolved_model_id(provider: str, model: str) -> str:
    """The `provider:model` string the SDK is asked for.

    Two shapes, because the providers differ. Google\'s chosen model *is* the image
    model, so it goes in the id. OpenAI\'s tool is called by a Responses model and
    draws with the chosen one, so the id names the caller from the catalog and the
    choice travels as the tool\'s own `model`.
    """
    entry = by_provider(provider)
    if entry is None:
        return f"{provider}:{model}"
    return f"{entry.prefix}:{entry.caller or model}"


def tool_model(provider: str, model: str) -> str | None:
    """What the tool itself draws with, or None where the model id already says.

    `ImageGenerationTool.model` is honoured by OpenAI Responses; Google reads the
    model it was built with, so passing one there would be a setting with no
    effect.
    """
    entry = by_provider(provider)
    return model if entry is not None and entry.caller != "" else None
