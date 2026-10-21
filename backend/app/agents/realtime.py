"""A realtime model for one call, from a catalog pick and an unsealed key (#54).

The key is the one the agent's Voice section names; nothing here looks one up.
Azure takes the deployment name as its model and its endpoint and API version
from the `azure_openai` secret. Gemini, xAI and Azure are not verified live.
"""

from typing import Literal

from pydantic_ai.realtime import RealtimeModel, RealtimeModelSettings, ReconnectPolicy
from pydantic_ai.realtime.google import GoogleRealtimeModelSettings
from pydantic_ai.realtime.openai import OpenAIRealtimeModelSettings, SemanticVAD
from pydantic_ai.realtime.xai import XaiRealtimeModelSettings
from pydantic_ai.settings import ThinkingEffort

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, AzureOpenAISecret, StorableSecret

_TURNS: SemanticVAD = {
    "type": "semantic_vad",
    "eagerness": "auto",
    "create_response": True,
    "interrupt_response": True,
}
"""Hands-free by default (Q9). Push-to-talk mutes the browser's track instead, so
the same detection serves both: a muted track is silence."""


def build_realtime_model(
    *, provider: str, model: str, secret: StorableSecret, settings: RealtimeModelSettings
) -> RealtimeModel:
    """The provider's realtime model, authenticated with `secret`.

    Constructing one opens no connection; the session does.

    Raises:
        BadRequestError: If the provider holds no voice conversations, or the key
            is not the shape that provider takes - which publish validation
            already refuses, so reaching it means a key changed kind since.
    """
    if provider == "azure":
        if not isinstance(secret, AzureOpenAISecret):
            raise BadRequestError(
                message="Azure voice needs an Azure OpenAI key", details={"provider": provider}
            )
        from pydantic_ai.providers.azure import AzureProvider
        from pydantic_ai.realtime.azure import AzureRealtimeModel

        return AzureRealtimeModel(
            model,
            provider=AzureProvider(
                api_key=secret.api_key.get_secret_value(),
                azure_endpoint=secret.azure_endpoint,
                api_version=secret.api_version,
            ),
            settings=settings,
        )
    if not isinstance(secret, ApiKeySecret):
        raise BadRequestError(
            message="This key cannot hold a voice call", details={"provider": provider}
        )
    key = secret.api_key.get_secret_value()
    if provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider
        from pydantic_ai.realtime.openai import OpenAIRealtimeModel

        return OpenAIRealtimeModel(model, provider=OpenAIProvider(api_key=key), settings=settings)
    if provider == "google":
        from pydantic_ai.providers.google import GoogleProvider
        from pydantic_ai.realtime.google import GoogleRealtimeModel

        return GoogleRealtimeModel(model, provider=GoogleProvider(api_key=key), settings=settings)
    if provider == "xai":
        from pydantic_ai.providers.xai import XaiProvider
        from pydantic_ai.realtime.xai import XaiRealtimeModel

        return XaiRealtimeModel(model, provider=XaiProvider(api_key=key), settings=settings)
    raise BadRequestError(
        message="This provider cannot hold voice conversations", details={"provider": provider}
    )


def realtime_settings(
    *,
    provider: str,
    voice: str,
    language: str | None,
    thinking: ThinkingEffort | Literal[True] | None,
    supports_thinking: bool,
) -> RealtimeModelSettings:
    """The session settings for one call.

    Gemini gets a reconnect policy because its connections end after about ten
    minutes with a GoAway; resumption restores the session in-process. It never
    reattaches after *we* close (call-ending research §4). The language is
    Gemini's output language; elsewhere it is in the instructions.
    """
    settings: RealtimeModelSettings
    if provider in ("openai", "azure"):
        settings = OpenAIRealtimeModelSettings(openai_voice=voice, openai_turn_detection=_TURNS)
    elif provider == "google":
        settings = GoogleRealtimeModelSettings(google_voice=voice, reconnect=ReconnectPolicy())
        if language:
            settings["google_language_code"] = language
    elif provider == "xai":
        settings = XaiRealtimeModelSettings(xai_voice=voice)
    else:
        settings = RealtimeModelSettings()
    if thinking is not None and supports_thinking:
        settings["thinking"] = thinking
    return settings
