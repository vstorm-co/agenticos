"""OpenAI-compatible model for Shop AI one-shot LLM helpers (D3 B64)."""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import settings


def shop_llm_generate_configured() -> bool:
    return bool((settings.SHOP_AI_LLM_GENERATE_API_KEY or "").strip())


def build_shop_llm_generate_model() -> OpenAIResponsesModel:
    api_key = (settings.SHOP_AI_LLM_GENERATE_API_KEY or "").strip()
    base_url = (settings.SHOP_AI_LLM_GENERATE_BASE_URL or "").strip()
    provider_kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        provider_kwargs["base_url"] = base_url
    model_name = (settings.SHOP_AI_LLM_GENERATE_MODEL or "gpt-4o-mini").strip()
    return OpenAIResponsesModel(model_name, provider=OpenAIProvider(**provider_kwargs))
