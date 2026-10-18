"""Single-shot LLM text for workflow_builder llm_generate nodes (D3 B64)."""

from __future__ import annotations

import logging
import re

from pydantic_ai import Agent

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.prompts.shop_llm_generate import (
    LLM_GENERATE_SYSTEM,
    LLM_GENERATE_WITH_SUBJECT_SYSTEM,
)
from app.schemas.shop_llm_generate import (
    ShopLlmGenerateIn,
    ShopLlmGenerateLlmResult,
    ShopLlmGenerateOut,
)
from app.services.shop_llm_openai import build_shop_llm_generate_model, shop_llm_generate_configured

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(r"<\s*(script|iframe|object|embed|form)\b", re.IGNORECASE)


class ShopLlmGenerateService:
    def __init__(self) -> None:
        self._text_agent: Agent[None, ShopLlmGenerateLlmResult] | None = None
        self._subject_agent: Agent[None, ShopLlmGenerateLlmResult] | None = None

    def _agent(self, *, include_subject: bool) -> Agent[None, ShopLlmGenerateLlmResult]:
        temp = min(settings.SHOP_AI_LLM_GENERATE_TEMPERATURE, 0.7)
        if include_subject:
            if self._subject_agent is None:
                self._subject_agent = Agent(
                    model=build_shop_llm_generate_model(),
                    model_settings={"temperature": temp},
                    system_prompt=LLM_GENERATE_WITH_SUBJECT_SYSTEM,
                    output_type=ShopLlmGenerateLlmResult,
                )
            return self._subject_agent
        if self._text_agent is None:
            self._text_agent = Agent(
                model=build_shop_llm_generate_model(),
                model_settings={"temperature": temp},
                system_prompt=LLM_GENERATE_SYSTEM,
                output_type=ShopLlmGenerateLlmResult,
            )
        return self._text_agent

    async def generate(self, data: ShopLlmGenerateIn) -> ShopLlmGenerateOut:
        if not shop_llm_generate_configured():
            raise BadRequestError(
                message="LLM is not configured",
                details={"hint": "Set SHOP_AI_LLM_GENERATE_API_KEY on Agentra"},
            )
        try:
            result = await self._agent(include_subject=data.include_subject).run(
                data.prompt.strip()
            )
            body = result.output.body.strip()
            if _FORBIDDEN.search(body):
                raise BadRequestError(message="Generated body contains forbidden HTML")
            subject = (result.output.subject or "").strip() or None
            return ShopLlmGenerateOut(body=body, subject=subject)
        except BadRequestError:
            raise
        except Exception as exc:
            logger.exception("shop llm_generate failed")
            raise ExternalServiceError(
                message="LLM generation failed",
                details={"error": str(exc)[:200]},
            ) from exc
