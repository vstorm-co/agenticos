"""Turning a resolved Voice section and an unsealed key into a realtime model (#54).

Offline: constructing a model opens no connection. Gemini, xAI and Azure are not
verified live; these tests pin only what is handed to the library.
"""

import pytest
from pydantic import SecretStr
from pydantic_ai.realtime.azure import AzureRealtimeModel
from pydantic_ai.realtime.google import GoogleRealtimeModel
from pydantic_ai.realtime.openai import OpenAIRealtimeModel
from pydantic_ai.realtime.xai import XaiRealtimeModel

from app.agents.realtime import build_realtime_model, realtime_settings
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, AzureOpenAISecret

_KEY = ApiKeySecret(api_key=SecretStr("sk-dummy"))


@pytest.mark.parametrize(
    ("provider", "model", "cls"),
    [
        ("openai", "gpt-realtime", OpenAIRealtimeModel),
        ("google", "gemini-2.5-flash-native-audio-latest", GoogleRealtimeModel),
        ("xai", "grok-voice-latest", XaiRealtimeModel),
    ],
)
def test_each_api_key_provider_builds_its_realtime_model(provider, model, cls):
    built = build_realtime_model(provider=provider, model=model, secret=_KEY, settings={})
    assert isinstance(built, cls)


def test_azure_builds_from_the_azure_secret_with_the_deployment_name():
    secret = AzureOpenAISecret(
        api_key=SecretStr("azure-key-1234"),
        azure_endpoint="https://x.openai.azure.com",
        api_version="2025-04-01-preview",
    )
    built = build_realtime_model(provider="azure", model="rt-prod", secret=secret, settings={})
    assert isinstance(built, AzureRealtimeModel) and built.model_name == "rt-prod"


def test_a_key_of_the_wrong_shape_is_refused():
    with pytest.raises(BadRequestError):
        build_realtime_model(provider="azure", model="rt-prod", secret=_KEY, settings={})


def test_openai_gets_its_voice_and_semantic_turn_detection():
    settings = realtime_settings(
        provider="openai", voice="cedar", language=None, thinking=None, supports_thinking=False
    )
    assert settings["openai_voice"] == "cedar"
    assert settings["openai_turn_detection"]["type"] == "semantic_vad"
    assert "thinking" not in settings


def test_thinking_is_sent_only_where_the_model_supports_it():
    assert (
        realtime_settings(
            provider="openai", voice="marin", language=None, thinking="high", supports_thinking=True
        )["thinking"]
        == "high"
    )
    assert "thinking" not in realtime_settings(
        provider="openai", voice="marin", language=None, thinking="high", supports_thinking=False
    )


def test_gemini_gets_voice_language_and_a_reconnect_policy_for_its_ten_minute_connections():
    settings = realtime_settings(
        provider="google", voice="Kore", language="pl", thinking=None, supports_thinking=True
    )
    assert settings["google_voice"] == "Kore" and settings["google_language_code"] == "pl"
    assert settings["reconnect"] is not None


def test_xai_gets_its_voice():
    assert (
        realtime_settings(
            provider="xai", voice="Ara", language=None, thinking=None, supports_thinking=True
        )["xai_voice"]
        == "Ara"
    )


def test_a_provider_that_holds_no_calls_is_refused():
    with pytest.raises(BadRequestError):
        build_realtime_model(provider="anthropic", model="claude", secret=_KEY, settings={})


def test_an_api_key_provider_refuses_an_azure_key():
    secret = AzureOpenAISecret(
        api_key=SecretStr("azure-key-1234"),
        azure_endpoint="https://x.openai.azure.com",
        api_version="2025-04-01-preview",
    )
    with pytest.raises(BadRequestError):
        build_realtime_model(provider="openai", model="gpt-realtime", secret=secret, settings={})


def test_gemini_without_a_pinned_language_follows_the_caller():
    settings = realtime_settings(
        provider="google", voice="Kore", language=None, thinking=None, supports_thinking=True
    )
    assert "google_language_code" not in settings


def test_a_provider_with_no_voice_settings_gets_only_the_shared_ones():
    assert realtime_settings(
        provider="other", voice="x", language=None, thinking="low", supports_thinking=True
    ) == {"thinking": "low"}
