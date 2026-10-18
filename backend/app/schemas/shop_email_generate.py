"""Email template AI generate schemas (Studio authoring)."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

OutputFormatLiteral = Literal["html", "puck"]
OccasionLiteral = Literal[
    "general",
    "welcome",
    "order_confirm",
    "order_status",
    "promo",
    "form_receipt",
]

MERGE_TOKEN_HINTS = (
    "shop.name",
    "shop.url",
    "customer.name",
    "customer.email",
    "order.code",
    "order.status",
    "form.email",
    "form.ref",
    "cta_url",
)

PuckBlockTypeLiteral = Literal[
    "EmailHeader",
    "EmailHeading",
    "EmailText",
    "EmailButton",
    "EmailFooter",
]


class ShopEmailGenerateIn(BaseSchema):
    prompt: str = Field(..., min_length=3, max_length=4000)
    output_format: OutputFormatLiteral = "html"
    occasion: OccasionLiteral = "general"
    tenant_id: UUID | None = Field(
        default=None, description="Validated against X-Tenant-Id when set"
    )


class ShopEmailGenerateHtmlOut(BaseSchema):
    subject: str
    body_html: str
    output_format: Literal["html"] = "html"


class ShopEmailPuckBlockOut(BaseSchema):
    type: PuckBlockTypeLiteral
    text: str | None = None
    href: str | None = None
    brand: str | None = None
    subtitle: str | None = None
    badge: str | None = None


class ShopEmailGeneratePuckOut(BaseSchema):
    subject: str
    merge_schema: dict
    output_format: Literal["puck"] = "puck"


class ShopEmailHtmlLlmResult(BaseSchema):
    subject: str = Field(..., min_length=1, max_length=998)
    body_html: str = Field(..., min_length=1, max_length=100_000)


class ShopEmailPuckLlmResult(BaseSchema):
    subject: str = Field(..., min_length=1, max_length=998)
    canvas_bg: str = "#f8fafc"
    card_bg: str = "#ffffff"
    blocks: list[ShopEmailPuckBlockOut] = Field(..., min_length=1, max_length=12)

    @field_validator("blocks")
    @classmethod
    def validate_blocks(cls, blocks: list[ShopEmailPuckBlockOut]) -> list[ShopEmailPuckBlockOut]:
        if len(blocks) > 12:
            raise ValueError("too many blocks (max 12)")
        return blocks
