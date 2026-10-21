"""The realtime catalog: what voice conversations may be configured with (#54).

The catalog is data, and data can be wrong. These tests hold it to the one
source that cannot drift from what actually runs - the library's own realtime
profiles - wherever the library states a value.
"""

from decimal import Decimal

import pytest
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.xai import XaiProvider
from pydantic_ai.realtime.azure import AzureRealtimeModel
from pydantic_ai.realtime.google import GoogleRealtimeModel
from pydantic_ai.realtime.openai import OpenAIRealtimeModel
from pydantic_ai.realtime.xai import XaiRealtimeModel

from app.core.secret_kinds import SecretKind
from app.services import realtime_models

_DUMMY = "sk-not-a-key"


def _library_model(provider: str, model: str):
    if provider == "openai":
        return OpenAIRealtimeModel(model, provider=OpenAIProvider(api_key=_DUMMY))
    if provider == "azure":
        return AzureRealtimeModel(
            model,
            provider=AzureProvider(
                api_key=_DUMMY,
                azure_endpoint="https://x.openai.azure.com",
                api_version="2025-04-01-preview",
            ),
        )
    if provider == "google":
        return GoogleRealtimeModel(model, provider=GoogleProvider(api_key=_DUMMY))
    return XaiRealtimeModel(model, provider=XaiProvider(api_key=_DUMMY))


def _profile_value(profile, key: str):
    return profile[key] if isinstance(profile, dict) else getattr(profile, key)


def test_the_four_providers_are_offered_with_their_credential_kinds():
    offered = {p.provider: p for p in realtime_models.providers()}

    assert set(offered) == {"openai", "azure", "google", "xai"}
    assert offered["azure"].secret_kind is SecretKind.AZURE_OPENAI
    assert offered["azure"].deployment is True
    assert offered["openai"].secret_kind is SecretKind.API_KEY


def test_gpt_live_is_not_offered():
    ids = {m.id for p in realtime_models.providers() for m in p.models}
    assert not any(model_id.startswith("gpt-live") for model_id in ids)


def test_only_openai_answers_over_webrtc():
    for provider in realtime_models.providers():
        for model in provider.models:
            expected = "webrtc" if provider.provider == "openai" else "relay"
            assert model.transport == expected, (provider.provider, model.id)


@pytest.mark.parametrize(
    ("provider", "model"),
    [(entry.provider, m.id) for entry in realtime_models.CATALOG for m in entry.models],
)
def test_each_entry_agrees_with_the_library_profile(provider: str, model: str):
    entry = realtime_models.offered(provider, model)
    assert entry is not None
    profile = _library_model(provider, model).profile

    assert entry.input_sample_rate == _profile_value(profile, "audio_input_sample_rate")
    assert entry.output_sample_rate == _profile_value(profile, "audio_output_sample_rate")
    assert entry.supports_thinking == _profile_value(profile, "supports_thinking")
    library_window = _profile_value(profile, "context_window")
    if library_window is not None:
        assert entry.context_window == library_window
    assert entry.default_voice in entry.voices


def test_every_entry_has_a_positive_worst_case_price():
    for provider in realtime_models.providers():
        for model in provider.models:
            assert model.pricing.worst_case_usd_per_minute > Decimal(0)
            if model.pricing.kind == "per_minute":
                assert model.pricing.usd_per_minute is not None


def test_a_model_outside_the_catalog_is_not_offered():
    assert realtime_models.offered("openai", "gpt-4o") is None
    assert realtime_models.offered("anthropic", "gpt-realtime") is None


def test_a_provider_the_platform_does_not_know_or_with_only_gpt_live_is_not_offered():
    from dataclasses import replace

    openai = next(entry for entry in realtime_models.CATALOG if entry.provider == "openai")
    gpt_live = replace(openai.models[0], id="gpt-live-1")
    assert (
        realtime_models.providers_in(
            (replace(openai, provider="nobody"), replace(openai, models=(gpt_live,)))
        )
        == ()
    )


def test_the_offering_is_read_from_the_catalog_once_not_on_every_lookup():
    """Every key check, readiness read and call start looks a provider up; the catalog
    and the platform's providers are fixed for the process, so neither is re-read."""
    assert realtime_models.providers() is realtime_models.providers()
