"""Workflow llm_generate node — single-shot text (optional subject)."""

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopLlmGenerateIn(BaseSchema):
    prompt: str = Field(..., min_length=3, max_length=8000)
    include_subject: bool = False


class ShopLlmGenerateOut(BaseSchema):
    body: str
    subject: str | None = None


class ShopLlmGenerateLlmResult(BaseSchema):
    body: str = Field(..., min_length=1, max_length=50_000)
    subject: str | None = Field(default=None, max_length=998)
