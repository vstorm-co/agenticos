"""Which models an agent can run on, and which are for something else (#2487)."""

import time
import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.model_profile import ModelProfileList, ModelProfileRead
from app.services import model_catalog
from app.services.model_catalog import CatalogModel
from app.services.model_outputs import ModelOutputs, model_outputs


@pytest.fixture(autouse=True)
def _empty_cache():
    model_catalog._cache.clear()
    yield
    model_catalog._cache.clear()


def _listed(provider: str, *models: CatalogModel) -> None:
    """A live listing as `models_for` would have cached it."""
    model_catalog._cache[provider] = model_catalog._Entry(
        models=models, fetched_at=time.monotonic()
    )


@pytest.mark.parametrize(
    ("provider", "model", "modalities", "kind"),
    [
        ("openai", "gpt-4o-mini-tts", ("audio",), "a text-to-speech model"),
        ("openai", "gpt-image-1", ("image",), "an image model"),
        ("openai", "text-embedding-3-small", ("embedding",), "an embedding model"),
        ("openai", "whisper-1", ("text",), "a transcription model"),
        ("google", "gemini-omni-1.1-flash", ("video",), "a video model"),
        # OpenRouter's namespaced id is the upstream model under another name.
        ("openrouter", "openai/gpt-4o-mini-tts", ("audio",), "a text-to-speech model"),
    ],
)
def test_a_model_a_catalog_lists_for_something_else_is_not_a_chat_model(
    provider: str, model: str, modalities: tuple[str, ...], kind: str
):
    assert model_outputs(provider, model) == ModelOutputs(
        modalities=modalities, chat=False, kind=kind
    )


def test_a_google_image_model_is_left_alone_because_it_also_answers_in_text():
    # The chosen model there is the one the capability talks to.
    assert model_outputs("google", "gemini-2.5-flash-image").chat


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("openai", "gpt-4.1"),
        ("ollama", "llama3.3:70b"),
        ("openai", "my-fine-tune"),
        ("openrouter", "nobody/knows-this"),
        ("openrouter", "unnamespaced"),
    ],
)
def test_a_model_nothing_says_anything_about_is_allowed(provider: str, model: str):
    # Unknown is not a refusal: a custom endpoint or a model shipped this morning
    # must never disappear from a picker because the platform cannot see it.
    assert model_outputs(provider, model) == ModelOutputs(modalities=(), chat=True)


def test_a_cached_listing_that_states_text_is_a_chat_model():
    _listed(
        "openrouter",
        CatalogModel(id="acme/painter", name="Painter", output_modalities=("image", "text")),
    )

    assert model_outputs("openrouter", "acme/painter") == ModelOutputs(
        modalities=("image", "text"), chat=True
    )


def test_a_cached_listing_that_states_no_text_is_not_a_chat_model():
    _listed(
        "openrouter",
        CatalogModel(id="acme/painter", name="Painter", output_modalities=("image",)),
    )

    outputs = model_outputs("openrouter", "acme/painter")

    assert outputs == ModelOutputs(
        modalities=("image",), chat=False, kind="a model that emits only image"
    )


def test_a_listed_model_that_states_nothing_is_unknown():
    _listed("openrouter", CatalogModel(id="acme/quiet", name="Quiet"))

    assert model_outputs("openrouter", "acme/quiet").chat


def test_the_cached_listing_is_read_however_old_and_never_fetched():
    # What a model emits does not change when the hour is up.
    model_catalog._cache["openrouter"] = model_catalog._Entry(
        models=(CatalogModel(id="a/b", name="b"),), fetched_at=0.0
    )

    assert model_catalog.cached_listing("openrouter") == (CatalogModel(id="a/b", name="b"),)
    assert model_catalog.cached_listing("anthropic") == ()


def _read(model: str) -> ModelProfileRead:
    now = datetime.now(UTC)
    return ModelProfileRead(
        id=uuid.uuid4(),
        label=model,
        provider="openai",
        model=model,
        created_at=now,
        updated_at=now,
    )


def test_a_profile_says_whether_an_agent_can_run_on_it():
    # Listed either way - text to speech runs on the speech profile - and marked,
    # so agent and chat pickers can leave it out without another call.
    body = ModelProfileList(items=[_read("gpt-4.1"), _read("gpt-4o-mini-tts")], total=2).model_dump(
        mode="json"
    )

    chat, speech = body["items"]
    assert (chat["chat_capable"], chat["output_modalities"]) == (True, [])
    assert (speech["chat_capable"], speech["output_modalities"]) == (False, ["audio"])
