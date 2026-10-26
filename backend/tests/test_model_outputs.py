"""Which models an agent can run on, and which are for something else (#2487)."""

import time
import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.model_profile import ModelProfileList, ModelProfileRead
from app.services import model_catalog
from app.services.model_catalog import CatalogModel
from app.services.model_outputs import ModelOutputs, listed_model_outputs, model_outputs


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

    assert listed_model_outputs("openrouter", "acme/painter") == ModelOutputs(
        modalities=("image", "text"), chat=True
    )


def test_a_cached_listing_that_states_no_text_is_not_a_chat_model():
    _listed(
        "openrouter",
        CatalogModel(id="acme/painter", name="Painter", output_modalities=("image",)),
    )

    outputs = listed_model_outputs("openrouter", "acme/painter")

    assert outputs == ModelOutputs(
        modalities=("image",), chat=False, kind="a model that emits only image"
    )


def test_a_refusal_never_rests_on_a_listing_this_process_happens_to_hold():
    # The cache is per process: publish on another replica, or after a restart,
    # must give the same answer, so only the catalogs decide it.
    _listed(
        "openrouter",
        CatalogModel(id="acme/painter", name="Painter", output_modalities=("image",)),
    )

    assert model_outputs("openrouter", "acme/painter") == ModelOutputs(modalities=(), chat=True)


def test_a_catalog_answer_wins_over_what_a_listing_states():
    _listed(
        "openrouter",
        CatalogModel(id="openai/gpt-4o-mini-tts", name="TTS", output_modalities=("text",)),
    )

    assert not listed_model_outputs("openrouter", "openai/gpt-4o-mini-tts").chat


def test_a_transcription_model_that_also_chats_is_a_chat_model():
    # An alias not confirmed transcription-only: an earlier Voxtral it named chatted.
    assert model_outputs("mistral", "voxtral-mini-latest").chat


def test_no_model_the_catalogs_refuse_is_one_they_also_offer_for_chat():
    # Through model_outputs, so an OpenRouter id that routes to a refused
    # upstream model counts too.
    refused = [
        (provider, model.id)
        for provider in model_catalog.CURATED
        for model in model_catalog.curated_models(provider)
        if not model_outputs(provider, model.id).chat
    ]

    assert refused == []


def test_a_listed_model_that_states_nothing_is_unknown():
    _listed("openrouter", CatalogModel(id="acme/quiet", name="Quiet"))

    assert listed_model_outputs("openrouter", "acme/quiet").chat


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
    # Listed either way, so it can still be removed, and marked, so agent and
    # chat pickers can leave it out without another call.
    body = ModelProfileList(items=[_read("gpt-4.1"), _read("gpt-4o-mini-tts")], total=2).model_dump(
        mode="json"
    )

    chat, speech = body["items"]
    assert (chat["chat_capable"], chat["output_modalities"]) == (True, [])
    assert (speech["chat_capable"], speech["output_modalities"]) == (False, ["audio"])
