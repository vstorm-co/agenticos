"""Which providers can draw, and which of their models the platform offers.

Two halves from two places, and both are asserted here: whether a provider *can*
is derived from the SDK, and which models it offers is
`app/core/catalog/image_models.json`. A catalog entry the SDK cannot drive is
dropped rather than trusted, which is the guard against the file growing an entry
that would fail on its first call.
"""

import pytest
from pydantic_ai.native_tools import ImageGenerationTool

from app.agents.capabilities.image_generation import ImageGenerationConfig
from app.agents.model_resolver import PROVIDERS
from app.services import image_models as service
from app.services.image_models import (
    CATALOG,
    ImageModel,
    ImageProviderEntry,
    by_provider,
    default_choice,
    draws_images,
    image_providers,
    is_offered,
    resolved_model_id,
    tool_model,
)


def test_the_providers_the_sdk_supports_are_found():
    # The probe's whole point: `supported_native_tools()` is asked rather than a
    # list kept by hand. A probe that silently starts failing would leave the
    # picker empty, and this is what says so.
    assert {entry.provider for entry in image_providers()} == {"openai", "google", "google_cloud"}


def test_openai_is_probed_as_responses_rather_than_as_chat():
    # Our OpenAI provider is built as `openai-chat` so OpenAI-compatible servers
    # work, and `OpenAIChatModel` does not honour the image tool - so the catalog
    # names the Responses prefix, and probing the chat one would drop OpenAI.
    assert PROVIDERS["openai"].prefix == "openai-chat"
    assert draws_images("openai-responses") is True
    assert draws_images("openai-chat") is False


@pytest.mark.parametrize("provider", ["anthropic", "together", "groq", "xai", "openrouter"])
def test_a_provider_whose_class_lacks_the_tool_cannot_draw(provider: str):
    # Real providers with real image models, every one of which would fail on its
    # first call: the tool is honoured by two model classes.
    assert draws_images(PROVIDERS[provider].prefix) is False


def test_a_provider_the_sdk_cannot_route_cannot_draw():
    assert draws_images("no-such-provider") is False


def test_the_probe_asks_the_class_rather_than_a_name():
    from pydantic_ai.models.google import GoogleModel

    assert ImageGenerationTool in GoogleModel.supported_native_tools()


def test_a_catalog_entry_the_sdk_cannot_drive_is_dropped(monkeypatch):
    # The file is data, and data can be wrong. Together ships image models and
    # `OpenAIChatModel` will not draw with them.
    monkeypatch.setattr(
        service,
        "CATALOG",
        (
            *CATALOG,
            ImageProviderEntry(
                provider="together",
                prefix="together",
                models=(ImageModel(id="flux", name="FLUX", description="Real, and undrawable."),),
            ),
        ),
    )

    assert "together" not in {entry.provider for entry in image_providers()}


def test_an_entry_for_a_provider_this_platform_does_not_offer_is_dropped(monkeypatch):
    monkeypatch.setattr(
        service,
        "CATALOG",
        (
            ImageProviderEntry(
                provider="not-a-provider",
                prefix="google",
                models=(ImageModel(id="x", name="X", description="."),),
            ),
        ),
    )

    assert image_providers() == ()


def test_an_entry_with_no_models_is_dropped(monkeypatch):
    # An empty picker for a provider that certainly draws is worse than no entry.
    monkeypatch.setattr(
        service, "CATALOG", (ImageProviderEntry(provider="google", prefix="google", models=()),)
    )

    assert image_providers() == ()


def test_every_catalog_model_says_what_it_is_for():
    # The description is why the file exists rather than an enum in a schema: a
    # dropdown of four ids is a decision made by guessing.
    for entry in CATALOG:
        for model in entry.models:
            assert model.name != ""
            assert model.description.endswith(".")


def test_openai_names_the_model_that_calls_the_tool():
    # OpenAI separates the two: the chosen model draws, and some Responses model
    # has to invoke it. That decision is data in the catalog, not a constant.
    openai = by_provider("openai")

    assert openai is not None
    assert openai.caller != ""


def test_google_has_no_caller_because_its_model_is_the_image_model():
    google = by_provider("google")

    assert google is not None
    assert google.caller == ""


def test_the_default_follows_the_catalog_rather_than_repeating_an_id():
    provider, model = default_choice()

    assert is_offered(provider, model)


@pytest.mark.parametrize(
    ("provider", "model", "offered"),
    [
        ("openai", "gpt-image-2", True),
        ("google", "gemini-3-pro-image", True),
        ("google_cloud", "gemini-3-pro-image", True),
        ("openai", "gemini-3-pro-image", False),
        ("together", "flux", False),
        ("openai", "dall-e-3", False),
        ("", "", False),
    ],
)
def test_a_pair_is_offered_only_when_both_halves_are(provider: str, model: str, offered: bool):
    assert is_offered(provider, model) is offered


def test_openai_resolves_to_the_caller_and_draws_with_the_choice():
    # The id the SDK is asked for names the Responses model; the choice travels as
    # the tool's own `model`.
    assert resolved_model_id("openai", "gpt-image-2") == "openai-responses:gpt-5.4"
    assert tool_model("openai", "gpt-image-2") == "gpt-image-2"


def test_google_resolves_to_the_chosen_model_and_passes_no_tool_model():
    # Google reads the model it was built with, so a tool-level model there would
    # be a setting with no effect.
    assert resolved_model_id("google", "gemini-3-pro-image") == "google:gemini-3-pro-image"
    assert tool_model("google", "gemini-3-pro-image") is None


def test_vertex_resolves_through_its_own_prefix():
    assert resolved_model_id("google_cloud", "gemini-3-pro-image") == (
        "google-cloud:gemini-3-pro-image"
    )


def test_a_provider_with_no_entry_resolves_verbatim():
    # Nothing reaches this through the config, which validates first - it is what
    # keeps the function total rather than raising inside a run.
    assert resolved_model_id("together", "flux") == "together:flux"
    assert tool_model("together", "flux") is None


def test_the_capability_defaults_to_something_offered():
    config = ImageGenerationConfig()

    assert is_offered(config.provider, config.model)


def test_the_capability_refuses_a_provider_that_cannot_draw():
    with pytest.raises(ValueError, match="cannot generate images"):
        ImageGenerationConfig(provider="together", model="flux-1.1-pro")


def test_the_capability_refuses_a_model_its_provider_does_not_have():
    with pytest.raises(ValueError, match="cannot generate images"):
        ImageGenerationConfig(provider="openai", model="gemini-3-pro-image")


def test_the_capability_hands_the_tool_the_drawing_model():
    config = ImageGenerationConfig(provider="openai", model="gpt-image-1-mini")

    assert config.to_tool_kwargs()["model"] == "gpt-image-1-mini"


def test_the_capability_hands_google_no_tool_model():
    config = ImageGenerationConfig(provider="google", model="gemini-3-pro-image")

    assert "model" not in config.to_tool_kwargs()
