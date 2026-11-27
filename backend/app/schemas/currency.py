"""An organization's effective reporting currency and available manual rates."""

from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.core.currency import CurrencyAmount, CurrencyCode, ExchangeRate, MonetaryTerm
from app.schemas.base import BaseSchema


class CurrencyContext(BaseSchema):
    currency: CurrencyCode
    default_currency: CurrencyCode
    inherited: bool
    rates: dict[str, Decimal]
    reporting_units_per_usd: ExchangeRate | None = None


class MonetaryInputSchema(BaseSchema):
    """Original terms accompanying unchanged canonical USD API fields.

    Each key names a monetary field supplied in the same request. The service
    checks the canonical amount against the authoritative reporting quote before
    saving it. Unrelated patches preserve the resource's existing terms.
    """

    monetary_inputs: dict[str, CurrencyAmount] = Field(
        default_factory=dict, max_length=16, exclude=True, json_schema_extra={"x-internal": True}
    )


class NodeMonetaryConfig(MonetaryInputSchema):
    """Original cap terms stored beside a workflow node's unchanged USD config."""

    monetary_terms: dict[Literal["max_cost_usd"], MonetaryTerm] = Field(
        default_factory=dict,
        exclude_if=lambda value: not value,
        json_schema_extra={"x-internal": True},
    )
