"""Explicit currency units and manual rates; recorded USD costs are immutable."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
ExchangeRate = Annotated[
    Decimal, Field(gt=0, allow_inf_nan=False, max_digits=24, decimal_places=12)
]


class CurrencySettings(BaseModel):
    """Supported currencies, expressed as units of that currency for one USD.

    Rates are supplied by the operator, never fetched during model inference.
    USD remains the compatible accounting unit. Each conversion records the
    amount, original currency and rate used, so edits affect only future usage.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_currency: CurrencyCode = "USD"
    rates: dict[CurrencyCode, ExchangeRate] = Field(
        default_factory=lambda: {"USD": Decimal(1)}, min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def valid_base_and_default(self) -> Self:
        if self.rates.get("USD") != Decimal(1):
            raise ValueError("Exchange rates must include USD at exactly 1")
        if self.default_currency not in self.rates:
            raise ValueError("The default currency must have a configured exchange rate")
        return self


def to_usd(amount: Decimal, currency: str, rates: Mapping[str, Decimal]) -> Decimal | None:
    """Convert using a supplied snapshot; a missing rate is unknown, never 1:1."""
    rate = rates.get(currency)
    if rate is None or not rate.is_finite() or rate <= 0:
        return None
    return amount / rate
