"""Single-shot email template generation for Studio (D3 B64)."""

from __future__ import annotations

import logging
import re
import uuid

from pydantic_ai import Agent

from app.core.config import settings
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.prompts.shop_email_generate import (
    EMAIL_GENERATE_HTML_SYSTEM,
    EMAIL_GENERATE_PUCK_SYSTEM,
    OCCASION_HINTS,
)
from app.schemas.shop_email_generate import (
    ShopEmailGenerateHtmlOut,
    ShopEmailGenerateIn,
    ShopEmailGeneratePuckOut,
    ShopEmailHtmlLlmResult,
    ShopEmailPuckBlockOut,
    ShopEmailPuckLlmResult,
)
from app.services.shop_llm_openai import build_shop_llm_generate_model, shop_llm_generate_configured

logger = logging.getLogger(__name__)

EMAIL_PUCK_VERSION = 2
_FORBIDDEN_HTML = re.compile(
    r"<\s*(script|iframe|object|embed|form)\b",
    re.IGNORECASE,
)


def _block_id() -> str:
    return f"gen_{uuid.uuid4().hex[:10]}"


def puck_block_to_item(block: ShopEmailPuckBlockOut) -> dict:
    props: dict = {"id": _block_id()}
    if block.type == "EmailHeader":
        props["brand"] = block.brand or "{{shop.name}}"
        props["subtitle"] = block.subtitle or ""
        if block.badge:
            props["badge"] = block.badge
        props["emailStyle"] = {
            "bg": "#0f172a",
            "color": "#ffffff",
            "accent": "#14b8a6",
            "subtitleColor": "#94a3b8",
            "badgeBg": "#0d9488",
            "badgeColor": "#ffffff",
        }
    elif block.type == "EmailHeading":
        props["text"] = block.text or "Hello {{customer.name}}"
    elif block.type == "EmailText":
        props["text"] = block.text or "Message from {{shop.name}}."
    elif block.type == "EmailButton":
        props["text"] = block.text or "Open"
        props["href"] = block.href or "{{cta_url}}"
    elif block.type == "EmailFooter":
        props["text"] = block.text or "{{shop.name}}"
    return {"type": block.type, "props": props}


def build_merge_schema_from_puck(result: ShopEmailPuckLlmResult) -> dict:
    content = [puck_block_to_item(b) for b in result.blocks]
    return {
        "builder": {
            "version": EMAIL_PUCK_VERSION,
            "puck": {
                "root": {
                    "props": {
                        "canvasBg": result.canvas_bg or "#f8fafc",
                        "cardBg": result.card_bg or "#ffffff",
                    },
                },
                "content": content,
            },
        },
    }


def sanitize_body_html(html: str) -> str:
    cleaned = html.strip()
    if _FORBIDDEN_HTML.search(cleaned):
        raise BadRequestError(
            message="Generated HTML contains forbidden elements",
            details={"hint": "script/iframe/form not allowed"},
        )
    return cleaned


class ShopEmailGenerateService:
    def __init__(self) -> None:
        self._html_agent: Agent[None, ShopEmailHtmlLlmResult] | None = None
        self._puck_agent: Agent[None, ShopEmailPuckLlmResult] | None = None

    def _html_agent_instance(self) -> Agent[None, ShopEmailHtmlLlmResult]:
        if self._html_agent is None:
            temp = min(settings.SHOP_AI_LLM_GENERATE_TEMPERATURE, 0.7)
            self._html_agent = Agent(
                model=build_shop_llm_generate_model(),
                model_settings={"temperature": temp},
                system_prompt=EMAIL_GENERATE_HTML_SYSTEM,
                output_type=ShopEmailHtmlLlmResult,
            )
        return self._html_agent

    def _puck_agent_instance(self) -> Agent[None, ShopEmailPuckLlmResult]:
        if self._puck_agent is None:
            temp = min(settings.SHOP_AI_LLM_GENERATE_TEMPERATURE, 0.7)
            self._puck_agent = Agent(
                model=build_shop_llm_generate_model(),
                model_settings={"temperature": temp},
                system_prompt=EMAIL_GENERATE_PUCK_SYSTEM,
                output_type=ShopEmailPuckLlmResult,
            )
        return self._puck_agent

    def _user_prompt(self, data: ShopEmailGenerateIn) -> str:
        occasion = OCCASION_HINTS.get(data.occasion, OCCASION_HINTS["general"])
        return (
            f"Occasion: {data.occasion} — {occasion}\n\n"
            f"Merchant prompt:\n{data.prompt.strip()}"
        )

    async def generate(
        self, data: ShopEmailGenerateIn
    ) -> ShopEmailGenerateHtmlOut | ShopEmailGeneratePuckOut:
        if not shop_llm_generate_configured():
            raise BadRequestError(
                message="LLM is not configured",
                details={"hint": "Set SHOP_AI_LLM_GENERATE_API_KEY on Agentra"},
            )
        user_prompt = self._user_prompt(data)
        try:
            if data.output_format == "puck":
                result = await self._puck_agent_instance().run(user_prompt)
                puck_out = result.output
                merge_schema = build_merge_schema_from_puck(puck_out)
                return ShopEmailGeneratePuckOut(
                    subject=puck_out.subject.strip(),
                    merge_schema=merge_schema,
                    output_format="puck",
                )
            result = await self._html_agent_instance().run(user_prompt)
            html_out = result.output
            return ShopEmailGenerateHtmlOut(
                subject=html_out.subject.strip(),
                body_html=sanitize_body_html(html_out.body_html),
                output_format="html",
            )
        except BadRequestError:
            raise
        except Exception as exc:
            logger.exception("Shop email generate failed")
            raise ExternalServiceError(
                message="Email generation failed",
                details={"error": str(exc)[:200]},
            ) from exc
