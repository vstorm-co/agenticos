"""Explicit currency units and manual rates; recorded USD costs are immutable."""

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
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
    """Convert a nonzero amount using a rate snapshot. Zero needs no exchange rate."""
    if amount.is_zero():
        return amount
    rate = rates.get(currency)
    if rate is None or not rate.is_finite() or rate <= 0:
        return None
    with localcontext() as arithmetic:
        arithmetic.prec = 128
        return amount / rate


class ReportingQuote(BaseModel):
    """A display and limit-entry quote, frozen until the currency preference changes."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    currency: CurrencyCode = "USD"
    units_per_usd: ExchangeRate | None = Decimal(1)

    @classmethod
    def from_settings(cls, settings: CurrencySettings, currency: str | None = None) -> Self:
        code = currency or settings.default_currency
        return cls(currency=code, units_per_usd=settings.rates.get(code))


class CurrencyAmount(BaseModel):
    """An explicitly denominated input; existing API USD fields keep their units."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    amount: Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=68, decimal_places=24)]
    currency: CurrencyCode


class MonetaryTerm(BaseModel):
    """Original configured terms and the quote that fixed their accounting value."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    amount: Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=700, decimal_places=400)]
    currency: CurrencyCode
    units_per_usd: ExchangeRate
    cost_usd: Annotated[
        Decimal, Field(ge=0, allow_inf_nan=False, max_digits=700, decimal_places=400)
    ]

    @model_validator(mode="after")
    def balanced_terms(self) -> Self:
        if self.currency == "USD":
            if self.units_per_usd != 1 or self.amount != self.cost_usd:
                raise ValueError("USD monetary terms must retain their exact accounting amount")
        else:
            with localcontext() as arithmetic:
                arithmetic.prec = 1024
                converted = (self.amount / self.units_per_usd).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                )
            if converted != self.cost_usd:
                raise ValueError("Original monetary terms must match their recorded conversion")
        return self


def sum_usd(values: Iterable[Decimal]) -> Decimal:
    """Add supported receipt values without the process's default 28-digit rounding."""
    with localcontext() as context:
        context.prec = 128
        return sum(values, Decimal(0))


def difference_usd(left: Decimal, right: Decimal) -> Decimal:
    """Subtract accounting values at the same precision used for conversion and totals."""
    with localcontext() as context:
        context.prec = 128
        return left - right
